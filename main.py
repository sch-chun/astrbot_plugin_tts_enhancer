import json
from pathlib import Path
import base64
import time

from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api.event.filter import on_llm_request, on_decorating_result
from astrbot.api.message_components import Plain, Record
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.agent.tool import ToolSet
from astrbot.core import logger
from astrbot.api.web import request, json_response, error_response, file_response
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .src.config import TTSEnhancerConfig
from .src.sub_agent import TTSSubAgent
from .src.tts_parser import split_by_tts_tags, TTS_START_TAG, TTS_END_TAG
from .src.file_server import TempFileServer, add_server, get_server, remove_server
from .providers import ProviderFactory

from typing import Optional


class TTSEnhancerPlugin(Star):
    """
    TTS Enhancer —— 多供应商智能语音合成插件

    架构：主模型输出 <tts> 标签 → SubAgent 增强语音参数 → Provider Adapter 调用 API。
    """
    def __init__(self, context: Context, config: Optional[dict] = None):
        super().__init__(context, config)
        self.config = TTSEnhancerConfig(config)
        self.providers = self.config.get_providers()
        self.sub_agent = TTSSubAgent(context, config)

        self._register_routes()

        self.plugin_data_path = Path(get_astrbot_data_path()) / "plugin_data" / self.name
        (self.plugin_data_path / "uploads").mkdir(parents=True, exist_ok=True)
        (self.plugin_data_path / "audio").mkdir(parents=True, exist_ok=True)

    async def _process_tts_text(
        self,
        text: str,
        event: AstrMessageEvent,
        context_messages: list[dict],
    ) -> list:
        """
        处理包含 TTS 标签的文本，将其转换为消息组件列表。

        Args:
            text (str): 包含 TTS 标签的原始文本。
            event (AstrMessageEvent): 消息事件对象。
            context_messages (list[dict]): 上下文消息列表。

        Returns:
            list: 包含 Plain 文本组件和 Record 音频组件的列表。
        """
        segments = split_by_tts_tags(text)
        components = []

        for seg in segments:
            if seg["type"] == "text":
                components.append(Plain(seg["content"]))
            elif seg["type"] == "tts":
                audio_component = await self._synthesize(seg["content"], event, context_messages)
                if audio_component:
                    components.append(audio_component)
                    if self.config.get("dual_output", False):
                        components.append(Plain(seg["content"]))
                else:
                    components.append(Plain(seg["content"]))
        return components

    # ———————— 事件钩子 ————————

    @on_llm_request()
    async def on_llm_req(self, event: AstrMessageEvent, request: ProviderRequest):
        """处理 LLM 请求事件，将配置中的 TTS 提示词追加到系统提示词中。

        Args:
            event (AstrMessageEvent): 消息事件对象。
            request (ProviderRequest): 提供者请求对象，包含系统提示词等信息。

        Returns:
            None: 如果未配置 TTS 提示词则直接返回，否则无显式返回值。
        """
        tts_prompt = self.config.get("tts_prompt", "")
        if not tts_prompt:
            logger.warning("未配置 TTS 提示词，模型可能不会进行 TTS 生成")
            return
        request.system_prompt += f"\n{tts_prompt}"

    @on_decorating_result(priority=13)
    async def on_decorate(self, event: AstrMessageEvent):
        """处理消息结果装饰事件，提取并处理文本中的 TTS 标签。

        检查消息链中的纯文本组件是否包含 TTS 标签，若存在则进行
        TTS 处理并替换原文本组件。

        Args:
            event: 消息事件对象，包含待处理的消息结果链。

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

        context_messages = await self._get_context_messages(event)

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

    async def _get_context_messages(self, event: AstrMessageEvent) -> list[dict]:
        """获取当前会话的上下文消息列表。

        根据配置中的 context_window 提取最近的历史消息。

        Args:
            event (AstrMessageEvent): 当前消息事件，用于获取会话 ID。

        Returns:
            list[dict]: 包含角色和内容的上下文消息列表。
                        如果获取失败或无历史记录，则返回空列表。
        """
        context_window = self.config.get("context_window", 10)
        if not isinstance(context_window, int) or context_window < 0:
            context_window = 10
        messages = []
        try:
            session_id = event.unified_msg_origin
            conv_mgr = self.context.conversation_manager
            if conv_mgr:
                conv_id = await conv_mgr.get_curr_conversation_id(session_id)
                if conv_id:
                    conv = await conv_mgr.get_conversation(session_id, conv_id)
                    if conv and conv.history:
                        history = json.loads(conv.history)
                        recent = history[-context_window * 2:] if context_window > 0 else []
                        for msg in recent:
                            role = msg.get("role", "user")
                            content = msg.get("content", "")
                            if content:
                                messages.append({"role": role, "content": str(content)})
        except Exception as e:
            logger.warning(f"获取上下文消息失败: {e}")
            pass
        return messages

    async def _synthesize(
        self,
        raw_text: str,
        event: AstrMessageEvent,
        context_messages: list[dict],
    ) -> Record | None:
        """
        按优先级尝试所有供应商，集成 SubAgent 工具调用 + 参数验证重试。

        Args:
            raw_text (str): 待合成的原始文本。
            event (AstrMessageEvent): 消息事件对象，用于上下文传递。
            context_messages (list[dict]): 上下文消息列表，用于 SubAgent 调用。

        Returns:
            Record | None: 合成成功则返回包含音频的 Record 对象，否则返回 None。
        """
        if not self.providers:
            logger.warning("没有配置任何 TTS 供应商，请在插件配置中添加 providers 条目")
            return None
        
        for idx, entry in enumerate(self.providers):
            entry_name = self.config.get_entry_name(entry, idx)
            adapter = ProviderFactory.get_adapter(entry)
            if not adapter:
                continue

            entry_with_data_dir = dict(entry)
            entry_with_data_dir["_data_dir"] = str(self.plugin_data_path / "audio")

            # 检查是否有文档
            has_docs = bool(adapter.docs_content)
            enable_enhance = self.config.get("enable_enhance", True) and has_docs

            # 无文档：降级为纯文本，直接调用 API
            if not enable_enhance:
                logger.warning(f"供应商 {entry_name} 缺少文档，降级为纯文本请求")
                try:
                    audio_path = await adapter.call_api(
                        text=raw_text,
                        raw_params={},
                        config=entry_with_data_dir
                    )
                    if audio_path:
                        return Record.fromFileSystem(audio_path, text=raw_text)
                except Exception as e:
                    logger.warning(f"纯文本 TTS 失败 ({entry_name}): {e}")
                    continue

            # 准备 SubAgent 工具
            tool_set = None
            if hasattr(adapter, "get_tool_schema"):
                tool = adapter.get_tool_schema()
                if tool:
                    tool_set = ToolSet(tools=[tool])
                else:
                    logger.warning(f"适配器 {entry_name} 的 get_tool_schema 返回 None，不启用工具")
            else:
                logger.warning(f"适配器 {entry_name} 不支持工具调用")

            # 复制上下文，用于重试时追加错误信息
            current_context = context_messages.copy() if context_messages else []
            api_params = None
            max_attempts = 2
            attempt = 0

            # --- SubAgent 调用循环（含参数验证与重试） ---
            while attempt < max_attempts:
                try:
                    sys_prompt = adapter.get_subagent_system_prompt(raw_text)
                    result = await self.sub_agent.call(
                        event,
                        sys_prompt,
                        raw_text,
                        current_context,
                        tool_set=tool_set
                    )

                    if result and isinstance(result, dict):
                        temp_params = adapter.parse_subagent_response(result)
                        is_valid, err_msg = adapter.validate_params(temp_params)

                        if is_valid:
                            api_params = temp_params
                            logger.debug(f"SubAgent 参数验证通过 (尝试 {attempt+1})")
                            break
                        else:
                            if attempt == max_attempts - 1:

                                # 最后一次尝试：清理非法参数
                                logger.warning(f"SubAgent 参数验证失败，清理非法参数: {err_msg}")
                                api_params = adapter.sanitize_params(temp_params)
                                break
                            else:

                                # 非最后一次：将 AI 回复和错误反馈追加到上下文
                                current_context.append({
                                    "role": "assistant",
                                    "content": f"我尝试调用 tts_enhance，参数为：{json.dumps(temp_params, ensure_ascii=False)}"
                                })
                                current_context.append({
                                    "role": "user",
                                    "content": f"参数格式错误：{err_msg}。请检查参数范围并仅调用 tts_enhance 工具修正。"
                                })
                                logger.info(f"SubAgent 参数验证失败，要求重试 ({attempt+1}/{max_attempts}): {err_msg}")
                                attempt += 1
                                continue
                    else:

                        # 未返回有效结构
                        if attempt == max_attempts - 1:
                            logger.warning("SubAgent 未返回有效结构，使用原始文本")
                            break
                        else:
                            current_context.append({
                                "role": "assistant",
                                "content": "我尝试调用 tts_enhance，但未返回有效结构。"
                            })
                            current_context.append({
                                "role": "user",
                                "content": "请检查你的 tts_enhance 工具调用，并确保返回有效的结构。"
                            })
                            logger.info(f"SubAgent 未返回有效结构，要求重试 ({attempt+1}/{max_attempts})")
                            attempt += 1
                            continue

                except Exception as e:

                    # SubAgent 调用异常
                    logger.warning(f"SubAgent 调用异常 (尝试 {attempt+1}): {e}")
                    if attempt == max_attempts - 1:
                        break

                    # 追加异常信息到上下文并重试
                    current_context.append({
                        "role": "user",
                        "content": f"调用过程中出现异常：{e}，请重新调用 tts_enhance 工具。"
                    })
                    attempt += 1
                    continue

            # --- 提取最终文本 ---
            enhanced_text = raw_text
            if api_params and "text" in api_params:
                enhanced_text = api_params["text"]

            # --- 打印增强参数（若配置开启）---
            if self.config.get("log_enhanced_params", False) and api_params:
                logger.info(f"增强参数: {json.dumps(api_params, ensure_ascii=False)}")

            # --- 调用 TTS API ---
            try:
                audio_path = await adapter.call_api(
                    text=enhanced_text,
                    raw_params=api_params or {},
                    config=entry_with_data_dir
                )
                if audio_path:
                    logger.info(f"TTS 合成成功，供应商: {entry_name}")
                    return Record.fromFileSystem(audio_path, text=enhanced_text)
            except Exception as e:
                logger.warning(f"供应商 {entry_name} TTS API 失败: {e}，尝试下一个")

        logger.error(f"所有 TTS 供应商均失败")
        return None

    def _register_routes(self):
        """注册音色管理相关的 Web API"""
        async def get_providers():
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

        async def create_voice():
            """创建音色"""
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

        async def list_voices():
            """列出音色"""
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
                return error_response("无法创建适配器", status_code=500)
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

        async def delete_voice():
            """删除音色"""
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
                return error_response("无法创建适配器", status_code=500)
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

        async def upload_file():
            """上传文件"""
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

                # 生成唯一文件名（时间戳 + 原始文件名）
                timestamp = int(time.time() * 1000)
                unique_name = f"upload_{timestamp}_{file_field.filename}"
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

        async def start_file_server():
            """启动临时文件服务器，只绑定内部端口，不构造 URL"""
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
            "启动临时文件服务器，返回公网 URL"
        )

        async def stop_file_server():
            """停止文件服务器，并删除临时文件"""
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

        async def preview_voice():
            """预览音色：合成语音并返回 Base64 编码的音频"""
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
                    return error_response("无法创建适配器", status_code=500)

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
