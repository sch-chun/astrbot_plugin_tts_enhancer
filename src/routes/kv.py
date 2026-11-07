"""通用键值存储相关 Web API 路由。

从 ``main._register_routes`` 拆分而来，行为与原实现保持一致；所有 handler 以闭包
形式捕获传入的 ``plugin`` 实例，经 ``register_kv(plugin)`` 统一注册。

路由（均 POST）：
  - ``/kv/set``：写入字符串键值对。
  - ``/kv/get``：读取键值对，缺省返回 None。
  - ``/kv/delete``：删除键值对。
"""

from fastapi.responses import JSONResponse

from astrbot.api import logger
from astrbot.api.web import error_response, json_response, request


def register_kv(plugin) -> None:
    """注册通用键值存储路由。"""

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
            await plugin.put_kv_data(key, value)
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
            value = await plugin.get_kv_data(key, None)
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
            await plugin.delete_kv_data(key)
            return json_response({"code": 0, "data": {"success": True}})
        except Exception as e:
            logger.error(f"KV 删除失败: {e}")
            return error_response(str(e), status_code=500)

    # 注册
    plugin.context.register_web_api(
        f"/{plugin.name}/kv/set", kv_set, ["POST"], "通用 KV 存储"
    )
    plugin.context.register_web_api(
        f"/{plugin.name}/kv/get", kv_get, ["POST"], "通用 KV 获取"
    )
    plugin.context.register_web_api(
        f"/{plugin.name}/kv/delete", kv_delete, ["POST"], "通用 KV 删除"
    )
