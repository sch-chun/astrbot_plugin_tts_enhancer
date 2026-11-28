"""Volcengine Doubao Seed TTS 3.0 unidirectional HTTP streaming adapter."""

import base64
import binascii
import json
import re
import wave
from collections.abc import AsyncIterator
from io import BytesIO
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx

from astrbot.api import logger

from .base import TTSProviderAdapter
from .mixins import VoiceManageable
from .utils.audio import save_audio_bytes

API_HOST = "https://voice.cn-beijing.volces.com"
MODEL_ID = "doubao-seed-tts-3.0"
MAX_INPUT_CHARS = 10000
FINAL_REASON = "TTS_STREAM_FINAL_REASON_CLOSED"
VALID_FORMATS = ("mp3", "pcm", "ogg_opus")
VALID_SAMPLE_RATES = (8000, 16000, 22050, 24000, 32000, 44100, 48000)
VALID_BIT_RATES = (64000, 160000)
MAX_CLONE_AUDIO_BYTES = 10 * 1024 * 1024
CLONE_AUDIO_FORMATS = ("wav", "mp3", "ogg", "m4a", "aac", "pcm")
CLONE_LANGUAGE_IDS = frozenset(range(101)) | {118}
CLONE_PROMPT_TEXT_REQUIRED_IDS = frozenset(
    {
        21,
        22,
        23,
        24,
        26,
        27,
        28,
        30,
        31,
        32,
        33,
        34,
        35,
        36,
        37,
        38,
        39,
        40,
        41,
        42,
        43,
        44,
        46,
        47,
        48,
        49,
        50,
        52,
        53,
        54,
        55,
        56,
        57,
        58,
        59,
        60,
        61,
        63,
        64,
        65,
        66,
        67,
        68,
        69,
        70,
        71,
        72,
        73,
        74,
        75,
        76,
        77,
        78,
        79,
        80,
        81,
        82,
        83,
        84,
        85,
        87,
        88,
        89,
        90,
        91,
        92,
        93,
        94,
        95,
        96,
        97,
        98,
        99,
        100,
        118,
    }
)
CLONE_PROSODY_UNSUPPORTED_IDS = CLONE_PROMPT_TEXT_REQUIRED_IDS | {62}
CLONE_EXTRA_FIELDS = frozenset(
    {
        "prompt_text",
        "prosody_boost",
        "demo_text",
        "enable_audio_denoise",
        "disable_volume_normalization",
    }
)
CUSTOM_SPEAKER_ID_RE = re.compile(
    r"(?x)\A"
    r"(?![a-z]{2}_)"
    r"(?!(?i:BV|(?:s|icl|mix|dit|wvae|moon|mercury|venus|earth|mars|"
    r"jupiter|saturn|uranus|neptune|pluto|umm)_))"
    r"(?!.*_(?i:bigtts|bigtts_cc|tob|cs_tob|streaming)\Z)"
    r"[A-Za-z][A-Za-z0-9_-]{6,254}[A-Za-z0-9]\Z"
)

LANGUAGE_CODES = frozenset(
    {
        "auto",
        "af",
        "am",
        "ar",
        "as",
        "ast",
        "az",
        "be",
        "bg",
        "bn",
        "bs",
        "ca",
        "ceb",
        "ckb",
        "cs",
        "cy",
        "da",
        "de",
        "el",
        "en",
        "en-GB",
        "es",
        "es-MX",
        "et",
        "fa",
        "fi",
        "fil",
        "fr",
        "fuv",
        "gl",
        "gu",
        "ha",
        "he",
        "hi",
        "hr",
        "hu",
        "hy",
        "id",
        "ig",
        "is",
        "it",
        "ja",
        "jv",
        "ka",
        "kam",
        "kea",
        "kk",
        "km",
        "kn",
        "ko",
        "ky",
        "lb",
        "lg",
        "ln",
        "lo",
        "lt",
        "luo",
        "lv",
        "mi",
        "mk",
        "ml",
        "mn",
        "mr",
        "ms",
        "mt",
        "my",
        "ne",
        "nl",
        "no",
        "nso",
        "ny",
        "oc",
        "ory",
        "pa",
        "pl",
        "ps",
        "pt",
        "pt-BR",
        "ro",
        "ru",
        "sd",
        "sk",
        "sl",
        "sn",
        "sq",
        "sr",
        "sv",
        "sw",
        "ta",
        "te",
        "tg",
        "th",
        "tr",
        "uk",
        "umb",
        "ur",
        "uz",
        "vi",
        "wo",
        "xh",
        "yo",
        "yue",
        "zh",
        "zh-CN-x-beijing",
        "zh-CN-x-changsha",
        "zh-CN-x-dongbei",
        "zh-CN-x-henan",
        "zh-CN-x-hubei",
        "zh-CN-x-kejia",
        "zh-CN-x-minnan",
        "zh-CN-x-nanchang",
        "zh-CN-x-nanjing",
        "zh-CN-x-shaanxi",
        "zh-CN-x-shandong",
        "zh-CN-x-shanghai",
        "zh-CN-x-sichuan",
        "zh-CN-x-taiwan",
        "zh-CN-x-tangshan",
        "zh-CN-x-tianjin",
        "zu",
    }
)

CONTROL_TAGS = frozenset(
    {
        "happy",
        "excited",
        "bored",
        "sad",
        "distressed",
        "angry",
        "nervous",
        "fearful",
        "panicked",
        "surprised",
        "disgusted",
        "disappointed",
        "hopeless",
        "desperate",
        "frustrated",
        "worried",
        "embarrassed",
        "guilty",
        "curious",
        "puzzled",
        "thoughtful",
        "confident",
        "serious",
        "commanding",
        "pleading",
        "reassuring",
        "sarcastic",
        "sympathetic",
        "indifferent",
        "very low pitch",
        "low pitch",
        "high pitch",
        "very high pitch",
        "very slow",
        "slow",
        "fast",
        "very fast",
        "very quiet",
        "quiet",
        "loud",
        "very loud",
        "hurried",
        "stammering",
        "whispering",
        "soft",
        "shouting",
        "muttering",
        "weak",
        "tired",
        "in pain",
        "panting",
        "laughing",
        "crying",
        "trembling",
    }
)

PARALINGUISTIC_TAGS = frozenset(
    {
        "laughs",
        "chuckles",
        "giggles",
        "whimpers",
        "cries",
        "sobs",
        "wails",
        "screams",
        "scoffs",
        "inhales",
        "inhales deeply",
        "gasps",
        "exhales",
        "exhales sharply",
        "sighs",
        "pants",
        "wheezing",
        "clears throat",
        "coughs",
        "grunts",
        "groans",
        "sniffs",
        "sneezes",
        "smacks lips",
        "clicks tongue",
        "yawns",
        "laughing hysterically",
        "swallows",
    }
)

_ERROR_GUIDANCE = {
    "authentication_error": "Check the API Key and authentication headers.",
    "authorization_error": "Check account access to the requested resource.",
    "invalid_request": "Check the request method, path, parameters, and body.",
    "not_found": "Check the requested resource and endpoint.",
    "payment_required": "Check the account balance and billing status.",
    "pronunciation_dictionary_not_found": "Check the pronunciation dictionary reference.",
    "rate_limit_error": "Reduce the request rate before trying again.",
    "validation_error": "Check field types, values, and required constraints.",
    "invalid_parameters": "Check parameter types, values, and combinations.",
    "missing_required_field": "Provide the missing request field.",
    "invalid_voice_id": "Check the voice_id path segment.",
    "invalid_voice_settings": "Check voice_settings values and combinations.",
    "unsupported_model": "Use doubao-seed-tts-3.0.",
    "text_too_long": "Shorten the text or split it into separate requests.",
    "empty_text": "Provide nonempty synthesis text.",
    "invalid_text": "Check the synthesis text format.",
    "invalid_output_format": "Check format, sample_rate, and bit_rate together.",
    "bad_request": "Check the request method, path, and body structure.",
    "malformed_json": "Send a valid JSON request body.",
    "invalid_content_type": "Use Content-Type: application/json.",
    "request_too_large": "Reduce the request body size.",
    "invalid_api_key": "Check the X-Api-Key value.",
    "missing_api_key": "Configure an API Key for X-Api-Key.",
    "invalid_authorization_header": "Use the X-Api-Key header as documented.",
    "unauthorized": "Check the API Key and access site.",
    "insufficient_credits": "Check the account balance.",
    "forbidden": "Check whether the service is enabled for this account.",
    "insufficient_permissions": "Check the account permissions.",
    "voice_access_denied": "Use a voice available to this account.",
    "model_access_denied": "Check access to doubao-seed-tts-3.0.",
    "voice_not_found": "Check the configured voice_id.",
    "model_not_found": "Check the model available at this site.",
    "rate_limit_exceeded": "Reduce the request rate before trying again.",
    "concurrent_limit_exceeded": "Wait for active requests to finish.",
    "internal_error": "Retry later and contact support if the issue persists.",
}


async def _iter_jsonl_lines(response: Any) -> AsyncIterator[bytes]:
    # HTTP chunks can split a JSONL record or contain several complete records.
    buffer = b""
    async for chunk in response.aiter_bytes():
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            yield line
    if buffer:
        yield buffer


class VolcengineSeedTts30Adapter(TTSProviderAdapter, VoiceManageable):
    """Synthesize speech and manage Seed TTS 3.0 voice clones."""

    DISPLAY_NAME = "豆包 Seed TTS 3.0"
    TOOL_EXTRA_FIELDS = frozenset(
        {"instructions", "speed", "volume", "pitch", "language_code"}
    )

    def get_tool_schema(self) -> Any:
        """Build the enhancement tool exposed to the SubAgent."""
        return self.build_enhance_tool(
            "为豆包 Seed TTS 3.0 准备文本、表达指令和演绎参数。",
            {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": (
                            "要朗读的文本，默认最多 10000 字符，配置可进一步调低。"
                            "可直接使用能力文档中的英文方括号 Inline Tag。"
                        ),
                    },
                    "instructions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "自然语言表达指令数组，按顺序生效；"
                            '例如 ["温柔自然", "句末稍作停顿"]。'
                        ),
                    },
                    "speed": {
                        "type": "number",
                        "minimum": 0.5,
                        "maximum": 2.0,
                        "description": "语速倍率，0.5~2.0。",
                    },
                    "volume": {
                        "type": "number",
                        "minimum": 0.5,
                        "maximum": 2.0,
                        "description": "音量倍率，0.5~2.0。",
                    },
                    "pitch": {
                        "type": "integer",
                        "minimum": -12,
                        "maximum": 12,
                        "description": "音高偏移，-12~12。",
                    },
                    "language_code": {
                        "type": "string",
                        "description": (
                            "合成语种或方言代码；由 SubAgent 按需提供，不读取插件配置。"
                            "仅支持 auto 或能力文档列出的官方代码。"
                        ),
                    },
                },
                "required": ["text"],
            },
        )

    def get_subagent_system_prompt(self) -> str:
        """Return the SubAgent instructions and provider capability reference."""
        return (
            "你是豆包 Seed TTS 3.0 语音合成参数优化助手。请调用 `tts_enhance` 工具：\n"
            "- text 必填，保留需要朗读的内容，并按需插入正式的 Inline Tag；\n"
            "- instructions 可选，用于整体表达、情绪或方言描述；\n"
            "- speed、volume、pitch 仅在用户明确要求时填写；\n"
            "- language_code 仅在语种明确或需要指定方言时填写。\n"
            "直接调用工具，不要额外解释。\n\n"
            f"{self.docs_content}"
        )

    def validate_params(self, params: dict) -> tuple[bool, str]:
        """Validate Tool parameters without injecting defaults."""
        if "text" in params:
            text = params["text"]
            if not isinstance(text, str) or not text.strip():
                return False, "text 必须是非空字符串"
            max_chars = self._as_int(self.entry.get("max_input_chars", MAX_INPUT_CHARS))
            if max_chars is None or not 1 <= max_chars <= MAX_INPUT_CHARS:
                max_chars = MAX_INPUT_CHARS
            if len(text.strip()) > max_chars:
                return False, f"text 不能超过 {max_chars} 字符"

        if "instructions" in params:
            instructions = params["instructions"]
            if not isinstance(instructions, list) or any(
                not isinstance(item, str) for item in instructions
            ):
                return False, "instructions 必须是字符串数组"

        for field in ("speed", "volume"):
            if field in params:
                value = self._as_float(params[field])
                if value is None or not 0.5 <= value <= 2.0:
                    return False, f"{field} 必须在 0.5~2.0 之间"

        if "pitch" in params:
            pitch = self._as_int(params["pitch"])
            if pitch is None or not -12 <= pitch <= 12:
                return False, "pitch 必须是 -12~12 的整数"

        if "language_code" in params:
            language = params["language_code"]
            if not isinstance(language, str) or language.strip() not in LANGUAGE_CODES:
                return False, "language_code 必须是官方支持的语种或方言代码"
        return True, ""

    def sanitize_params(self, params: dict) -> dict:
        """Keep only valid supplied Tool fields and preserve omission semantics."""
        sanitized: dict[str, Any] = {}
        if isinstance(params.get("text"), str):
            sanitized["text"] = params["text"].strip()

        if isinstance(params.get("instructions"), list):
            instructions = [
                item.strip()
                for item in params["instructions"]
                if isinstance(item, str) and item.strip()
            ]
            if instructions:
                sanitized["instructions"] = instructions

        for field in ("speed", "volume"):
            if field in params:
                value = self._as_float(params[field])
                if value is not None and 0.5 <= value <= 2.0:
                    sanitized[field] = value

        if "pitch" in params:
            pitch = self._as_int(params["pitch"])
            if pitch is not None and -12 <= pitch <= 12:
                sanitized["pitch"] = pitch

        if isinstance(params.get("language_code"), str):
            language = params["language_code"].strip()
            if language in LANGUAGE_CODES:
                sanitized["language_code"] = language
        return sanitized

    def _build_payload(self, text: str, config: dict, params: dict) -> dict[str, Any]:
        """Build the request body from explicit configuration and Tool fields."""
        fmt = config.get("format")
        if fmt not in VALID_FORMATS:
            logger.warning("[VolcengineSeedTTS3] Invalid format %r; using mp3", fmt)
            fmt = "mp3"

        sample_rate = self._as_int(config.get("sample_rate", 24000))
        if sample_rate not in VALID_SAMPLE_RATES:
            logger.warning(
                "[VolcengineSeedTTS3] Invalid sample_rate %r; using 24000", sample_rate
            )
            sample_rate = 24000
        if fmt == "ogg_opus" and sample_rate != 48000:
            logger.warning(
                "[VolcengineSeedTTS3] OGG Opus requires 48000 Hz; using 48000"
            )
            sample_rate = 48000

        output_format: dict[str, Any] = {"format": fmt, "sample_rate": sample_rate}
        if fmt != "pcm":
            bit_rate = self._as_int(config.get("bit_rate", 64000))
            if bit_rate not in VALID_BIT_RATES or (
                fmt == "mp3" and sample_rate == 8000
            ):
                logger.warning(
                    "[VolcengineSeedTTS3] Invalid bit_rate %r for %s/%s; using 64000",
                    bit_rate,
                    fmt,
                    sample_rate,
                )
                bit_rate = 64000
            output_format["bit_rate"] = bit_rate

        payload: dict[str, Any] = {
            "model_id": MODEL_ID,
            "text": text,
            "output_format": output_format,
        }
        language = params.get("language_code")
        if isinstance(language, str) and language in LANGUAGE_CODES:
            payload["language_code"] = language

        voice_settings: dict[str, Any] = {}
        instructions = params.get("instructions")
        if instructions:
            voice_settings["instructions"] = instructions
        for field in ("speed", "volume", "pitch"):
            if field in params:
                voice_settings[field] = params[field]
        if self._as_bool(config.get("similarity_boost")) is True:
            voice_settings["similarity_boost"] = True
        if instructions and self._as_bool(config.get("dialect_boost")) is True:
            voice_settings["dialect_boost"] = True
        if voice_settings:
            payload["voice_settings"] = voice_settings

        normalization = self._as_bool(config.get("text_normalization"))
        payload["text_normalization"] = True if normalization is None else normalization
        markdown_filter = self._as_bool(config.get("enable_markdown_filter"))
        payload["enable_markdown_filter"] = (
            True if markdown_filter is None else markdown_filter
        )
        silence_duration = self._as_int(config.get("silence_duration", 0))
        payload["silence_duration"] = (
            silence_duration
            if silence_duration is not None and 0 <= silence_duration <= 30000
            else 0
        )

        watermark: dict[str, Any] = {}
        if self._as_bool(config.get("aigc_watermark")) is True:
            watermark["aigc_watermark"] = True
        if self._as_bool(config.get("aigc_metadata_enable")) is True:
            metadata = {"enable": True}
            for field, api_field in (
                ("aigc_content_producer", "content_producer"),
                ("aigc_produce_id", "produce_id"),
                ("aigc_content_propagator", "content_propagator"),
                ("aigc_propagate_id", "propagate_id"),
            ):
                value = config.get(field)
                if isinstance(value, str) and value.strip():
                    metadata[api_field] = value.strip()
            watermark["aigc_metadata"] = metadata
        if watermark:
            payload["watermark"] = watermark
        return payload

    def _voice_client_settings(self) -> tuple[str, dict[str, Any], int]:
        entry = self.entry if isinstance(self.entry, dict) else {}
        api_key = entry.get("api_key")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("API Key 未配置")
        timeout = self._as_int(entry.get("timeout", 180))
        if timeout is None or timeout <= 0:
            timeout = 180
        client_kwargs: dict[str, Any] = {"timeout": timeout}
        proxy = entry.get("proxy")
        if isinstance(proxy, str) and proxy.strip():
            client_kwargs["proxy"] = proxy.strip()
        return api_key.strip(), client_kwargs, timeout

    @staticmethod
    def _voice_api_error(body: bytes, fallback: str) -> dict[str, Any]:
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"message": fallback or "音色接口返回了无效响应"}
        if not isinstance(data, dict):
            return {"message": fallback or "音色接口返回了无效响应"}
        error = data.get("error", data)
        if isinstance(error, dict):
            return error
        return {"message": str(error)}

    async def _post_voice_api(
        self, path: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        api_key, client_kwargs, timeout = self._voice_client_settings()
        headers = {
            "X-Api-Key": api_key,
            "Content-Type": "application/json",
            "X-Api-Request-Id": str(uuid4()),
        }
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.post(
                    f"{API_HOST}{path}", headers=headers, json=payload
                )
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"音色接口请求超时（{timeout} 秒）") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"音色接口请求失败：{exc}") from exc
        log_id = response.headers.get("X-Tt-Logid")
        try:
            data = json.loads(response.content)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.error(
                "[VolcengineSeedTTS3] Invalid voice response: status=%s log_id=%s",
                response.status_code,
                log_id,
            )
            raise RuntimeError("音色接口返回了无效响应") from exc
        if response.status_code < 200 or response.status_code >= 300:
            error = self._voice_api_error(response.content, response.text)
            logger.error(
                "[VolcengineSeedTTS3] Voice API error: status=%s log_id=%s error=%s",
                response.status_code,
                log_id,
                error,
            )
            message = error.get("message") or error.get("code") or "音色接口请求失败"
            raise RuntimeError(str(message))
        if not isinstance(data, dict):
            raise RuntimeError("音色接口返回了无效响应")
        return data

    @staticmethod
    def _validate_clone_audio(audio_bytes: bytes, fmt: str) -> None:
        if fmt == "pcm":
            if len(audio_bytes) % 2:
                raise ValueError("PCM 音频数据不完整，必须为 16 bit 单声道数据")
            duration = len(audio_bytes) / (24000 * 2)
        elif fmt == "wav":
            try:
                with wave.open(BytesIO(audio_bytes), "rb") as wav:
                    if wav.getframerate() <= 0:
                        raise ValueError("WAV 音频采样率无效")
                    duration = wav.getnframes() / wav.getframerate()
            except (wave.Error, EOFError) as exc:
                raise ValueError("WAV 音频无效或无法读取时长") from exc
        else:
            return
        if not 10 <= duration <= 60:
            raise ValueError("音频时长必须在 10–60 秒之间")

    async def create_voice(self, params: dict) -> dict:
        """Register a Seed TTS 3.0 voice clone using Base64 audio in JSON."""
        audio = params.get("audio")
        if not isinstance(audio, dict):
            raise ValueError("复刻音频格式不正确")
        encoded = audio.get("data")
        if not isinstance(encoded, str) or not encoded:
            raise ValueError("复刻音频内容不能为空")
        try:
            audio_bytes = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("复刻音频内容无效") from exc
        if not audio_bytes:
            raise ValueError("音频内容不能为空")
        if len(audio_bytes) > MAX_CLONE_AUDIO_BYTES:
            raise ValueError("音频文件不能超过 10 MB")
        fmt = audio.get("format")
        if fmt not in CLONE_AUDIO_FORMATS:
            raise ValueError(f"音频格式必须是 {', '.join(CLONE_AUDIO_FORMATS)} 之一")
        self._validate_clone_audio(audio_bytes, fmt)

        custom_speaker_id = params.get("custom_speaker_id")
        if custom_speaker_id is not None and custom_speaker_id != "":
            if not isinstance(custom_speaker_id, str):
                raise ValueError("自定义音色 ID 必须是字符串")
            custom_speaker_id = custom_speaker_id.strip()
            if not CUSTOM_SPEAKER_ID_RE.fullmatch(custom_speaker_id):
                raise ValueError("自定义音色 ID 不符合命名规则")
            existing_speaker_id = params.get("speaker_id")
            if existing_speaker_id not in (None, "", "custom_speaker_id"):
                raise ValueError("已有音色 ID 与自定义音色 ID 不能同时填写")
            if params.get("fee_confirmed") is not True:
                raise ValueError("自定义音色首次正式合成会收取槽位费，请先确认")
            speaker_id = "custom_speaker_id"
        else:
            speaker_id = params.get("speaker_id")
            if not isinstance(speaker_id, str) or not speaker_id.strip():
                raise ValueError("请填写已有音色 ID 或自定义音色 ID")
            speaker_id = speaker_id.strip()
            if speaker_id == "custom_speaker_id":
                raise ValueError("已有音色 ID 不能使用自定义名称占位值")

        language = params.get("language", 0)
        if (
            not isinstance(language, int)
            or isinstance(language, bool)
            or language not in CLONE_LANGUAGE_IDS
        ):
            raise ValueError("复刻语种必须是官方支持的选项")
        payload: dict[str, Any] = {
            "speaker_id": speaker_id,
            "audio": {"data": encoded, "format": fmt},
            "language": language,
        }
        if speaker_id == "custom_speaker_id":
            payload["custom_speaker_id"] = custom_speaker_id

        extra = params.get("extra_params", {})
        if not isinstance(extra, dict):
            raise ValueError("高级参数必须是对象")
        unknown = set(extra) - CLONE_EXTRA_FIELDS
        if unknown:
            raise ValueError("包含不支持的高级参数")
        extra_labels = {
            "prompt_text": "音源转写文本",
            "prosody_boost": "韵律美化",
            "demo_text": "试听文本",
            "enable_audio_denoise": "音频降噪",
            "disable_volume_normalization": "保留原始音量差异",
        }
        clean_extra: dict[str, Any] = {}
        for field in ("prompt_text", "demo_text"):
            value = extra.get(field)
            if value is None or value == "":
                continue
            if not isinstance(value, str):
                raise ValueError(f"{extra_labels[field]}必须是字符串")
            value = value.strip()
            if not value:
                continue
            if field == "demo_text" and not 4 <= len(value) <= 300:
                raise ValueError("试听文本长度必须在 4~300 个字符之间")
            clean_extra[field] = value
        for field in (
            "prosody_boost",
            "enable_audio_denoise",
            "disable_volume_normalization",
        ):
            value = extra.get(field)
            if value is None:
                continue
            if not isinstance(value, bool):
                raise ValueError(f"{extra_labels[field]}必须使用开关值")
            clean_extra[field] = value
        if (
            language in CLONE_PROMPT_TEXT_REQUIRED_IDS
            and "prompt_text" not in clean_extra
        ):
            raise ValueError("该复刻语种必须填写音源转写文本")
        if (
            clean_extra.get("prosody_boost") is True
            and language in CLONE_PROSODY_UNSUPPORTED_IDS
        ):
            raise ValueError("该复刻语种不支持韵律美化")
        if clean_extra:
            payload["extra_params"] = clean_extra
        return await self._post_voice_api("/api/v3/tts/voice_clone", payload)

    async def query_voice(
        self, voice_id: str, custom_speaker_id: str | None = None
    ) -> dict:
        """Query one Seed TTS 3.0 voice by speaker ID or custom name.

        Args:
            voice_id: Existing speaker ID, or ``custom_speaker_id`` for a custom name.
            custom_speaker_id: Custom name when ``voice_id`` is ``custom_speaker_id``.

        Returns:
            The voice query response.

        Raises:
            ValueError: If the query identifiers are invalid.
        """
        if not isinstance(voice_id, str) or not voice_id.strip():
            raise ValueError("音色 ID 不能为空")
        voice_id = voice_id.strip()
        payload = {"speaker_id": voice_id}
        if custom_speaker_id is not None:
            if not isinstance(custom_speaker_id, str):
                raise ValueError("自定义音色 ID 必须是字符串")
            custom_speaker_id = custom_speaker_id.strip()
            if voice_id != "custom_speaker_id":
                raise ValueError("查询自定义音色时 ID 格式不正确")
            if not CUSTOM_SPEAKER_ID_RE.fullmatch(custom_speaker_id):
                raise ValueError("自定义音色 ID 不符合命名规则")
            payload["custom_speaker_id"] = custom_speaker_id
        return await self._post_voice_api("/api/v3/tts/get_voice", payload)

    async def call_api(
        self,
        text: str,
        raw_params: dict[str, Any],
        config: dict[str, Any],
        voice_id: str | None = None,
    ) -> str:
        """Synthesize text through HTTP streaming and save a complete audio file.

        Args:
            text: Original synthesis text.
            raw_params: Parameters returned by the enhancement Tool.
            config: Provider configuration with the injected audio data directory.
            voice_id: Optional preview voice ID overriding the configured voice.

        Returns:
            Saved audio path, or an empty string when synthesis fails.
        """
        try:
            api_key, client_kwargs, timeout = self._voice_client_settings()
        except ValueError:
            logger.error("[VolcengineSeedTTS3] API Key is not configured")
            return ""
        selected_voice = voice_id or self.entry.get("voice_id")
        if not isinstance(selected_voice, str) or not selected_voice.strip():
            logger.error("[VolcengineSeedTTS3] voice_id is not configured")
            return ""

        params = self.sanitize_params(raw_params)
        final_text = params.get("text", text)
        if not isinstance(final_text, str) or not final_text.strip():
            logger.error("[VolcengineSeedTTS3] Synthesis text is empty")
            return ""
        final_text = final_text.strip()
        max_chars = self._as_int(config.get("max_input_chars", MAX_INPUT_CHARS))
        if max_chars is None or not 1 <= max_chars <= MAX_INPUT_CHARS:
            max_chars = MAX_INPUT_CHARS
        if len(final_text) > max_chars:
            logger.error(
                "[VolcengineSeedTTS3] Text length %s exceeds limit %s",
                len(final_text),
                max_chars,
            )
            return ""

        payload = self._build_payload(final_text, config, params)
        headers = {
            "X-Api-Key": api_key.strip(),
            "Content-Type": "application/json",
            "X-Request-Id": str(uuid4()),
        }
        url = f"{API_HOST}/api/v3/text-to-speech/{quote(selected_voice.strip(), safe='')}/streaming"

        def log_error(error: Any, fallback: str = "") -> None:
            details = error if isinstance(error, dict) else {}
            code = details.get("code")
            logger.error(
                "[VolcengineSeedTTS3] API error: status=%s type=%s code=%s "
                "param=%s request_id=%s message=%s",
                status,
                details.get("type"),
                code,
                details.get("param"),
                details.get("request_id"),
                details.get("message") or fallback,
            )
            guidance = _ERROR_GUIDANCE.get(code) if isinstance(code, str) else None
            if guidance:
                logger.error("[VolcengineSeedTTS3] %s", guidance)

        status = 0
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                async with client.stream(
                    "POST", url, headers=headers, json=payload
                ) as response:
                    status = response.status_code
                    if status != 200:
                        body = await response.aread()
                        error = None
                        try:
                            data = json.loads(body)
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            data = None
                        if isinstance(data, dict):
                            if data.get("event") == "error":
                                error = data.get("error")
                            elif isinstance(data.get("error"), dict):
                                error = data["error"]
                        if error is None:
                            for line in body.splitlines() or [body]:
                                try:
                                    data = json.loads(line)
                                except (json.JSONDecodeError, UnicodeDecodeError):
                                    continue
                                if not isinstance(data, dict):
                                    continue
                                if data.get("event") == "error":
                                    error = data.get("error")
                                    break
                                if isinstance(data.get("error"), dict):
                                    error = data["error"]
                                    break
                        log_error(error, body.decode("utf-8", errors="replace"))
                        return ""

                    audio_chunks: list[bytes] = []
                    stream_final = False
                    async for line in _iter_jsonl_lines(response):
                        if not line.strip():
                            continue
                        try:
                            event = json.loads(line)
                        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                            logger.error(
                                "[VolcengineSeedTTS3] Invalid JSONL event: %s", exc
                            )
                            return ""
                        if not isinstance(event, dict):
                            logger.error(
                                "[VolcengineSeedTTS3] JSONL event is not an object"
                            )
                            return ""

                        event_type = event.get("event")
                        if event_type == "error":
                            log_error(
                                event.get("error"),
                                line.decode("utf-8", errors="replace"),
                            )
                            return ""
                        if event_type == "audio":
                            encoded = event.get("audio")
                            if encoded is None or encoded == "":
                                continue
                            if not isinstance(encoded, str):
                                logger.error(
                                    "[VolcengineSeedTTS3] Audio event has invalid data"
                                )
                                return ""
                            try:
                                chunk = base64.b64decode(encoded, validate=True)
                            except (binascii.Error, ValueError) as exc:
                                logger.error(
                                    "[VolcengineSeedTTS3] Invalid Base64 audio chunk: %s",
                                    exc,
                                )
                                return ""
                            if chunk:
                                audio_chunks.append(chunk)
                        elif event_type == "final":
                            if (
                                event.get("is_final") is not True
                                or event.get("reason") != FINAL_REASON
                            ):
                                logger.error(
                                    "[VolcengineSeedTTS3] Abnormal final event: %s",
                                    event,
                                )
                                return ""
                            stream_final = True
                            break

                    if not stream_final:
                        logger.error(
                            "[VolcengineSeedTTS3] Stream ended without a valid final event"
                        )
                        return ""
                    audio = b"".join(audio_chunks)
                    if not audio:
                        logger.error(
                            "[VolcengineSeedTTS3] Stream contained no audio data"
                        )
                        return ""
        except httpx.TimeoutException:
            logger.error(
                "[VolcengineSeedTTS3] Request timed out after %s seconds", timeout
            )
            return ""
        except httpx.HTTPError as exc:
            logger.error("[VolcengineSeedTTS3] HTTP streaming failed: %s", exc)
            return ""
        except Exception:
            logger.exception("[VolcengineSeedTTS3] Synthesis failed")
            return ""

        extension = (
            "ogg"
            if payload["output_format"]["format"] == "ogg_opus"
            else payload["output_format"]["format"]
        )
        return save_audio_bytes(config.get("_data_dir", ""), audio, extension)
