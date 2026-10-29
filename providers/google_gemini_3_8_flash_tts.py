"""Google Gemini 3.8 Flash TTS 适配器模块。

提供 GoogleGemini3_8FlashTTSAdapter，覆盖 Gemini Developer API (ai.google.dev) 的三大能力：

1. 语音合成（Speech Generation）
   - 端点：``POST {BASE}/interactions``（Gemini 3.8 的 Interactions API）
   - 鉴权：``x-goog-api-key`` 请求头（非 Bearer）
   - 请求体：``model`` + ``input[].content[].text``（逐字稿）+ ``speech_metadata.style``（回合级风格）
     + ``response_format={"type":"audio"}`` + ``generation_config.speech_config``（单说话人为 ``[{"voice": <id>}]``）
   - 一元（unary）请求默认返回 **WAV**（audio/wav，24kHz 单声道 16bit PCM，含 RIFF 头），直接保存即可；
     若显式请求 audio/l16 等裸 PCM，则封装为 WAV 后保存

2. 语音设计（Voice Design）
   - 端点：``POST {BASE}/voices``，``voice.type="prompted"``
   - 用自然语言描述生成自定义音色，返回持久化 ``voice_...`` ID 与 sample_audio

3. 语音复刻（Voice Replication）
   - 端点：``POST {BASE}/voices``，``voice.type="replicated"``
   - 需要 10~30s 参考音频 + 同意声明音频（24kHz 单声道 16bit WAV），返回 ``voice_...`` 或 ``voicekey_...``
"""

import base64
import struct
from pathlib import Path
from typing import Any

import httpx

from astrbot.api import logger

from .base import TTSProviderAdapter
from .utils.audio import save_audio_bytes

# Gemini Developer API (v1beta) 基址
API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Gemini 3.8 系列 TTS 模型：同时支持语音合成、设计与复刻，无单独分层。
GEMINI_TTS_MODELS = [
    "gemini-3.8-flash-tts",
    "gemini-3.8-flash-lite-tts",
]

# 预置音色（官方 30 个 Studio 预置音色；模型自动检测语言，下列为通用英文预置音色名）
# 完整列表见 https://ai.google.dev/gemini-api/docs/speech-generation#prebuilt-voices
PREBUILT_VOICES = [
    "Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede",
    "Callirrhoe", "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba",
    "Despina", "Erinome", "Algenib", "Rasalgethi", "Laomedeia", "Achernar",
    "Alnilam", "Schedar", "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi",
    "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat",
]

# 复刻音频约束
REPLICATE_MIN_SEC = 10.0
REPLICATE_MAX_SEC = 30.0
REPLICATE_SAMPLE_RATE = 24000


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

    @staticmethod
    def _is_custom_voice(voice_id: str) -> bool:
        """判断 voice_id 是否为自定义/设计/复刻音色（Gemini 返回的持久化 ID）。"""
        return bool(voice_id) and (
            voice_id.startswith("voice_") or voice_id.startswith("voicekey_")
        )

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
            return REPLICATE_SAMPLE_RATE
        import re

        m = re.search(r"rate=(\d+)", mime_type)
        return int(m.group(1)) if m else REPLICATE_SAMPLE_RATE

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

    # ————————————————————————————————
    # 音色管理：设计 / 复刻 / 列表 / 删除
    # ————————————————————————————————

    def _voice_model(self) -> str:
        """语音设计/复刻与合成共用同一个 model 字段（3.8 系列）。"""
        return self.entry.get("model") or GEMINI_TTS_MODELS[0]

    def _http_kwargs(self, timeout: int) -> dict:
        """构造 httpx.AsyncClient 关键字参数，统一注入代理（若已配置）。

        代理地址取配置项 ``proxy``（如 ``http://127.0.0.1:7890`` 或
        ``socks5://127.0.0.1:7891``）。AstrBot 启动时会清空环境变量中的
        ``http_proxy``/``https_proxy``，故此处用显式配置项而非依赖环境变量。
        """
        kwargs: dict[str, Any] = {"timeout": timeout}
        proxy = self.entry.get("proxy")
        if isinstance(proxy, str) and proxy.strip():
            kwargs["proxy"] = proxy.strip()
        return kwargs

    async def create_voice(self, params: dict) -> dict:
        """创建音色：mode=design（设计）或 mode=replicate（复刻）。"""
        mode = (params.get("mode") or "").strip().lower()
        if mode in ("design", "prompted"):
            return await self._create_voice_by_design(params)
        if mode in ("replicate", "clone"):
            return await self._create_voice_by_replicate(params)
        # 自动推断
        if params.get("prompt") or params.get("voice_prompt"):
            return await self._create_voice_by_design(params)
        if params.get("source_audio") or params.get("source_audio_path"):
            return await self._create_voice_by_replicate(params)
        raise ValueError("无法推断创建模式，请指定 mode='design' 或 mode='replicate'")

    async def _create_voice_by_design(self, params: dict) -> dict:
        """语音设计：自然语言描述 → 自定义音色。"""
        api_key = self.entry.get("api_key")
        if not api_key:
            raise ValueError("API Key 未配置")

        prompt = params.get("prompt") or params.get("voice_prompt")
        if not prompt or not str(prompt).strip():
            raise ValueError("prompt（音色描述）为必填参数")

        payload: dict[str, Any] = {
            "store": True,
            "voice": {
                "model": self._voice_model(),
                "type": "prompted",
                "prompted": {"input": str(prompt).strip()},
            },
        }
        if params.get("display_name"):
            payload["voice"]["display_name"] = params["display_name"]

        result = await self._post_voices(api_key, payload, timeout=120)
        voice_id = result.get("id") or result.get("voiceId")
        if not voice_id:
            raise RuntimeError(f"未返回 voice_id: {result}")
        response = {"voice_id": voice_id}
        sample = result.get("sample_audio") or result.get("sampleAudio")
        if sample and sample.get("data"):
            response["sample_audio_base64"] = sample["data"]
            response["sample_audio_mime"] = sample.get("mime_type", "audio/wav")
        return response

    async def _create_voice_by_replicate(self, params: dict) -> dict:
        """语音复刻：参考音频 + 同意声明音频 → 复刻音色。"""
        api_key = self.entry.get("api_key")
        if not api_key:
            raise ValueError("API Key 未配置")

        source_b64 = await self._resolve_replicate_audio(
            params.get("source_audio"), params.get("source_audio_path"), "参考音频"
        )
        consent_b64 = await self._resolve_replicate_audio(
            params.get("consent_audio"),
            params.get("consent_audio_path"),
            "同意声明音频",
        )

        store = params.get("store", True)
        payload: dict[str, Any] = {
            "store": bool(store),
            "voice": {
                "model": self._voice_model(),
                "type": "replicated",
                "replicated": {
                    "source_audio": {"mime_type": "audio/wav", "data": source_b64},
                    "consent_audio": {"mime_type": "audio/wav", "data": consent_b64},
                },
            },
        }
        if params.get("display_name"):
            payload["voice"]["display_name"] = params["display_name"]

        result = await self._post_voices(api_key, payload, timeout=120)
        # store=True → id；store=False → key（voicekey_...）
        voice_id = (
            result.get("id")
            or result.get("voiceId")
            or result.get("key")
            or result.get("voiceKey")
        )
        if not voice_id:
            raise RuntimeError(f"未返回 voice_id/key: {result}")
        return {"voice_id": voice_id}

    async def _resolve_replicate_audio(
        self, raw_b64: Any, file_path: Any, label: str
    ) -> str:
        """复刻音频：优先用 base64 原文；否则读取本地文件并（必要时）转为 24k 单声道 16bit WAV。"""
        if raw_b64 and isinstance(raw_b64, str):
            return raw_b64
        if not file_path:
            raise ValueError(
                f"{label}缺失（需提供 source_audio/consent_audio 或对应文件路径）"
            )
        p = Path(file_path)
        if not p.exists():
            raise ValueError(f"{label}文件不存在: {file_path}")
        # 时长校验
        try:
            from .utils.audio import validate_audio_duration

            ok, msg = validate_audio_duration(
                str(p), REPLICATE_MIN_SEC, REPLICATE_MAX_SEC
            )
            if not ok:
                logger.warning(f"{label}时长校验: {msg}（仍尝试提交）")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"无法校验{label}时长: {e}")
        # 统一转码为 24kHz 单声道 16bit WAV
        try:
            from pydub import AudioSegment

            seg = AudioSegment.from_file(str(p))
            seg = (
                seg.set_frame_rate(REPLICATE_SAMPLE_RATE)
                .set_channels(1)
                .set_sample_width(2)
            )
            import io

            buf = io.BytesIO()
            seg.export(buf, format="wav")
            return base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"{label}转码失败，回退为原文件 base64: {e}")
            return base64.b64encode(p.read_bytes()).decode("utf-8")

    async def _post_voices(
        self, api_key: str, payload: dict, timeout: int = 120
    ) -> dict:
        url = f"{API_BASE}/voices"
        headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(**self._http_kwargs(timeout)) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                return resp.json()
        except httpx.TimeoutException:
            raise RuntimeError("语音创建请求超时")
        except Exception as e:
            raise RuntimeError(f"语音创建失败: {e}")

    async def list_voice(self, **kwargs) -> dict:
        """列出已创建的音色（voices.list）。"""
        api_key = self.entry.get("api_key")
        if not api_key:
            raise ValueError("API Key 未配置")
        url = f"{API_BASE}/voices"
        headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(**self._http_kwargs(30)) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            raise RuntimeError(f"查询音色列表失败: {e}")

        items = []
        for v in data.get("voices", data.get("voiceList", [])):
            items.append(
                {
                    "voice_id": v.get("id") or v.get("voiceId"),
                    "display_name": v.get("displayName") or v.get("display_name"),
                    "type": v.get("type"),
                }
            )
        return {"items": items, "total": len(items)}

    async def delete_voice(self, **kwargs) -> bool:
        """删除指定音色（voices.delete）。"""
        api_key = self.entry.get("api_key")
        if not api_key:
            raise ValueError("API Key 未配置")
        voice_id = kwargs.get("voice_id")
        if not voice_id:
            raise ValueError("voice_id 为必填参数")
        url = f"{API_BASE}/voices/{voice_id}"
        headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(**self._http_kwargs(30)) as client:
                resp = await client.delete(url, headers=headers)
                resp.raise_for_status()
                return True
        except Exception as e:
            logger.error(f"删除音色失败: {e}")
            return False

    async def query_voice(self, voice_id: str) -> str:
        """Gemini 设计/复刻为同步返回，无异步部署流程，直接返回 OK。"""
        return "OK"
