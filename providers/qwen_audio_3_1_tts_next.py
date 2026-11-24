"""阿里云百炼「音频生成」适配器（qwen-audio-3.1-tts-next）。

与 ``bailian_qwen_audio_3_*`` 的标准语音合成不同，本适配器调用百炼的
音频生成接口 ``SpeechSynthesizer``：请求体以 ``text_prompt``（提示词）为核心，
可通过 ``references`` 提交 Base64 参考音频，在提示词中用 ``@voice1`` 引用。

本适配器只暴露「单说话人」能力：参考音频取配置项 ``voice_sample`` 的第一个文件，
固定映射到 ``@voice1``。参考音频文件由 AstrBot 配置页的 ``type: file`` 控件上传，
本模块负责从插件数据目录读取、Base64 编码并缓存，与 MiMo 的 voice_sample 一致。

工具层只暴露一个 ``text_prompt`` 字段：由 SubAgent 直接产出完整的音频生成提示词
（台词 + 场景/音色/情绪描述），适配器不再做模板拼接或 instruction 拆解。
有无参考音频分别由两份能力文档指导 SubAgent，文档在构造 SubAgent 提示词时按
当前是否配置了参考音频择一注入。
"""

import base64
import random
import re

from pathlib import Path
from typing import Any, Optional

import httpx

from astrbot.api import logger
from astrbot.core.agent.tool import FunctionTool

from .base import TTSProviderAdapter
from .utils import http
from .utils.audio import (
    AudioConstraints,
    Base64FileCache,
    get_audio_duration,
    save_audio_bytes,
    trim_audio_to_max,
)


class QwenAudio3_1TTSNextAdapter(TTSProviderAdapter):
    """百炼音频生成（qwen-audio-3.1-tts-next）适配器，单说话人模式。"""

    DISPLAY_NAME = "百炼 Qwen Audio 3.1 TTS Next"

    MODEL_NAME = "qwen-audio-3.1-tts-next"

    # 工具层只有 text_prompt：SubAgent 直接产出完整提示词，而非原始台词 + 指令。
    TOOL_PROMPT_FIELD = "text_prompt"
    TOOL_EXTRA_FIELDS = frozenset({"volume", "rate"})

    # 官方文档：POST https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer
    _API_ENDPOINT = (
        "https://{workspace_id}.cn-beijing.maas.aliyuncs.com"
        "/api/v1/services/audio/tts/SpeechSynthesizer"
    )

    VALID_FORMATS = ("wav", "mp3", "pcm")
    DEFAULT_FORMAT = "wav"
    VALID_SAMPLE_RATES = (8000, 16000, 24000, 44100, 48000)
    DEFAULT_SAMPLE_RATE = 48000

    # 官方限制：单条参考音频最长 30 秒（通用常量）、不超过 10MB。
    # 超限不再直接拒绝，而是自动截断（留 margin）并打 warning。
    TRIM_MARGIN_SEC = 0.5
    MAX_VOICE_BASE64_BYTES = 10 * 1024 * 1024
    MAX_PROMPT_CHARS = 3000

    # 参考音频支持 WAV / MP3 / OGG Opus（不支持裸 PCM）。
    _MIME_BY_EXT = {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
    }

    # Base64 缓存目录（位于 <plugin_data>/cache/... 下，与 MiMo 分离）。
    _CACHE_DIRNAME = "cache/qwen_audio_3_1_tts_next"

    def __init__(self, entry: dict) -> None:
        super().__init__(entry)
        self._voice_data_url: Optional[str] = None
        self._prepare_voice_sample()

    # ———————— 参考音频 ————————

    def _prepare_voice_sample(self) -> None:
        """预编码并缓存参考音频样本，超限时自动截断而非拒绝。

        ``_data_dir`` 由 ``src/tts_service.py`` 注入，指向 ``<plugin_data>/<name>/audio``，
        其父目录即插件数据根目录。AstrBot 配置页上传的 ``type: file`` 字段保存的是
        相对该根目录的路径（如 ``files/voice_sample/xxx.wav``）。处理流程：

        1. 路径穿越校验（必须，无法自动修复）与格式白名单校验；
        2. 时长超过 30 秒 → 自动截断到 29.5 秒并打 warning；
        3. Base64 编码后超过 10MB → 按超出比例再次截断并打 warning；
        4. 时长读取 ffprobe 优先、pydub 兜底（WAV 免 ffmpeg）；两者都失败
           → 降级跳过时长校验（仍按大小截断），不阻断合成；
        5. 截断产物写入缓存目录，不污染用户上传目录；缓存 key 含原文件
           mtime/size 与「是否被截断」标记，避免源文件变更后命中陈旧缓存。

        Raises:
            ValueError: 路径越权（唯一保留的硬失败项）。
        """
        data_dir = self.entry.get("_data_dir", "")
        if not data_dir:
            logger.debug("[QwenAudioNext] 未注入 _data_dir，跳过参考音频预编码")
            return

        samples = self.entry.get("voice_sample")
        if not isinstance(samples, list) or not samples:
            logger.debug("[QwenAudioNext] 未配置 voice_sample，使用纯文本生成")
            return

        rel_path = str(samples[0]).strip()
        if not rel_path:
            return

        root = Path(data_dir).parent
        sample_path = (root / rel_path).resolve()
        try:
            sample_path.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(f"voice_sample 路径越权: {rel_path!r}") from exc

        if not sample_path.is_file():
            logger.warning(f"[QwenAudioNext] voice_sample 文件不存在: {sample_path}")
            return

        mime = self._MIME_BY_EXT.get(sample_path.suffix.lower())
        if mime is None:
            logger.error(
                f"[QwenAudioNext] 不支持的 voice_sample 格式: {sample_path.suffix}，"
                "仅支持 wav/mp3/ogg"
            )
            return

        cache_dir = root / self._CACHE_DIRNAME

        # 先按时长截断（需要读取时长），得到一个「处理中」文件路径与是否已截断的标记。
        work_path = sample_path
        was_trimmed = False
        duration = get_audio_duration(str(sample_path))
        if duration is None:
            # 时长读不到（MP3/OGG 且无 ffmpeg）时无法精确校验，
            # 仍会按 Base64 大小兜底截断；这里明确告知用户校验受限。
            logger.warning(
                "[QwenAudioNext] 无法读取参考音频时长，30s 时长校验跳过；"
                "仍会按 Base64 大小截断，建议手动确保音频不超过 30 秒或改用 WAV"
            )
        elif duration > AudioConstraints.QWEN_AUDIO_NEXT_MAX + 0.01:
            try:
                trimmed = trim_audio_to_max(
                    str(sample_path),
                    max_sec=AudioConstraints.QWEN_AUDIO_NEXT_MAX,
                    margin=self.TRIM_MARGIN_SEC,
                    output_dir=str(cache_dir),
                )
                if Path(trimmed).resolve() != sample_path.resolve():
                    work_path = Path(trimmed)
                    was_trimmed = True
                    logger.warning(
                        f"[QwenAudioNext] voice_sample 时长 {duration:.1f}s 超过 "
                        f"{AudioConstraints.QWEN_AUDIO_NEXT_MAX:.0f}s，已自动截断: {work_path.name}"
                    )
            except Exception as exc:
                logger.warning(f"[QwenAudioNext] voice_sample 自动截断失败，回退原文件: {exc}")

        # 业务参数进缓存键：截断标记 + 时长上限 + 裁剪余量 + 大小上限，
        # 任一变化都会生成新键，避免命中按旧规则产出的缓存。
        cache = Base64FileCache(
            cache_dir,
            key_parts={
                "trim" if was_trimmed else "raw": "",
                "max": AudioConstraints.QWEN_AUDIO_NEXT_MAX,
                "margin": self.TRIM_MARGIN_SEC,
                "bytes": self.MAX_VOICE_BASE64_BYTES,
            },
        )
        encoded = cache.load(sample_path)

        if encoded is None:
            encoded = base64.b64encode(work_path.read_bytes()).decode("ascii")

            # 编码后超限：按超出比例估算目标时长再截一次（最多 2 次，避免死循环）。
            for _ in range(2):
                encoded_bytes = len(encoded.encode("utf-8"))
                if encoded_bytes <= self.MAX_VOICE_BASE64_BYTES:
                    break
                cur_duration = get_audio_duration(str(work_path))
                if cur_duration is None or cur_duration <= 1.0:
                    logger.warning(
                        f"[QwenAudioNext] voice_sample 编码后 "
                        f"{encoded_bytes / 1024 / 1024:.1f}MB 超过 10MB，"
                        "但无法读取时长或音频过短，已跳过二次截断"
                    )
                    break
                # 线性估算：目标时长 = 当前时长 × (上限 / 实际大小) × 0.9 留余量
                target_sec = max(
                    1.0,
                    cur_duration
                    * self.MAX_VOICE_BASE64_BYTES
                    / encoded_bytes
                    * 0.9,
                )
                try:
                    trimmed = trim_audio_to_max(
                        str(work_path),
                        max_sec=target_sec,
                        margin=self.TRIM_MARGIN_SEC,
                        output_dir=str(cache_dir),
                    )
                except Exception as exc:
                    logger.warning(f"[QwenAudioNext] voice_sample 二次截断失败: {exc}")
                    break
                new_path = Path(trimmed)
                if new_path.resolve() == work_path.resolve():
                    break
                work_path = new_path
                encoded = base64.b64encode(work_path.read_bytes()).decode("ascii")

            # 仍超限则不再抛错，打 warning 让请求继续（服务端会给出明确错误）。
            final_bytes = len(encoded.encode("utf-8"))
            if final_bytes > self.MAX_VOICE_BASE64_BYTES:
                logger.warning(
                    f"[QwenAudioNext] voice_sample 截断后仍为 "
                    f"{final_bytes / 1024 / 1024:.1f}MB（超过 10MB），仍将提交，"
                    "如服务端拒绝请更换更短的参考音频"
                )

            cache.save(sample_path, encoded)

        self._voice_data_url = f"data:{mime};base64,{encoded}"

    # ———————— 提示词文档 ————————

    def get_docs_for_scenario(self) -> str:
        """返回与当前参考音频状态匹配的能力文档。

        通用文档由基类载入 ``self.docs_content``（保证 ``has_docs`` 为真）；
        两份场景文档分别指导 SubAgent 在无参考音频时编写人物/音色，以及
        在有参考音频时固定使用 ``@voice1`` 指代说话人。
        """
        if self._voice_data_url:
            key = f"{self.template_key}_with_ref"
        else:
            key = f"{self.template_key}_no_ref"
        docs_path = Path(__file__).parent / "docs" / f"{key}.md"
        if docs_path.exists():
            return docs_path.read_text(encoding="utf-8")
        logger.warning(f"[QwenAudioNext] 场景文档不存在: {docs_path}")
        return ""

    # ———————— 请求构造 ————————

    def _build_payload(self, text_prompt: str, config: dict, dynamic: dict) -> dict:
        """构造音频生成 API 请求体。

        ``text_prompt`` 是 SubAgent 经 ``tts_enhance`` 工具产出的完整提示词，
        这里不再做任何模板拼接。``dynamic`` 是同一工具产出的演绎参数
        （volume/rate），它们只来自 tool、不来自 config。仅当没有参考音频时，
        兜底移除对不存在槽位的 ``@voiceN`` 引用（正常由场景文档指导）。
        """
        prompt = text_prompt.strip()
        if not self._voice_data_url:
            prompt = re.sub(r"@voice[123]\b\s*", "", prompt).strip()

        input_obj: dict[str, Any] = {
            "text_prompt": prompt,
            "format": self._normalize_format(config),
            "sample_rate": self._normalize_sample_rate(config),
            "channels": self._normalize_channels(config),
        }

        if self._voice_data_url:
            input_obj["references"] = [{"audio_data": self._voice_data_url}]

        # volume/rate 唯一来源为 tool；未填则不下发，由服务端用默认值（50 / 1.0）。
        volume = dynamic.get("volume")
        if isinstance(volume, (int, float)) and not isinstance(volume, bool) and 0 <= volume <= 100:
            input_obj["volume"] = volume
        rate = dynamic.get("rate")
        if isinstance(rate, (int, float)) and not isinstance(rate, bool) and 0.5 <= rate <= 2.0:
            input_obj["rate"] = rate

        seed = self._as_int(config.get("seed"))
        if seed == -1:
            # 官方默认 seed=42，不传会导致每次结果固定；-1 表示本地随机一个，
            # 让同一提示词的多次生成真正不同。
            input_obj["seed"] = random.randint(0, 2**31 - 1)
        elif seed is not None:
            input_obj["seed"] = seed

        aigc = self._as_bool(config.get("enable_aigc_tag"))
        if aigc is not None:
            input_obj["enable_aigc_tag"] = aigc

        # 仅 MP3 生效：CBR 与 VBR 二选一，按采样率约束码率范围。
        if input_obj["format"] == "mp3":
            cbr = self._as_bool(config.get("enable_cbr"))
            if cbr is not None:
                input_obj["enable_cbr"] = cbr
            if cbr:
                bit_rate = self._as_int(config.get("bit_rate"))
                if bit_rate is not None and 8 <= bit_rate <= 320:
                    input_obj["bit_rate"] = bit_rate
            else:
                quality = self._as_int(config.get("quality"))
                if quality is not None and 0 <= quality <= 9:
                    input_obj["quality"] = quality

        return {"model": self.MODEL_NAME, "input": input_obj}

    @classmethod
    def _normalize_format(cls, config: dict) -> str:
        fmt = config.get("format") or cls.DEFAULT_FORMAT
        if fmt not in cls.VALID_FORMATS:
            logger.warning(f"[QwenAudioNext] 不支持的格式 {fmt}，回退到 {cls.DEFAULT_FORMAT}")
            return cls.DEFAULT_FORMAT
        return fmt

    @classmethod
    def _normalize_sample_rate(cls, config: dict) -> int:
        rate = cls._as_int(config.get("sample_rate"))
        if rate not in cls.VALID_SAMPLE_RATES:
            return cls.DEFAULT_SAMPLE_RATE
        return rate

    @staticmethod
    def _normalize_channels(config: dict) -> int:
        channels = QwenAudio3_1TTSNextAdapter._as_int(config.get("channels"))
        return channels if channels in (1, 2) else 2

    # ———————— 语音生成 ————————

    def get_tool_schema(self) -> FunctionTool:
        return self.build_enhance_tool(
            "为百炼音频生成（单说话人）编写完整的音频生成提示词，"
            "必要时可调整音量与语速。把要说的台词和场景/音色/情绪描述写进同一个 text_prompt。",
            {
                "type": "object",
                "properties": {
                    "text_prompt": {
                        "type": "string",
                        "description": (
                            "完整的音频生成提示词：包含要说的台词（用引号标出）以及"
                            "场景、人物、音色、情绪、背景音效等描述。"
                            "务必阅读能力文档——有无参考音频时的写法不同。"
                        ),
                    },
                    "volume": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 100,
                        "description": (
                            "输出音量，范围 0-100，默认 50。"
                            "仅在用户明确要求调整音量（如「大声点」「轻声」）时填写；"
                            "不填则不下发，由服务端使用默认值 50。"
                        ),
                    },
                    "rate": {
                        "type": "number",
                        "minimum": 0.5,
                        "maximum": 2.0,
                        "description": (
                            "语速倍率，范围 0.5-2.0，默认 1.0。"
                            "仅在用户明确要求快慢时填写；"
                            "情绪/语速的演绎优先写进 text_prompt，此字段用于整体倍率调整。"
                            "不填则不下发，由服务端使用默认值 1.0。"
                        ),
                    },
                },
                "required": ["text_prompt"],
            },
        )

    def get_subagent_system_prompt(self) -> str:
        scenario_docs = self.get_docs_for_scenario()
        docs = self.docs_content
        if scenario_docs:
            docs = f"{docs}\n\n---\n\n{scenario_docs}"
        return f"""你是百炼「音频生成」提示词优化助手（单说话人模式）。以下是能力说明：

{docs}

请根据用户提供的文本和上下文，调用 `tts_enhance` 工具：
- text_prompt（必填）：填入完整的音频生成提示词，写法遵循上面的场景指引；
- volume、rate（可选）：仅当用户明确要求调整音量或语速时填写，否则留空不下发。
直接调用工具，不要额外解释。"""

    async def call_api(
        self,
        text: str,
        raw_params: dict[str, Any],
        config: dict[str, Any],
        voice_id: Optional[str] = None,
    ) -> str:
        """调用百炼音频生成接口，下载生成的音频并落盘。

        Returns:
            保存后的音频文件路径；失败时返回空字符串，由主流程切换到下一个供应商。
        """
        api_key = config.get("api_key", "")
        if not api_key:
            logger.error("[QwenAudioNext] api_key 未配置")
            return ""

        workspace_id = config.get("workspace_id", "")
        if not workspace_id:
            logger.error("[QwenAudioNext] workspace_id 未配置")
            return ""

        # SubAgent 产出的完整提示词；缺失时退回原始文本（未走增强的降级路径）。
        final_prompt = raw_params.get("text_prompt") or text
        if not final_prompt or not str(final_prompt).strip():
            logger.error("[QwenAudioNext] TTS 提示词为空")
            return ""

        try:
            payload = self._build_payload(str(final_prompt), config, raw_params)
        except Exception as exc:
            logger.error(f"[QwenAudioNext] 构造请求失败: {exc}")
            return ""

        text_prompt = payload["input"]["text_prompt"]
        if len(text_prompt) > self.MAX_PROMPT_CHARS:
            logger.error(
                f"[QwenAudioNext] text_prompt 超过 {self.MAX_PROMPT_CHARS} 字符限制 "
                f"(当前 {len(text_prompt)})"
            )
            return ""

        timeout = self._as_int(config.get("timeout")) or 300
        url = self._API_ENDPOINT.format(workspace_id=workspace_id)
        headers = http.bearer_headers(api_key)

        # 日志脱敏：不打印 Base64 参考音频。
        safe_payload = {
            "model": payload["model"],
            "input": {
                k: (f"<base64 {len(v[0]['audio_data'])} chars>" if k == "references" else v)
                for k, v in payload["input"].items()
            },
        }
        logger.debug(f"[QwenAudioNext] 请求参数: {safe_payload}")

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code >= 400:
                    error_msg = http.extract_error_message(resp.json(), resp.text)
                    logger.error(f"[QwenAudioNext] API 返回 {resp.status_code}: {error_msg}")
                    if any(k in error_msg.lower() for k in ("reference", "audio", "duration", "voice")):
                        logger.warning(
                            "[QwenAudioNext] 疑似参考音频问题：请确认不超过 30s/10MB；"
                            "无 ffmpeg 时 MP3/OGG 无法自动截断，建议改用 WAV 短音频"
                        )
                    return ""

                data = resp.json()
                if not isinstance(data, dict):
                    logger.error(f"[QwenAudioNext] 响应格式异常: {data}")
                    return ""

                # 服务端成功时可能带 code: 0 / "0"，不能当作错误（truthy 误判）。
                code = data.get("code")
                has_error = (
                    code not in (None, "", 0, "0")
                    or bool(data.get("error"))
                )
                if has_error:
                    error_msg = http.extract_error_message(data, str(data))
                    logger.error(f"[QwenAudioNext] API 错误: {error_msg}")
                    if any(k in error_msg.lower() for k in ("reference", "audio", "duration", "voice")):
                        logger.warning(
                            "[QwenAudioNext] 疑似参考音频问题：请确认不超过 30s/10MB；"
                            "无 ffmpeg 时 MP3/OGG 无法自动截断，建议改用 WAV 短音频"
                        )
                    return ""

                audio = (
                    data.get("output", {})
                    .get("audio", {})
                )
                audio_url = audio.get("url") if isinstance(audio, dict) else None
                if not audio_url:
                    logger.error(f"[QwenAudioNext] 响应中无 output.audio.url: {data}")
                    return ""

                # 下载 URL 有效期 24 小时，取到后立即下载。
                audio_resp = await client.get(audio_url, timeout=60)
                if audio_resp.status_code >= 400:
                    logger.error(
                        f"[QwenAudioNext] 音频下载失败 {audio_resp.status_code}: {audio_url}"
                    )
                    return ""

                return save_audio_bytes(
                    config.get("_data_dir", ""),
                    audio_resp.content,
                    payload["input"]["format"],
                )

        except httpx.TimeoutException:
            logger.error(f"[QwenAudioNext] API 超时 (timeout={timeout}s)")
            return ""
        except Exception:
            logger.exception("[QwenAudioNext] API 调用失败")
            return ""

    # ———————— 参数校验 ————————

    def validate_params(self, params: dict) -> tuple[bool, str]:
        if "text_prompt" in params and not str(params.get("text_prompt", "")).strip():
            return False, "text_prompt 不能为空"
        if "volume" in params:
            vol = params["volume"]
            if (isinstance(vol, bool) or not isinstance(vol, (int, float))
                    or not 0 <= vol <= 100):
                return False, "volume 必须为 0-100 的数值"
        if "rate" in params:
            spd = params["rate"]
            if (isinstance(spd, bool) or not isinstance(spd, (int, float))
                    or not 0.5 <= spd <= 2.0):
                return False, "rate 必须为 0.5-2.0 的数值"
        return True, ""

    def sanitize_params(self, params: dict) -> dict:
        sanitized: dict[str, Any] = {}
        prompt = params.get("text_prompt")
        if isinstance(prompt, str):
            sanitized["text_prompt"] = prompt
        elif prompt is not None:
            logger.warning(f"[QwenAudioNext] 丢弃非法的 text_prompt 参数: {prompt}")
        vol = params.get("volume")
        if isinstance(vol, (int, float)) and not isinstance(vol, bool) and 0 <= vol <= 100:
            sanitized["volume"] = vol
        elif vol is not None:
            logger.warning(f"[QwenAudioNext] 丢弃非法的 volume 参数: {vol}")
        spd = params.get("rate")
        if isinstance(spd, (int, float)) and not isinstance(spd, bool) and 0.5 <= spd <= 2.0:
            sanitized["rate"] = spd
        elif spd is not None:
            logger.warning(f"[QwenAudioNext] 丢弃非法的 rate 参数: {spd}")
        return sanitized
