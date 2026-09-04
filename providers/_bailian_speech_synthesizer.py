"""百炼 Speech Synthesizer 适配器"""

import httpx
from datetime import datetime
from pathlib import Path
import traceback

from astrbot.core import logger
from astrbot.core.agent.tool import FunctionTool

from .base import TTSProviderAdapter

from typing import Any


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
    VALID_LANGS = ["zh", "en", "fr", "de", "ja", "ko", "ru", "pt", "th", "id", "vi", "es", "it", "ms", "fil", "ar"]
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
    
        logger.debug(f"Initializing {self.__class__.__name__} with entry: {entry}, MODEL_NAME: {self.MODEL_NAME}")
        self.docs_content = self._load_docs()
        self.design_docs_content = self._load_design_docs()

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
        按 '-' 分割后长度为 len(MODEL_NAME.split('-')) + 4，且索引 len(MODEL_NAME.split('-')) + 1 为 'vd'。
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
        """返回用于 TTS 参数增强的 Function Tool。
        
        该方法定义了一个名为 "tts_enhance" 的工具，用于接收和结构化语音合成参数。
        参数包括文本内容、情感指令、音量、语速和语言提示等。
        
        Returns:
            FunctionTool: 配置好的 FunctionTool 对象，包含所有必要的参数定义
        """
        return FunctionTool(
            name="tts_enhance",
            description="为语音合成提供增强参数，包括文本、指令、音量、语速和语言提示。",
            parameters={
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
            
            # 无需执行，只用于让 LLM 输出参数
            handler=None  
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
        return f"""你是语音合成参数优化助手，负责为 TTS 模型准备合成参数。以下是 TTS 模型的参数使用说明：

{docs}

现在请根据用户提供的文本和上下文，调用 `tts_enhance` 工具，提供合适的参数（包括 text 和其他可选参数）。请直接调用工具，不要额外解释。"""

    # ---------- 3. 解析 SubAgent 响应 ----------
    def parse_subagent_response(self, response_data: Any) -> dict[str, Any]:
        """解析 SubAgent 返回的数据，提取语音合成参数。
        
        该方法处理 SubAgent 的响应数据，将其转换为语音合成所需的参数格式。
        如果响应是字典格式，则直接返回；如果是字符串，则作为文本参数返回。
        
        Args:
            response_data (Any): SubAgent 的响应数据，可以是字典或字符串
            
        Returns:
            dict[str, Any]: 包含语音合成参数的字典，至少包含 text 字段；
                           如果响应无效或缺少 text 字段，则返回空字典
        """
        if isinstance(response_data, dict):

            # 确保 text 存在
            if "text" not in response_data:
                logger.warning("工具调用缺少 'text' 字段，使用原始文本")
                return {}
            return response_data
        
        # 降级：纯文本
        if isinstance(response_data, str) and response_data.strip():
            return {"text": response_data.strip()}
        return {}

    # ---------- 4. 调用 TTS API ----------
    async def call_api(
        self,
        text: str,               # 原始文本（备用）
        raw_params: dict[str, Any],  # 从工具解析出的参数（优先）
        config: dict[str, Any]   # 当前供应商的 entry 配置
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
        voice = raw_params.get("voice") or config.get("voice")
        if not voice:
            raise ValueError("未提供音色 ID，无法合成语音")

        # 从 voice 解析模型（仅对复刻音色）
        parsed_model = self._extract_model_from_voice_id(voice)
        if parsed_model is not None:

            # 复刻音色：使用解析出的模型
            model_suffix = parsed_model
            config_model = config.get("model")

            # 如果配置中有 model 且不一致，发出警告（除非抑制）
            if config_model and config_model != model_suffix and not raw_params.get("_suppress_model_warning", False):
                logger.warning(
                    f"配置中的 model 参数 '{config_model}' 与音色 ID 解析的模型 '{model_suffix}' 不一致，"
                    f"将使用解析出的模型。请检查配置。"
                )
        else:

            # 非复刻音色：使用配置中的 model
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
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

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
            data_dir = config.get("_data_dir")
            if not data_dir:
                logger.error("未找到 _data_dir")
                return ""
            data_dir = Path(data_dir)
            data_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"tts_{timestamp}.{fmt}"
            filepath = data_dir / filename

            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                filepath.write_bytes(resp.content)

            logger.debug(f"TTS 音频已保存: {filepath}")
            return str(filepath)

        except Exception as e:
            logger.error(f"下载音频失败: {e}")
            return ""

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
            vol = params["volume"]
            if not isinstance(vol, int) or not (0 <= vol <= 100):
                return False, f"volume 必须是 0-100 之间的整数。当前值: {vol}"

        if "rate" in params:
            rate = params["rate"]
            if not isinstance(rate, (int, float)) or not (0.5 <= rate <= 2.0):
                return False, f"rate 必须是 0.5-2.0 之间的数字。当前值: {rate}"

        if "pitch" in params:
            pitch = params["pitch"]
            if not isinstance(pitch, (int, float)) or not (0.5 <= pitch <= 2.0):
                return False, f"pitch 必须是 0.5-2.0 之间的数字。当前值: {pitch}"

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
            vol = params["volume"]
            if isinstance(vol, int) and 0 <= vol <= 100:
                sanitized["volume"] = vol
            else:
                logger.warning(f"丢弃非法的 volume 参数: {vol}")

        if "rate" in params:
            rate = params["rate"]
            if isinstance(rate, (int, float)) and 0.5 <= rate <= 2.0:
                sanitized["rate"] = rate
            else:
                logger.warning(f"丢弃非法的 rate 参数: {rate}")

        if "pitch" in params:
            pitch = params["pitch"]
            if isinstance(pitch, (int, float)) and 0.5 <= pitch <= 2.0:
                sanitized["pitch"] = pitch
            else:
                logger.warning(f"丢弃非法的 pitch 参数: {pitch}")

        if "language_hints" in params:
            hints = params["language_hints"]
            if isinstance(hints, list):
                valid_hints = [lang for lang in hints if lang in self.VALID_LANGS]
                if valid_hints:
                    sanitized["language_hints"] = valid_hints
                else:
                    logger.warning(f"丢弃非法的 language_hints 参数: {hints}")

        return sanitized

    # ———————— 音色管理 ————————

    async def create_voice(self, params: dict) -> dict:
        """根据参数确定是声音克隆还是声音设计，并调用对应的创建方法。

        Args:
            params (dict): 创建音色的参数字典，包含以下键：
                - model (str, optional): 模型后缀，如 'flash' 或 'plus'
                - prefix (str): 音色前缀，必填，字母数字且长度不超过 10
                - language_hints (list, optional): 语言提示列表
                - mode (str, optional): 创建模式，'clone' 或 'design'，若不指定则根据参数自动推断
                - audio_url (str, optional): 声音克隆时的音频 URL（mode='clone' 时必填）
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

            # 声音克隆分支
            audio_url = params.get("audio_url")
            if not audio_url:
                raise ValueError("audio_url 为必填参数")
            enable_volume_normalization = params.get("enable_volume_normalization", False)
            enable_preprocess = params.get("enable_preprocess", False)
            max_prompt_audio_length = params.get("max_prompt_audio_length")

            return await self._create_voice_by_clone(
                target_model=target_model,
                prefix=prefix,
                language_hints=language_hints,
                audio_url=audio_url,
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
        audio_url: str,
        enable_volume_normalization: bool,
        enable_preprocess: bool,
        max_prompt_audio_length: float | None
    ) -> dict:
        """通过声音克隆方式创建音色。

        Args:
            target_model (str): 目标模型名称，如 'qwen-audio-3.0-tts-flash'
            prefix (str): 音色前缀
            language_hints (list): 语言提示列表
            audio_url (str): 用于克隆的参考音频 URL
            enable_volume_normalization (bool): 是否启用音量归一化
            enable_preprocess (bool): 是否启用音频预处理
            max_prompt_audio_length (float | None): 最大提示音频长度（秒），为 None 时不限制

        Returns:
            dict: 创建结果字典，包含 'voice_id' 和 'extra' 等信息

        Raises:
            RuntimeError: 如果 API 请求失败或未返回 voice_id
        """
        workspace_id = self.entry.get("workspace_id", "")
        api_key = self.entry.get("api_key", "")
        url = f"https://{workspace_id}.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/customization"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"

        }
        payload = {
            "model": "voice-enrollment",
            "input": {
                "action": "create_voice",
                "target_model": target_model,
                "prefix": prefix,
                "url": audio_url,
                "enable_volume_normalization": str(enable_volume_normalization).lower(),
            }
        }
        if language_hints:
            payload["input"]["language_hints"] = language_hints
        if enable_preprocess:
            payload["input"]["enable_preprocess"] = True
        if max_prompt_audio_length is not None:
            payload["input"]["max_prompt_audio_length"] = float(max_prompt_audio_length)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                logger.debug(f"创建音色请求: {payload}")
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code != 200:
                    try:
                        error_json = resp.json()
                        
                        # 常见错误字段：message、error、detail 等
                        error_msg = error_json.get("message") or error_json.get("error") or error_json.get("detail") or resp.text
                    except:
                        error_msg = resp.text
                    raise RuntimeError(f"百炼 API 错误 (HTTP {resp.status_code}): {error_msg}")
                data = resp.json()
        except httpx.HTTPStatusError as e:

            # 捕获 httpx 抛出的 HTTPStatusError
            try:
                error_json = e.response.json()
                error_msg = error_json.get("message") or error_json.get("error") or error_json.get("detail") or e.response.text
            except:
                error_msg = e.response.text
            raise RuntimeError(f"请求失败: {error_msg}")
        except Exception as e:
            raise RuntimeError(f"请求异常: {str(e)}")

        voice_id = data.get("output", {}).get("voice_id")
        if not voice_id:
            raise RuntimeError(f"创建音色失败: {data}")
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
        workspace_id = self.entry.get("workspace_id")
        api_key = self.entry.get("api_key")

        url = f"https://{workspace_id}.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/customization"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
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
                    error_json = resp.json()
                    error_msg = error_json.get("message") or error_json.get("error") or resp.text
                except:
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
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
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
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
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
