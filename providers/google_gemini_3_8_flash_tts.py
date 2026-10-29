"""Google Gemini 3.8 Flash TTS 适配器模块。

封装 GoogleGemini3_8FlashTTSAdapter，对接 Gemini Developer API (ai.google.dev) 的语音合成能力：

- 端点：``POST {BASE}/interactions``（Gemini 3.8 的 Interactions API）
- 鉴权：``x-goog-api-key`` 请求头（非 Bearer）
- 请求体：``model`` + ``input[].content[].text``（逐字稿）+ ``speech_metadata.style``（回合级风格）
  + ``response_format={"type":"audio"}`` + ``generation_config.speech_config``（单说话人为 ``[{"voice": <id>}]``）
- 一元（unary）请求默认返回 **WAV**（audio/wav，24kHz 单声道 16bit PCM，含 RIFF 头），直接保存即可；
  若显式请求 audio/l16 等裸 PCM，则封装为 WAV 后保存

音色设计（Voice Design）与复刻（Voice Replication）由 Google AI Studio 提供
（https://aistudio.google.com/generate-speech）：其返回的持久化 ``voice_...`` / ``voicekey_...`` ID
可直接填入 ``voice_id`` 配置项使用；本适配器不实现相关的创建与管理接口。
"""

import base64
import struct
from typing import Any

import httpx

from astrbot.api import logger

from .base import TTSProviderAdapter
from .utils.audio import save_audio_bytes

# Gemini Developer API (v1beta) 基址
API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Gemini 3.8 系列 TTS 模型：语音合成 / 设计 / 复刻共用同一模型，无单独分层。
GEMINI_TTS_MODELS = [
    "gemini-3.8-flash-tts",
    "gemini-3.8-flash-lite-tts",
]


class GoogleGemini3_8FlashTTSAdapter(TTSProviderAdapter):
    """Google Gemini 3.8 Flash TTS 适配器。"""

    def __init__(self, entry: dict) -> None:
        super().__init__(entry)
        logger.debug(
            f"Initialized GoogleGemini3_8FlashTTSAdapter with template_key={self.template_key}"
        )

    # ————————————————————————————————
    # 工具 Schema 与 SubAgent 提示词
    # ————————————————————————————————

    def get_tool_schema(self) -> Any:
        """返回 tts_enhance 工具。

        Gemini 的风格/情绪控制以自然语言提示为主，因此工具仅暴露：
        - text（必填，合成文本）
        - style（可选，风格/语气/情绪/口音等自然语言指引，映射到 speech_metadata.style）
        """
        return self.build_enhance_tool(
            "为 Google Gemini 3.8 Flash TTS 语音合成提供增强参数。"
            "Gemini 以自然语言控制风格，请将语气、情绪、口音、节奏等要求写入 style。",
            {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "合成文本。",
                    },
                    "style": {
                        "type": "string",
                        "description": (
                            "自然语言风格指引，如 '用温柔舒缓的语气'、'带一点犹豫和紧张'、"
                            "'新闻播报腔，字正腔圆'。模型会据此调整表达。"
                        ),
                    },
                },
                "required": ["text"],
            },
        )

    def get_subagent_system_prompt(self) -> str:
        return (
            "你是语音合成参数优化助手，负责为 Google Gemini 3.8 Flash TTS 准备合成参数。"
            "Gemini 通过自然语言提示控制音色风格，请调用 `tts_enhance` 工具：\n"
            "- text 必填，为待合成文本；\n"
            "- style 可选，用自然语言描述语气、情绪、口音、节奏（如'兴奋地''低沉沙哑'）。\n"
            "若用户未指定风格，style 可省略。直接调用工具，不要额外解释。\n\n"
            "参考能力说明：\n"
            f"{self.docs_content}"
        )

    # ————————————————————————————————
    # 参数校验 / 清洗（契约要求输出仅含 text/style）
    # ————————————————————————————————

    def validate_params(self, params: dict) -> tuple[bool, str]:
        if "style" in params and not isinstance(params["style"], str):
            return False, "style 必须是字符串"
        return True, ""

    def sanitize_params(self, params: dict) -> dict:
        out: dict[str, Any] = {"text": params.get("text", "")}
        instr = params.get("style")
        if instr and isinstance(instr, str) and instr.strip():
            out["style"] = instr.strip()
        return out

    # ————————————————————————————————
    # 语音合成
    # ————————————————————————————————

    def _build_speech_config(self, config: dict, voice_id: str | None) -> list[dict]:
        """构造单说话人 speech_config（数组形式）。

        Gemini 3.8 TTS 对预置音色名与自定义/设计/复刻 ID 统一使用
        ``{"voice": <id>}``，无需区分 ``prebuiltVoiceConfig``。
        """
        vid = voice_id or config.get("voice_id") or "Kore"
        return [{"voice": vid}]

    async def call_api(
        self,
        text: str,
        raw_params: dict[str, Any],
        config: dict[str, Any],
        voice_id: str | None = None,
    ) -> str:
        """调用 Gemini TTS 合成语音并保存为本地 WAV 文件。"""
        api_key = config.get("api_key")
        if not api_key:
            logger.error("Gemini API Key 未配置")
            return ""

        model = config.get("model") or GEMINI_TTS_MODELS[0]
        if model not in GEMINI_TTS_MODELS:
            logger.warning(f"不支持的模型 {model}，将使用 {GEMINI_TTS_MODELS[0]}")
            model = GEMINI_TTS_MODELS[0]

        final_text = raw_params.get("text") or text
        if not final_text:
            logger.error("TTS 文本为空")
            return ""

        # 单说话人：request body 用 input[].content[].text（逐字稿），
        # style 映射到 speech_metadata.style（回合级风格）。
        content_item: dict[str, Any] = {"type": "text", "text": final_text}
        style = raw_params.get("style")
        if style and isinstance(style, str) and style.strip():
            content_item["annotations"] = [
                {"type": "speech_metadata", "style": style.strip()}
            ]

        payload = {
            "model": model,
            "input": [{"type": "user_input", "content": [content_item]}],
            "response_format": {"type": "audio"},
            "generation_config": {
                "speech_config": self._build_speech_config(config, voice_id),
            },
        }

        url = f"{API_BASE}/interactions"
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }
        timeout = config.get("timeout", 60)

        try:
            async with httpx.AsyncClient(**self._http_kwargs(timeout)) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException:
            logger.error(f"Gemini TTS 超时 (timeout={timeout}s)")
            return ""
        except Exception as e:
            logger.error(f"Gemini TTS 调用失败: {e}")
            return ""

        audio_b64, mime_type = self._extract_audio(data)
        if not audio_b64:
            logger.error("Gemini 响应中无音频数据")
            return ""

        pcm = base64.b64decode(audio_b64)
        # 一元（unary）请求默认返回 WAV（audio/wav，含 RIFF 头），直接保存；
        # 若显式请求了 audio/l16 等裸 PCM，则封装为 WAV 再保存。
        if "wav" in (mime_type or "audio/wav").lower():
            wav = pcm
        else:
            sample_rate = self._parse_sample_rate(mime_type)
            wav = self.pcm16le_to_wav_bytes(pcm, sample_rate=sample_rate)

        return save_audio_bytes(config.get("_data_dir", ""), wav, "wav")

    @staticmethod
    def _extract_audio(data: dict) -> tuple[str, str]:
        """从 Interactions API 响应提取 base64 音频与 mimeType。

        优先取 ``output_audio.data``（SDK 便捷字段）；否则遍历 ``steps`` 中
        ``type=="model_output"`` 的步，取其 ``content`` 中 ``type=="audio"`` 的最后一段。
        """
        out = data.get("output_audio") or data.get("outputAudio")
        if out and out.get("data"):
            return out.get("data", ""), out.get("mime_type", out.get("mimeType", ""))
        for step in data.get("steps", []):
            if step.get("type") != "model_output":
                continue
            for content in step.get("content", []):
                if content.get("type") == "audio" and content.get("data"):
                    return content.get("data", ""), content.get(
                        "mimeType", content.get("mime_type", "")
                    )
        return "", ""

    @staticmethod
    def _parse_sample_rate(mime_type: str) -> int:
        """从 mimeType（如 audio/L16;codec=pcm;rate=24000）解析采样率。"""
        if not mime_type:
            return 24000
        import re

        m = re.search(r"rate=(\d+)", mime_type)
        return int(m.group(1)) if m else 24000

    @staticmethod
    def pcm16le_to_wav_bytes(
        pcm: bytes, sample_rate: int = 24000, channels: int = 1
    ) -> bytes:
        """将 16bit 小端 PCM 裸流封装为标准 WAV 字节。"""
        bits = 16
        byte_rate = sample_rate * channels * bits // 8
        block_align = channels * bits // 8
        data_len = len(pcm)
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + data_len,
            b"WAVE",
            b"fmt ",
            16,  # fmt chunk size
            1,  # PCM
            channels,
            sample_rate,
            byte_rate,
            block_align,
            bits,
            b"data",
            data_len,
        )
        return header + pcm

    def _http_kwargs(self, timeout: int) -> dict:
        """构造 httpx.AsyncClient 关键字参数，统一注入代理（若已配置）。

        代理地址取配置项 ``proxy``（如 ``http://127.0.0.1:7890`` 或
        ``socks5://127.0.0.1:7891``）。留空则直连。
        """
        kwargs: dict[str, Any] = {"timeout": timeout}
        proxy = self.entry.get("proxy")
        if isinstance(proxy, str) and proxy.strip():
            kwargs["proxy"] = proxy.strip()
        return kwargs
