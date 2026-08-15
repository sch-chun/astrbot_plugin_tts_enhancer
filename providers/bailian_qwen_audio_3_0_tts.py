"""阿里云 Qwen Audio 3.0 TTS 适配器 - 支持 Function Calling 结构化参数"""

import httpx
from datetime import datetime
from pathlib import Path
import traceback

from typing import Any

from astrbot.core import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from astrbot.core.agent.tool import FunctionTool

from .base import TTSProviderAdapter


class BailianQwenAudio3_0TTSAdapter(TTSProviderAdapter):
    """百炼 Qwen-Audio-TTS 供应商适配器，通过 Tool Calling 接收增强参数。"""
    _API_ENDPOINT = "https://{workspace_id}.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"

    # ---------- 1. 定义工具 Schema ----------
    def get_tool_schema(self) -> FunctionTool:
        """返回用于 TTS 参数增强的 Function Tool。"""
        return FunctionTool(
            name="tts_enhance",
            description="为语音合成提供增强参数，包括带情感标签的文本、指令、音量、语速和语言提示。",
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "需要合成的文本，可嵌入情感标签（如 [excited]、[laughing]）以控制表现力。"
                    },
                    "instruction": {
                        "type": "string",
                        "description": "自然语言指令，用于控制方言、情感或角色（如'请用河南话表达'）。"
                    },
                    "volume": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 100,
                        "description": "音量，范围 0-100，默认 50。"
                    },
                    "rate": {
                        "type": "number",
                        "minimum": 0.5,
                        "maximum": 2.0,
                        "description": "语速倍率，范围 0.5-2.0，默认 1.0。"
                    },
                    "language_hints": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["zh", "en", "fr", "de", "ja", "ko", "ru", "pt", "th", "id", "vi", "es", "it", "ms", "fil", "ar"]
                        },
                        "description": "指定语音合成的目标语言，建议与文本语种一致。"
                    }
                },
                "required": ["text"]
            },
            handler=None  # 无需执行，只用于让 LLM 输出参数
        )

    # ---------- 2. 构建 SubAgent 系统提示 ----------
    def get_subagent_system_prompt(self, raw_tts_text: str) -> str:
        docs = self.docs_content
        return f"""你是语音合成参数优化助手，负责为 TTS 模型准备合成参数。以下是 TTS 模型的参数使用说明：

{docs}

现在请根据待合成文本「{raw_tts_text}」，调用 `tts_enhance` 工具，提供合适的参数（包括 text 和其他可选参数）。请直接调用工具，不要额外解释。"""

    # ---------- 3. 解析 SubAgent 响应 ----------
    def parse_subagent_response(self, response_data: Any) -> dict[str, Any]:
        """
        解析 SubAgent 返回的数据。
        如果 response_data 是 dict（工具参数），直接返回；
        否则视为纯文本，将其作为 `text`，其余参数留空。
        """
        if isinstance(response_data, dict):

            # 确保 text 存在
            if "text" not in response_data:
                logger.warning("工具调用缺少 'text' 字段，使用原始文本")
                return {}
            return response_data
        
        # 降级：纯文本
        if isinstance(response_data, str) and response_data.strip():
            return {"text": response_data.strip()}
        return {}

    # ---------- 4. 调用 TTS API ----------
    async def call_api(
        self,
        text: str,               # 原始文本（备用）
        raw_params: dict[str, Any],  # 从工具解析出的参数（优先）
        config: dict[str, Any]   # 当前供应商的 entry 配置
    ) -> str:
        """执行 TTS 合成，返回音频文件路径。"""
        # 提取配置
        api_key = config.get("api_key", "")
        workspace_id = config.get("workspace_id", "")
        model_suffix = config.get("model", "flash")
        model = f"qwen-audio-3.0-tts-{model_suffix}"
        voice = config.get("voice", "longanhuan_v3.6")
        timeout = config.get("timeout", 60)
        format_type = config.get("format", "wav")
        sample_rate = config.get("sample_rate", 24000)
        seed = config.get("seed", -1)
        enable_aigc = config.get("enable_aigc_tag", False)
        aigc_propagator = config.get("aigc_propagator", "")
        aigc_propagate_id = config.get("aigc_propagate_id", "")

        # ---------- 合并参数（工具参数优先） ----------
        # text: 优先使用 raw_params 中的，否则使用传入的 text
        final_text = raw_params.get("text", text)
        if not final_text:
            logger.error("TTS 文本为空")
            return ""

        # 其他参数：如果 raw_params 中有则使用，否则不传（让 API 使用默认值）
        final_instruction = raw_params.get("instruction")
        final_volume = raw_params.get("volume")
        final_rate = raw_params.get("rate")
        final_language_hints = raw_params.get("language_hints")

        # 构造 payload
        payload = {
            "model": model,
            "input": {
                "text": final_text,
                "voice": voice,
                "format": format_type,
                "sample_rate": sample_rate,
            }
        }

        # 可选参数（仅当存在时添加）
        if final_instruction:
            payload["input"]["instruction"] = final_instruction
        if final_volume is not None:
            payload["input"]["volume"] = final_volume
        if final_rate is not None:
            payload["input"]["rate"] = final_rate
        if final_language_hints:
            payload["input"]["language_hints"] = final_language_hints

        # 配置中的固定参数
        if seed != -1:
            payload["input"]["seed"] = seed
        if enable_aigc:
            payload["input"]["enable_aigc_tag"] = True
            if aigc_propagator:
                payload["input"]["aigc_propagator"] = aigc_propagator
            if aigc_propagate_id:
                payload["input"]["aigc_propagate_id"] = aigc_propagate_id

        # 请求
        if not api_key or not workspace_id:
            logger.error("Qwen Audio 3.0 TTS: api_key 或 workspace_id 未配置")
            return ""

        url = self._API_ENDPOINT.format(workspace_id=workspace_id)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()

            audio_url = data.get("output", {}).get("audio", {}).get("url")
            if not audio_url:
                logger.error(f"Qwen Audio 3.0 TTS API 未返回音频 URL: {data}")
                return ""

            return await self._download_audio(audio_url, format_type, timeout)

        except httpx.TimeoutException as e:
            logger.error(f"Qwen Audio 3.0 TTS API 超时 (超时设置: {timeout}s): {e}")
            return ""
        except Exception as e:
            logger.error(f"Qwen Audio 3.0 TTS API 调用失败: {e}\n{traceback.format_exc()}")
            return ""

    async def _download_audio(self, url: str, fmt: str, timeout: int = 60) -> str:
        """下载音频到本地。"""
        try:
            data_dir = Path(get_astrbot_data_path()) / "tts_enhancer"
            data_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"tts_{timestamp}.{fmt}"
            filepath = data_dir / filename

            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                filepath.write_bytes(resp.content)

            logger.info(f"TTS 音频已保存: {filepath}")
            return str(filepath)

        except Exception as e:
            logger.error(f"下载音频失败: {e}")
            return ""

    VALID_LANGS = ["zh", "en", "fr", "de", "ja", "ko", "ru", "pt", "th", "id", "vi", "es", "it", "ms", "fil", "ar"]

    def validate_params(self, params: dict) -> tuple[bool, str]:
        """验证 Qwen Audio 3.0 TTS 参数"""
        if "volume" in params:
            vol = params["volume"]
            if not isinstance(vol, int) or not (0 <= vol <= 100):
                return False, f"volume 必须是 0-100 之间的整数。当前值: {vol}"

        if "rate" in params:
            rate = params["rate"]
            if not isinstance(rate, (int, float)) or not (0.5 <= rate <= 2.0):
                return False, f"rate 必须是 0.5-2.0 之间的数字。当前值: {rate}"

        if "language_hints" in params:
            hints = params["language_hints"]
            if not isinstance(hints, list):
                return False, f"language_hints 必须是一个列表。当前值: {hints}"
            for lang in hints:
                if lang not in self.VALID_LANGS:
                    return False, f"不支持的语言代码: {lang}，支持: {', '.join(self.VALID_LANGS)}"

        return True, ""

    def sanitize_params(self, params: dict) -> dict:
        """清理 Qwen Audio 3.0 TTS 参数"""
        sanitized = {}
        sanitized["text"] = params.get("text", "")
        sanitized["instruction"] = params.get("instruction", "")
        if "volume" in params:
            vol = params["volume"]
            if isinstance(vol, int) and 0 <= vol <= 100:
                sanitized["volume"] = vol
            else:
                logger.warning(f"丢弃非法的 volume 参数: {vol}")

        if "rate" in params:
            rate = params["rate"]
            if isinstance(rate, (int, float)) and 0.5 <= rate <= 2.0:
                sanitized["rate"] = rate
            else:
                logger.warning(f"丢弃非法的 rate 参数: {rate}")

        if "language_hints" in params:
            hints = params["language_hints"]
            if isinstance(hints, list):
                valid_hints = [lang for lang in hints if lang in self.VALID_LANGS]
                if valid_hints:
                    sanitized["language_hints"] = valid_hints
                else:
                    logger.warning(f"丢弃非法的 language_hints 参数: {hints}")

        return sanitized
    