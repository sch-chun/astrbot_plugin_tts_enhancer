"""Xiaomi MiMo V2.5 TTS adapter module.

Provides ``MimoV2_5TTSAdapter``, which wraps the OpenAI-compatible
chat-completions endpoint exposed by Xiaomi MiMo to perform speech synthesis.
It supports the three MiMo-V2.5-TTS models:

- ``mimo-v2.5-tts``: synthesis with preset voices.
- ``mimo-v2.5-tts-voicedesign``: synthesis driven by a text voice prompt.
- ``mimo-v2.5-tts-voiceclone``: synthesis driven by an audio sample.
"""

import base64
import hashlib

from pathlib import Path

from typing import Any, Optional

import httpx

from astrbot.api import logger
from astrbot.core.agent.tool import FunctionTool

from .base import TTSProviderAdapter
from .utils import http
from .utils.audio import save_audio_bytes


class MimoV2_5TTSAdapter(TTSProviderAdapter):
    """Xiaomi MiMo V2.5 TTS provider adapter.

    Implements speech synthesis through the OpenAI-compatible
    ``/chat/completions`` endpoint. The synthesized text is placed in an
    ``assistant`` message while style instructions or voice design prompts are
    placed in a ``user`` message, per the upstream API contract.
    """

    # Supported MiMo-V2.5-TTS models.
    MODEL_PRESET = "mimo-v2.5-tts"
    MODEL_VOICE_DESIGN = "mimo-v2.5-tts-voicedesign"
    MODEL_VOICE_CLONE = "mimo-v2.5-tts-voiceclone"
    SUPPORTED_MODELS = (MODEL_PRESET, MODEL_VOICE_DESIGN, MODEL_VOICE_CLONE)

    # The upstream endpoint is fixed and documented at
    # https://mimo.mi.com/docs/zh-CN/api/audio/tts.
    _API_ENDPOINT = "https://api.xiaomimimo.com/v1/chat/completions"

    DEFAULT_VOICE = "mimo_default"
    DEFAULT_FORMAT = "wav"
    VALID_FORMATS = ("wav", "mp3", "pcm")

    # MiMo requires the *base64-encoded* voice sample to stay under 10 MB.
    MAX_VOICE_BASE64_BYTES = 10 * 1024 * 1024

    # MIME type lookup for the supported voice sample extensions.
    _MIME_BY_EXT = {".mp3": "audio/mpeg", ".wav": "audio/wav"}

    _CACHE_DIRNAME = "cache/mimo_voiceclone"

    def __init__(self, entry: dict) -> None:
        """Initialize the adapter and pre-encode the voice sample if needed.

        The main flow injects ``_data_dir`` into ``entry`` before calling
        ``get_adapter``, so the voiceclone sample can be encoded and cached
        here, mirroring how other providers read paths from config.

        Args:
            entry: Provider config dictionary (``__template_key``, ``model``,
                ``voice_sample``, ``_data_dir`` and other fields).
        """
        super().__init__(entry)

        self._voice_data_url: Optional[str] = None
        self.preset_docs_content = self._load_preset_docs()
        self._prepare_voice_sample()

    def _load_preset_docs(self) -> str:
        """Load the capability doc dedicated to the preset voice model.

        The preset model additionally supports the singing tag, which the
        voicedesign and voiceclone models do not, so it uses a dedicated doc.
        The doc is only read for the preset model; other models return empty.

        Returns:
            The preset voice doc content, or an empty string when not needed
            or when the file is missing.
        """
        if self.entry.get("model") != self.MODEL_PRESET:
            return ""

        docs_path = Path(__file__).parent / "docs" / f"{self.template_key}_preset.md"
        if docs_path.exists():
            return docs_path.read_text(encoding="utf-8")
        logger.warning(f"[MiMo] 预置音色文档不存在: {docs_path}")
        return ""

    def get_docs_for_model(self) -> str:
        """Return the capability doc matching the configured model.

        Returns:
            The preset doc for the preset model, otherwise the common doc.
        """
        if self.entry.get("model") == self.MODEL_PRESET:
            return self.preset_docs_content or self.docs_content
        return self.docs_content

    def _prepare_voice_sample(self) -> None:
        """Pre-encode and cache the voice sample for ``voiceclone`` entries.

        The base64 payload is cached under ``<plugin_data>/cache/mimo_voiceclone``
        keyed by a digest of the source path plus its size and mtime, so the
        sample is re-encoded only when the underlying file changes. The encoded
        size is checked against MiMo's 10 MB limit. The data root is derived
        from ``entry["_data_dir"]``, which points at ``<plugin_data>/audio``.

        Raises:
            ValueError: If the encoded sample exceeds the 10 MB limit or the
                configured path escapes the plugin data directory.
        """
        if self.entry.get("model") != self.MODEL_VOICE_CLONE:
            return

        data_dir = self.entry.get("_data_dir", "")
        if not data_dir:
            logger.warning("[MiMo] 未注入 _data_dir，无法定位 voice_sample")
            return

        samples = self.entry.get("voice_sample")
        if not isinstance(samples, list) or not samples:
            logger.debug("[MiMo] voiceclone 未配置 voice_sample，跳过样本预编码")
            return

        rel_path = str(samples[0]).strip()
        if not rel_path:
            logger.debug("[MiMo] voiceclone 未配置 voice_sample，跳过样本预编码")
            return

        root = Path(data_dir).parent
        sample_path = (root / rel_path).resolve()
        try:
            sample_path.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(f"voice_sample 路径越权: {rel_path!r}") from exc

        if not sample_path.is_file():
            logger.warning(f"[MiMo] voice_sample 文件不存在: {sample_path}")
            return

        mime = self._MIME_BY_EXT.get(sample_path.suffix.lower())
        if mime is None:
            logger.error(f"[MiMo] 不支持的 voice_sample 格式: {sample_path.suffix}")
            return

        stat = sample_path.stat()
        digest = hashlib.sha1(str(sample_path).encode("utf-8")).hexdigest()[:12]
        cache_file = (
            root / self._CACHE_DIRNAME / f"{digest}_{stat.st_mtime_ns}_{stat.st_size}.b64"
        )

        if cache_file.is_file():
            encoded = cache_file.read_text(encoding="ascii")
            logger.debug(f"[MiMo] 命中 voice_sample 缓存: {cache_file.name}")
        else:
            encoded = base64.b64encode(sample_path.read_bytes()).decode("ascii")

            if len(encoded.encode("utf-8")) > self.MAX_VOICE_BASE64_BYTES:
                raise ValueError(
                    f"voice_sample 编码后超过 10MB 限制 "
                    f"({len(encoded) / 1024 / 1024:.1f} MB)，请使用更小的音频样本"
                )

            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(encoded, encoding="ascii")
            logger.debug(f"[MiMo] voice_sample 已编码缓存: {cache_file.name}")

        self._voice_data_url = f"data:{mime};base64,{encoded}"

    def _normalize_model(self, model: Optional[str]) -> str:
        """Normalize and validate the requested model identifier.

        Args:
            model: The configured model identifier.

        Returns:
            The normalized model identifier.

        Raises:
            ValueError: If the model is unsupported.
        """
        model = model or self.MODEL_PRESET
        if model not in self.SUPPORTED_MODELS:
            raise ValueError(f"不支持的 MiMo 模型: {model}，支持: {self.SUPPORTED_MODELS}")
        return model

    def _build_payload(
        self,
        text: str,
        instruction: Optional[str],
        voice_id: Optional[str],
        format_type: str,
    ) -> dict:
        """Build the chat-completions payload for the configured model.

        Args:
            text: The text to synthesize (assistant message).
            instruction: Optional natural-language style instruction (user message).
            voice_id: Explicit voice override, used for preset voice previews.
            format_type: The output audio format.

        Returns:
            The JSON payload to POST to ``/chat/completions``.

        Raises:
            ValueError: If a required field for the selected model is missing.
        """
        model = self._normalize_model(self.entry.get("model"))

        if model == self.MODEL_PRESET:
            voice = voice_id or self.entry.get("voice")
            if not voice:
                logger.warning("[MiMo] 未配置预置音色，使用默认语音")
                self.DEFAULT_VOICE
            messages = []
            if instruction:
                messages.append({"role": "user", "content": instruction})
            messages.append({"role": "assistant", "content": text})
            audio = {"format": format_type, "voice": voice}

        elif model == self.MODEL_VOICE_DESIGN:
            voice_prompt = self.entry.get("voice_prompt", "")
            if not voice_prompt:
                raise ValueError("mimo-v2.5-tts-voicedesign 需要配置 voice_prompt")

            messages = [{"role": "user", "content": voice_prompt}]

            # When text optimization is enabled, the assistant message may be
            # omitted so the model generates a matching line itself.
            optimize = bool(self.entry.get("optimize_text_preview", False))
            if text or not optimize:
                messages.append({"role": "assistant", "content": text})
            audio = {"format": format_type, "optimize_text_preview": optimize}

        else:  # MODEL_VOICE_CLONE
            if not self._voice_data_url:
                raise ValueError(
                    "mimo-v2.5-tts-voiceclone 需要有效的 voice_sample 配置"
                )
            messages = []
            if instruction:
                messages.append({"role": "user", "content": instruction})
            messages.append({"role": "assistant", "content": text})
            audio = {"format": format_type, "voice": self._voice_data_url}

        return {"model": model, "messages": messages, "audio": audio}

    # ———————— 语音合成 ————————

    def get_tool_schema(self) -> FunctionTool:
        """Return the TTS enhancement tool schema.

        Returns:
            A FunctionTool exposing ``text`` and an optional ``instruction``
            used for natural-language style control.
        """
        return FunctionTool(
            name="tts_enhance",
            description="为 MiMo V2.5 TTS 语音合成提供文本与自然语言风格指令。",
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "需要合成的文本。",
                    },
                    "instruction": {
                        "type": "string",
                        "description": (
                            "自然语言风格/情绪/导演指令，用于控制语音的语调、语速、"
                            "语气与角色演绎。可为空。"
                        ),
                    },
                },
                "required": ["text"],
            },
            handler=None,
        )

    def get_subagent_system_prompt(self) -> str:
        """Return the SubAgent system prompt for parameter optimization.

        Returns:
            The prompt string, embedding the model-specific capability docs.
        """
        docs = self.get_docs_for_model()
        return f"""你是 MiMo V2.5 TTS 语音合成参数优化助手。以下是 MiMo V2.5 TTS 的能力说明：

{docs}

请根据用户提供的文本和上下文，调用 `tts_enhance` 工具，提供合适的 text 与可选的 instruction。直接调用工具，不要额外解释。"""

    async def call_api(
        self,
        text: str,
        raw_params: dict[str, Any],
        config: dict[str, Any],
        voice_id: Optional[str] = None,
    ) -> str:
        """Synthesize speech via the MiMo chat-completions endpoint.

        Args:
            text: Original text to synthesize (fallback when no params exist).
            raw_params: Enhanced params from the SubAgent (``text``,
                ``instruction`` preferred).
            config: Provider config including ``api_key``, ``_data_dir``, etc.
            voice_id: Optional explicit preset voice override.

        Returns:
            The saved audio file path, or an empty string on failure.
        """
        api_key = config.get("api_key", "")
        if not api_key:
            logger.error("[MiMo] api_key 未配置")
            return ""

        format_type = config.get("format") or self.DEFAULT_FORMAT
        if format_type not in self.VALID_FORMATS:
            logger.warning(
                f"[MiMo] 不支持的音频格式 {format_type}，回退到 {self.DEFAULT_FORMAT}"
            )
            format_type = self.DEFAULT_FORMAT
        timeout = config.get("timeout", 60)

        final_text = raw_params.get("text") or text
        if not final_text:
            logger.error("[MiMo] TTS 文本为空")
            return ""

        instruction = raw_params.get("instruction")
        if instruction and not isinstance(instruction, str):
            instruction = None

        try:
            payload = self._build_payload(final_text, instruction, voice_id, format_type)
        except ValueError as e:
            logger.error(f"[MiMo] {e}")
            return ""

        url = self._API_ENDPOINT
        headers = http.bearer_headers(api_key)

        logger.debug(f"[MiMo] 请求参数: {payload}")

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()

            if isinstance(data, dict) and data.get("error"):
                logger.error(
                    f"[MiMo] API 错误: {http.extract_error_message(data)}"
                )
                return ""

            audio_data = data.get("choices", [{}])[0].get("message", {}).get(
                "audio", {}
            ).get("data")
            if not audio_data:
                logger.error(f"[MiMo] 响应中无音频数据: {data}")
                return ""

            audio_bytes = base64.b64decode(audio_data)
            return save_audio_bytes(config.get("_data_dir", ""), audio_bytes, format_type)

        except httpx.TimeoutException:
            logger.error(f"[MiMo] API 超时 (timeout={timeout}s)")
            return ""
        except Exception:
            logger.exception("[MiMo] API 调用失败")
            return ""

    # ————————————————————————

    # ———————— 参数校验 ————————

    def validate_params(self, params: dict) -> tuple[bool, str]:
        """Validate the enhanced TTS params.

        Args:
            params: The params dict, may contain ``text`` and ``instruction``.

        Returns:
            A tuple of (valid, error message).
        """
        if "text" in params and not str(params.get("text", "")).strip():
            return False, "text 不能为空"

        if "instruction" in params and not isinstance(params.get("instruction"), str):
            return False, "instruction 必须为字符串"

        return True, ""

    def sanitize_params(self, params: dict) -> dict:
        """Sanitize enhanced params, dropping invalid entries.

        Args:
            params: The params dict to sanitize.

        Returns:
            The sanitized dict containing ``text`` and optionally ``instruction``.
        """
        sanitized: dict[str, Any] = {"text": str(params.get("text", ""))}

        instruction = params.get("instruction")
        if isinstance(instruction, str):
            sanitized["instruction"] = instruction
        elif instruction is not None:
            logger.warning(f"[MiMo] 丢弃非法的 instruction 参数: {instruction}")

        return sanitized

    # ————————————————————————
