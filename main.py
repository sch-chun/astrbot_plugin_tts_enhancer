from pathlib import Path
import base64
import time

from astrbot.api.star import Star
from astrbot.api.event.filter import on_llm_request, on_decorating_result
from astrbot.api.message_components import Plain
from astrbot.core import logger
from astrbot.api.web import request, json_response, error_response
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .src.config import TTSEnhancerConfig
from .src.tts_parser import split_by_tts_tags, TTS_START_TAG, TTS_END_TAG
from .src.file_server import TempFileServer, add_server, get_server, remove_server
from .src.tts_service import TTSService
from .src.tools import SendVoiceTool
from .providers import ProviderFactory

from typing import Optional
from fastapi.responses import JSONResponse
from astrbot.core.provider.entities import ProviderRequest
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context


class TTSEnhancerPlugin(Star):
    """TTS Enhancer —— 多供应商智能语音合成插件

    架构：主模型输出 <tts> 标签 → SubAgent 增强语音参数 → Provider Adapter 调用 API。

    Args:
        context (Context): 插件上下文对象，提供与 AstrBot 核心交互的能力。
        config (Optional[dict]): 插件配置字典，默认为 None。

    Attributes:
        config (TTSEnhancerConfig): TTS 增强配置对象。
        providers (list): TTS 供应商配置列表。
        plugin_data_path (Path): 插件数据存储路径。
        tts_service (TTSService): TTS 核心服务实例。
    """
    def __init__(self, context: Context, config: Optional[dict] = None) -> None:
        """初始化 TTS Enhancer 插件。

        依次完成数据目录初始化、核心服务初始化、LLM Tool 注册和 Web API 路由注册。

        Args:
            context (Context): 插件上下文对象。
            config (Optional[dict]): 插件配置字典。
        """
        super().__init__(context, config)
        self.config = TTSEnhancerConfig(config)
        self.providers = self.config.get_providers()

        # 初始化数据目录
        self.plugin_data_path = Path(get_astrbot_data_path()) / "plugin_data" / self.name
        (self.plugin_data_path / "uploads").mkdir(parents=True, exist_ok=True)
        (self.plugin_data_path / "audio").mkdir(parents=True, exist_ok=True)

        # 初始化核心服务
        self.tts_service = TTSService(
            context=self.context,
            providers=self.providers,
            config=self.config,
            audio_data_dir=self.plugin_data_path / "audio"
        )

        # 注册 Tool
        send_voice_tool = SendVoiceTool(tts_service=self.tts_service)
        self.context.add_llm_tools(send_voice_tool)

        # 注册路由
        self._register_routes()

    async def _process_tts_text(
        self,
        text: str,
        event: AstrMessageEvent,
        context_messages: list[dict],
    ) -> list:
        """处理包含 TTS 标签的文本，将其转换为消息组件列表。

        Args:
            text (str): 包含 TTS 标签的原始文本。
            event (AstrMessageEvent): 消息事件对象。
            context_messages (list[dict]): 上下文消息列表。

        Returns:
            list: 包含 Plain 文本组件和 Record 音频组件的列表。若 TTS 合成失败，则降级为 Plain 文本组件。
        """
        segments = split_by_tts_tags(text)
        components = []

        for seg in segments:
            if seg["type"] == "text":
                components.append(Plain(seg["content"]))
            elif seg["type"] == "tts":
                audio_component = await self.tts_service.synthesize(seg["content"], event, context_messages)
                if audio_component:
                    components.append(audio_component)
                    if self.config.get("dual_output", False):
                        components.append(Plain(seg["content"]))
                else:
                    components.append(Plain(seg["content"]))
        return components

    # ———————— 事件钩子 ————————

    @on_llm_request()
    async def on_llm_req(self, event: AstrMessageEvent, request: ProviderRequest) -> None:
        """处理 LLM 请求事件，将配置中的 TTS 提示词追加到系统提示词中。

        Args:
            event (AstrMessageEvent): 消息事件对象。
            request (ProviderRequest): 提供者请求对象，包含系统提示词等信息。

        Returns:
            None: 若未配置 TTS 提供商或提示词则直接返回，否则将提示词追加至系统提示词后无显式返回。
        """
        if not self.providers:
            logger.warning("未配置 TTS 提供商，跳过 TTS 提示词追加")
            return
        tts_prompt = self.config.get("tts_prompt", "")
        if not tts_prompt:
            logger.warning("未配置 TTS 提示词，模型可能不会进行 TTS 生成")
            return
        request.system_prompt += f"\n{tts_prompt}"

    @on_decorating_result(priority=13)
    async def on_decorate(self, event: AstrMessageEvent) -> None:
        """处理消息结果装饰事件，提取并处理文本中的 TTS 标签。

        检查消息链中的纯文本组件是否包含 TTS 标签，若存在则进行
        TTS 处理并替换原文本组件。

        Args:
            event (AstrMessageEvent): 消息事件对象，包含待处理的消息结果链。

        Returns:
            None
        """
        result = event.get_result()
        if not result or not result.chain:
            return

        # 检查消息链中是否存在 TTS 标签
        has_tts_tag = any(
            isinstance(comp, Plain)
            and (TTS_START_TAG in comp.text or TTS_END_TAG in comp.text)
            for comp in result.chain
        )
        if not has_tts_tag:
            return

        context_messages = await self.tts_service.get_context_messages(event)

        # 遍历消息链，处理包含 TTS 标签的文本组件
        new_chain = []
        modified = False
        for comp in result.chain:
            if isinstance(comp, Plain) and (
                TTS_START_TAG in comp.text or TTS_END_TAG in comp.text
            ):
                # 替换为 TTS 处理后的组件列表
                components = await self._process_tts_text(comp.text, event, context_messages)
                new_chain.extend(components)
                modified = True
            else:
                new_chain.append(comp)

        # 若有修改，则更新消息结果链
        if modified:
            result.chain = new_chain

    # ————————————————————————

    def _register_routes(self) -> None:
        """注册音色管理相关的 Web API 路由。

        包含以下路由：
            - GET  /providers: 获取分组后的供应商列表。
            - POST /voice/create: 创建音色。
            - POST /voice/list: 查询音色列表。
            - POST /voice/delete: 删除音色。
            - POST /upload: 上传音频文件。
            - POST /start_file_server: 启动临时文件服务器。
            - POST /stop_file_server: 停止临时文件服务器。
            - POST /voice/preview: 预览音色。
        """
        async def get_providers() -> JSONResponse:
            """获取分组后的供应商列表。

            将供应商按 template_key 分组，并对 api_key 进行脱敏处理。

            Returns:
                JSONResponse: 包含分组后供应商列表的 JSON 响应。
            """
            providers_raw = self.config.get_providers()
            groups = {}
            for idx, entry in enumerate(providers_raw):
                template_key = entry.get("__template_key", "unknown")
                if template_key not in groups:
                    groups[template_key] = []

                # 深拷贝原始配置，脱敏 api_key
                item = dict(entry)
                api_key = item.get("api_key", "")
                if len(api_key) > 5:
                    item["api_key"] = "*****" + api_key[-5:]
                else:
                    item["api_key"] = "*****"
                item["id"] = idx
                groups[template_key].append(item)
            result = [{"template_key": k, "entries": v} for k, v in groups.items()]
            return json_response({"code": 0, "data": result})

        self.context.register_web_api(
            f"/{self.name}/providers",
            get_providers,
            ["GET"],
            "获取分组后的供应商列表"
        )

        async def create_voice() -> JSONResponse:
            """创建音色。

            Args (JSON Body):
                entry_id (int): 供应商配置的索引 ID。
                **kwargs: 供应商特定的创建参数。

            Returns:
                JSONResponse: 包含创建结果的 JSON 响应。
            """
            payload = await request.json(default={})
            if not payload:
                return error_response("payload required", status_code=400)
            entry_id = payload.get("entry_id")
            if entry_id is None:
                return error_response("entry_id required", status_code=400)
            params = {k: v for k, v in payload.items() if k != "entry_id"}
            providers_raw = self.config.get_providers()
            if entry_id < 0 or entry_id >= len(providers_raw):
                return error_response("entry not found", status_code=404)
            entry = providers_raw[entry_id]
            adapter = ProviderFactory.get_adapter(entry)
            if not adapter:
                return error_response("无法创建适配器，请检查配置", status_code=500)
            try:
                result = await adapter.create_voice(params)
                return json_response({"code": 0, "data": result})
            except NotImplementedError:
                return error_response("该供应商不支持音色创建", status_code=501)
            except Exception as e:
                logger.error(f"创建音色失败: {e}")
                return error_response(str(e), status_code=500)

        self.context.register_web_api(
            f"/{self.name}/voice/create",
            create_voice,
            ["POST"],
            "创建音色（请求体包含 entry_id 及供应商特定参数）"
        )

        async def list_voices() -> JSONResponse:
            """列出音色。

            Args (JSON Body):
                entry_id (int): 供应商配置的索引 ID。
                **kwargs: 供应商特定的查询参数。

            Returns:
                JSONResponse: 包含音色列表的 JSON 响应。
            """
            payload = await request.json(default={})
            if not payload:
                return error_response("payload required", status_code=400)
            entry_id = payload.get("entry_id")
            if entry_id is None:
                return error_response("entry_id required", status_code=400)
            params = {k: v for k, v in payload.items() if k != "entry_id"}
            providers_raw = self.config.get_providers()
            if entry_id < 0 or entry_id >= len(providers_raw):
                return error_response("entry not found", status_code=404)
            entry = providers_raw[entry_id]
            adapter = ProviderFactory.get_adapter(entry)
            if not adapter:
                return error_response("无法创建适配器，请检查配置", status_code=500)
            try:
                result = await adapter.list_voice(**params)
                return json_response({"code": 0, "data": result})
            except NotImplementedError:
                return error_response("该供应商不支持音色列表查询", status_code=501)
            except Exception as e:
                logger.error(f"查询音色列表失败: {e}")
                return error_response(str(e), status_code=500)

        self.context.register_web_api(
            f"/{self.name}/voice/list",
            list_voices,
            ["POST"],
            "查询音色列表（请求体包含 entry_id 及供应商特定参数）"
        )

        async def delete_voice() -> JSONResponse:
            """删除音色。

            Args (JSON Body):
                entry_id (int): 供应商配置的索引 ID。
                **kwargs: 供应商特定的标识参数。

            Returns:
                JSONResponse: 包含删除成功状态的 JSON 响应。
            """
            payload = await request.json(default={})
            if not payload:
                return error_response("payload required", status_code=400)
            entry_id = payload.get("entry_id")
            if entry_id is None:
                return error_response("entry_id required", status_code=400)
            params = {k: v for k, v in payload.items() if k != "entry_id"}
            providers_raw = self.config.get_providers()
            if entry_id < 0 or entry_id >= len(providers_raw):
                return error_response("entry not found", status_code=404)
            entry = providers_raw[entry_id]
            adapter = ProviderFactory.get_adapter(entry)
            if not adapter:
                return error_response("无法创建适配器，请检查配置", status_code=500)
            try:
                success = await adapter.delete_voice(**params)
                return json_response({"code": 0, "data": {"success": success}})
            except NotImplementedError:
                return error_response("该供应商不支持音色删除", status_code=501)
            except Exception as e:
                logger.error(f"删除音色失败: {e}")
                return error_response(str(e), status_code=500)

        self.context.register_web_api(
            f"/{self.name}/voice/delete",
            delete_voice,
            ["POST"],
            "删除音色（请求体包含 entry_id 及供应商特定标识参数）"
        )

        async def upload_file() -> JSONResponse:
            """上传音频文件。

            支持的格式：wav, mp3, m4a。文件将重命名为包含时间戳的唯一文件名并保存。
            支持可选的时长校验与自动裁剪。

            Args (Form Data):
                file: 上传的音频文件对象。
                min_sec: 可选，音频最小时长（秒）。
                max_sec: 可选，音频最大时长（秒）。
                auto_trim: 可选，是否在超长时自动裁剪至 max_sec - 0.5s，默认为 False。

            Returns:
                JSONResponse: 包含 file_id 和 file_path 的 JSON 响应。
            """
            try:

                # 使用 request.post() 同时获取文件和表单字段
                data = await request.post()
                file_field = data.get('file')
                if not file_field:
                    return error_response("缺少文件", status_code=400)

                # 获取可选的校验参数
                min_sec_str = data.get('min_sec')
                max_sec_str = data.get('max_sec')
                auto_trim_str = data.get('auto_trim', 'false')

                min_sec = float(min_sec_str) if min_sec_str else None
                max_sec = float(max_sec_str) if max_sec_str else None
                auto_trim = auto_trim_str.lower() == 'true'

                # 检查扩展名（仅当需要校验时）
                original_filename = file_field.filename or "file.bin"
                ext = Path(original_filename).suffix.lower()
                audio_extensions = {'.wav', '.mp3', '.m4a', '.flac', '.ogg', '.aac'}
                if (min_sec is not None or max_sec is not None) and ext not in audio_extensions:
                    return error_response("校验仅支持音频文件 (wav, mp3, m4a, flac, ogg, aac)", status_code=400)

                # 保存文件（先保存再校验，因为需要读取文件内容）
                upload_dir = self.plugin_data_path / "uploads"
                upload_dir.mkdir(parents=True, exist_ok=True)
                timestamp = int(time.time() * 1000)
                unique_name = f"upload_{timestamp}{ext}"
                file_path = upload_dir / unique_name
                await file_field.save(file_path)

                # ---------- 音频校验与裁剪 ----------
                if min_sec is not None or max_sec is not None:
                    from .src.audio_utils import get_audio_duration, trim_audio_to_max

                    duration = get_audio_duration(str(file_path))
                    if duration is None:
                        file_path.unlink(missing_ok=True)
                        return error_response("无法读取音频时长，请确认文件为有效的音频格式", status_code=400)

                    # 检查过短
                    if min_sec is not None and duration < min_sec - 0.01:
                        file_path.unlink(missing_ok=True)
                        return error_response(f"音频时长 {duration:.1f}s 短于要求的最小值 {min_sec}s", status_code=400)

                    # 检查过长
                    if max_sec is not None and duration > max_sec + 0.01:
                        if not auto_trim:
                            file_path.unlink(missing_ok=True)
                            return error_response(f"音频时长 {duration:.1f}s 超过允许的最大值 {max_sec}s", status_code=400)
                        else:

                            # 自动裁剪
                            try:

                                # 裁剪到 max_sec - 0.5 秒，保留余量
                                trimmed_path = trim_audio_to_max(
                                    str(file_path),
                                    max_sec=max_sec,
                                    margin=0.5,
                                    output_dir=str(upload_dir)
                                )

                                # 用裁剪后的文件替换原文件（保持文件名不变）
                                trimmed_path_obj = Path(trimmed_path)
                                if trimmed_path_obj != file_path:
                                    file_path.unlink()  # 删除原文件
                                    trimmed_path_obj.rename(file_path)  # 重命名裁剪文件为原文件名
                                    logger.info(f"音频已自动裁剪并覆盖原文件: {file_path}")
                            except Exception as e:
                                file_path.unlink(missing_ok=True)
                                return error_response(f"音频裁剪失败: {str(e)}", status_code=500)

                # 返回结果
                return json_response({
                    "code": 0,
                    "data": {
                        "file_id": unique_name,
                        "file_path": str(file_path)
                    }
                })

            except Exception as e:
                logger.error(f"文件上传失败: {e}")
                return error_response(str(e), status_code=500)

        self.context.register_web_api(
            f"/{self.name}/upload",
            upload_file,
            ["POST"],
            "上传音频文件，返回 file_id"
        )

        async def start_file_server() -> JSONResponse:
            """启动临时文件服务器，只绑定内部端口，不构造 URL。

            Args (JSON Body):
                file_id (str): 上传文件的唯一标识符。
                internal_port (int): 内部绑定的端口号，范围为 1024-65535。

            Returns:
                JSONResponse: 包含启动成功状态的 JSON 响应。
            """
            try:
                payload = await request.json()
                if not payload:
                    return error_response("payload required", status_code=400)
                file_id = payload.get('file_id')
                internal_port = payload.get('internal_port')
                if not all([file_id, internal_port]):
                    return error_response("缺少 file_id 或 internal_port", status_code=400)

                try:
                    internal_port = int(internal_port)
                    if not (1024 <= internal_port <= 65535):
                        raise ValueError
                except ValueError:
                    return error_response("内部端口必须为 1024-65535 的整数", status_code=400)

                file_path = self.plugin_data_path / "uploads" / file_id
                if not file_path.exists():
                    return error_response("文件不存在", status_code=404)

                if get_server(file_id):
                    return error_response("该文件已有服务器在运行", status_code=400)

                server = TempFileServer(file_path, internal_port)
                await server.start()
                add_server(file_id, server)
                return json_response({"code": 0, "data": {"success": True}})
            except Exception as e:
                logger.error(f"启动文件服务器失败: {e}")
                return error_response(str(e), status_code=500)

        self.context.register_web_api(
            f"/{self.name}/start_file_server",
            start_file_server,
            ["POST"],
            "启动临时文件服务器（由前端拼接公网 URL）"
        )

        async def stop_file_server() -> JSONResponse:
            """停止文件服务器，并删除临时文件。

            Args (JSON Body):
                file_id (str): 上传文件的唯一标识符。

            Returns:
                JSONResponse: 包含停止成功状态的 JSON 响应。
            """
            try:
                payload = await request.json()
                if not payload:
                    return error_response("payload required", status_code=400)
                file_id = payload.get('file_id')
                if not file_id:
                    return error_response("缺少 file_id", status_code=400)

                server = get_server(file_id)
                if server:
                    await server.stop()
                    remove_server(file_id)

                # 删除临时文件
                file_path = self.plugin_data_path / "uploads" / file_id
                if file_path.exists():
                    file_path.unlink()

                return json_response({"code": 0, "data": {"success": True}})
            except Exception as e:
                logger.error(f"停止文件服务器失败: {e}")
                return error_response(str(e), status_code=500)

        self.context.register_web_api(
            f"/{self.name}/stop_file_server",
            stop_file_server,
            ["POST"],
            "停止文件服务器并删除文件"
        )

        async def preview_voice() -> JSONResponse:
            """预览音色：合成语音并返回 Base64 编码的音频。

            Args (JSON Body):
                entry_id (int): 供应商配置的索引 ID。
                voice_id (str): 待预览的音色 ID。
                text (str, optional): 预览合成的文本，默认为 "欢迎使用语音合成预览功能。"。

            Returns:
                JSONResponse: 包含 Base64 编码音频数据 (audio_base64) 和音频格式 (format) 的 JSON 响应。
            """
            try:
                payload = await request.json()
                if not payload:
                    return error_response("payload required", status_code=400)
                entry_id = payload.get("entry_id")
                voice_id = payload.get("voice_id")
                text = payload.get("text", "欢迎使用语音合成预览功能。")
                if entry_id is None or not voice_id:
                    return error_response("entry_id 和 voice_id 是必需的", status_code=400)

                providers_raw = self.config.get_providers()
                if entry_id < 0 or entry_id >= len(providers_raw):
                    return error_response("entry not found", status_code=404)
                entry = providers_raw[entry_id]

                adapter = ProviderFactory.get_adapter(entry)
                if not adapter:
                    return error_response("无法创建适配器，请检查配置", status_code=500)

                entry_with_data_dir = dict(entry)
                entry_with_data_dir["_data_dir"] = str(self.plugin_data_path / "audio")

                audio_path = await adapter.call_api(
                    text=text,
                    raw_params={"voice": voice_id, "_suppress_model_warning": True},
                    config=entry_with_data_dir
                )
                if not audio_path:
                    return error_response("合成失败", status_code=500)

                # 读取音频文件并 Base64 编码
                with open(audio_path, 'rb') as f:
                    audio_bytes = f.read()
                audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
                ext = Path(audio_path).suffix.lstrip('.')

                # 删除临时文件
                Path(audio_path).unlink(missing_ok=True)

                return json_response({
                    "code": 0,
                    "data": {
                        "audio_base64": audio_base64,
                        "format": ext
                    }
                })
            except NotImplementedError:
                return error_response("该适配器不支持预览", status_code=501)
            except Exception as e:
                logger.error(f"预览音色失败: {e}")
                return error_response(str(e), status_code=500)

        self.context.register_web_api(
            f"/{self.name}/voice/preview",
            preview_voice,
            ["POST"],
            "预览音色，返回音频文件"
        )

        # ========== 通用 KV 存储（供前端/供应商存取元数据，如 prompt_text） ==========
        async def kv_set() -> JSONResponse:
            """存储键值对（字符串）。"""
            try:
                payload = await request.json()
                if not payload:
                    return error_response("payload required", status_code=400)
                key = payload.get("key")
                value = payload.get("value")
                if not key or value is None:
                    return error_response("key 和 value 都是必需的", status_code=400)
                
                # 允许存储任何字符串，由前端控制键名规范，如 "minimax_prompt_{file_id}"
                await self.put_kv_data(key, value)
                return json_response({"code": 0, "data": {"success": True}})
            except Exception as e:
                logger.error(f"KV 存储失败: {e}")
                return error_response(str(e), status_code=500)

        async def kv_get() -> JSONResponse:
            """获取键值对。"""
            try:
                payload = await request.json()
                if not payload:
                    return error_response("payload required", status_code=400)
                key = payload.get("key")
                if not key:
                    return error_response("key 是必需的", status_code=400)
                value = await self.get_kv_data(key, None)
                return json_response({"code": 0, "data": {"value": value}})
            except Exception as e:
                logger.error(f"KV 获取失败: {e}")
                return error_response(str(e), status_code=500)

        async def kv_delete() -> JSONResponse:
            """删除键值对。"""
            try:
                payload = await request.json()
                if not payload:
                    return error_response("payload required", status_code=400)
                key = payload.get("key")
                if not key:
                    return error_response("key 是必需的", status_code=400)
                await self.delete_kv_data(key)
                return json_response({"code": 0, "data": {"success": True}})
            except Exception as e:
                logger.error(f"KV 删除失败: {e}")
                return error_response(str(e), status_code=500)

        # 注册
        self.context.register_web_api(
            f"/{self.name}/kv/set",
            kv_set,
            ["POST"],
            "通用 KV 存储"
        )
        self.context.register_web_api(
            f"/{self.name}/kv/get",
            kv_get,
            ["POST"],
            "通用 KV 获取"
        )
        self.context.register_web_api(
            f"/{self.name}/kv/delete",
            kv_delete,
            ["POST"],
            "通用 KV 删除"
        )

        # ---------- 供应商文件管理（上传、列表、获取、删除） ----------
        async def file_upload() -> JSONResponse:
            """上传文件到指定的供应商（适配器需实现 upload_file 方法）。"""
            try:
                data = await request.post()
                file_field = data.get('file')
                if not file_field:
                    return error_response("缺少文件", status_code=400)

                entry_id = data.get('entry_id')
                if entry_id is None:
                    return error_response("entry_id 是必需的", status_code=400)

                kwargs = {k: v for k, v in data.items() if k not in ['file', 'entry_id']}

                providers_raw = self.config.get_providers()
                try:
                    entry_id = int(entry_id)
                except ValueError:
                    return error_response("entry_id 必须为整数", status_code=400)
                if entry_id < 0 or entry_id >= len(providers_raw):
                    return error_response("entry not found", status_code=404)
                entry = providers_raw[entry_id]
                adapter = ProviderFactory.get_adapter(entry)
                if not adapter or not hasattr(adapter, 'upload_file'):
                    return error_response("该适配器不支持文件上传", status_code=501)

                # 保存临时文件
                upload_dir = self.plugin_data_path / "temp_uploads"
                upload_dir.mkdir(parents=True, exist_ok=True)
                ext = Path(file_field.filename or "file.bin").suffix
                temp_path = upload_dir / f"file_{int(time.time()*1000)}{ext}"
                await file_field.save(temp_path)

                try:
                    # 调用适配器的 upload_file
                    result = await adapter.upload_file(  # type: ignore
                        file_path=str(temp_path),
                        **kwargs
                    )
                    return json_response({
                        "code": 0,
                        "data": result  # 包含 file_id 等
                    })
                finally:
                    if temp_path.exists():
                        temp_path.unlink(missing_ok=True)

            except ValueError as e:
                return error_response(str(e), status_code=400)
            except Exception as e:
                logger.error(f"文件上传失败: {e}")
                return error_response(str(e), status_code=500)

        async def file_list() -> JSONResponse:
            """列出供应商的文件（适配器需实现 list_files）。"""
            try:
                payload = await request.json()
                if not payload:
                    return error_response("payload required", status_code=400)
                
                entry_id = payload.get("entry_id")
                if entry_id is None:
                    return error_response("entry_id 是必需的", status_code=400)

                kwargs = {k: v for k, v in payload.items() if k != "entry_id"}

                providers_raw = self.config.get_providers()
                if entry_id < 0 or entry_id >= len(providers_raw):
                    return error_response("entry not found", status_code=404)
                entry = providers_raw[entry_id]
                adapter = ProviderFactory.get_adapter(entry)
                if not adapter or not hasattr(adapter, 'list_files'):
                    return error_response("该适配器不支持文件列表", status_code=501)

                result = await adapter.list_files(**kwargs)  # type: ignore
                return json_response({"code": 0, "data": result})
            except Exception as e:
                logger.error(f"文件列表失败: {e}")
                return error_response(str(e), status_code=500)

        async def file_get() -> JSONResponse:
            """获取文件内容（适配器需实现 get_file_content）。"""
            try:
                payload = await request.json()
                if not payload:
                    return error_response("payload required", status_code=400)
                entry_id = payload.get("entry_id")
                file_id = payload.get("file_id")
                if entry_id is None or file_id is None:
                    return error_response("entry_id 和 file_id 都是必需的", status_code=400)

                providers_raw = self.config.get_providers()
                if entry_id < 0 or entry_id >= len(providers_raw):
                    return error_response("entry not found", status_code=404)
                entry = providers_raw[entry_id]
                adapter = ProviderFactory.get_adapter(entry)
                if not adapter or not hasattr(adapter, 'get_file_content'):
                    return error_response("该适配器不支持文件获取", status_code=501)

                content = await adapter.get_file_content(int(file_id))  # type: ignore
                audio_base64 = base64.b64encode(content).decode('utf-8')
                return json_response({
                    "code": 0,
                    "data": {
                        "audio_base64": audio_base64
                    }
                })
            except Exception as e:
                logger.error(f"获取文件失败: {e}")
                return error_response(str(e), status_code=500)

        async def file_delete() -> JSONResponse:
            """删除供应商的文件（适配器需实现 delete_file）。"""
            try:
                payload = await request.json()
                if not payload:
                    return error_response("payload required", status_code=400)
                entry_id = payload.get("entry_id")
                file_id = payload.get("file_id")
                kwargs = {k: v for k, v in payload.items() if k not in ["entry_id", "file_id"]}
                if entry_id is None or file_id is None:
                    return error_response("entry_id 和 file_id 都是必需的", status_code=400)

                providers_raw = self.config.get_providers()
                if entry_id < 0 or entry_id >= len(providers_raw):
                    return error_response("entry not found", status_code=404)
                entry = providers_raw[entry_id]
                adapter = ProviderFactory.get_adapter(entry)
                if not adapter or not hasattr(adapter, 'delete_file'):
                    return error_response("该适配器不支持文件删除", status_code=501)
                
                success = await adapter.delete_file(int(file_id), **kwargs)  # type: ignore
                return json_response({"code": 0, "data": {"success": success}})
            except Exception as e:
                logger.error(f"删除文件失败: {e}")
                return error_response(str(e), status_code=500)

        # 注册
        self.context.register_web_api(f"/{self.name}/file/upload", file_upload, ["POST"], "上传文件到供应商")
        self.context.register_web_api(f"/{self.name}/file/list", file_list, ["POST"], "列出供应商的文件")
        self.context.register_web_api(f"/{self.name}/file/get", file_get, ["POST"], "获取文件内容（Base64）")
        self.context.register_web_api(f"/{self.name}/file/delete", file_delete, ["POST"], "删除供应商的文件")
