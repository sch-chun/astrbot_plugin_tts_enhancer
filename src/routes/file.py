"""音频上传与供应商文件管理相关 Web API 路由。

从 ``main._register_routes`` 拆分而来，行为与原实现保持一致；所有 handler 以闭包
形式捕获传入的 ``plugin`` 实例，经 ``register_file(plugin)`` 统一注册。

包含两类路由：
  - 通用音频上传 ``POST /upload``：接收表单文件，落盘至 ``uploads/`` 并返回 ``file_id``，
    供前端暂存后交由「供应商文件管理」流程处理。
  - 供应商文件管理 ``POST /file/{upload,list,get,delete}``：适配器需实现对应方法
    （``upload_file`` / ``list_files`` / ``get_file_content`` / ``delete_file``），
    未实现时统一返回 501。
"""

import base64
import time
from pathlib import Path

from fastapi.responses import JSONResponse

from astrbot.api import logger
from astrbot.api.web import error_response, json_response, request

from ...providers import ProviderFactory
from ..routes.helpers import _parse_entry_id, _validate_file_id


def register_file(plugin) -> None:
    """注册音频上传与供应商文件管理路由。"""

    async def upload_file() -> JSONResponse:
        """上传音频文件。

        支持的格式：wav, mp3, m4a, aac, ogg, flac。文件将重命名为包含时间戳的唯一文件名并保存。

        Args (Form Data):
            file: 上传的音频文件对象。

        Returns:
            JSONResponse: 包含 file_id 和 file_path 的 JSON 响应。
        """
        try:
            files = await request.files()

            file_field = files.get("file")
            if not file_field:
                return error_response("缺少文件", status_code=400)

            # 保存文件（先保存再校验，因为需要读取文件内容）
            upload_dir = plugin.plugin_data_path / "uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)
            original_filename = file_field.filename or "file.bin"
            ext = Path(original_filename).suffix.lower()

            # 白名单化扩展名，防止 .php / .sh 等异常后缀被写入 uploads 目录
            if ext not in {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"}:
                return error_response(
                    f"不支持的文件格式: {ext or '(无扩展名)'}，仅允许 wav/mp3/m4a/aac/ogg/flac",
                    status_code=400,
                )
            timestamp = int(time.time() * 1000)
            unique_name = f"upload_{timestamp}{ext}"
            file_path = upload_dir / unique_name
            await file_field.save(file_path)

            # 返回结果
            return json_response(
                {
                    "code": 0,
                    "data": {"file_id": unique_name, "file_path": str(file_path)},
                }
            )

        except Exception as e:
            logger.error(f"文件上传失败: {e}")
            return error_response(str(e), status_code=500)

    plugin.context.register_web_api(
        f"/{plugin.name}/upload", upload_file, ["POST"], "上传音频文件，返回 file_id"
    )

    # ---------- 供应商文件管理（上传、列表、获取、删除） ----------
    async def file_upload() -> JSONResponse:
        """上传文件到供应商（适配器需实现 upload_file 方法）。所有额外参数透传给适配器。"""
        try:
            payload = await request.json()
            if not payload:
                return error_response("payload required", status_code=400)

            entry_id = payload.get("entry_id")
            file_id = payload.get("file_id")
            if entry_id is None or file_id is None:
                return error_response("entry_id 和 file_id 都是必需的", status_code=400)

            # 查找本地文件
            try:
                file_id = _validate_file_id(file_id)
                file_path = plugin._resolve_uploads_path(file_id)
            except ValueError as e:
                return error_response(str(e), status_code=400)
            if not file_path.is_file():
                return error_response("本地文件不存在", status_code=404)

            # 获取适配器
            providers_raw = plugin.config.get_providers()
            entry_idx = _parse_entry_id(entry_id, len(providers_raw))
            if entry_idx is None:
                return error_response("entry not found", status_code=404)
            entry = providers_raw[entry_idx]
            adapter = ProviderFactory.get_adapter(entry)
            if not adapter or not hasattr(adapter, "upload_file"):
                return error_response("该适配器不支持文件上传", status_code=501)

            # 提取所有参数，去除 entry_id 和 file_id，其余全部作为 kwargs 透传
            kwargs = {
                k: v for k, v in payload.items() if k not in ["entry_id", "file_id"]
            }

            # 调用适配器的 upload_file
            result = await adapter.upload_file(  # type: ignore
                file_path=str(file_path), **kwargs
            )

            # 适配器返回的结果直接透传
            return json_response({"code": 0, "data": result})

        except Exception as e:
            logger.error(f"文件上传到供应商失败: {e}")
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

            providers_raw = plugin.config.get_providers()
            entry_idx = _parse_entry_id(entry_id, len(providers_raw))
            if entry_idx is None:
                return error_response("entry not found", status_code=404)
            entry = providers_raw[entry_idx]
            adapter = ProviderFactory.get_adapter(entry)
            if not adapter or not hasattr(adapter, "list_files"):
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

            providers_raw = plugin.config.get_providers()
            entry_idx = _parse_entry_id(entry_id, len(providers_raw))
            if entry_idx is None:
                return error_response("entry not found", status_code=404)
            entry = providers_raw[entry_idx]
            adapter = ProviderFactory.get_adapter(entry)
            if not adapter or not hasattr(adapter, "get_file_content"):
                return error_response("该适配器不支持文件获取", status_code=501)

            content = await adapter.get_file_content(int(file_id))  # type: ignore
            audio_base64 = base64.b64encode(content).decode("utf-8")
            return json_response({"code": 0, "data": {"audio_base64": audio_base64}})
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
            kwargs = {
                k: v for k, v in payload.items() if k not in ["entry_id", "file_id"]
            }
            if entry_id is None or file_id is None:
                return error_response("entry_id 和 file_id 都是必需的", status_code=400)

            providers_raw = plugin.config.get_providers()
            entry_idx = _parse_entry_id(entry_id, len(providers_raw))
            if entry_idx is None:
                return error_response("entry not found", status_code=404)
            entry = providers_raw[entry_idx]
            adapter = ProviderFactory.get_adapter(entry)
            if not adapter or not hasattr(adapter, "delete_file"):
                return error_response("该适配器不支持文件删除", status_code=501)

            success = await adapter.delete_file(int(file_id), **kwargs)  # type: ignore
            return json_response({"code": 0, "data": {"success": success}})
        except Exception as e:
            logger.error(f"删除文件失败: {e}")
            return error_response(str(e), status_code=500)

    # 注册
    plugin.context.register_web_api(
        f"/{plugin.name}/file/upload", file_upload, ["POST"], "上传文件到供应商"
    )
    plugin.context.register_web_api(
        f"/{plugin.name}/file/list", file_list, ["POST"], "列出供应商的文件"
    )
    plugin.context.register_web_api(
        f"/{plugin.name}/file/get", file_get, ["POST"], "获取文件内容（Base64）"
    )
    plugin.context.register_web_api(
        f"/{plugin.name}/file/delete", file_delete, ["POST"], "删除供应商的文件"
    )
