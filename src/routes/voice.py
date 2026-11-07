"""音色管理相关 Web API 路由（供应商列表 + 音色 CRUD + 预览）。

从 ``main._register_routes`` 拆分而来，行为与原实现保持一致；所有 handler 以闭包
形式捕获传入的 ``plugin`` 实例，经 ``register_voice(plugin)`` 统一注册。
"""

import base64
from pathlib import Path

from fastapi.responses import JSONResponse

from astrbot.api import logger
from astrbot.api.web import error_response, json_response, request

from ...providers import ProviderFactory
from ...providers.mixins import FileManageable, VoiceManageable
from ..routes.helpers import _parse_entry_id
from ..synthesis_store import SOURCE_PREVIEW


def register_voice(plugin) -> None:
    """注册音色管理相关路由。

    包含以下路由：
        - GET  /providers: 获取分组后的供应商列表。
        - POST /voice/create: 创建音色。
        - POST /voice/query: 查询音色部署状态（前端轮询审核进度）。
        - POST /voice/list: 查询音色列表。
        - POST /voice/delete: 删除音色。
        - POST /voice/preview: 预览音色。
    """

    async def get_providers() -> JSONResponse:
        """获取分组后的供应商列表。

        将供应商按 template_key 分组，并对 api_key 进行脱敏处理。

        Returns:
            JSONResponse: 包含分组后供应商列表的 JSON 响应。
        """
        providers_raw = plugin.config.get_providers()
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
        # 从自动发现注册表取出每类适配器的元信息，作为「单一数据源」：
        # 展示名与能力（是否支持音色管理 / 供应商文件管理）由后端口径决定，
        # 前端不再各自硬编码，避免前后端漂移。
        ProviderFactory._discover_adapters()
        registry = ProviderFactory._adapters or {}
        result = []
        for k, v in groups.items():
            adapter_cls = registry.get(k)
            capabilities = {
                "voice_management": bool(
                    adapter_cls and issubclass(adapter_cls, VoiceManageable)
                ),
                "file_management": bool(
                    adapter_cls and issubclass(adapter_cls, FileManageable)
                ),
            }
            result.append(
                {
                    "template_key": k,
                    "entries": v,
                    "display_name": getattr(adapter_cls, "DISPLAY_NAME", k)
                    if adapter_cls
                    else k,
                    "capabilities": capabilities,
                    # ui_component 标记该供应商对应的前端组件文件名（约定 = template_key），
                    # 前端按此约定懒加载组件，取代散落的硬编码映射。
                    "ui_component": k,
                }
            )
        return json_response({"code": 0, "data": result})

    plugin.context.register_web_api(
        f"/{plugin.name}/providers",
        get_providers,
        ["GET"],
        "获取分组后的供应商列表",
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
        providers_raw = plugin.config.get_providers()
        entry_idx = _parse_entry_id(entry_id, len(providers_raw))
        if entry_idx is None:
            return error_response("entry not found", status_code=404)
        entry = providers_raw[entry_idx]
        adapter = ProviderFactory.get_adapter(entry)
        if not adapter:
            return error_response("无法创建适配器，请检查配置", status_code=500)
        # 能力检测：未继承 VoiceManageable 的适配器结构上即「不支持」。
        if not hasattr(adapter, "create_voice"):
            return error_response("该供应商不支持音色创建", status_code=501)
        try:
            result = await adapter.create_voice(params)
            return json_response({"code": 0, "data": result})
        except NotImplementedError:
            return error_response("该供应商不支持音色创建", status_code=501)
        except Exception as e:
            logger.error(f"创建音色失败: {e}")
            return error_response(str(e), status_code=500)

    plugin.context.register_web_api(
        f"/{plugin.name}/voice/create",
        create_voice,
        ["POST"],
        "创建音色（请求体包含 entry_id 及供应商特定参数）",
    )

    async def query_voice_status() -> JSONResponse:
        """查询音色部署状态（前端轮询审核进度用）。

        仅做转发：按 entry_id 取出适配器后调用其 ``query_voice``，
        不在此耦合任何供应商特有的查询逻辑；适配器未实现时返回 501。
        """
        payload = await request.json(default={})
        if not payload:
            return error_response("payload required", status_code=400)
        entry_id = payload.get("entry_id")
        voice_id = payload.get("voice_id")
        if entry_id is None:
            return error_response("entry_id required", status_code=400)
        if not voice_id:
            return error_response("voice_id required", status_code=400)
        providers_raw = plugin.config.get_providers()
        entry_idx = _parse_entry_id(entry_id, len(providers_raw))
        if entry_idx is None:
            return error_response("entry not found", status_code=404)
        entry = providers_raw[entry_idx]
        adapter = ProviderFactory.get_adapter(entry)
        if not adapter:
            return error_response("无法创建适配器，请检查配置", status_code=500)
        # 适配器根本未实现 query_voice（方法缺失）即视为「供应商不支持」，
        # 与显式抛 NotImplementedError 等价，统一返回 501。
        if not callable(getattr(adapter, "query_voice", None)):
            return error_response("该供应商不支持查询音色状态", status_code=501)
        try:
            status = await adapter.query_voice(voice_id)
            return json_response(
                {"code": 0, "data": {"voice_id": voice_id, "status": status}}
            )
        except NotImplementedError:
            # 仅「明确未实现」视为供应商不支持；其它异常（含真实 bug 抛出的
            # AttributeError）不应被误判为不支持，应交由下方通用分支如实记录。
            return error_response("该供应商不支持查询音色状态", status_code=501)
        except Exception as e:
            logger.error(f"查询音色状态失败: {e}")
            # 不把原始异常字符串回传前端（可能泄漏 workspace_id 等内部信息）
            return error_response("查询音色状态失败，请稍后重试", status_code=500)

    plugin.context.register_web_api(
        f"/{plugin.name}/voice/query",
        query_voice_status,
        ["POST"],
        "查询音色部署状态（前端轮询审核进度，请求体含 entry_id 与 voice_id）",
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
        providers_raw = plugin.config.get_providers()
        entry_idx = _parse_entry_id(entry_id, len(providers_raw))
        if entry_idx is None:
            return error_response("entry not found", status_code=404)
        entry = providers_raw[entry_idx]
        adapter = ProviderFactory.get_adapter(entry)
        if not adapter:
            return error_response("无法创建适配器，请检查配置", status_code=500)
        # 能力检测：未继承 VoiceManageable 的适配器结构上即「不支持」。
        if not hasattr(adapter, "list_voice"):
            return error_response("该供应商不支持音色列表查询", status_code=501)
        try:
            result = await adapter.list_voice(**params)
            return json_response({"code": 0, "data": result})
        except NotImplementedError:
            return error_response("该供应商不支持音色列表查询", status_code=501)
        except Exception as e:
            logger.error(f"查询音色列表失败: {e}")
            return error_response(str(e), status_code=500)

    plugin.context.register_web_api(
        f"/{plugin.name}/voice/list",
        list_voices,
        ["POST"],
        "查询音色列表（请求体包含 entry_id 及供应商特定参数）",
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
        providers_raw = plugin.config.get_providers()
        entry_idx = _parse_entry_id(entry_id, len(providers_raw))
        if entry_idx is None:
            return error_response("entry not found", status_code=404)
        entry = providers_raw[entry_idx]
        adapter = ProviderFactory.get_adapter(entry)
        if not adapter:
            return error_response("无法创建适配器，请检查配置", status_code=500)
        # 能力检测：未继承 VoiceManageable 的适配器结构上即「不支持」。
        if not hasattr(adapter, "delete_voice"):
            return error_response("该供应商不支持音色删除", status_code=501)
        try:
            success = await adapter.delete_voice(**params)
            return json_response({"code": 0, "data": {"success": success}})
        except NotImplementedError:
            return error_response("该供应商不支持音色删除", status_code=501)
        except Exception as e:
            logger.error(f"删除音色失败: {e}")
            return error_response(str(e), status_code=500)

    plugin.context.register_web_api(
        f"/{plugin.name}/voice/delete",
        delete_voice,
        ["POST"],
        "删除音色（请求体包含 entry_id 及供应商特定标识参数）",
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
            text = payload.get("text", "你好呀，今天天气真不错，我们一起去公园散步吧！")
            if entry_id is None or not voice_id:
                return error_response("entry_id 和 voice_id 是必需的", status_code=400)

            providers_raw = plugin.config.get_providers()
            entry_idx = _parse_entry_id(entry_id, len(providers_raw))
            if entry_idx is None:
                return error_response("entry not found", status_code=404)
            entry = providers_raw[entry_idx]

            entry_with_data_dir = dict(entry)
            entry_with_data_dir["_data_dir"] = str(plugin.plugin_data_path / "audio")

            adapter = ProviderFactory.get_adapter(entry_with_data_dir)
            if not adapter:
                return error_response("无法创建适配器，请检查配置", status_code=500)

            # 复用核心合成流程：预览可显式开关 SubAgent 增强（默认关闭）。
            # 记录落盘（含 AI 增强参数 / 配置快照）统一在 _synthesize_one 内完成。
            enhance = bool(payload.get("enhance", False))
            source = payload.get("source") or SOURCE_PREVIEW
            provider_name = plugin.config.get_entry_name(entry, entry_idx)
            audio_path, ext = await plugin.tts_service.preview_synthesize(
                entry, provider_name, text, voice_id, enhance, source
            )
            if not audio_path:
                return error_response("合成失败", status_code=500)

            # 读取音频文件并 Base64 编码
            with open(audio_path, "rb") as f:
                audio_bytes = f.read()
            audio_base64 = base64.b64encode(audio_bytes).decode("ascii")

            # 删除临时文件
            Path(audio_path).unlink(missing_ok=True)

            return json_response(
                {
                    "code": 0,
                    "data": {
                        "audio_base64": audio_base64,
                        "format": ext,
                    },
                }
            )
        except NotImplementedError:
            return error_response("该适配器不支持预览", status_code=501)
        except Exception as e:
            logger.error(f"预览音色失败: {e}")
            return error_response(str(e), status_code=500)

    plugin.context.register_web_api(
        f"/{plugin.name}/voice/preview",
        preview_voice,
        ["POST"],
        "预览音色，返回音频文件",
    )
