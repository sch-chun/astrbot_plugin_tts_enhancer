"""ElevenLabs v4 TTS 适配器模块。

封装 ``ElevenLabsV4Adapter``，对接 ElevenLabs 的
``POST /v1/text-to-speech/{voice_id}`` 接口（非流式 convert）。

核心要点
--------
- 端点：``{base_url}/v1/text-to-speech/{voice_id}``（base_url 默认 api.elevenlabs.io）
- 鉴权：``xi-api-key`` 请求头（**不是** Bearer）
- 模型不在 body 默认，必须显式传 model_id（eleven_v4 / eleven_v4_turbo）
- v4 不支持 style/speed 滑块与 SSML；情绪用文本内 [标签] 控制
- output_format 由 codec + 采样率/码率组合（仅容器格式 mp3/wav/opus）
- 音频效果（audio_effects）ID 通过 GET /v1/audio-effects/catalog 实时拉取
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from astrbot.api import logger

from .base import TTSProviderAdapter
from .utils.audio import save_audio_bytes
from .utils.http import extract_error_message

# ElevenLabs TTS 路径（非流式 convert）
API_PATH = "/v1/text-to-speech"

# 支持的容器编码（裸 PCM/ulaw/alaw 无文件头，Record 无法播放，故不暴露）
OUTPUT_EXT = {"mp3": "mp3", "wav": "wav", "opus": "opus"}

# audio_effects catalog 缓存 TTL（秒）
CATALOG_TTL = 300

# 可选采样率 / 码率白名单（用于脏数据兜底）
WAV_SAMPLE_RATES = (8000, 16000, 22050, 24000, 32000, 44100, 48000)
OPUS_BITRATES = (32, 64, 96, 128, 192)


class ElevenLabsV4Adapter(TTSProviderAdapter):
    """ElevenLabs v4 / v4 Turbo TTS 适配器。"""

    def __init__(self, entry: dict) -> None:
        super().__init__(entry)
        # 缓存：(catalog, 获取时间戳)；TTL 内复用，避免每次合成打 API
        self._catalog: dict[str, list[str]] | None = None
        self._catalog_ts: float = 0.0

    # ————————————————————————————————
    # 工具 Schema 与 SubAgent 提示词
    # ————————————————————————————————

    def get_tool_schema(self) -> Any:
        """返回 tts_enhance 工具。

        文本内联 [情绪标签] / /IPA/ / <break> 控制表达；audio_effects 仅在
        use_audio_effects 开启时，通过实时拉取的 catalog 动态生成枚举。

        Returns:
            FunctionTool 实例（name=tts_enhance），或 None。
        """
        properties: dict[str, Any] = {
            "text": {
                "type": "string",
                "description": (
                    "合成文本（必填）。情绪/风格用方括号标签直接写进此处，"
                    "如 [whispering]、[excited][laughing]、[warm and happy]；"
                    "专有名词可用正斜杠包裹的 IPA 指定发音，如 /ˌbaɪoʊˈkemɪstri/；"
                    '停顿可用 <break time="1.5s" />（最长 3s，v4 行为可能不稳定）。'
                ),
            },
            "language_code": {
                "type": "string",
                "enum": [
                    "af",
                    "am",
                    "ar",
                    "hy",
                    "as",
                    "ast",
                    "az",
                    "be",
                    "bn",
                    "bs",
                    "bg",
                    "my",
                    "yue",
                    "ca",
                    "ceb",
                    "hr",
                    "cs",
                    "da",
                    "nl",
                    "en",
                    "et",
                    "fil",
                    "fi",
                    "fr",
                    "ff",
                    "gl",
                    "ka",
                    "de",
                    "el",
                    "gu",
                    "ha",
                    "he",
                    "hi",
                    "hu",
                    "is",
                    "id",
                    "it",
                    "ja",
                    "kn",
                    "kk",
                    "ko",
                    "ky",
                    "lo",
                    "ln",
                    "lt",
                    "lg",
                    "lb",
                    "mk",
                    "ms",
                    "ml",
                    "mt",
                    "cmn",
                    "mi",
                    "mr",
                    "mn",
                    "ne",
                    "nb",
                    "oc",
                    "or",
                    "ps",
                    "fa",
                    "pl",
                    "pt-BR",
                    "pa",
                    "ro",
                    "ru",
                    "sr",
                    "sn",
                    "sd",
                    "sk",
                    "sl",
                    "so",
                    "ku",
                    "es-419",
                    "sw",
                    "sv",
                    "tg",
                    "ta",
                    "te",
                    "th",
                    "tr",
                    "uk",
                    "ur",
                    "uz",
                    "vi",
                    "cy",
                    "wo",
                ],
                "description": (
                    "ISO 639-1 语言代码；v4 音色支持跨语种合成，可按需在文本中切换语言。"
                    "留空则用供应商配置的默认语言。"
                ),
            },
        }
        if self.entry.get("use_audio_effects"):
            catalog = self._load_effects_catalog()
            if catalog is None:
                logger.warning(
                    "audio_effects 目录获取失败，本次丢弃 audio_effects 参数"
                )
            else:
                properties.update(
                    {
                        "filter_preset_id": {
                            "type": "string",
                            "enum": catalog["filter_presets"],
                            "description": "音色滤镜预设，如 phone、old_radio、robot。",
                        },
                        "environment_id": {
                            "type": "string",
                            "enum": catalog["environments"],
                            "description": "混响环境，如 small_room、hall、tunnel。",
                        },
                        "background_noise_id": {
                            "type": "string",
                            "enum": catalog["background_noises"],
                            "description": "背景噪声底音，如 cafe、keyboard、city。",
                        },
                        "distance": {
                            "type": "number",
                            "description": "说话者距离感，0（近）~1（远），默认 0。",
                            "minimum": 0,
                            "maximum": 1,
                        },
                        "send_level": {
                            "type": "number",
                            "description": "混响干湿比，仅 environment_id 生效；0 关混响，默认 1。",
                            "minimum": 0,
                            "maximum": 1,
                        },
                        "pan": {
                            "type": "number",
                            "description": "立体声像位置，-1（最左）~1（最右），默认 0。",
                            "minimum": -1,
                            "maximum": 1,
                        },
                    }
                )
        return self.build_enhance_tool(
            "为 ElevenLabs 语音合成提供增强参数。"
            "情绪/风格请用方括号标签直接写进 text（如 [whispering]、[excited]）；"
            "仅在开启音频效果时填写 filter_preset_id / environment_id / "
            "background_noise_id / distance / send_level / pan。",
            {"type": "object", "properties": properties, "required": ["text"]},
        )

    def get_subagent_system_prompt(self) -> str:
        """返回驱动 SubAgent 的系统提示词（含按需注入的音频效果指引）。

        SubAgent 只能看到工具 schema 与本提示词，看不到插件配置，因此不在此
        处提及「配置」。音频效果字段是否可用完全由工具 schema 决定；当开启且
        成功拉取 catalog 时，再拼接实时 ID 枚举注入本提示词。
        """
        prompt = (
            "你是语音合成参数优化助手，负责为 ElevenLabs 准备合成参数。"
            "ElevenLabs v4 通过文本内联方括号标签表达情绪与风格，请调用 `tts_enhance` 工具：\n"
            "- text 必填，为待合成文本；情绪/风格标签（如 [whispering]、[excited]、"
            "[warm and happy]）直接写进 text；\n"
            '- 专有名词可用 /IPA/ 标注发音；停顿可用 <break time="1.5s" />；\n'
            "- 若工具提供了音频效果相关字段，请从 schema 枚举中选取填写；\n"
            "根据对话内容与情绪，为合适的句子加 [标签] 来表达语气/情绪。直接调用工具，不要额外解释。\n\n"
            "参考能力说明：\n"
            f"{self.docs_content}"
        )
        fx_guidance = self._build_audio_effects_guidance()
        if fx_guidance:
            prompt += "\n\n" + fx_guidance
        return prompt

    def _build_audio_effects_guidance(self) -> str:
        """开启音频效果且成功拉取 catalog 时，拼接实时可选值注入 SubAgent 提示。

        仅在 ``use_audio_effects`` 开启且 catalog 成功获取时返回非空字符串；
        否则返回空（不注入），避免向 SubAgent 暴露其无法看到的插件配置，也避免
        用硬编码的示例 ID 误导模型。

        Returns:
            音频效果使用指引（含实时 ID 枚举），或空字符串。
        """
        if not self.entry.get("use_audio_effects"):
            return ""
        catalog = self._load_effects_catalog()
        if not catalog:
            return ""
        lines = [
            "## 音频效果（audio_effects）",
            "`tts_enhance` 工具提供了以下音频效果字段，请从给出的枚举中选取（不要臆造）：",
        ]
        if catalog["filter_presets"]:
            lines.append(
                f"- filter_preset_id（音色滤镜）：{', '.join(catalog['filter_presets'])}"
            )
        if catalog["environments"]:
            lines.append(
                f"- environment_id（混响环境）：{', '.join(catalog['environments'])}"
            )
        if catalog["background_noises"]:
            lines.append(
                f"- background_noise_id（背景噪声）：{', '.join(catalog['background_noises'])}"
            )
        lines.append("- distance：说话者距离感 0~1（默认 0）")
        lines.append("- send_level：混响干湿比 0~1，仅 environment_id 生效（默认 1）")
        lines.append("- pan：立体声像 -1（最左）~1（最右）（默认 0）")
        lines.append(
            "仅在需要营造空间感 / 底噪 / 音色滤镜时填写，不需要则留空；不要为了用而用。"
        )
        return "\n".join(lines)

    # ————————————————————————————————
    # 参数校验 / 清洗（契约要求输出仅含合法字段）
    # ————————————————————————————————

    def validate_params(self, params: dict) -> tuple[bool, str]:
        """校验 tts_enhance 工具参数。"""
        if "text" in params and not isinstance(params["text"], str):
            return False, "text 必须是字符串"
        if "language_code" in params and not isinstance(params["language_code"], str):
            return False, "language_code 必须是字符串"
        bounds = (("distance", 0.0, 1.0), ("send_level", 0.0, 1.0), ("pan", -1.0, 1.0))
        for key, lo, hi in bounds:
            val = params.get(key)
            if val is None:
                continue
            f = self._as_float(val)
            if f is None or not (lo <= f <= hi):
                return False, f"{key} 必须在 {lo}~{hi} 之间"
        return True, ""

    def sanitize_params(self, params: dict) -> dict:
        """清洗 tts_enhance 工具参数，仅保留合法字段。"""
        out: dict[str, Any] = {}
        text = params.get("text")
        if isinstance(text, str) and text.strip():
            out["text"] = text
        for key in ("filter_preset_id", "environment_id", "background_noise_id"):
            val = params.get(key)
            if isinstance(val, str) and val.strip():
                out[key] = val.strip()
        lang = params.get("language_code")
        if isinstance(lang, str) and lang.strip():
            out["language_code"] = lang.strip()
        bounds = (("distance", 0.0, 1.0), ("send_level", 0.0, 1.0), ("pan", -1.0, 1.0))
        for key, lo, hi in bounds:
            f = self._as_float(params.get(key))
            if f is not None and lo <= f <= hi:
                out[key] = f
        return out

    # ————————————————————————————————
    # audio_effects catalog 实时拉取
    # ————————————————————————————————

    def _catalog_url(self) -> str:
        """返回 audio_effects catalog 端点（base_url 可配置）。"""
        base = (self.entry.get("base_url") or "https://api.elevenlabs.io").rstrip("/")
        return f"{base}/v1/audio-effects/catalog"

    def _load_effects_catalog(self) -> dict[str, list[str]] | None:
        """实时拉取音频效果目录并提取 ID 列表（带 TTL 缓存，阻塞式）。

        成功返回 {filter_presets, environments, background_noises} 三个 ID 列表；
        任意失败（缺 Key / 网络异常 / 结构异常）返回 None，调用方据此丢弃
        audio_effects schema 或参数。

        Returns:
            包含三类效果 ID 列表的字典，或 None。
        """
        now = time.time()
        if self._catalog is not None and now - self._catalog_ts < CATALOG_TTL:
            return self._catalog

        api_key = self.entry.get("api_key")
        if not api_key:
            logger.warning("未配置 ElevenLabs API Key，无法拉取 audio_effects 目录")
            return None
        try:
            resp = httpx.get(
                self._catalog_url(),
                headers={"xi-api-key": api_key},
                timeout=5,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"拉取 audio_effects 目录失败: {e}")
            return None

        catalog = {
            "filter_presets": self._collect_ids(
                data.get("filter_presets", []), "filter_preset_id"
            ),
            "environments": self._collect_ids(
                data.get("environments", []), "environment_id"
            ),
            "background_noises": self._collect_ids(
                data.get("background_noises", []), "background_noise_id"
            ),
        }
        if not any(catalog.values()):
            logger.warning("audio_effects 目录为空或结构异常")
            return None
        self._catalog = catalog
        self._catalog_ts = now
        return catalog

    @staticmethod
    def _collect_ids(items: Any, id_key: str) -> list[str]:
        """从 catalog 分类列表中提取 ID（容忍 None / 缺字段 / description 为 null）。"""
        ids: list[str] = []
        if not isinstance(items, list):
            return ids
        for item in items:
            if isinstance(item, dict):
                vid = item.get(id_key)
                if isinstance(vid, str) and vid:
                    ids.append(vid)
        return ids

    # ————————————————————————————————
    # 语音合成
    # ————————————————————————————————

    def _http_kwargs(self, timeout: int) -> dict:
        """构造 httpx.AsyncClient 关键字参数，统一注入代理（若已配置）。"""
        kwargs: dict[str, Any] = {"timeout": timeout}
        proxy = self.entry.get("proxy")
        if isinstance(proxy, str) and proxy.strip():
            kwargs["proxy"] = proxy.strip()
        return kwargs

    def _compose_output_format(self, config: dict) -> str:
        """根据 codec + 采样率/码率组合 ElevenLabs output_format 字符串。

        Args:
            config: 供应商配置（含 output_codec 及其条件子项）。

        Returns:
            形如 mp3_44100_128 / wav_44100 / opus_48000_128 的字符串。
        """
        codec = config.get("output_codec", "mp3")
        if codec == "wav":
            sr = self._as_int(config.get("wav_sample_rate", 44100)) or 44100
            if sr not in WAV_SAMPLE_RATES:
                sr = 44100
            return f"wav_{sr}"
        if codec == "opus":
            br = self._as_int(config.get("opus_bitrate", 128)) or 128
            if br not in OPUS_BITRATES:
                br = 128
            return f"opus_48000_{br}"
        # mp3：采样率决定可用码率（22050→32、24000→48、44100→可选）。
        # 位深选项仅在 44100 时由 schema 的 condition 开放，故无需跨组合回退。
        sr = self._as_int(config.get("mp3_sample_rate", 44100)) or 44100
        if sr == 44100:
            br = self._as_int(config.get("mp3_bitrate", 128)) or 128
            if br not in (32, 64, 96, 128, 192):
                br = 128
        elif sr == 24000:
            br = 48
        elif sr == 22050:
            br = 32
        else:
            logger.warning(f"mp3 采样率 {sr} 不被接受，回退到 mp3_44100_128")
            sr, br = 44100, 128
        return f"mp3_{sr}_{br}"

    def _build_audio_effects(self, raw_params: dict) -> dict | None:
        """从工具参数组装 audio_effects（仅当任一字段被填）。

        Args:
            raw_params: SubAgent 返回的清洗后参数。

        Returns:
            audio_effects 字典，未填任何效果时返回 None。
        """
        fx: dict[str, Any] = {}
        for key in ("filter_preset_id", "environment_id", "background_noise_id"):
            val = raw_params.get(key)
            if isinstance(val, str) and val.strip():
                fx[key] = val.strip()
        bounds = (("distance", 0.0, 1.0), ("send_level", 0.0, 1.0), ("pan", -1.0, 1.0))
        for key, lo, hi in bounds:
            f = self._as_float(raw_params.get(key))
            if f is not None and lo <= f <= hi:
                fx[key] = f
        return fx or None

    async def call_api(
        self,
        text: str,
        raw_params: dict[str, Any],
        config: dict[str, Any],
        voice_id: str | None = None,
    ) -> str:
        """调用 ElevenLabs TTS 合成语音并保存为本地音频文件。

        Returns:
            合成后的音频文件路径，失败时返回空字符串。
        """
        api_key = config.get("api_key")
        if not api_key:
            logger.error("ElevenLabs API Key 未配置")
            return ""

        voice = voice_id or config.get("voice_id")
        if not voice:
            logger.error("ElevenLabs voice_id 未配置")
            return ""
        try:
            # ElevenLabs 音色 ID 以数字开头（如 21m00Tcm4TlvDq8ikWAM），
            # 故覆盖基类默认正则（要求首字符为字母）。
            self.validate_voice_id(voice, pattern=r"^[A-Za-z0-9]{8,256}$")
        except ValueError as e:
            logger.error(f"ElevenLabs voice_id 非法: {e}")
            return ""

        final_text = raw_params.get("text") or text
        if not final_text:
            logger.error("TTS 文本为空")
            return ""

        base = (config.get("base_url") or "https://api.elevenlabs.io").rstrip("/")
        output_format = self._compose_output_format(config)
        url = f"{base}{API_PATH}/{voice}?output_format={output_format}"
        headers = {"xi-api-key": api_key, "Content-Type": "application/json"}

        model = config.get("model") or "eleven_v4"
        if model not in ("eleven_v4", "eleven_v4_turbo"):
            logger.warning(f"不支持的模型 {model}，回退到 eleven_v4")
            model = "eleven_v4"

        payload: dict[str, Any] = {
            "text": final_text,
            "model_id": model,
        }
        if config.get("use_voice_settings"):
            stability = self._as_float(config.get("stability", 0.5))
            similarity_boost = self._as_float(config.get("similarity_boost", 0.75))
            payload["voice_settings"] = {
                "stability": stability if stability is not None else 0.5,
                "similarity_boost": similarity_boost
                if similarity_boost is not None
                else 0.75,
                "use_speaker_boost": bool(config.get("use_speaker_boost", True)),
            }

        # 工具参数优先（逐句切换语言），否则回退到供应商配置的默认语言
        lang = raw_params.get("language_code") or config.get("language_code")
        if isinstance(lang, str) and lang.strip():
            payload["language_code"] = lang.strip()

        norm = config.get("apply_text_normalization", "auto")
        if norm in ("auto", "on", "off"):
            payload["apply_text_normalization"] = norm

        seed = self._as_int(config.get("seed"))
        if isinstance(seed, int) and 0 <= seed <= 4294967295:
            payload["seed"] = seed

        enable_logging = config.get("enable_logging", True)
        if isinstance(enable_logging, bool):
            payload["enable_logging"] = enable_logging

        use_pvc_as_ivc = config.get("use_pvc_as_ivc", False)
        if isinstance(use_pvc_as_ivc, bool):
            payload["use_pvc_as_ivc"] = use_pvc_as_ivc

        if config.get("use_pronunciation_dictionary"):
            pid = config.get("pronunciation_dictionary_id")
            pver = config.get("pronunciation_dictionary_version")
            if pid:
                locator: dict[str, Any] = {"pronunciation_dictionary_id": pid}
                if pver:
                    locator["version_id"] = pver
                payload["pronunciation_dictionary_locators"] = [locator]
            else:
                logger.warning("已启用发音词典但未提供 id，将忽略该参数")

        effects = self._build_audio_effects(raw_params)
        if effects:
            payload["audio_effects"] = effects

        timeout = self._as_int(config.get("timeout", 120)) or 120
        try:
            async with httpx.AsyncClient(**self._http_kwargs(timeout)) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                content = resp.content
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            try:
                err = extract_error_message(e.response.json(), e.response.text)
            except Exception:  # noqa: BLE001
                err = e.response.text or str(e)
            logger.error(f"ElevenLabs TTS 调用失败 ({status}): {err}")
            return ""
        except httpx.TimeoutException:
            logger.error(f"ElevenLabs TTS 超时 (timeout={timeout}s)")
            return ""
        except Exception as e:  # noqa: BLE001
            logger.error(f"ElevenLabs TTS 调用失败: {e}")
            return ""

        if not content:
            logger.error("ElevenLabs 响应无音频数据")
            return ""

        ext = OUTPUT_EXT.get(config.get("output_codec", "mp3"), "mp3")
        return save_audio_bytes(config.get("_data_dir", ""), content, ext)
