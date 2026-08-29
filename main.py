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

            Args (Form Data):
                file: 上传的音频文件对象。

            Returns:
                JSONResponse: 包含 file_id 和 file_path 的 JSON 响应。
            """
            try:
                data = await request.files()
                file_field = data.get('file')
                if not file_field:
                    return error_response("缺少文件", status_code=400)

                # 检查扩展名
                filename = file_field.filename or "file.bin"
                ext = Path(filename).suffix.lower()
                if ext not in ['.wav', '.mp3', '.m4a']:
                    return error_response("仅支持 wav, mp3, m4a 格式", status_code=400)

                upload_dir = self.plugin_data_path / "uploads"
                upload_dir.mkdir(parents=True, exist_ok=True)

                # 生成唯一文件名（时间戳）
                original_filename = file_field.filename or "file.bin"
                ext = Path(original_filename).suffix.lower()
                timestamp = int(time.time() * 1000)
                unique_name = f"upload_{timestamp}{ext}"
                file_path = upload_dir / unique_name

                await file_field.save(file_path)

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
