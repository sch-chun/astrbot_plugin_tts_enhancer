import httpx
from pathlib import Path
from datetime import datetime
from typing import Any

from astrbot.core import logger
from astrbot.core.agent.tool import FunctionTool

from .base import TTSProviderAdapter
from ..src.audio_utils import get_audio_duration, trim_audio_to_max, AudioConstraints


class MinimaxSpeech2_8Adapter(TTSProviderAdapter):
    """MiniMax Speech 2.8 TTS 适配器（仅支持 HD / Turbo）"""

    # 仅支持 2.8 系列
    SUPPORTED_MODELS = ["HD", "Turbo"]

    # 情感标签（与 API 一致）
    VALID_EMOTIONS = [
        "happy", "sad", "angry", "fearful",
        "disgusted", "surprised", "calm", "fluent"
    ]

    # 语言增强（完整列表，与官方一致）
    VALID_LANGUAGE_BOOST = [
        "Chinese", "Chinese,Yue", "English", "Arabic", "Russian",
        "Spanish", "French", "Portuguese", "German", "Turkish",
        "Dutch", "Ukrainian", "Vietnamese", "Indonesian", "Japanese",
        "Italian", "Korean", "Thai", "Polish", "Romanian",
        "Greek", "Czech", "Finnish", "Hindi", "Bulgarian",
        "Danish", "Hebrew", "Malay", "Persian", "Slovak",
        "Swedish", "Croatian", "Filipino", "Hungarian", "Norwegian",
        "Slovenian", "Catalan", "Nynorsk", "Tamil", "Afrikaans",
        "auto"
    ]

    def __init__(self, entry: dict) -> None:
        super().__init__(entry)   # 基类会加载 docs/minimax_speech_2_8.md 到 self.docs_content

    # ---------- 工具 Schema ----------
    def get_tool_schema(self) -> FunctionTool:
        return FunctionTool(
            name="tts_enhance",
            description="为 MiniMax Speech 2.8 语音合成提供增强参数，支持情感、语速、音量、语调、语言增强及 LaTeX 朗读。",
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "合成文本，支持语气词标签 (laughs) 和停顿 <#x#>"
                    },
                    "emotion": {
                        "type": "string",
                        "enum": self.VALID_EMOTIONS,
                        "description": "情感标签（模型会自动匹配合适情绪，一般无需指定）"
                    },
                    "speed": {
                        "type": "number",
                        "minimum": 0.5,
                        "maximum": 2.0,
                        "description": "语速倍率，默认 1.0"
                    },
                    "vol": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 10.0,
                        "description": "音量，默认 1.0"
                    },
                    "pitch": {
                        "type": "integer",
                        "minimum": -12,
                        "maximum": 12,
                        "description": "语调偏移，默认 0"
                    },
                    "language_boost": {
                        "type": "string",
                        "enum": self.VALID_LANGUAGE_BOOST,
                        "description": "增强对指定语种的识别，一般留空，默认设为 'auto' 让模型自主判断"
                    },
                    "latex_read": {
                        "type": "boolean",
                        "description": "是否朗读 LaTeX 公式，仅中文有效，会自动设置 language_boost=Chinese，公式需在首尾加上 $$ 包裹"
                    }
                },
                "required": ["text"]
            },
            handler=None
        )

    # ---------- SubAgent 系统提示 ----------
    def get_subagent_system_prompt(self) -> str:
        return f"""你是语音合成参数优化助手，负责为 MiniMax Speech 2.8 模型准备合成参数。以下是模型能力说明：

{self.docs_content}

请根据用户提供的文本和上下文，调用 `tts_enhance` 工具提供合适的参数（text 必填，其他可选）。直接调用工具，不要额外解释。"""

    # ---------- 解析 SubAgent 响应 ----------
    def parse_subagent_response(self, response_data: Any) -> dict[str, Any]:
        if isinstance(response_data, dict):
            if "text" not in response_data:
                logger.warning("工具调用缺少 'text' 字段，使用原始文本")
                return {}
            return response_data
        if isinstance(response_data, str) and response_data.strip():
            return {"text": response_data.strip()}
        return {}

    # ---------- 调用 API ----------
    async def call_api(
        self,
        text: str,
        raw_params: dict[str, Any],
        config: dict[str, Any]
    ) -> str:
        api_key = config.get("api_key")
        if not api_key:
            logger.error("MiniMax API Key 未配置")
            return ""

        model = config.get("model", "HD")
        if model not in self.SUPPORTED_MODELS:
            logger.warning(f"不支持的模型 {model}，将使用 HD")
            model = "HD"

        model_id = f"speech-2.8-{model.lower()}"

        voice_id = config.get("voice_id")
        if not voice_id:
            logger.error("未配置 voice_id")
            return ""

        # 音频设置
        audio_setting = {
            "sample_rate": config.get("sample_rate", 32000),
            "bitrate": config.get("bitrate", 128000),
            "format": config.get("format", "mp3"),
            "channel": config.get("channel", 1),
        }

        # 合并参数（工具参数优先）
        final_text = raw_params.get("text", text)
        if not final_text:
            logger.error("TTS 文本为空")
            return ""

        voice_setting = {
            "voice_id": voice_id,
            "speed": raw_params.get("speed", 1.0),
            "vol": raw_params.get("vol", 1.0),
            "pitch": raw_params.get("pitch", 0),
        }

        # text_normalization 从配置获取（若配置未设置则默认 false）
        if config.get("text_normalization", False):
            voice_setting["text_normalization"] = True

        # 可选 emotion
        if "emotion" in raw_params:
            voice_setting["emotion"] = raw_params["emotion"]

        # latex_read 从工具参数获取（不写入 voice_setting，需特殊处理）
        latex_read = raw_params.get("latex_read", False)

        # 语言增强
        language_boost = raw_params.get("language_boost", "auto")

        # 若 latex_read 为 True，强制 language_boost = "Chinese"（覆盖）
        if latex_read:
            language_boost = "Chinese"
            if "language_boost" in raw_params and raw_params["language_boost"] != "Chinese":
                logger.warning("latex_read 为 True，强制将 language_boost 设置为 'Chinese'")

        payload = {
            "model": model_id,
            "text": final_text,
            "stream": False,
            "voice_setting": voice_setting,
            "audio_setting": audio_setting,
            "output_format": "hex",
        }

        if language_boost:
            payload["language_boost"] = language_boost

        if latex_read:
            payload["latex_read"] = True

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        url = "https://api.minimax.cn/v1/t2a_v2"
        timeout = config.get("timeout", 60)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()

            base_resp = data.get("base_resp", {})
            if base_resp.get("status_code") != 0:
                logger.error(f"MiniMax API 错误: {base_resp.get('status_msg')}")
                return ""

            audio_hex = data.get("data", {}).get("audio")
            if not audio_hex:
                logger.error("响应中无 audio 字段")
                return ""

            audio_bytes = bytes.fromhex(audio_hex)
            audio_format = audio_setting.get("format", "mp3")
            data_dir = config.get("_data_dir")
            if not data_dir:
                logger.error("未找到 _data_dir，无法保存音频")
                return ""
            data_dir = Path(data_dir)
            data_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"tts_{timestamp}.{audio_format}"
            filepath = data_dir / filename
            filepath.write_bytes(audio_bytes)
            logger.debug(f"TTS 音频已保存: {filepath}")
            return str(filepath)

        except httpx.TimeoutException:
            logger.error(f"MiniMax API 超时 (timeout={timeout}s)")
            return ""
        except Exception as e:
            logger.error(f"MiniMax API 调用失败: {e}")
            return ""

    # ---------- 参数校验 ----------
    def validate_params(self, params: dict) -> tuple[bool, str]:
        if "speed" in params and not (0.5 <= params["speed"] <= 2.0):
            return False, f"speed 必须在 0.5~2.0 之间，当前 {params['speed']}"
        
        if "vol" in params and not (0.0 <= params["vol"] <= 10.0):
            return False, f"vol 必须在 0~10 之间，当前 {params['vol']}"
        
        if "pitch" in params and not (-12 <= params["pitch"] <= 12):
            return False, f"pitch 必须在 -12~12 之间，当前 {params['pitch']}"
        
        if "emotion" in params and params["emotion"] not in self.VALID_EMOTIONS:
            return False, f"不支持的情感标签: {params['emotion']}"
        
        if "language_boost" in params and params["language_boost"] not in self.VALID_LANGUAGE_BOOST:
            return False, f"不支持的语言增强: {params['language_boost']}"
        
        return True, ""

    def sanitize_params(self, params: dict) -> dict:
        sanitized = {"text": params.get("text", "")}
        for key in ["speed", "vol", "pitch", "emotion", "language_boost"]:
            if key in params:
                valid, _ = self.validate_params({key: params[key]})
                if valid:
                    sanitized[key] = params[key]
                else:
                    logger.warning(f"丢弃非法的 {key} 参数: {params[key]}")
        return sanitized

    # ---------- 音色管理 ----------
    
    # ============================================================
    # 1. 文件管理
    # ============================================================

    async def upload_file(self, file_path: str, **kwargs) -> dict:
        """上传音频文件到 MiniMax，返回文件信息。

        支持自动裁剪超长的主音频 (voice_clone)，但示例音频（prompt_audio）超长会直接报错。

        Args:
            file_path: 本地音频文件路径
            **kwargs:
                purpose (str): "voice_clone" (主音频) 或 "prompt_audio" (示例音频)，默认 "voice_clone"

        Returns:
            dict: 包含 file_id, bytes, created_at, filename, purpose

        Raises:
            ValueError: purpose 参数不合法
            RuntimeError: 上传失败
        """
        # 1. 提取参数
        purpose = kwargs.get("purpose", "voice_clone")

        # 2. 基础校验
        if purpose not in ["voice_clone", "prompt_audio"]:
            raise ValueError(f"不支持的 purpose: {purpose}，仅支持 'voice_clone' 或 'prompt_audio'")

        api_key = self.entry.get("api_key")
        if not api_key:
            raise RuntimeError("API Key 未配置")

        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            raise RuntimeError(f"文件不存在: {file_path}")

        # 3. 时长校验与裁剪
        duration = get_audio_duration(str(file_path_obj))
        if duration is None:
            raise RuntimeError("无法读取音频时长，请确认文件格式有效（mp3/m4a/wav）")

        trimmed_path = None
        try:
            if purpose == "voice_clone":
                if duration < AudioConstraints.MINIMAX_CLONE_MIN - 0.01:
                    raise ValueError(f"音频时长 {duration:.1f}s 不足 {AudioConstraints.MINIMAX_CLONE_MIN}s")
                if duration > AudioConstraints.MINIMAX_CLONE_MAX + 0.01:
                    logger.warning(
                        f"音频时长 {duration:.1f}s 超过限制 {AudioConstraints.MINIMAX_CLONE_MAX}s，"
                        f"将自动裁剪至 {AudioConstraints.MINIMAX_CLONE_MAX - 0.5:.1f}s 后上传"
                    )
                    trimmed_path = trim_audio_to_max(
                        str(file_path_obj),
                        max_sec=AudioConstraints.MINIMAX_CLONE_MAX,
                        margin=0.5,
                    )
                    file_path = trimmed_path

            elif purpose == "prompt_audio":
                if duration > AudioConstraints.MINIMAX_PROMPT_MAX + 0.01:
                    raise ValueError(
                        f"示例音频时长 {duration:.1f}s 超过 {AudioConstraints.MINIMAX_PROMPT_MAX}s，请提供更短的音频"
                    )

            # 4. 文件大小 & 格式检查
            file_size = Path(file_path).stat().st_size
            if file_size > 20 * 1024 * 1024:
                raise RuntimeError(f"文件大小超过 20MB 限制: {file_size} 字节")

            ext = Path(file_path).suffix.lower()
            if ext not in [".mp3", ".m4a", ".wav"]:
                raise RuntimeError(f"不支持的音频格式: {ext}，仅支持 mp3、m4a、wav")

            # 5. 调用 MiniMax API
            url = "https://api.minimax.cn/v1/files/upload"
            headers = {"Authorization": f"Bearer {api_key}"}

            async with httpx.AsyncClient(timeout=60) as client:
                with open(file_path, "rb") as f:
                    files = {"file": (Path(file_path).name, f, "audio/mpeg")}
                    data = {"purpose": purpose}
                    resp = await client.post(url, headers=headers, data=data, files=files)
                    resp.raise_for_status()
                    result = resp.json()

            base_resp = result.get("base_resp", {})
            if base_resp.get("status_code") != 0:
                raise RuntimeError(f"上传失败: {base_resp.get('status_msg')}")

            file_obj = result.get("file", {})
            if not file_obj.get("file_id"):
                raise RuntimeError(f"未返回 file_id: {result}")

            logger.debug(f"文件上传成功: file_id={file_obj.get('file_id')}, purpose={purpose}")
            return file_obj

        finally:
            if trimmed_path and trimmed_path != str(file_path_obj):
                try:
                    Path(trimmed_path).unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"删除裁剪临时文件失败: {e}")

    async def list_files(self, **kwargs) -> dict:
        """列出已上传的文件。

        Args:
            **kwargs:
                purpose (str): "voice_clone" 或 "prompt_audio"，默认 "voice_clone"

        Returns:
            dict: 包含 files 列表和 base_resp
        """
        purpose = kwargs.get("purpose", "voice_clone")

        api_key = self.entry.get("api_key")
        if not api_key:
            raise ValueError("API Key 未配置")

        if purpose not in ["voice_clone", "prompt_audio"]:
            raise ValueError(f"不支持的 purpose: {purpose}")

        url = f"https://api.minimax.cn/v1/files/list?purpose={purpose}"
        headers = {"Authorization": f"Bearer {api_key}"}

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                result = resp.json()

            base_resp = result.get("base_resp", {})
            if base_resp.get("status_code") != 0:
                raise RuntimeError(f"查询文件列表失败: {base_resp.get('status_msg')}")

            return {
                "files": result.get("files", []),
                "total": len(result.get("files", [])),
                "base_resp": base_resp
            }

        except httpx.TimeoutException:
            raise RuntimeError("查询文件列表超时")
        except Exception as e:
            raise RuntimeError(f"查询文件列表异常: {e}")

    async def get_file_content(self, file_id: int) -> bytes:
        """下载文件内容（用于前端预览播放）。

        Args:
            file_id: 文件的数字 ID

        Returns:
            bytes: 音频文件的二进制数据
        """
        api_key = self.entry.get("api_key")
        if not api_key:
            raise ValueError("API Key 未配置")

        url = f"https://api.minimax.cn/v1/files/retrieve_content?file_id={file_id}"
        headers = {"Authorization": f"Bearer {api_key}"}

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                return resp.content  # 直接返回音频字节

        except httpx.TimeoutException:
            raise RuntimeError("下载文件超时")
        except Exception as e:
            raise RuntimeError(f"下载文件异常: {e}")

    async def delete_file(self, file_id: int, **kwargs) -> bool:
        """删除已上传的文件。

        Args:
            file_id: 文件的数字 ID
            **kwargs:
                purpose (str): "voice_clone" 或 "prompt_audio"，默认 "voice_clone"

        Returns:
            bool: 删除成功返回 True
        """
        api_key = self.entry.get("api_key")
        if not api_key:
            raise ValueError("API Key 未配置")

        purpose = kwargs.get("purpose", "voice_clone")
        if purpose not in ["voice_clone", "prompt_audio"]:
            raise ValueError(f"不支持的 purpose: {purpose}")

        payload = {"file_id": file_id, "purpose": purpose}
        url = "https://api.minimax.cn/v1/files/delete"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                result = resp.json()

            base_resp = result.get("base_resp", {})
            if base_resp.get("status_code") != 0:
                logger.error(f"删除文件失败: {base_resp.get('status_msg')}")
                return False

            logger.debug(f"文件删除成功: file_id={file_id}")
            return True

        except httpx.TimeoutException:
            raise RuntimeError("删除文件超时")
        except Exception as e:
            raise RuntimeError(f"删除文件异常: {e}")

    # ============================================================
    # 2. 音色克隆
    # ============================================================

    async def create_voice(self, params: dict) -> dict:
        """创建音色（支持克隆和设计两种模式）。

        Args:
            params: 创建参数
                - mode (str): "clone" 或 "design"

                克隆模式 (mode="clone") 参数：
                    - file_id (int): 主音频的 file_id（必填），通过 upload_file(purpose="voice_clone") 获得
                    - prompt_file_id (int, optional): 示例音频的 file_id，通过 upload_file(purpose="prompt_audio") 获得
                    - voice_id (str, optional): 自定义音色 ID，长度 8-256，首字母必须为英文字母
                    - text (str, optional): 试听文本，限制 1000 字符
                    - model (str, optional): 试听模型，默认 "speech-2.8-hd"
                    - language_boost (str, optional): 语言增强
                    - text_validation (str, optional): ASR 验证文本，上限 200 字符
                    - accuracy (float, optional): ASR 相似度阈值 0-1，默认 0.7
                    - need_noise_reduction (bool, optional): 是否降噪，默认 False
                    - need_volume_normalization (bool, optional): 是否音量归一化，默认 False
                    - aigc_watermark (bool, optional): 是否添加 AIGC 标识，默认 False

                设计模式 (mode="design") 参数：
                    - prompt (str): 音色描述（必填）
                    - preview_text (str): 试听音频文本（必填，上限 500 字符）
                    - voice_id (str, optional): 自定义音色 ID
                    - aigc_watermark (bool, optional): 是否添加 AIGC 标识，默认 False

        Returns:
            dict: 包含 voice_id 和 demo_audio/trial_audio（如有）的结果
        """
        mode = params.get("mode")
        if mode is None:
            if "file_id" in params:
                mode = "clone"
            elif "prompt" in params and "preview_text" in params:
                mode = "design"
            else:
                raise ValueError("无法推断创建模式，请指定 mode='clone' 或 mode='design'")

        if mode == "clone":
            return await self._create_voice_by_clone(params)
        elif mode == "design":
            return await self._create_voice_by_design(params)
        else:
            raise ValueError(f"未知模式: {mode}")

    async def _create_voice_by_clone(self, params: dict) -> dict:
        """通过 file_id 进行音色克隆（不处理本地文件）。"""
        api_key = self.entry.get("api_key")
        if not api_key:
            raise ValueError("API Key 未配置")

        file_id = params.get("file_id")
        if not file_id:
            raise ValueError("file_id 为必填参数（主音频）")

        # 构造请求
        voice_id = params.get("voice_id")
        if not voice_id:

            # 自动生成 voice_id（首字母必须为英文字母）
            voice_id = f"Clone_{datetime.now().strftime('%Y%m%d%H%M%S')}_{id(self)}"

        payload = {
            "file_id": int(file_id),
            "voice_id": voice_id,
        }

        # 可选：示例音频
        prompt_file_id = params.get("prompt_file_id")
        if prompt_file_id:
            prompt_text = params.get("prompt_text")
            if not prompt_text or not prompt_text.strip():
                raise ValueError("提供 prompt_file_id 时必须同时提供非空的 prompt_text（音频对应的文本内容）")
            payload["clone_prompt"] = {
                "prompt_audio": int(prompt_file_id),
                "prompt_text": prompt_text,
            }

        # 可选：试听参数
        text = params.get("text")
        if text:
            payload["text"] = text
            payload["model"] = params.get("model", "speech-2.8-hd")
            if params.get("language_boost"):
                payload["language_boost"] = params["language_boost"]

        # 可选：ASR 验证
        if params.get("text_validation"):
            payload["text_validation"] = params["text_validation"]
            payload["accuracy"] = params.get("accuracy", 0.7)

        # 可选：音频处理
        if params.get("need_noise_reduction"):
            payload["need_noise_reduction"] = True
        if params.get("need_volume_normalization"):
            payload["need_volume_normalization"] = True
        if params.get("aigc_watermark"):
            payload["aigc_watermark"] = True

        url = "https://api.minimax.cn/v1/voice_clone"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                result = resp.json()

            base_resp = result.get("base_resp", {})
            if base_resp.get("status_code") != 0:
                raise RuntimeError(f"克隆失败: {base_resp.get('status_msg')}")

            response = {"voice_id": voice_id}
            if result.get("demo_audio"):
                response["demo_audio"] = result["demo_audio"]
            if result.get("extra_info"):
                response["extra_info"] = result["extra_info"]

            logger.info(f"音色克隆成功: voice_id={voice_id}")
            return response

        except httpx.TimeoutException:
            raise RuntimeError("音色克隆请求超时")
        except Exception as e:
            raise RuntimeError(f"音色克隆异常: {e}")

    async def _create_voice_by_design(self, params: dict) -> dict:
        """通过文本描述设计音色。"""
        api_key = self.entry.get("api_key")
        if not api_key:
            raise ValueError("API Key 未配置")

        prompt = params.get("prompt")
        preview_text = params.get("preview_text")
        if not prompt:
            raise ValueError("prompt 为必填参数")
        if not preview_text:
            raise ValueError("preview_text 为必填参数")
        if len(preview_text) > 500:
            raise ValueError("preview_text 不能超过 500 字符")

        payload = {"prompt": prompt, "preview_text": preview_text}
        if params.get("voice_id"):
            payload["voice_id"] = params["voice_id"]
        if params.get("aigc_watermark"):
            payload["aigc_watermark"] = True

        url = "https://api.minimax.cn/v1/voice_design"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                result = resp.json()

            base_resp = result.get("base_resp", {})
            if base_resp.get("status_code") != 0:
                raise RuntimeError(f"音色设计失败: {base_resp.get('status_msg')}")

            voice_id = result.get("voice_id")
            if not voice_id:
                raise RuntimeError(f"未返回 voice_id: {result}")

            response = {"voice_id": voice_id}
            if result.get("trial_audio"):
                response["trial_audio"] = result["trial_audio"]

            logger.info(f"音色设计成功: voice_id={voice_id}")
            return response

        except httpx.TimeoutException:
            raise RuntimeError("音色设计请求超时")
        except Exception as e:
            raise RuntimeError(f"音色设计异常: {e}")

    # ============================================================
    # 3. 音色查询与删除
    # ============================================================

    async def list_voice(self, **kwargs) -> dict:
        """查询音色列表。

        Args:
            voice_type: 音色类型，"system"、"voice_cloning"、"voice_generation" 或 "all"，默认 "all"

        Returns:
            dict: 包含 system_voice、voice_cloning、voice_generation 三个列表
        """
        api_key = self.entry.get("api_key")
        if not api_key:
            raise ValueError("API Key 未配置")

        voice_type = kwargs.get("voice_type", "all")
        if voice_type not in ["system", "voice_cloning", "voice_generation", "all"]:
            raise ValueError(f"不支持的 voice_type: {voice_type}")

        payload = {"voice_type": voice_type}
        url = "https://api.minimax.cn/v1/get_voice"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                result = resp.json()

            base_resp = result.get("base_resp", {})
            if base_resp.get("status_code") != 0:
                raise RuntimeError(f"查询音色失败: {base_resp.get('status_msg')}")

            # 格式化返回结果
            response = {"items": [], "total": 0}

            # 系统音色
            for v in result.get("system_voice", []):
                response["items"].append({
                    "voice_id": v.get("voice_id"),
                    "voice_name": v.get("voice_name"),
                    "description": v.get("description", []),
                    "created_time": v.get("created_time"),
                    "type": "system"
                })

            # 克隆音色
            for v in result.get("voice_cloning", []):
                response["items"].append({
                    "voice_id": v.get("voice_id"),
                    "description": v.get("description", []),
                    "created_time": v.get("created_time"),
                    "type": "voice_cloning"
                })

            # 文生音色
            for v in result.get("voice_generation", []):
                response["items"].append({
                    "voice_id": v.get("voice_id"),
                    "description": v.get("description", []),
                    "created_time": v.get("created_time"),
                    "type": "voice_generation"
                })

            response["total"] = len(response["items"])
            return response

        except httpx.TimeoutException:
            raise RuntimeError("查询音色请求超时")
        except Exception as e:
            raise RuntimeError(f"查询音色异常: {e}")

    async def delete_voice(self, **kwargs) -> bool:
        """删除音色。

        Args:
            voice_id: 要删除的音色 ID（必填）
            voice_type: 音色类型，"voice_cloning" 或 "voice_generation"（必填）

        Returns:
            bool: 删除成功返回 True
        """
        api_key = self.entry.get("api_key")
        if not api_key:
            raise ValueError("API Key 未配置")

        voice_id = kwargs.get("voice_id")
        voice_type = kwargs.get("voice_type")

        if not voice_id:
            raise ValueError("voice_id 为必填参数")
        if not voice_type:
            raise ValueError("voice_type 为必填参数（voice_cloning 或 voice_generation）")
        if voice_type not in ["voice_cloning", "voice_generation"]:
            raise ValueError(f"不支持的 voice_type: {voice_type}，仅支持 voice_cloning 或 voice_generation")

        payload = {
            "voice_id": voice_id,
            "voice_type": voice_type,
        }
        url = "https://api.minimax.cn/v1/delete_voice"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                result = resp.json()

            base_resp = result.get("base_resp", {})
            if base_resp.get("status_code") != 0:
                logger.error(f"删除音色失败: {base_resp.get('status_msg')}")
                return False

            logger.info(f"音色删除成功: voice_id={voice_id}")
            return True

        except httpx.TimeoutException:
            raise RuntimeError("删除音色请求超时")
        except Exception as e:
            raise RuntimeError(f"删除音色异常: {e}")
        