"""合成记录管理与管理页背景图相关 Web API 路由。

从 ``main._register_routes`` 拆分而来，行为与原实现保持一致；所有 handler 以闭包
形式捕获传入的 ``plugin`` 实例，经 ``register_records(plugin)`` 统一注册。

包含两类路由：
  - 管理页背景图 ``GET /page-background``：返回背景图 Data URL 与显示参数，附 ETag
    条件缓存（304）。
  - 合成记录管理 ``POST /synthesis-records(+ /audio | /delete | /clear | /record)``：
    查看 / 播放 / 删除 / 清空 / 回传记录，全部经由 ``plugin.synthesis_store``。
"""

import base64

from fastapi.responses import JSONResponse, Response

from astrbot.api import logger
from astrbot.api.web import error_response, json_response, request

from ..routes.helpers import _build_page_background_response, _if_none_match_matches
from ..synthesis_store import SOURCE_PREVIEW


def register_records(plugin) -> None:
    """注册合成记录管理与管理页背景图路由。"""

    async def get_page_background() -> Response:
        """获取管理页背景图（Data URL）与显示参数。

        仅当配置了背景图时返回 data_url；否则 data_url 为空，前端不渲染背景。
        图片以 base64 Data URL 返回，避免二进制穿桥与跨域/外链，保持离线可用。
        配置了背景图时附加 ETag 与 Cache-Control: private, no-cache：
        浏览器再次请求自动携带 If-None-Match，文件未变更则返回 304，
        已存 base64 由 HTTP 缓存透明复用，大图不再每次进入页面全量重传。

        Returns:
            Response: 包含 data_url / opacity / blur 的 JSON 响应；
            条件请求命中时为 304 空响应。
        """
        payload, etag = _build_page_background_response(
            plugin.config, plugin.plugin_data_path
        )
        if not etag:
            return json_response(payload)
        cache_headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
        if _if_none_match_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=cache_headers)
        response = json_response(payload)
        response.headers.update(cache_headers)
        return response

    plugin.context.register_web_api(
        f"/{plugin.name}/page-background",
        get_page_background,
        ["GET"],
        "获取管理页背景图与显示参数",
    )

    # ---------- 合成记录管理（查看 / 播放 / 删除 / 清空 / 回传记录） ----------
    async def list_synthesis_records() -> JSONResponse:
        """列出全部合成记录（最新在前）。

        Returns:
            JSONResponse: 含记录列表（元数据，不含音频）的 JSON 响应。
        """
        store = getattr(plugin, "synthesis_store", None)
        if store is None:
            return json_response({"code": 0, "data": []})
        try:
            records = await store.list_records()
            return json_response({"code": 0, "data": records})
        except Exception as e:
            logger.error(f"读取合成记录失败: {e}")
            return error_response(str(e), status_code=500)

    async def get_synthesis_audio() -> JSONResponse:
        """按 id 获取合成音频（Base64 返回，便于前端直接播放）。

        Args (JSON Body):
            id (str): 合成记录 id。

        Returns:
            JSONResponse: 含 audio_base64 与 format 的 JSON 响应；记录或音频缺失返回 404。
        """
        store = getattr(plugin, "synthesis_store", None)
        if store is None:
            return error_response("合成记录未启用", status_code=404)
        try:
            payload = await request.json(default={})
            rec_id = (payload.get("id") or "").strip()
            rec = await store.get_record(rec_id)
            if not rec:
                return error_response("记录不存在", status_code=404)
            audio = await store.get_audio_bytes(rec_id)
            if not audio:
                return error_response("音频文件缺失", status_code=404)
            audio_base64 = base64.b64encode(audio).decode("ascii")
            return json_response(
                {
                    "code": 0,
                    "data": {
                        "audio_base64": audio_base64,
                        "format": rec.get("format") or "mp3",
                    },
                }
            )
        except Exception as e:
            logger.error(f"读取合成音频失败: {e}")
            return error_response(str(e), status_code=500)

    async def delete_synthesis_record() -> JSONResponse:
        """删除单条合成记录（含音频文件）。

        Args (JSON Body):
            id (str): 合成记录 id。

        Returns:
            JSONResponse: 删除结果；记录不存在返回 404。
        """
        store = getattr(plugin, "synthesis_store", None)
        if store is None:
            return error_response("合成记录未启用", status_code=404)
        try:
            payload = await request.json(default={})
            rec_id = (payload.get("id") or "").strip()
            ok = await store.delete(rec_id)
            if not ok:
                return error_response("记录不存在", status_code=404)
            return json_response({"code": 0, "data": {"success": True}})
        except Exception as e:
            logger.error(f"删除合成记录失败: {e}")
            return error_response(str(e), status_code=500)

    async def clear_synthesis_records() -> JSONResponse:
        """清空全部合成记录。

        Returns:
            JSONResponse: 含被删除条数的 JSON 响应。
        """
        store = getattr(plugin, "synthesis_store", None)
        if store is None:
            return error_response("合成记录未启用", status_code=404)
        try:
            deleted = await store.clear()
            return json_response({"code": 0, "data": {"deleted": deleted}})
        except Exception as e:
            logger.error(f"清空合成记录失败: {e}")
            return error_response(str(e), status_code=500)

    async def record_synthesis_audio() -> JSONResponse:
        """回传一段已合成的音频并落盘为记录（供前端持有的试听音频等场景）。

        例如声音设计创建时返回的预览音频由前端持有，经此接口回填为记录。

        Args (JSON Body):
            audio_base64 (str): 标准 base64 音频数据（不含 data: 前缀）。
            format (str): 音频格式（扩展名或 MIME 子类型）。
            source (str): 合成来源；缺省视为预览。
            provider (str, optional): 供应商显示名。
            text (str, optional): 合成文本。

        Returns:
            JSONResponse: 含新建记录 id 的 JSON 响应。
        """
        store = getattr(plugin, "synthesis_store", None)
        if store is None or store.max_records <= 0:
            return error_response("合成记录未启用", status_code=404)
        try:
            payload = await request.json(default={})
            audio_base64 = payload.get("audio_base64") or ""
            if not audio_base64:
                return error_response("audio_base64 必填", status_code=400)
            source = payload.get("source") or SOURCE_PREVIEW
            rec = await store.record_from_base64(
                audio_base64=audio_base64,
                source=source,
                provider=payload.get("provider", "") or "",
                text=payload.get("text", "") or "",
                fmt=payload.get("format", "mp3") or "mp3",
                source_detail=payload.get("source_detail", "") or "",
            )
            if rec is None:
                return error_response("音频数据非法或体积超限", status_code=400)
            return json_response({"code": 0, "data": {"id": rec["id"]}})
        except Exception as e:
            logger.error(f"回传合成记录失败: {e}")
            return error_response(str(e), status_code=500)

    plugin.context.register_web_api(
        f"/{plugin.name}/synthesis-records",
        list_synthesis_records,
        ["POST"],
        "列出合成记录",
    )
    plugin.context.register_web_api(
        f"/{plugin.name}/synthesis-records/audio",
        get_synthesis_audio,
        ["POST"],
        "获取合成音频（Base64）",
    )
    plugin.context.register_web_api(
        f"/{plugin.name}/synthesis-records/delete",
        delete_synthesis_record,
        ["POST"],
        "删除合成记录",
    )
    plugin.context.register_web_api(
        f"/{plugin.name}/synthesis-records/clear",
        clear_synthesis_records,
        ["POST"],
        "清空合成记录",
    )
    plugin.context.register_web_api(
        f"/{plugin.name}/synthesis-records/record",
        record_synthesis_audio,
        ["POST"],
        "回传并落盘一段合成音频",
    )
