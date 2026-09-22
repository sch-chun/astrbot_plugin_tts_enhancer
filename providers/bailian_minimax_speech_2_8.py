"""百炼 MiniMax Speech 2.8 TTS 适配器模块。

提供 BailianMinimaxSpeech2_8Adapter 类，通过阿里云百炼平台调用 MiniMax Speech 2.8 模型，
支持 HD 和 Turbo 两种模型，实现语音合成、参数校验、音色克隆等完整功能。
"""
import httpx
import traceback

from datetime import datetime
from typing import Any, Optional

from astrbot.api import logger
from astrbot.core.agent.tool import FunctionTool

from .base import TTSProviderAdapter
from .utils import http
from .utils.audio import save_audio_bytes


class BailianMinimaxSpeech2_8Adapter(TTSProviderAdapter):
    """百炼 MiniMax Speech 2.8 TTS 适配器。

    通过阿里云百炼平台调用 MiniMax Speech 2.8 模型，支持 HD 和 Turbo 两种模型，
    提供语音合成、参数校验、音色克隆等功能。
    """

    # 百炼 MiniMax API 端点
    _API_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"

    # 复用官方 MiniMax 2.8 的能力说明文档
    DOCS_KEY = "minimax_speech_2_8"

    # 支持的模型（百炼前缀）
    SUPPORTED_MODELS = ["HD", "Turbo"]

    # 情感标签（与官方 MiniMax 2.8 一致）
    VALID_EMOTIONS = [
        "happy", "sad", "angry", "fearful",
        "disgusted", "surprised", "calm", "fluent"
    ]

    # 语言增强（完整列表，与官方一致）
    VALID_LANGUAGE_BOOST = [
        "Chinese", "Chinese,Yue", "English", "Arabic", "Russian",
        "Spanish", "French", "Portuguese", "German", "Turkish",
        "Dutch", "Ukrainian", "Vietnamese", "Indonesian", "Japanese",
        "Italian", "Korean", "Thai", "Polish", "Romanian",
        "Greek", "Czech", "Finnish", "Hindi", "Bulgarian",
        "Danish", "Hebrew", "Malay", "Persian", "Slovak",
        "Swedish", "Croatian", "Filipino", "Hungarian", "Norwegian",
        "Slovenian", "Catalan", "Nynorsk", "Tamil", "Afrikaans",
        "auto"
    ]

    def __init__(self, entry: dict) -> None:
        super().__init__(entry)
        logger.debug(f"Initialized BailianMinimaxSpeech2_8Adapter with template_key={self.template_key}")

    def _truncate_data_url(self, url: str, max_len: int = 100) -> str:
        """截断 Data URL 以避免日志过长。

        Args:
            url: 原始 URL 字符串
            max_len: 最大显示长度，默认 100

        Returns:
            截断后的 URL 字符串
        """
        if url and url.startswith('data:') and len(url) > max_len:
            return url[:max_len] + f"... (truncated, total {len(url)} chars)"
        return url

    def _sanitize_payload_for_log(self, payload: dict) -> dict:
        """清理 payload 中的 Data URL 以便日志打印。

        Args:
            payload: 原始请求 payload

        Returns:
            清理后的 payload 副本（深拷贝）
        """
        import copy
        sanitized = copy.deepcopy(payload)
        
        # 截断主音频 URL
        if "input" in sanitized and "audio_url" in sanitized["input"]:
            sanitized["input"]["audio_url"] = self._truncate_data_url(
                sanitized["input"]["audio_url"]
            )
        
        # 截断示例音频 URL
        if "input" in sanitized and "clone_prompt" in sanitized["input"]:
            if "prompt_audio" in sanitized["input"]["clone_prompt"]:
                sanitized["input"]["clone_prompt"]["prompt_audio"] = self._truncate_data_url(
                    sanitized["input"]["clone_prompt"]["prompt_audio"]
                )
        
        return sanitized

    def _check_base_resp(self, base_resp: dict, action: str) -> str | None:
        """检查百炼 MiniMax 响应的 base_resp 状态。

        Args:
            base_resp: 响应中的 base_resp 字典。
            action: 当前动作描述，用于组装错误消息。

        Returns:
            错误消息字符串，成功（status_code == 0）时返回 None。
        """
        if not base_resp:
            return None  # 无 base_resp 视为通过
        if base_resp.get("status_code") != 0:
            return f"{action}: {base_resp.get('status_msg')}"
        return None

    # ———————— 语音合成 ————————

    def get_tool_schema(self) -> FunctionTool:
        """返回 TTS 增强工具的 Schema 定义。

        Returns:
            FunctionTool: 包含名称、描述和参数定义的工具对象。
        """
        return FunctionTool(
            name="tts_enhance",
            description="为百炼 MiniMax Speech 2.8 语音合成提供增强参数，支持情感、语速、音量、语调、语言增强及 LaTeX 朗读。",
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "合成文本，支持语气词标签 (laughs) 和停顿 <#x#>"
                    },
                    "emotion": {
                        "type": "string",
                        "enum": self.VALID_EMOTIONS,
                        "description": "情感标签（模型会自动匹配合适情绪，一般无需指定）"
                    },
                    "speed": {
                        "type": "number",
                        "minimum": 0.5,
                        "maximum": 2.0,
                        "description": "语速倍率，默认 1.0"
                    },
                    "vol": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 10.0,
                        "description": "音量，默认 1.0"
                    },
                    "pitch": {
                        "type": "integer",
                        "minimum": -12,
                        "maximum": 12,
                        "description": "语调偏移，默认 0"
                    },
                    "language_boost": {
                        "type": "string",
                        "enum": self.VALID_LANGUAGE_BOOST,
                        "description": "增强对指定语种的识别，一般留空，默认设为 'auto' 让模型自主判断"
                    },
                    "latex_read": {
                        "type": "boolean",
                        "description": "是否朗读 LaTeX 公式，仅中文有效，会自动设置 language_boost=Chinese，公式需在首尾加上 $$ 包裹"
                    }
                },
                "required": ["text"]
            },
            handler=None
        )

    def get_subagent_system_prompt(self) -> str:
        """返回 SubAgent 的系统提示词，用于指导模型调用 TTS 增强工具。

        Returns:
            str: 包含模型能力说明和调用指引的系统提示字符串。
        """
        return f"""你是语音合成参数优化助手，负责为百炼 MiniMax Speech 2.8 模型准备合成参数。以下是模型能力说明：

{self.docs_content}

请根据用户提供的文本和上下文，调用 `tts_enhance` 工具提供合适的参数（text 必填，其他可选）。直接调用工具，不要额外解释。"""

    async def call_api(
        self,
        text: str,
        raw_params: dict[str, Any],
        config: dict[str, Any],
        voice_id: Optional[str] = None
    ) -> str:
        """调用百炼 MiniMax TTS API 进行语音合成并保存为本地文件。

        Args:
            text: 待合成的原始文本。
            raw_params: SubAgent 提供的增强参数（如 speed, vol, pitch 等）。
            config: 提供商配置字典，包含 api_key, model, voice_id 等。
            voice_id: 可选的音色 ID，覆盖 config 中的音色 ID。

        Returns:
            str: 成功时返回保存的音频文件绝对路径，失败时返回空字符串。
        """
        api_key = config.get("api_key")
        if not api_key:
            logger.error("百炼 MiniMax API Key 未配置")
            return ""

        model = config.get("model", "HD")
        if model not in self.SUPPORTED_MODELS:
            logger.warning(f"不支持的模型 {model}，将使用 HD")
            model = "HD"

        # 百炼模型名称带 MiniMax/ 前缀
        model_id = f"MiniMax/speech-2.8-{model.lower()}"

        voice_id = voice_id or config.get("voice_id")
        if not voice_id:
            raise ValueError("未提供音色 ID，无法合成语音")

        # 音频设置
        audio_setting = {
            "sample_rate": config.get("sample_rate", 32000),
            "bitrate": config.get("bitrate", 128000),
            "format": config.get("format", "mp3"),
            "channel": config.get("channel", 1),
        }

        # 合并参数（工具参数优先）
        final_text = raw_params.get("text", text)
        if not final_text:
            logger.error("TTS 文本为空")
            return ""

        voice_setting = {
            "voice_id": voice_id,
            "speed": raw_params.get("speed", 1.0),
            "vol": raw_params.get("vol", 1.0),
            "pitch": raw_params.get("pitch", 0),
        }

        # text_normalization 从配置获取
        if config.get("text_normalization", False):
            voice_setting["text_normalization"] = True

        # 可选 emotion
        if "emotion" in raw_params:
            voice_setting["emotion"] = raw_params["emotion"]

        # latex_read 从工具参数获取
        latex_read = raw_params.get("latex_read", False)

        # 语言增强
        language_boost = raw_params.get("language_boost", "auto")

        # 若 latex_read 为 True，强制 language_boost = "Chinese"
        if latex_read:
            language_boost = "Chinese"
            if "language_boost" in raw_params and raw_params["language_boost"] != "Chinese":
                logger.warning("latex_read 为 True，强制将 language_boost 设置为 'Chinese'")

        # 构造百炼 API 请求体（嵌套在 input 下）
        payload = {
            "model": model_id,
            "input": {
                "text": final_text,
                "voice_setting": voice_setting,
                "audio_setting": audio_setting,
            }
        }

        if language_boost:
            payload["input"]["language_boost"] = language_boost

        if latex_read:
            payload["input"]["latex_read"] = True

        logger.debug(f"百炼 MiniMax API 请求参数: {self._sanitize_payload_for_log(payload)}")

        headers = http.bearer_headers(api_key)
        timeout = config.get("timeout", 60)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(self._API_ENDPOINT, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()

            # 检查 base_resp
            output = data.get("output", {})
            base_resp = output.get("base_resp", {})
            error_msg = self._check_base_resp(base_resp, "百炼 MiniMax API 错误")
            if error_msg:
                logger.error(error_msg)
                return ""

            # 百炼 MiniMax 返回的是 hex 编码的音频数据，位于 output.data.audio
            audio_hex = output.get("data", {}).get("audio")
            if not audio_hex:
                logger.error(f"响应中无 audio 字段，完整响应: {data}")
                return ""

            # 转换 hex 为字节并保存
            audio_bytes = bytes.fromhex(audio_hex)
            audio_format = audio_setting.get("format", "mp3")
            return save_audio_bytes(config.get("_data_dir", ""), audio_bytes, audio_format)

        except httpx.TimeoutException:
            logger.error(f"百炼 MiniMax API 超时 (timeout={timeout}s)")
            return ""
        except Exception as e:
            logger.error(f"百炼 MiniMax API 调用失败: {e}\n{traceback.format_exc()}")
            return ""

    # ————————————————————————

    # ———————— 参数校验 ————————

    def validate_params(self, params: dict) -> tuple[bool, str]:
        """校验 TTS 增强参数是否合法。

        Args:
            params: 待校验的参数字典，可包含 speed, vol, pitch, emotion, language_boost, latex_read。

        Returns:
            tuple[bool, str]: 校验结果与错误信息。合法时返回 (True, "")，非法时返回 (False, 错误描述)。
        """
        if "speed" in params and not (0.5 <= params["speed"] <= 2.0):
            return False, f"speed 必须在 0.5~2.0 之间，当前 {params['speed']}"

        if "vol" in params and not (0.0 <= params["vol"] <= 10.0):
            return False, f"vol 必须在 0~10 之间，当前 {params['vol']}"

        if "pitch" in params and not (-12 <= params["pitch"] <= 12):
            return False, f"pitch 必须在 -12~12 之间，当前 {params['pitch']}"

        if "emotion" in params and params["emotion"] not in self.VALID_EMOTIONS:
            return False, f"不支持的情感标签: {params['emotion']}"

        if "language_boost" in params and params["language_boost"] not in self.VALID_LANGUAGE_BOOST:
            return False, f"不支持的语言增强: {params['language_boost']}"

        if "latex_read" in params and not isinstance(params["latex_read"], bool):
            return False, f"latex_read 必须为布尔值，当前 {params['latex_read']}"

        return True, ""

    def sanitize_params(self, params: dict) -> dict:
        """清洗参数，丢弃不合法的项并保留合法项。

        Args:
            params: 待清洗的参数字典。

        Returns:
            dict: 仅包含合法参数的清洗后字典，始终包含 text 字段。
        """
        sanitized = {"text": params.get("text", "")}
        for key in ["speed", "vol", "pitch", "emotion", "language_boost"]:
            if key in params:
                valid, _ = self.validate_params({key: params[key]})
                if valid:
                    sanitized[key] = params[key]
                else:
                    logger.warning(f"丢弃非法的 {key} 参数: {params[key]}")
        
        # 单独处理 latex_read
        if "latex_read" in params:
            valid, _ = self.validate_params({"latex_read": params["latex_read"]})
            if valid:
                sanitized["latex_read"] = params["latex_read"]
            else:
                logger.warning(f"丢弃非法的 latex_read 参数: {params['latex_read']}")
        
        return sanitized

    # ————————————————————————

    # ———————— 音色管理 ————————

    async def create_voice(self, params: dict) -> dict:
        """创建音色（声音克隆）。

        通过百炼 MiniMax API 进行声音克隆，需要提供音频 URL。

        Args:
            params: 创建参数
                - voice_id (str): 自定义音色 ID（必填）
                - audio_url (str): 音频文件的可访问 URL（必填）
                - text (str): 试听文本，限制 1000 字符（必填）
                - model (str, optional): 模型版本，默认 "HD"
                - prompt_audio_url (str, optional): 示例音频 URL，时长 < 8 秒
                - prompt_text (str, optional): 示例音频对应的文本
                - language_boost (str, optional): 语言增强，如 "auto"、"Chinese" 等
                - need_noise_reduction (bool, optional): 是否开启降噪，默认 false
                - need_volume_normalization (bool, optional): 是否开启音量归一化，默认 false
                - aigc_watermark (bool, optional): 是否添加 AIGC 水印，默认 false

        Returns:
            dict: 包含 voice_id 的结果字典

        Raises:
            ValueError: 参数不合法
            RuntimeError: API 请求失败
        """
        api_key = self.entry.get("api_key")
        if not api_key:
            raise ValueError("API Key 未配置")

        voice_id = params.get("voice_id")
        if not voice_id:
            # 自动生成 voice_id
            voice_id = f"Clone_{datetime.now().strftime('%Y%m%d%H%M%S')}_{id(self)}"
            logger.warning(f"未提供 voice_id，自动生成: {voice_id}")
        else:
            # 校验 voice_id 格式
            self.validate_voice_id(voice_id)

        audio_url = params.get("audio_url")
        if not audio_url:
            raise ValueError("audio_url 为必填参数")

        text = params.get("text")
        if not text:
            raise ValueError("text 为必填参数（试听文本）")

        # 校验试听文本长度（汉字按 2 字符计算）
        self.validate_text_length(text=text, max_len=1000, field_name="试听文本")

        # 模型名称
        model = params.get("model", self.entry.get("model", "HD"))
        if model not in self.SUPPORTED_MODELS:
            logger.warning(f"不支持的模型 {model}，将使用 HD")
            model = "HD"
        model_id = f"MiniMax/speech-2.8-{model.lower()}"

        # 构造声音克隆请求
        payload = {
            "model": model_id,
            "input": {
                "action": "voice_clone",
                "voice_id": voice_id,
                "audio_url": audio_url,
                "text": text
            }
        }

        # 可选：示例音频
        prompt_audio_url = params.get("prompt_audio_url")
        prompt_text = params.get("prompt_text")
        if prompt_audio_url:
            if not prompt_text:
                raise ValueError("提供 prompt_audio_url 时必须同时提供 prompt_text")
            # 校验示例音频文本长度
            self.validate_text_length(text=prompt_text, max_len=200, field_name="示例音频文本")
            payload["input"]["clone_prompt"] = {
                "prompt_audio": prompt_audio_url,
                "prompt_text": prompt_text
            }

        # 可选：语言增强
        language_boost = params.get("language_boost")
        if language_boost:
            payload["input"]["language_boost"] = language_boost

        # 可选：降噪
        if params.get("need_noise_reduction"):
            payload["input"]["need_noise_reduction"] = True

        # 可选：音量归一化
        if params.get("need_volume_normalization"):
            payload["input"]["need_volume_normalization"] = True

        # 可选：AIGC 水印
        if params.get("aigc_watermark"):
            payload["input"]["aigc_watermark"] = True

        headers = http.bearer_headers(api_key)

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                logger.debug(f"百炼 MiniMax 声音克隆请求: {self._sanitize_payload_for_log(payload)}")
                resp = await client.post(self._API_ENDPOINT, headers=headers, json=payload)
                resp.raise_for_status()
                result = resp.json()

            # 检查响应
            output = result.get("output", {})
            base_resp = output.get("base_resp", {})
            error_msg = self._check_base_resp(base_resp, "声音克隆失败")
            if error_msg:
                raise RuntimeError(error_msg)

            # 提取试听音频 URL
            demo_audio = output.get("demo_audio")
            
            logger.info(f"声音克隆成功: voice_id={voice_id}")
            response = {"voice_id": voice_id}
            if demo_audio:
                response["demo_audio"] = demo_audio
            
            return response

        except httpx.TimeoutException:
            raise RuntimeError("声音克隆请求超时")
        except httpx.HTTPStatusError as e:
            try:
                error_msg = http.extract_error_message(e.response.json(), fallback_text=e.response.text)
            except Exception:
                error_msg = e.response.text
            raise RuntimeError(f"请求失败: {error_msg}")
        except Exception as e:
            raise RuntimeError(f"声音克隆异常: {e}")

    async def list_voice(self, **kwargs) -> dict:
        """通过百炼声音管理接口查询可用音色列表。

        Args:
            **kwargs:
                voice_type (str): 音色类型，"system"、"voice_cloning"、"voice_generation" 或 "all"，默认 "all"

        Returns:
            dict: 包含 items 列表的字典，每项含 voice_id、voice_name、type 等信息。

        Raises:
            ValueError: API Key 未配置
            RuntimeError: API 请求失败
        """
        api_key = self.entry.get("api_key")
        if not api_key:
            raise ValueError("API Key 未配置")

        voice_type = kwargs.get("voice_type", "all")
        if voice_type not in ["system", "voice_cloning", "voice_generation", "all"]:
            raise ValueError(f"不支持的 voice_type: {voice_type}")

        payload = {
            "model": "MiniMax/speech-2.8-turbo",
            "input": {
                "action": "get_voice",
                "voice_type": voice_type
            }
        }

        headers = http.bearer_headers(api_key)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(self._API_ENDPOINT, headers=headers, json=payload)
                resp.raise_for_status()
                result = resp.json()

            output = result.get("output", {})
            base_resp = output.get("base_resp", {})
            error_msg = self._check_base_resp(base_resp, "查询音色列表失败")
            if error_msg:
                raise RuntimeError(error_msg)

            items = []

            # 系统音色
            for v in output.get("system_voice", []):
                items.append({
                    "voice_id": v.get("voice_id"),
                    "voice_name": v.get("voice_name"),
                    "type": "system",
                    "created_at": v.get("created_time")
                })
                
            # 复刻音色
            for v in output.get("voice_cloning", []):
                items.append({
                    "voice_id": v.get("voice_id"),
                    "voice_name": v.get("voice_name"),
                    "type": "voice_cloning",
                    "created_at": v.get("created_time")
                })

            # 文生音色（百炼 MiniMax 暂不支持，但保留解析逻辑）
            for v in output.get("voice_generation", []):
                items.append({
                    "voice_id": v.get("voice_id"),
                    "voice_name": v.get("voice_name"),
                    "type": "voice_generation",
                    "created_at": v.get("created_time")
                })

            return {"items": items, "total": len(items)}

        except httpx.TimeoutException:
            raise RuntimeError("查询音色列表超时")
        except httpx.HTTPStatusError as e:
            try:
                error_msg = http.extract_error_message(e.response.json(), fallback_text=e.response.text)
            except Exception:
                error_msg = e.response.text
            raise RuntimeError(f"请求失败: {error_msg}")
        except Exception as e:
            raise RuntimeError(f"查询音色列表异常: {e}")

    async def delete_voice(self, **kwargs) -> bool:
        """通过百炼声音管理接口删除复刻音色。

        Args:
            **kwargs:
                voice_id (str): 待删除的音色 ID，必填

        Returns:
            bool: 删除成功返回 True

        Raises:
            ValueError: API Key 或 voice_id 未提供
            RuntimeError: API 请求失败
        """
        api_key = self.entry.get("api_key")
        if not api_key:
            raise ValueError("API Key 未配置")

        voice_id = kwargs.get("voice_id")
        if not voice_id:
            raise ValueError("voice_id 不能为空")

        payload = {
            "model": "MiniMax/speech-2.8-turbo",
            "input": {
                "action": "delete_voice",
                "voice_type": "voice_cloning",
                "voice_id": voice_id
            }
        }

        headers = http.bearer_headers(api_key)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(self._API_ENDPOINT, headers=headers, json=payload)
                resp.raise_for_status()
                result = resp.json()

            output = result.get("output", {})
            base_resp = output.get("base_resp", {})
            error_msg = self._check_base_resp(base_resp, "删除音色失败")
            if error_msg:
                raise RuntimeError(error_msg)

            logger.info(f"音色删除成功: voice_id={voice_id}")
            return True

        except httpx.TimeoutException:
            raise RuntimeError("删除音色超时")
        except httpx.HTTPStatusError as e:
            try:
                error_msg = http.extract_error_message(e.response.json(), fallback_text=e.response.text)
            except Exception:
                error_msg = e.response.text
            raise RuntimeError(f"请求失败: {error_msg}")
        except Exception as e:
            raise RuntimeError(f"删除音色异常: {e}")
