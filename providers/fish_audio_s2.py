"""Fish Audio (S2 / S2-Pro) TTS 适配器模块。

封装 ``FishAudioS2Adapter``，对接 Fish Audio 的 ``POST /v1/tts`` 接口。

核心要点
--------
- 端点：``https://api.fish.audio/v1/tts``
- 鉴权：``Authorization: Bearer <api_key>``
- **模型不在请求体里**，而是放在请求头 ``model``（如 ``s2.1-pro``、
  ``s2.1-pro-free``、``s2-pro``）；省略或非法时平台回退到 ``s2.1-pro``。
- 成功（200）直接返回音频二进制流（按 ``format`` 决定 wav/pcm/mp3/opus）；
  错误（401/402/503 等）返回 JSON（含 ``message`` / ``reason``）。
- 情绪 / 风格控制：S2 系列支持在 ``text`` 里用方括号标记情绪，
  如 ``[happy]``、``[warm and happy]``，支持自然语言描述与多标记组合
  （每句最多约 3 个）；不需要单独的 emotion 配置字段，跨句改变情绪时
  直接在各句开头写不同标记即可。

音色通过 ``reference_id``（Voice Library 模型 ID 或克隆所得 ID）指定，
也可由 ``voice_id`` 参数在预览时覆盖。
"""

from typing import Any

import httpx

from astrbot.api import logger

from .base import TTSProviderAdapter
from .utils.audio import save_audio_bytes
from .utils.http import bearer_headers, extract_error_message

# Fish Audio TTS 端点
API_URL = "https://api.fish.audio/v1/tts"

# 本适配器支持的模型（S2 系列；S1 已弃用且圆括号语法不同，drama-3 控制方式另写）
FISH_AUDIO_MODELS = [
    "s2.1-pro",
    "s2.1-pro-free",
    "s2-pro",
]


class FishAudioS2Adapter(TTSProviderAdapter):
    """Fish Audio (S2 / S2-Pro) TTS 适配器。"""

    def __init__(self, entry: dict) -> None:
        super().__init__(entry)
        logger.debug(
            f"Initialized FishAudioS2Adapter with template_key={self.template_key}"
        )

    # ————————————————————————————————
    # 工具 Schema 与 SubAgent 提示词
    # ————————————————————————————————

    def get_tool_schema(self) -> Any:
        """返回 tts_enhance 工具。

        Fish Audio 的风格/情绪控制以文本内联标记为主，工具仅暴露：
        - text（必填，合成文本，情绪标记直接写进此处）
        - speed（语速 0.5~2.0）
        - volume（音量 dB）
        - language（BCP-47 语言标签，仅影响数字/日期口语化读法）
        """
        return self.build_enhance_tool(
            "为 Fish Audio 语音合成提供增强参数。"
            "情绪/风格请用方括号标记直接写进 text（如 [happy]、[warm and happy]），"
            "可跨句改变；语速、音量与语言用对应字段控制。",
            {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": (
                            "合成文本。情绪/风格标记直接写进文本，"
                            "如 '[happy] 今天天气真好'、'[angry][shouting] 出去！'；"
                            "支持自然语言描述（'[warm and happy]'）与多标记组合（每句最多约 3 个）。"
                        ),
                    },
                    "speed": {
                        "type": "number",
                        "description": "语速，范围 0.5~2.0，默认 1.0。",
                    },
                    "volume": {
                        "type": "number",
                        "description": "音量，单位 dB，默认 0；正数更响、负数更轻；范围 -20~20，超出由适配器裁剪到边界。",
                    },
                    "language": {
                        "type": "string",
                        "description": (
                            "BCP-47 语言标签，如 zh-CN、en、es-MX、ja-JP；"
                            "仅影响数字/日期等口语化读法，不改变口音或音质。"
                        ),
                    },
                },
                "required": ["text"],
            },
        )

    def get_subagent_system_prompt(self) -> str:
        return (
            "你是语音合成参数优化助手，负责为 Fish Audio 准备合成参数。"
            "Fish Audio 通过文本内联方括号标记表达情绪与风格，请调用 `tts_enhance` 工具：\n"
            "- text 必填，为待合成文本；情绪/风格标记（如 [happy]、[warm and happy]）"
            "直接写进 text，可跨句改变，每句最多约 3 个；\n"
            "- speed 可选，语速 0.5~2.0；\n"
            "- volume 可选，音量 dB（默认 0，范围 -20~20，超出由适配器裁剪）；\n"
            "- language 可选，BCP-47 标签（如 zh-CN、en），仅影响数字/日期读法。\n"
            "根据对话内容与情绪，为合适的句子加 [标记] 来表达语气/情绪。直接调用工具，不要额外解释。\n\n"
            "参考能力说明：\n"
            f"{self.docs_content}"
        )

    # ————————————————————————————————
    # 参数校验 / 清洗（契约要求输出仅含 text/speed/volume/language）
    # ————————————————————————————————

    def validate_params(self, params: dict) -> tuple[bool, str]:
        if "speed" in params and params["speed"] is not None:
            s = self._as_float(params["speed"])
            if s is None or not (0.5 <= s <= 2.0):
                return False, "speed 必须在 0.5~2.0 之间"
        if "volume" in params and params["volume"] is not None:
            if self._as_float(params["volume"]) is None:
                return False, "volume 必须是数字"
        if "language" in params and params["language"] is not None:
            if not isinstance(params["language"], str):
                return False, "language 必须是字符串"
        return True, ""

    def sanitize_params(self, params: dict) -> dict:
        out: dict[str, Any] = {"text": params.get("text", "")}
        s = self._as_float(params.get("speed"))
        if s is not None and 0.5 <= s <= 2.0:
            out["speed"] = s
        v = self._as_float(params.get("volume"))
        if v is not None:
            out["volume"] = v
        lang = params.get("language")
        if lang and isinstance(lang, str) and lang.strip():
            out["language"] = lang.strip()
        return out

    # ————————————————————————————————
    # 语音合成
    # ————————————————————————————————

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

    async def call_api(
        self,
        text: str,
        raw_params: dict[str, Any],
        config: dict[str, Any],
        voice_id: str | None = None,
    ) -> str:
        """调用 Fish Audio TTS 合成语音并保存为本地音频文件。"""
        api_key = config.get("api_key")
        if not api_key:
            logger.error("Fish Audio API Key 未配置")
            return ""

        model = config.get("model") or FISH_AUDIO_MODELS[1]  # s2.1-pro-free
        if model not in FISH_AUDIO_MODELS:
            logger.warning(f"不支持的模型 {model}，将使用 {FISH_AUDIO_MODELS[1]}")
            model = FISH_AUDIO_MODELS[1]

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

        # reference_id：预览时 voice_id 优先，否则用配置项
        ref = voice_id or config.get("reference_id") or None
        if ref:
            payload["reference_id"] = ref

        # 格式相关编码参数（仅对应格式生效）
        if fmt == "mp3":
            br = self._as_int(config.get("mp3_bitrate", 128))
            payload["mp3_bitrate"] = br if br in (64, 128, 192) else 128
        elif fmt in ("wav", "pcm"):
            sr = self._as_int(config.get("sample_rate", 44100))
            payload["sample_rate"] = sr if sr is not None else 44100
        elif fmt == "opus":
            ob = self._as_int(config.get("opus_bitrate", -1000))
            payload["opus_bitrate"] = ob if ob is not None else -1000

        # language（来自工具，可选）
        lang = raw_params.get("language")
        if lang and isinstance(lang, str) and lang.strip():
            payload["language"] = lang.strip()

        # prosody：speed/volume 来自工具，normalize_loudness 来自配置
        prosody: dict[str, Any] = {}
        speed = self._as_float(raw_params.get("speed"))
        if speed is not None and 0.5 <= speed <= 2.0:
            prosody["speed"] = speed
        volume = self._as_float(raw_params.get("volume"))
        if volume is not None:
            # Fish Audio 限制音量为 -20~20 dB，超出边界由服务端拒绝，故在此裁剪
            volume = max(-20.0, min(20.0, volume))
            prosody["volume"] = volume
        nl = config.get("normalize_loudness", True)
        if isinstance(nl, bool):
            prosody["normalize_loudness"] = nl
        if prosody:
            payload["prosody"] = prosody

        # 采样等引擎参数（来自配置，建议保持默认）
        float_keys = (
            "temperature",
            "top_p",
            "repetition_penalty",
            "early_stop_threshold",
        )
        int_keys = ("chunk_length", "min_chunk_length", "max_new_tokens")
        for key in float_keys:
            val = config.get(key)
            parsed = self._as_float(val)
            if parsed is not None:
                payload[key] = parsed
        for key in int_keys:
            val = config.get(key)
            parsed = self._as_int(val)
            if parsed is not None:
                payload[key] = parsed
        cp = config.get("condition_on_previous_chunks", True)
        if isinstance(cp, bool):
            payload["condition_on_previous_chunks"] = cp

        # features：逗号分隔字符串 → 数组
        feat = config.get("features", "")
        if isinstance(feat, str) and feat.strip():
            payload["features"] = [f.strip() for f in feat.split(",") if f.strip()]

        # 发音词典（平台引用形式：id + version）
        if config.get("use_pronunciation_dictionary"):
            pid = config.get("pronunciation_dictionary_id")
            pver = config.get("pronunciation_dictionary_version")
            if pid and pver:
                payload["pronunciation_dictionary"] = [{"id": pid, "version": pver}]
            else:
                logger.warning("已启用发音词典但未提供完整 id/version，将忽略该参数")

        headers = bearer_headers(api_key)
        headers["model"] = model
        timeout = self._as_int(config.get("timeout", 120)) or 120

        try:
            async with httpx.AsyncClient(**self._http_kwargs(timeout)) as client:
                resp = await client.post(API_URL, headers=headers, json=payload)
                resp.raise_for_status()
                content = resp.content
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            try:
                err = extract_error_message(e.response.json(), e.response.text)
            except Exception:
                err = e.response.text or str(e)
            logger.error(f"Fish Audio TTS 调用失败 ({status}): {err}")
            return ""
        except httpx.TimeoutException:
            logger.error(f"Fish Audio TTS 超时 (timeout={timeout}s)")
            return ""
        except Exception as e:
            logger.error(f"Fish Audio TTS 调用失败: {e}")
            return ""

        if not content:
            logger.error("Fish Audio 响应无音频数据")
            return ""

        return save_audio_bytes(config.get("_data_dir", ""), content, fmt)
