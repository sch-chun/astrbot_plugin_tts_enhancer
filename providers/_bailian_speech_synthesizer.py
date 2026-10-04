"""百炼 Speech Synthesizer 适配器"""

import base64
import binascii
from pathlib import Path
import re
import traceback

import httpx

from astrbot.api import logger
from astrbot.core.agent.tool import FunctionTool

from .base import TTSProviderAdapter
from .utils import http
from .utils.audio import save_audio_bytes

from typing import Any, Optional


_CLONE_DATA_URL_MIME_TYPES = frozenset({"audio/wav", "audio/mpeg", "audio/mp4"})
_MAX_CLONE_AUDIO_BYTES = 10 * 1024 * 1024
_DATA_URL_RE = re.compile(
    r"data:audio/[A-Za-z0-9.+-]+;base64,[A-Za-z0-9+/=_-]+",
    re.IGNORECASE,
)


def _redact_data_urls(value: Any) -> Any:
    """递归脱敏错误响应中的音频 Data URL，避免 Base64 泄漏到日志或前端。"""
    if isinstance(value, str):
        return _DATA_URL_RE.sub("<Data URL omitted>", value)
    if isinstance(value, dict):
        return {key: _redact_data_urls(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_data_urls(item) for item in value]
    return value


def _validate_clone_data_url(value: str) -> tuple[str, int]:
    """校验百炼复刻音频 Data URL，并返回 MIME 与解码后字节数。"""
    if not isinstance(value, str) or not value.startswith("data:"):
        raise ValueError("audio_data_url 必须是 Base64 Data URL")

    header, separator, encoded = value.partition(",")
    if not separator or not encoded or not header.endswith(";base64"):
        raise ValueError("audio_data_url 格式错误，应为 data:{mime};base64,{data}")

    mime_type = header[5:-7].lower()
    if mime_type not in _CLONE_DATA_URL_MIME_TYPES:
        supported = ", ".join(sorted(_CLONE_DATA_URL_MIME_TYPES))
        raise ValueError(f"不支持的复刻音频 MIME 类型: {mime_type}，仅支持 {supported}")

    try:
        audio_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("audio_data_url 包含无效的 Base64 数据") from exc

    if not audio_bytes:
        raise ValueError("audio_data_url 不得包含空音频")
    if len(audio_bytes) > _MAX_CLONE_AUDIO_BYTES:
        raise ValueError("复刻音频不得超过 10MB")

    return mime_type, len(audio_bytes)


class BailianSpeechSynthesizerAdapter(TTSProviderAdapter):
    """百炼 Speech Synthesizer 端点公共基类。
    
    该适配器实现了阿里云百炼平台的 Speech Synthesizer 服务，支持通过 Function Calling
    方式接收结构化的语音合成参数，包括可能的情感标签、指令、音量、语速和语言提示等。
    同时支持音色的创建 (克隆与设计)、查询与删除等管理功能。
    
    Attributes:
        _API_ENDPOINT (str): 阿里云百炼 TTS API 的端点地址
        VALID_LANGS (list[str]): 支持的语言代码列表
        docs_content (str): 标准 TTS 参数使用文档内容
        design_docs_content (str): 声音设计音色专用文档内容
    """
    _API_ENDPOINT = "https://{workspace_id}.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"

    # 可被覆盖
    VALID_LANGS = [
        "zh", "en", "fr", "de", "ja", "ko", "ru", "pt",
        "th", "id", "vi", "es", "it", "ms", "fil", "ar"
    ]
    MODEL_NAME = ""

    def __init__(self, entry: dict) -> None:
        """初始化适配器，加载标准文档和声音设计专用文档。

        因为 Qwen Audio 3.0 TTS / CosyVoice V3.5 声音设计音色不支持方言，所以分出两份文档。

        Args:
            entry (dict): 供应商配置字典，包含 API 密钥、工作空间 ID 等信息
        """
        super().__init__(entry=entry)
        safe_entry = dict(entry)
        api_key = safe_entry.get("api_key", "")
        if len(api_key) > 5:
            safe_entry["api_key"] = "*****" + api_key[-5:]
        else:
            safe_entry["api_key"] = "*****"
    
        logger.debug(
            f"Initializing {self.__class__.__name__} with entry: {entry}, MODEL_NAME: {self.MODEL_NAME}"
        )
        self.docs_content = self._load_docs()
        self.design_docs_content = self._load_design_docs()

         # 配置一致性检查：voice 解析出的 model 与显式配置的 model 是否冲突
        voice = entry.get("voice", "")
        config_model = entry.get("model")
        parsed_model = self._extract_model_from_voice_id(voice)
        if parsed_model is not None and config_model and config_model != parsed_model:
            logger.warning(
                f"[{self.template_key}] 配置中的 model='{config_model}' 与音色 ID 解析出的 "
                f"model='{parsed_model}' 不一致，合成时将使用解析值。请检查配置。"
            )

    # ———————— 语音合成 ————————

    def _load_design_docs(self) -> str:
        """加载声音设计音色专用文档。

        Returns:
            str: 声音设计专用文档的文本内容，如果文件不存在则返回空字符串
        """
        docs_path = Path(__file__).parent / "docs" / f"{self.template_key}_design.md"
        if docs_path.exists():
            return docs_path.read_text(encoding="utf-8")
        logger.warning(f"{self.template_key} design docs not found at {docs_path}")
        return ""

    def get_docs_for_voice(self, voice: str) -> str:
        """根据音色 ID 返回对应的文档。

        声音设计音色格式（包含 -vd-）：{MODEL_NAME}-{model}-vd-{prefix}-{unique}
        按 '-' 分割后长度为 len(MODEL_NAME.split('-')) + 4，
        且索引 len(MODEL_NAME.split('-')) + 1 为 'vd'。
        其他情况均使用标准文档。

        Args:
            voice (str): 音色 ID，如果为空则返回标准文档

        Returns:
            str: 对应音色类型的参数使用文档内容
        """
        if not voice:
            logger.warning("voice_id is empty, using standard docs")
            return self.docs_content
        
        parts = voice.split('-')
        name_parts = self.MODEL_NAME.split('-')
        if len(parts) == len(name_parts) + 4 and parts[len(name_parts) + 1] == 'vd':
            return self.design_docs_content

        return self.docs_content

    # ---------- 1. 定义工具 Schema ----------
    def get_tool_schema(self) -> FunctionTool:
        """返回用于 TTS 参数增强的 Function Tool。"""
        return self.build_enhance_tool(
            "为语音合成提供增强参数，包括文本、指令、音量、语速和语言提示。",
            {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "需要合成的文本。"
                    },
                    "instruction": {
                        "type": "string",
                        "description": "自然语言指令。"
                    },
                    "volume": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 100,
                        "description": "音量，范围 0-100，默认 50。"
                    },
                    "rate": {
                        "type": "number",
                        "minimum": 0.5,
                        "maximum": 2.0,
                        "description": "语速倍率，范围 0.5-2.0，默认 1.0。"
                    },
                    "pitch": {
                        "type": "number",
                        "minimum": 0.5,
                        "maximum": 2.0,
                        "description": "音调倍率，范围 0.5-2.0，默认 1.0。"
                    },
                    "language_hints": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": self.VALID_LANGS
                        },
                        "description": "指定语音合成的目标语言，建议与文本语种一致。"
                    }
                },
                "required": ["text"]
            },
        )

    # ---------- 2. 构建 SubAgent 系统提示 ----------
    def get_subagent_system_prompt(self) -> str:
        """构建 SubAgent 的系统提示，用于指导参数优化。
        
        该方法生成一个系统提示，指导 SubAgent 如何根据待合成文本优化语音合成参数。
        提示中包含了 TTS 模型的参数使用说明和具体的优化要求。
            
        Returns:
            str: 包含参数优化指导的系统提示文本
        """
        voice = self.entry.get("voice", "")
        docs = self.get_docs_for_voice(voice)
        return f"""你是语音合成参数优化助手，负责为 {self.MODEL_NAME} 模型准备合成参数。以下是 {self.MODEL_NAME} 模型的参数使用说明：

{docs}

现在请根据用户提供的文本和上下文，调用 `tts_enhance` 工具，提供合适的参数（包括 text 和其他可选参数）。请直接调用工具，不要额外解释。"""

    # ---------- 3. 调用 TTS API ----------
    async def call_api(
        self,
        text: str,               # 原始文本（备用）
        raw_params: dict[str, Any],  # 从工具解析出的参数（优先）
        config: dict[str, Any],   # 当前供应商的 entry 配置
        voice_id: Optional[str] = None
    ) -> str:
        """执行 TTS 合成，调用阿里云百炼 API 并返回音频文件路径。
        
        该方法是 TTS 合成的核心方法，负责：
        1. 提取和合并配置参数
        2. 构造 API 请求 payload
        3. 调用阿里云百炼 TTS API
        4. 下载生成的音频文件
        
        Args:
            text (str): 原始待合成文本，作为备用参数
            raw_params (dict[str, Any]): 从工具解析出的参数，优先级高于 text
            config (dict[str, Any]): 当前供应商的配置信息，包含 API 密钥等
            
        Returns:
            str: 生成的音频文件路径，失败时返回空字符串
        """

        # 提取配置
        api_key = config.get("api_key", "")
        workspace_id = config.get("workspace_id", "")

        # 确定使用的 voice
        voice = voice_id or config.get("voice")
        if not voice:
            raise ValueError("未提供音色 ID，无法合成语音")

        # 从 voice 解析模型（仅对复刻音色）
        parsed_model = self._extract_model_from_voice_id(voice)
        if parsed_model is not None:
            model_suffix = parsed_model
        else:
            model_suffix = config.get("model")
            if model_suffix not in ("flash", "plus"):
                logger.warning("无法确定 model 参数，将使用默认模型 'flash'")
                model_suffix = "flash"

        model = f"{self.MODEL_NAME}-{model_suffix}"

        timeout = config.get("timeout", 60)
        format_type = config.get("format", "wav")
        sample_rate = config.get("sample_rate", 24000)
        seed = config.get("seed", -1)
        enable_aigc = config.get("enable_aigc_tag", False)
        aigc_propagator = config.get("aigc_propagator", "")
        aigc_propagate_id = config.get("aigc_propagate_id", "")

        # ---------- 合并参数（工具参数优先） ----------
        # text: 优先使用 raw_params 中的，否则使用传入的 text
        final_text = raw_params.get("text", text)
        if not final_text:
            logger.error("TTS 文本为空")
            return ""

        # 其他参数：如果 raw_params 中有则使用，否则不传（让 API 使用默认值）
        final_instruction = raw_params.get("instruction")
        final_volume = raw_params.get("volume")
        final_rate = raw_params.get("rate")
        final_pitch = raw_params.get("pitch")
        final_language_hints = raw_params.get("language_hints")

        # 构造 payload
        payload = {
            "model": model,
            "input": {
                "text": final_text,
                "voice": voice,
                "format": format_type,
                "sample_rate": sample_rate,
            }
        }

        # 可选参数（仅当存在时添加）
        if final_instruction:
            payload["input"]["instruction"] = final_instruction
        if final_volume is not None:
            payload["input"]["volume"] = final_volume
        if final_rate is not None:
            payload["input"]["rate"] = final_rate
        if final_pitch is not None:
            payload["input"]["pitch"] = final_pitch
        if final_language_hints:
            payload["input"]["language_hints"] = final_language_hints

        # 配置中的固定参数
        if seed != -1:
            payload["input"]["seed"] = seed
        if enable_aigc:
            payload["input"]["enable_aigc_tag"] = True
            if aigc_propagator:
                payload["input"]["aigc_propagator"] = aigc_propagator
            if aigc_propagate_id:
                payload["input"]["aigc_propagate_id"] = aigc_propagate_id

        # 请求
        if not api_key or not workspace_id:
            logger.error(f"{self.template_key}: api_key 或 workspace_id 未配置")
            return ""

        url = self._API_ENDPOINT.format(workspace_id=workspace_id)
        headers = http.bearer_headers(api_key)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()

            audio_url = data.get("output", {}).get("audio", {}).get("url")
            if not audio_url:
                logger.error(f"{self.template_key} API 未返回音频 URL: {data}")
                return ""

            return await self._download_audio(audio_url, format_type, config, timeout)

        except httpx.TimeoutException as e:
            logger.error(f"{self.template_key} API 超时 (超时设置: {timeout}s): {e}")
            return ""
        except Exception as e:
            logger.error(f"{self.template_key} API 调用失败: {e}\n{traceback.format_exc()}")
            return ""

    async def _download_audio(self, url: str, fmt: str, config: dict, timeout: int = 60) -> str:
        """下载音频文件到本地存储。
        
        该方法负责从指定的 URL 下载音频文件，并将其保存到本地 TTS 增强器目录中。
        文件名包含时间戳以确保唯一性。
        
        Args:
            url (str): 音频文件的下载 URL
            fmt (str): 音频文件格式（如 "wav"、"mp3" 等）
            config (dict): 供应商配置字典，需包含 `_data_dir` 以指定保存路径
            timeout (int, optional): 下载超时时间，默认为 60 秒
            
        Returns:
            str: 下载后的音频文件路径，失败时返回空字符串
        """
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url)
                resp.raise_for_status()

            return save_audio_bytes(config.get("_data_dir", ""), resp.content, fmt)

        except Exception as e:
            logger.error(f"下载音频失败: {e}")
            return ""

    # ————————————————————————

    # ———————— 参数验证 ————————

    def validate_params(self, params: dict) -> tuple[bool, str]:
        """验证语音合成参数的有效性。
        
        该方法检查传入的参数是否符合百炼 Speech Synthesizer 的要求，
        包括音量范围、语速范围和语言代码的有效性。
        
        Args:
            params (dict): 待验证的语音合成参数字典
            
        Returns:
            tuple[bool, str]: 验证结果，第一个元素表示是否通过验证，
                              第二个元素是错误信息（验证失败时）
        """
        if "volume" in params:
            vol = self._as_int(params["volume"])
            if vol is None or not (0 <= vol <= 100):
                return False, f"volume 必须是 0-100 之间的整数。当前值: {params['volume']}"

        if "rate" in params:
            rate = self._as_float(params["rate"])
            if rate is None or not (0.5 <= rate <= 2.0):
                return False, f"rate 必须是 0.5-2.0 之间的数字。当前值: {params['rate']}"

        if "pitch" in params:
            pitch = self._as_float(params["pitch"])
            if pitch is None or not (0.5 <= pitch <= 2.0):
                return False, f"pitch 必须是 0.5-2.0 之间的数字。当前值: {params['pitch']}"

        if "language_hints" in params:
            hints = params["language_hints"]
            if not isinstance(hints, list):
                return False, f"language_hints 必须是一个列表。当前值: {hints}"
            for lang in hints:
                if lang not in self.VALID_LANGS:
                    return False, f"不支持的语言代码: {lang}，支持: {', '.join(self.VALID_LANGS)}"

        return True, ""

    def sanitize_params(self, params: dict) -> dict:
        """清理和规范化语音合成参数。
        
        该方法对输入的参数进行清理，确保所有参数都符合 API 要求：
        - 移除无效的参数值
        - 保留有效的参数值
        - 记录被移除的无效参数
        
        Args:
            params (dict): 待清理的语音合成参数字典
            
        Returns:
            dict: 清理后的语音合成参数字典
        """
        sanitized = {}
        sanitized["text"] = params.get("text", "")
        sanitized["instruction"] = params.get("instruction", "")
        if "volume" in params:
            vol = self._as_int(params["volume"])
            if vol is not None and 0 <= vol <= 100:
                sanitized["volume"] = vol
            else:
                logger.warning(f"丢弃非法的 volume 参数: {params['volume']}")

        if "rate" in params:
            rate = self._as_float(params["rate"])
            if rate is not None and 0.5 <= rate <= 2.0:
                sanitized["rate"] = rate
            else:
                logger.warning(f"丢弃非法的 rate 参数: {params['rate']}")

        if "pitch" in params:
            pitch = self._as_float(params["pitch"])
            if pitch is not None and 0.5 <= pitch <= 2.0:
                sanitized["pitch"] = pitch
            else:
                logger.warning(f"丢弃非法的 pitch 参数: {params['pitch']}")

        if "language_hints" in params:
            hints = params["language_hints"]
            if isinstance(hints, list):
                valid_hints = [lang for lang in hints if lang in self.VALID_LANGS]
                if valid_hints:
                    sanitized["language_hints"] = valid_hints
                else:
                    logger.warning(f"丢弃非法的 language_hints 参数: {hints}")

        return sanitized

    # ————————————————————————

    # ———————— 音色管理 ————————

    async def create_voice(self, params: dict) -> dict:
        """根据参数确定是声音克隆还是声音设计，并调用对应的创建方法。

        Args:
            params (dict): 创建音色的参数字典，包含以下键：
                - model (str, optional): 模型后缀，如 'flash' 或 'plus'
                - prefix (str): 音色前缀，必填，字母数字且长度不超过 10
                - language_hints (list, optional): 语言提示列表
                - mode (str, optional): 创建模式，'clone' 或 'design'，若不指定则根据参数自动推断
                - audio_data_url (str, optional): 声音克隆时的音频 Data URL（mode='clone' 时必填）
                - voice_prompt (str, optional): 声音设计时的提示词（mode='design' 时必填）
                - preview_text (str, optional): 声音设计时的预览文本
                - sample_rate (int, optional): 声音设计时的采样率
                - response_format (str, optional): 声音设计时的响应格式
                - enable_volume_normalization (bool, optional): 声音克隆时是否启用音量归一化
                - enable_preprocess (bool, optional): 声音克隆时是否启用预处理
                - max_prompt_audio_length (float, optional): 声音克隆时的最大提示音频长度

        Returns:
            dict: 创建结果字典，包含 'voice_id' 和 'extra' 等信息

        Raises:
            ValueError: 如果缺少必填参数或参数格式不合法
            RuntimeError: 如果 API 请求失败
        """
        workspace_id = self.entry.get("workspace_id", "")
        api_key = self.entry.get("api_key", "")
        if not workspace_id or not api_key:
            raise ValueError("workspace_id 和 api_key 不能为空")

        # 公共参数
        model = params.get("model") or self.entry.get("model", "flash")
        target_model = f"{self.MODEL_NAME}-{model}"
        prefix = params.get("prefix")
        if not prefix:
            raise ValueError("prefix 为必填参数")
        if not prefix.isalnum() or len(prefix) > 10:
            raise ValueError("prefix 必须为字母数字，且长度不超过10")
        language_hints = params.get("language_hints", [])
        if not isinstance(language_hints, list):
            raise ValueError("language_hints 必须为列表")
        for hint in language_hints:
            if hint not in self.VALID_LANGS:
                raise ValueError("language_hints 包含不支持的语种")

        mode = params.get("mode")

        # 兼容
        if mode is None:
            if "voice_prompt" in params and "preview_text" in params:
                mode = "design"
            else:
                mode = "clone"
        
        if mode == "design":

            # 声音设计分支
            voice_prompt = params.get("voice_prompt")
            if not voice_prompt:
                raise ValueError("voice_prompt 为必填参数")

            # 声音设计的 language_hints 只支持中英文
            for hint in language_hints:
                if hint not in ["zh", "en"]:
                    raise ValueError("声音设计的 language_hints 只支持中英文")
            preview_text = params.get("preview_text", "欢迎使用声音设计功能")
            sample_rate = params.get("sample_rate", 24000)
            response_format = params.get("response_format", "wav")

            return await self._create_voice_by_design(
                target_model=target_model,
                prefix=prefix,
                language_hints=language_hints,
                voice_prompt=voice_prompt,
                preview_text=preview_text,
                sample_rate=sample_rate,
                response_format=response_format
            )
        elif mode == "clone":

            # 声音克隆分支：仅接受 Data URL，避免依赖公网文件服务器。
            audio_data_url = params.get("audio_data_url")
            if not audio_data_url:
                raise ValueError("audio_data_url 为必填参数")
            enable_volume_normalization = params.get("enable_volume_normalization", False)
            enable_preprocess = params.get("enable_preprocess", False)
            max_prompt_audio_length = params.get("max_prompt_audio_length")

            return await self._create_voice_by_clone(
                target_model=target_model,
                prefix=prefix,
                language_hints=language_hints,
                audio_data_url=audio_data_url,
                enable_volume_normalization=enable_volume_normalization,
                enable_preprocess=enable_preprocess,
                max_prompt_audio_length=max_prompt_audio_length
            )
        else:
            raise ValueError("未知模式的声音创建请求")

    async def _create_voice_by_clone(
        self,
        target_model: str,
        prefix: str,
        language_hints: list,
        audio_data_url: str,
        enable_volume_normalization: bool,
        enable_preprocess: bool,
        max_prompt_audio_length: float | None
    ) -> dict:
        """通过 Data URL 方式复刻音色。

        Args:
            target_model (str): 目标模型名称，如 'qwen-audio-3.0-tts-flash'
            prefix (str): 音色前缀
            language_hints (list): 语言提示列表
            audio_data_url (str): Base64 编码的参考音频 Data URL
            enable_volume_normalization (bool): 是否启用音量归一化
            enable_preprocess (bool): 是否启用音频预处理
            max_prompt_audio_length (float | None): 最大提示音频长度（秒），为 None 时不限制

        Returns:
            dict: 创建结果字典，包含 'voice_id' 和 'extra' 等信息

        Raises:
            ValueError: Data URL 格式、MIME 类型、Base64 数据或文件大小不合法
            RuntimeError: 如果 API 请求失败或未返回 voice_id
        """
        mime_type, audio_size = _validate_clone_data_url(audio_data_url)
        workspace_id = self.entry.get("workspace_id", "")
        api_key = self.entry.get("api_key", "")
        url = f"https://{workspace_id}.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/customization"
        headers = http.bearer_headers(api_key)
        payload = {
            "model": "voice-enrollment",
            "input": {
                "action": "create_voice",
                "target_model": target_model,
                "prefix": prefix,
                "url": audio_data_url,
                "enable_volume_normalization": str(enable_volume_normalization).lower(),
            }
        }
        if language_hints:
            payload["input"]["language_hints"] = language_hints
        if enable_preprocess:
            payload["input"]["enable_preprocess"] = True
        if max_prompt_audio_length is not None:
            if not isinstance(max_prompt_audio_length, (int, float)):
                raise ValueError("max_prompt_audio_length 必须为数字")
            if 3.0 <= max_prompt_audio_length <= 30.0:
                payload["input"]["max_prompt_audio_length"] = float(max_prompt_audio_length)
            else:
                raise ValueError("max_prompt_audio_length 必须在 3.0 到 30.0 之间")

        safe_payload = {
            **payload,
            "input": {
                **payload["input"],
                "url": f"<Data URL {mime_type}, {audio_size} bytes>",
            },
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                logger.debug(f"创建音色请求: {safe_payload}")
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code != 200:
                    try:
                        error_msg = http.extract_error_message(resp.json(), fallback_text=resp.text)
                    except Exception:
                        error_msg = resp.text
                    error_msg = _redact_data_urls(error_msg)
                    raise RuntimeError(f"百炼 API 错误 (HTTP {resp.status_code}): {error_msg}")
                data = resp.json()
        except httpx.HTTPStatusError as e:

            # 捕获 httpx 抛出的 HTTPStatusError
            try:
                error_msg = http.extract_error_message(
                    e.response.json(), fallback_text=e.response.text
                )
            except Exception:
                error_msg = e.response.text
            error_msg = _redact_data_urls(error_msg)
            raise RuntimeError(f"请求失败: {error_msg}")
        except Exception as e:
            safe_error = _redact_data_urls(str(e))
            raise RuntimeError(f"请求异常: {safe_error}")

        voice_id = data.get("output", {}).get("voice_id")
        if not voice_id:
            safe_data = _redact_data_urls(data)
            raise RuntimeError(f"创建音色失败: {safe_data}")
        return {"voice_id": voice_id, "extra": data.get("output", {})}

    async def _create_voice_by_design(
        self,
        target_model: str,
        prefix: str,
        language_hints: list,
        voice_prompt: str,
        preview_text: str,
        sample_rate: int,
        response_format: str
    ) -> dict:
        """通过声音设计方式创建音色。

        Args:
            target_model (str): 目标模型名称，如 'qwen-audio-3.0-tts-plus'
            prefix (str): 音色前缀
            language_hints (list): 语言提示列表（仅支持 'zh' 和 'en'）
            voice_prompt (str): 声音设计的提示词
            preview_text (str): 预览合成的文本
            sample_rate (int): 采样率
            response_format (str): 响应音频格式（如 'wav'）

        Returns:
            dict: 创建结果字典，包含 'voice_id'、'preview_audio' 和 'extra' 等信息

        Raises:
            RuntimeError: 如果 API 请求失败或未返回 voice_id
        """
        workspace_id = self.entry.get("workspace_id", "")
        api_key = self.entry.get("api_key", "")

        url = f"https://{workspace_id}.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/customization"
        headers = http.bearer_headers(api_key)

        self.validate_text_length(text=voice_prompt, max_len=500, field_name="voice_prompt")
        payload = {
            "model": "voice-enrollment",
            "input": {
                "action": "create_voice",
                "target_model": target_model,
                "voice_prompt": voice_prompt,
                "preview_text": preview_text,
                "prefix": prefix,
            },
            "parameters": {
                "sample_rate": sample_rate,
                "response_format": response_format
            }
        }
        if language_hints:

            # 语言提示作为 input 下的 language_hints
            payload["input"]["language_hints"] = language_hints

        async with httpx.AsyncClient(timeout=30) as client:
            logger.debug(f"创建声音设计音色请求: {payload}")
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                try:
                    error_msg = http.extract_error_message(resp.json(), fallback_text=resp.text)
                except Exception:
                    error_msg = resp.text
                raise RuntimeError(f"百炼设计 API 错误 (HTTP {resp.status_code}): {error_msg}")
            data = resp.json()

        voice_id = data.get("output", {}).get("voice_id")
        preview_audio = data.get("output", {}).get("preview_audio")
        if not voice_id:
            raise RuntimeError(f"创建音色失败，未返回 voice_id: {data}")

        return {
            "voice_id": voice_id,
            "preview_audio": preview_audio,   # 包含 data (base64), sample_rate, response_format
            "extra": data.get("output", {})
        }

    async def list_voice(self, **kwargs) -> dict:
        """查询百炼音色列表。

        Args:
            **kwargs: 查询参数，支持以下键：
                - prefix (str, optional): 按前缀过滤音色
                - page_size (int, optional): 每页数量，默认 20
                - page_index (int, optional): 页码索引，默认 0

        Returns:
            dict: 包含 'items'（音色列表）和 'total'（音色总数）的字典

        Raises:
            ValueError: 如果 workspace_id 或 api_key 未配置
            httpx.HTTPStatusError: 如果 API 请求返回非 200 状态码
        """
        workspace_id = self.entry.get("workspace_id", "")
        api_key = self.entry.get("api_key", "")
        if not workspace_id or not api_key:
            raise ValueError("workspace_id 和 api_key 不能为空")

        prefix = kwargs.get("prefix", "")
        page_size = kwargs.get("page_size", 20)
        page_index = kwargs.get("page_index", 0)

        url = f"https://{workspace_id}.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/customization"
        headers = http.bearer_headers(api_key)
        payload = {
            "model": "voice-enrollment",
            "input": {
                "action": "list_voice",
                "page_size": page_size,
                "page_index": page_index
            }
        }
        if prefix:
            payload["input"]["prefix"] = prefix

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        voice_list = data.get("output", {}).get("voice_list", [])
        items = []
        for v in voice_list:
            voice_id = v.get("voice_id")

            # 只保留 MODEL_NAME 开头的音色
            if voice_id.startswith(self.MODEL_NAME):
                items.append({
                    "voice_id": v.get("voice_id"),
                    "created_at": v.get("gmt_create"),
                    "updated_at": v.get("gmt_modified"),
                    "status": v.get("status", "UNKNOWN")
                })
        return {"items": items, "total": len(items)}

    async def delete_voice(self, **kwargs) -> bool:
        """删除百炼音色。

        Args:
            **kwargs: 删除参数，支持以下键：
                - voice_id (str): 待删除的音色 ID，必填

        Returns:
            bool: 删除成功返回 True

        Raises:
            ValueError: 如果 workspace_id、api_key 或 voice_id 为空
            httpx.HTTPStatusError: 如果 API 请求返回非 200 状态码
        """
        workspace_id = self.entry.get("workspace_id", "")
        api_key = self.entry.get("api_key", "")
        voice_id = kwargs.get("voice_id")
        if not workspace_id or not api_key or not voice_id:
            raise ValueError("workspace_id, api_key, voice_id 不能为空")

        url = f"https://{workspace_id}.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/customization"
        headers = http.bearer_headers(api_key)
        payload = {
            "model": "voice-enrollment",
            "input": {
                "action": "delete_voice",
                "voice_id": voice_id
            }
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()

            # 百炼删除成功会返回 {}，无错误即为成功
            return True

    def _extract_model_from_voice_id(self, voice_id: str) -> str | None:
        """从音色 ID 中提取模型版本 (flash/plus)。

        Args:
            voice_id (str): 音色 ID 字符串

        Returns:
            str | None: 如果识别到 'flash' 或 'plus' 则返回对应字符串，否则返回 None
        """
        if not voice_id or not voice_id.startswith(self.MODEL_NAME):
            return None
        parts = voice_id.split('-')
        name_parts = self.MODEL_NAME.split('-')
        version = parts[len(name_parts)]
        if version in ('flash', 'plus'):
            return version
        return None

    # ————————————————————————
