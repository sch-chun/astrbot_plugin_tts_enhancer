"""Web 路由共享工具函数（纯函数 / 校验），供 ``src/routes`` 各模块复用。

原集中于 ``main.py`` 的模块级辅助函数，迁移至此以避免 ``main._register_routes``
巨型方法并消除循环导入（路由模块改为从这里导入）。
"""

import base64
import hashlib
import mimetypes
import re
from pathlib import Path

# file_id 白名单：首字符非点，禁止 "." / ".." / 路径分隔符，长度 <=128。
_SAFE_FILE_ID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,127}$")


def _validate_file_id(file_id: str) -> str:
    """校验 file_id 是否为安全文件名片段。

    Args:
        file_id: 调用方传入的文件标识符。

    Returns:
        校验通过的 file_id（原样返回）。

    Raises:
        ValueError: file_id 为空、非字符串或不匹配白名单时。
    """
    if not isinstance(file_id, str) or not _SAFE_FILE_ID_RE.match(file_id):
        raise ValueError(f"非法 file_id: {file_id!r}")
    return file_id


def _parse_entry_id(entry_id, providers_count: int) -> int | None:
    """校验请求体中的 entry_id 并返回合法索引。

    Args:
        entry_id: 待校验的 entry_id，类型未知。
        providers_count: 当前已配置的供应商数量。

    Returns:
        合法时返回 entry_id；类型错误或越界时返回 None。
    """
    # bool 是 int 子类，需显式排除，避免 {"entry_id": true} 被当作索引 1
    if isinstance(entry_id, bool) or not isinstance(entry_id, int):
        return None
    if entry_id < 0 or entry_id >= providers_count:
        return None
    return entry_id


def _build_page_background_response(
    config, plugin_data_path
) -> tuple[dict, str | None]:
    """构造管理页背景图响应数据（纯函数，便于单测）。

    仅当配置了背景图且文件可读时返回 data_url；否则 data_url 为空，前端不渲染背景。
    图片以 base64 Data URL 返回，避免二进制穿桥与跨域/外链，保持离线可用。
    路径解析后强制锁定在 plugin_data 目录内，防止路径穿越；不做硬编码体积上限
    （由配置 hint 提示用户图片不宜过大，避免超大 base64 拖慢页面加载）。

    同时按文件字节计算内容 ETag：路由据此应答条件请求，文件未变更时返回 304，
    浏览器经 HTTP 缓存把已存 base64 透明交给 XHR，大图不再每次进入页面全量重传。

    Args:
        config: 插件配置（dict 或带 .get 的配置对象），可为 None。
        plugin_data_path: 插件数据目录（Path 或等价字符串）。

    Returns:
        (响应 dict, ETag 或 None) 二元组。响应 dict 含 data_url / opacity / blur，
        尚未包裹 JSONResponse；未配置背景图或读取失败时 ETag 为 None，
        路由不附加缓存头（空响应体积极小，无缓存意义）。
        ETag 由图片字节与 opacity / blur 共同哈希：任一变（换图或调显示参数）
        缓存即失效，避免条件请求把旧参数继续发给前端。
    """
    empty = {"code": 0, "data": {"data_url": "", "opacity": 1.0, "blur": 0}}
    if config is None:
        return empty, None
    background_files = config.get("page_background") or []
    if not isinstance(background_files, list) or not background_files:
        return empty, None

    rel_path = background_files[0]
    if not isinstance(rel_path, str) or not rel_path:
        return empty, None

    # 锁定在 plugin_data 目录内，防止路径穿越
    base = Path(plugin_data_path).resolve()
    target = (base / rel_path).resolve()
    if target != base and base not in target.parents:
        return empty, None

    if not target.is_file():
        return empty, None

    try:
        raw = target.read_bytes()
    except OSError:
        return empty, None

    mime, _ = mimetypes.guess_type(target.name)
    if not mime:
        mime = "application/octet-stream"
    data_url = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
    opacity = config.get("page_background_opacity", 0.5)
    blur = config.get("page_background_blur", 0)
    # ETag 必须覆盖整个响应表示：图片字节 + 显示参数。
    # 只哈希文件字节时，用户仅调透明度/模糊度（不换图）ETag 不变，
    # 304 会把旧 opacity/blur 接着发给前端，调整被缓存挡住。
    etag_material = b"|".join(
        [raw, str(opacity).encode("utf-8"), str(blur).encode("utf-8")]
    )
    etag = f'"{hashlib.sha256(etag_material).hexdigest()[:16]}"'
    return {
        "code": 0,
        "data": {"data_url": data_url, "opacity": opacity, "blur": blur},
    }, etag


def _if_none_match_matches(if_none_match: str | None, etag: str) -> bool:
    """按 RFC 7232 弱比较判断 If-None-Match 头是否命中 etag。

    请求头按规范可能是逗号分隔的多值列表，列表项也可带 W/ 弱验证器前缀；
    If-None-Match 语义上使用弱比较（弱验证器与强验证器等价），逐项剥离
    W/ 后与 etag 比对，任一项相同即命中。头缺失或全不命中返回 False。

    Args:
        if_none_match: 请求头 If-None-Match 的值，可为 None。
        etag: 服务端生成的强 ETag（带引号的十六进制串）。

    Returns:
        命中返回 True，否则 False。
    """
    if not if_none_match:
        return False
    for candidate in if_none_match.split(","):
        candidate = candidate.strip().removeprefix("W/")
        if candidate == etag:
            return True
    return False
