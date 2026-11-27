"""Fish Audio Text-to-Speech 公共适配器。"""

from typing import Any

import httpx

from astrbot.api import logger

from .base import TTSProviderAdapter
from .utils.audio import save_audio_bytes
from .utils.http import bearer_headers, extract_error_message

API_URL = "https://api.fish.audio/v1/tts"
S2_MODELS = ("s2.1-pro", "s2.1-pro-free", "s2-pro")
MIN_SPEED = 0.5
MAX_SPEED = 2.0


class FishAudioAdapter(TTSProviderAdapter):
    SUPPORTED_MODELS = S2_MODELS
    DEFAULT_MODEL = "s2.1-pro-free"
    MODEL_NAME = ""
    SUPPORTS_LOUDNESS_NORMALIZATION = True
    TOOL_EXTRA_FIELDS = frozenset({"language", "speed", "volume"})

    def _resolve_model(self, config: dict[str, Any]) -> str:
        if self.MODEL_NAME:
            return self.MODEL_NAME
        model = config.get("model") or self.DEFAULT_MODEL
        if model not in self.SUPPORTED_MODELS:
            logger.warning(f"不支持的模型 {model}，将使用 {self.DEFAULT_MODEL}")
            model = self.DEFAULT_MODEL
        return model

    def validate_params(self, params: dict) -> tuple[bool, str]:
        if "speed" in params and params["speed"] is not None:
            speed = self._as_float(params["speed"])
            if speed is None or not (MIN_SPEED <= speed <= MAX_SPEED):
                return False, f"speed 必须在 {MIN_SPEED}~{MAX_SPEED} 之间"
        if "volume" in params and params["volume"] is not None:
            if self._as_float(params["volume"]) is None:
                return False, "volume 必须是数字"
        if "language" in params and params["language"] is not None:
            if not isinstance(params["language"], str):
                return False, "language 必须是字符串"
        return True, ""

    def sanitize_params(self, params: dict) -> dict:
        out: dict[str, Any] = {"text": params.get("text", "")}
        speed = self._as_float(params.get("speed"))
        if speed is not None and MIN_SPEED <= speed <= MAX_SPEED:
            out["speed"] = speed
        volume = self._as_float(params.get("volume"))
        if volume is not None:
            out["volume"] = volume
        language = params.get("language")
        if language and isinstance(language, str) and language.strip():
            out["language"] = language.strip()
        return out

    def _http_kwargs(self, timeout: int) -> dict:
        kwargs: dict[str, Any] = {"timeout": timeout}
        proxy = self.entry.get("proxy")
        if isinstance(proxy, str) and proxy.strip():
            kwargs["proxy"] = proxy.strip()
        return kwargs

    def _resolve_reference_id(
        self, voice_id: str | None, config: dict[str, Any]
    ) -> str | None:
        return voice_id or config.get("reference_id") or None

    async def call_api(
        self,
        text: str,
        raw_params: dict[str, Any],
        config: dict[str, Any],
        voice_id: str | None = None,
    ) -> str:
        api_key = config.get("api_key")
        if not api_key:
            logger.error("Fish Audio API Key 未配置")
            return ""

        model = self._resolve_model(config)

        final_text = raw_params.get("text") or text
        if not final_text:
            logger.error("TTS 文本为空")
            return ""

        fmt = config.get("format", "mp3")
        if fmt not in ("mp3", "wav", "pcm", "opus"):
            logger.warning(f"不支持的格式 {fmt}，回退到 mp3")
            fmt = "mp3"

        payload: dict[str, Any] = {
            "text": final_text,
            "format": fmt,
            "latency": config.get("latency", "normal"),
            "normalize": bool(config.get("normalize", True)),
        }

        reference_id = self._resolve_reference_id(voice_id, config)
        if reference_id:
            payload["reference_id"] = reference_id

        if fmt == "mp3":
            bitrate = self._as_int(config.get("mp3_bitrate", 128))
            payload["mp3_bitrate"] = bitrate if bitrate in (64, 128, 192) else 128
        elif fmt in ("wav", "pcm"):
            sample_rate = self._as_int(config.get("sample_rate", 44100))
            payload["sample_rate"] = sample_rate if sample_rate is not None else 44100
        elif fmt == "opus":
            bitrate = self._as_int(config.get("opus_bitrate", -1000))
            payload["opus_bitrate"] = bitrate if bitrate is not None else -1000

        language = raw_params.get("language")
        if language and isinstance(language, str) and language.strip():
            payload["language"] = language.strip()

        prosody: dict[str, Any] = {}
        speed = self._as_float(raw_params.get("speed"))
        if speed is not None and MIN_SPEED <= speed <= MAX_SPEED:
            prosody["speed"] = speed
        volume = self._as_float(raw_params.get("volume"))
        if volume is not None:
            prosody["volume"] = volume
        normalize_loudness = config.get("normalize_loudness", True)
        if self.SUPPORTS_LOUDNESS_NORMALIZATION and isinstance(
            normalize_loudness, bool
        ):
            prosody["normalize_loudness"] = normalize_loudness
        if prosody:
            payload["prosody"] = prosody

        for key in (
            "temperature",
            "top_p",
            "repetition_penalty",
            "early_stop_threshold",
        ):
            value = self._as_float(config.get(key))
            if value is not None:
                payload[key] = value
        for key in ("chunk_length", "min_chunk_length", "max_new_tokens"):
            value = self._as_int(config.get(key))
            if value is not None:
                payload[key] = value
        condition_on_previous_chunks = config.get("condition_on_previous_chunks", True)
        if isinstance(condition_on_previous_chunks, bool):
            payload["condition_on_previous_chunks"] = condition_on_previous_chunks

        features = config.get("features", "")
        if isinstance(features, str) and features.strip():
            payload["features"] = [
                item.strip() for item in features.split(",") if item.strip()
            ]

        if config.get("use_pronunciation_dictionary"):
            dictionary_id = config.get("pronunciation_dictionary_id")
            dictionary_version = config.get("pronunciation_dictionary_version")
            if dictionary_id and dictionary_version:
                payload["pronunciation_dictionary"] = [
                    {"id": dictionary_id, "version": dictionary_version}
                ]
            else:
                logger.warning("已启用发音词典但未提供完整 id/version，将忽略该参数")

        headers = bearer_headers(api_key)
        headers["model"] = model
        timeout = self._as_int(config.get("timeout", 120)) or 120

        try:
            async with httpx.AsyncClient(**self._http_kwargs(timeout)) as client:
                response = await client.post(API_URL, headers=headers, json=payload)
                response.raise_for_status()
                content = response.content
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            try:
                error = extract_error_message(
                    exc.response.json(), exc.response.text
                )
            except Exception:
                error = exc.response.text or str(exc)
            logger.error(f"Fish Audio TTS 调用失败 ({status}): {error}")
            return ""
        except httpx.TimeoutException:
            logger.error(f"Fish Audio TTS 超时 (timeout={timeout}s)")
            return ""
        except Exception as exc:
            logger.error(f"Fish Audio TTS 调用失败: {exc}")
            return ""

        if not content:
            logger.error("Fish Audio 响应无音频数据")
            return ""

        return save_audio_bytes(config.get("_data_dir", ""), content, fmt)
