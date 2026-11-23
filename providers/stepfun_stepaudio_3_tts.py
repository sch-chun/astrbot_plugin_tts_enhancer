"""阶跃星辰 StepFun StepAudio 3 TTS 适配器模块。

封装 ``StepfunStepaudio3TtsAdapter``，对接 StepFun 开放平台：

- 合成：``POST https://api.stepfun.com/v1/audio/speech``
  鉴权 ``Authorization: Bearer <api_key>``；请求体含 ``model``（固定
  ``stepaudio-3-tts``）、``input``（≤1000 字符）、``voice``（必填）。
  成功（200）直接返回音频二进制，按 ``response_format`` 决定格式；错误返回 JSON
  （含 ``message`` / ``error`` / ``detail`` / ``reason``）。

- 音色：``GET https://api.stepfun.com/v1/audio/system_voices?model=stepaudio-3-tts``
  返回官方音色列表（实测 70 个）。本适配器继承 ``VoiceManageable`` 但只实现只读
  ``list_voice``；``create_voice`` / ``delete_voice`` 保持 mixin 默认的
  ``NotImplementedError``，路由返回 501。

情绪 / 风格控制用 ``instruction``（≤500 字符）或文本里的 ``()`` 内联指令；
StepAudio 3 会把 ``()`` 内容当指令且默认不发音，所以纯朗读文本请勿写括号。
``speed`` 0.5~2.0、``volume`` 0.1~2.0 均为倍数（不是 dB）。

音色 ID 来自官方列表，长度最短为 4（如 ``Jake`` / ``Nick``），本适配器**不调用**
``validate_voice_id()``（基类默认 min_len=8 会误拒 12 个合法音色）。
"""

from typing import Any

import httpx

from astrbot.api import logger

from .base import TTSProviderAdapter
from .mixins import VoiceManageable
from .utils.audio import save_audio_bytes
from .utils.http import bearer_headers, extract_error_message

# StepFun TTS 端点
API_URL = "https://api.stepfun.com/v1/audio/speech"
VOICES_URL = "https://api.stepfun.com/v1/audio/system_voices"
# 已复刻音色（当前账号下），游标分页；预览只取第一页
CLONED_VOICES_URL = "https://api.stepfun.com/v1/audio/voices"

# 固定模型 ID（配置里只放一个选项，这里仍以白名单兜底）
MODEL_NAME = "stepaudio-3-tts"

# 响应格式与采样率白名单（配置脏数据回退用）
ALLOWED_FORMATS = ("mp3", "wav", "flac", "opus", "pcm")
ALLOWED_SAMPLE_RATES = (8000, 16000, 22050, 24000, 48000)

# 官方服务端硬上限（配置的 max_input_chars 只能下调）
MAX_INPUT_CHARS = 1000
MAX_INSTRUCTION_CHARS = 500


class StepfunStepaudio3TtsAdapter(TTSProviderAdapter, VoiceManageable):
    """StepFun StepAudio 3 TTS 适配器（合成 + 只读官方音色列表）。"""

    DISPLAY_NAME = "StepFun StepAudio 3 TTS"

    TOOL_EXTRA_FIELDS = frozenset({"instruction", "speed", "text_normalization", "volume"})

    def __init__(self, entry: dict) -> None:
        super().__init__(entry)
        logger.debug(
            f"Initialized StepfunStepaudio3TtsAdapter with template_key={self.template_key}"
        )

    # ————————————————————————————————
    # 工具 Schema 与 SubAgent 提示词
    # ————————————————————————————————

    def get_tool_schema(self) -> Any:
        """返回 tts_enhance 工具（暴露 5 个字段给 SubAgent）。"""
        return self.build_enhance_tool(
            "为 StepFun StepAudio 3 语音合成提供增强参数。"
            "情绪/人设用 instruction 或文本里的 () 内联指令控制；"
            "语速、音量与文本归一化用对应字段控制。",
            {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": (
                            "要朗读的纯文本（len<=1000）。不要把情绪写进括号："
                            "StepAudio 3 会把 () 内内容当作指令且不发音；情绪请放 instruction。"
                        ),
                    },
                    "instruction": {
                        "type": "string",
                        "description": "全局情绪/人设指导，len<=500，如'语气轻柔，略带笑意'。",
                    },
                    "speed": {
                        "type": "number",
                        "description": "语速 0.5~2.0，默认 1.0。",
                    },
                    "volume": {
                        "type": "number",
                        "description": "音量倍数 0.1~2.0，默认 1.0；不是 dB。",
                    },
                    "text_normalization": {
                        "type": "string",
                        "enum": ["standard", "enhanced"],
                        "description": "standard 适合实时；数字/单位/英文多或长文播报选 enhanced。",
                    },
                },
                "required": ["text"],
            },
        )

    def get_subagent_system_prompt(self) -> str:
        return (
            "你是语音合成参数优化助手，负责为 StepFun StepAudio 3 准备合成参数。"
            "请调用 `tts_enhance` 工具：\n"
            "- text 必填，为待朗读的纯文本（≤1000 字符）；不要把情绪写进括号，"
            "因为 () 内内容会被当作指令且不发音；\n"
            "- instruction 可选，≤500 字符，写全局情绪/人设（如'语气轻柔，略带笑意'）；\n"
            "- speed 可选，语速 0.5~2.0；\n"
            "- volume 可选，音量倍数 0.1~2.0（不是 dB）；\n"
            "- text_normalization 可选，standard 或 enhanced；数字/单位/英文多或长文播报选 enhanced。\n"
            "根据对话内容与情绪，把情绪写进 instruction，text 保持纯朗读内容。直接调用工具，不要额外解释。\n\n"
            "参考能力说明：\n"
            f"{self.docs_content}"
        )

    # ————————————————————————————————
    # 参数校验 / 清洗（内部，不属于 tool schema）
    # ————————————————————————————————

    def validate_params(self, params: dict) -> tuple[bool, str]:
        text = params.get("text")
        if text is not None and len(text) > MAX_INPUT_CHARS:
            return False, f"text 不能超过 {MAX_INPUT_CHARS} 字符"
        ins = params.get("instruction")
        if ins is not None:
            if not isinstance(ins, str):
                return False, "instruction 必须是字符串"
            if len(ins) > MAX_INSTRUCTION_CHARS:
                return False, f"instruction 不能超过 {MAX_INSTRUCTION_CHARS} 字符"
        speed = params.get("speed")
        if speed is not None:
            s = self._as_float(speed)
            if s is None or not (0.5 <= s <= 2.0):
                return False, "speed 必须在 0.5~2.0 之间"
        volume = params.get("volume")
        if volume is not None:
            v = self._as_float(volume)
            if v is None or not (0.1 <= v <= 2.0):
                return False, "volume 必须在 0.1~2.0 之间"
        norm = params.get("text_normalization")
        if norm is not None and norm not in ("standard", "enhanced"):
            return False, "text_normalization 只能是 standard 或 enhanced"
        return True, ""

    def sanitize_params(self, params: dict) -> dict:
        """只保留实际传入的白名单字段，绝不写默认值（冒烟硬约束）。"""
        out: dict[str, Any] = {}
        if "text" in params:
            text = params["text"]
            out["text"] = text.strip() if isinstance(text, str) else text
        if "instruction" in params:
            ins = params["instruction"]
            if isinstance(ins, str) and ins.strip():
                out["instruction"] = ins.strip()
        if "speed" in params:
            s = self._as_float(params["speed"])
            if s is not None and 0.5 <= s <= 2.0:
                out["speed"] = s
        if "volume" in params:
            v = self._as_float(params["volume"])
            if v is not None and 0.1 <= v <= 2.0:
                out["volume"] = v
        if "text_normalization" in params:
            norm = params["text_normalization"]
            if norm in ("standard", "enhanced"):
                out["text_normalization"] = norm
        return out

    # ————————————————————————————————
    # HTTP 工具
    # ————————————————————————————————

    def _http_kwargs(self, timeout: int) -> dict:
        """构造 httpx.AsyncClient 关键字参数，统一注入代理（若已配置）。"""
        kwargs: dict[str, Any] = {"timeout": timeout}
        proxy = self.entry.get("proxy")
        if isinstance(proxy, str) and proxy.strip():
            kwargs["proxy"] = proxy.strip()
        return kwargs

    # ————————————————————————————————
    # 语音合成
    # ————————————————————————————————

    async def call_api(
        self,
        text: str,
        raw_params: dict[str, Any],
        config: dict[str, Any],
        voice_id: str | None = None,
    ) -> str:
        """调用 StepFun TTS 合成语音并保存为本地音频文件。"""
        api_key = config.get("api_key")
        if not api_key:
            logger.error("StepFun StepAudio 3 API Key 未配置")
            return ""

        # voice 必填：预览 voice_id 优先，否则用配置；不做 validate_voice_id（见模块 docstring）
        voice = voice_id or config.get("voice") or config.get("voice_id")
        if not voice:
            logger.error("StepFun StepAudio 3 未配置 voice（音色 ID 必填）")
            return ""

        # 工具 text 优先，其次原始 text
        final_text = raw_params.get("text") or text
        if not final_text:
            logger.error("TTS 文本为空")
            return ""

        # 本地长度守卫：配置的 max_input_chars 只能下调，服务端硬上限 1000
        max_chars = self._as_int(config.get("max_input_chars", MAX_INPUT_CHARS))
        if max_chars is None or not (1 <= max_chars <= MAX_INPUT_CHARS):
            max_chars = MAX_INPUT_CHARS
        if len(final_text) > max_chars:
            logger.error(
                f"文本长度 {len(final_text)} 超过 StepAudio 3 上限 {max_chars} 字符"
            )
            return ""

        fmt = config.get("format", "mp3")
        if fmt not in ALLOWED_FORMATS:
            logger.warning(f"不支持的格式 {fmt}，回退到 mp3")
            fmt = "mp3"

        sample_rate = self._as_int(config.get("sample_rate", 24000))
        if sample_rate not in ALLOWED_SAMPLE_RATES:
            logger.warning(f"不支持的采样率 {sample_rate}，回退到 24000")
            sample_rate = 24000

        # payload 只由白名单字段逐一构造，不从 raw_params / config 整体展开，
        # 天然不会透传任何非白名单字段。
        payload: dict[str, Any] = {
            "model": MODEL_NAME,
            "input": final_text,
            "voice": voice,
            "response_format": fmt,
            "sample_rate": sample_rate,
            "markdown_filter": bool(config.get("markdown_filter", True)),
        }

        # 条件加入：仅来自工具清洗结果，未传则整键不构造
        instruction = raw_params.get("instruction")
        if isinstance(instruction, str) and instruction.strip():
            payload["instruction"] = instruction.strip()
        speed = self._as_float(raw_params.get("speed"))
        if speed is not None and 0.5 <= speed <= 2.0:
            payload["speed"] = speed
        volume = self._as_float(raw_params.get("volume"))
        if volume is not None and 0.1 <= volume <= 2.0:
            payload["volume"] = volume
        norm = raw_params.get("text_normalization")
        if norm in ("standard", "enhanced"):
            payload["text_normalization"] = norm

        # 发音替换规则：逗号分隔字符串 → {"tone": [...]}，逐项要求含 "/"
        pron = config.get("pronunciation_tone", "")
        if isinstance(pron, str) and pron.strip():
            tones = [p.strip() for p in pron.split(",") if p.strip() and "/" in p]
            if tones:
                payload["pronunciation_map"] = {"tone": tones}
            else:
                logger.warning("pronunciation_tone 未包含有效的 '原字/替换' 规则，已忽略")

        headers = bearer_headers(api_key)
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
            logger.error(f"StepFun StepAudio 3 TTS 调用失败 ({status}): {err}")
            return ""
        except httpx.TimeoutException:
            logger.error(f"StepFun StepAudio 3 TTS 超时 (timeout={timeout}s)")
            return ""
        except Exception as e:
            logger.error(f"StepFun StepAudio 3 TTS 调用失败: {e}")
            return ""

        if not content:
            logger.error("StepFun StepAudio 3 响应无音频数据")
            return ""

        return save_audio_bytes(config.get("_data_dir", ""), content, fmt)

    # ————————————————————————————————
    # 只读官方音色列表（VoiceManageable）
    # ————————————————————————————————

    async def list_voice(self, **kwargs) -> dict:
        """列出音色（只读），按 ``voice_type`` 分发：

        - ``system``（默认）：官方系统音色 ``GET /v1/audio/system_voices``；
        - ``cloned``：当前账号已复刻音色 ``GET /v1/audio/voices``。

        两者都返回 ``{"items": [...], "total": n}``，异常按现有语义返回空列表而
        不向上抛出（由路由包装为正常空结果，区别于 create/delete 的 501）。
        """
        if kwargs.get("voice_type") == "cloned":
            return await self._list_cloned_voices()
        return await self._list_system_voices()

    async def _list_system_voices(self) -> dict:
        """官方系统音色：voice_id / voice_name / description / recommended_scene / type=system。"""
        api_key = self.entry.get("api_key")
        if not api_key:
            logger.error("StepFun StepAudio 3 API Key 未配置，无法拉取音色列表")
            return {"items": [], "total": 0}

        timeout = self._as_int(self.entry.get("timeout", 120)) or 120
        headers = bearer_headers(api_key)
        try:
            async with httpx.AsyncClient(**self._http_kwargs(timeout)) as client:
                resp = await client.get(
                    VOICES_URL, headers=headers, params={"model": MODEL_NAME}
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            try:
                err = extract_error_message(e.response.json(), e.response.text)
            except Exception:
                err = e.response.text or str(e)
            logger.error(f"StepFun 音色列表查询失败 ({status}): {err}")
            return {"items": [], "total": 0}
        except httpx.TimeoutException:
            logger.error(f"StepFun 音色列表查询超时 (timeout={timeout}s)")
            return {"items": [], "total": 0}
        except Exception as e:
            logger.error(f"StepFun 音色列表查询失败: {e}")
            return {"items": [], "total": 0}

        # 兼容 voices 列表与 voices-details 映射两种形态
        voices = data.get("voices") or []
        if isinstance(voices, dict):
            voices = list(voices.keys())
        details = data.get("voices-details") or {}

        def pick(d: dict, *keys: str) -> str | None:
            """从 dict 里取第一个非空值，兼容官方连字符字段与 Python 风格字段。"""
            for key in keys:
                val = d.get(key)
                if val not in (None, ""):
                    return val
            return None

        items: list[dict[str, Any]] = []
        for entry in voices:
            # voices 元素可能是字符串 ID，也可能是 dict
            if isinstance(entry, str):
                vid = entry
                raw_name = raw_desc = raw_scene = None
            elif isinstance(entry, dict):
                vid = entry.get("voice_id") or entry.get("voice-name")
                raw_name = pick(entry, "voice-name", "voice_name")
                raw_desc = pick(entry, "voice-description", "description")
                raw_scene = pick(entry, "recommended_scene", "recommended-scene")
            else:
                continue
            if not vid:
                continue

            # voices-details 以 voice id 为键，补充名称/描述/推荐场景
            detail = details.get(vid) if isinstance(details, dict) else None
            if isinstance(detail, dict):
                detail_name = pick(detail, "voice-name", "voice_name")
                detail_desc = pick(detail, "voice-description", "description")
                detail_scene = pick(detail, "recommended_scene", "recommended-scene")
            else:
                detail_name = detail_desc = detail_scene = None

            voice_name = raw_name or detail_name or vid
            description = raw_desc or detail_desc or ""
            scene = raw_scene or detail_scene or ""
            items.append(
                {
                    "voice_id": vid,
                    "voice_name": voice_name,
                    "description": description,
                    "recommended_scene": scene,
                    "type": "system",
                }
            )

        return {"items": items, "total": len(items)}

    async def _list_cloned_voices(self) -> dict:
        """列出当前账号已复刻音色（只读）。

        ``GET /v1/audio/voices`` 返回 ``{"data": [{"id", "file_id", "created_at"}],
        "has_more", ...}``。预览只取第一页（limit=100），每项映射为
        voice_id=id / file_id / created_at / type=cloned，异常返回空列表。
        """
        api_key = self.entry.get("api_key")
        if not api_key:
            logger.error("StepFun StepAudio 3 API Key 未配置，无法拉取复刻音色列表")
            return {"items": [], "total": 0}

        timeout = self._as_int(self.entry.get("timeout", 120)) or 120
        headers = bearer_headers(api_key)
        try:
            async with httpx.AsyncClient(**self._http_kwargs(timeout)) as client:
                resp = await client.get(
                    CLONED_VOICES_URL, headers=headers, params={"limit": "100"}
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            try:
                err = extract_error_message(e.response.json(), e.response.text)
            except Exception:
                err = e.response.text or str(e)
            logger.error(f"StepFun 复刻音色列表查询失败 ({status}): {err}")
            return {"items": [], "total": 0}
        except httpx.TimeoutException:
            logger.error(f"StepFun 复刻音色列表查询超时 (timeout={timeout}s)")
            return {"items": [], "total": 0}
        except Exception as e:
            logger.error(f"StepFun 复刻音色列表查询失败: {e}")
            return {"items": [], "total": 0}

        raw = data.get("data") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            return {"items": [], "total": 0}

        items: list[dict[str, Any]] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            vid = entry.get("id") or entry.get("voice_id")
            if not vid:
                continue
            items.append(
                {
                    "voice_id": str(vid),
                    "file_id": str(entry.get("file_id") or ""),
                    "created_at": entry.get("created_at"),
                    "type": "cloned",
                }
            )
        return {"items": items, "total": len(items)}
