"""HTTP 请求辅助函数，供各 TTS 供应商适配器复用。"""

from typing import Any

# 业务成功码：同一平台可能返回数值或字符串两种形态（如百炼网关 0 / "0"、
# 部分兼容层 200 / "200"）。统一在此声明，避免各适配器各自硬编码。
_SUCCESS_CODES = (0, 200)
_SUCCESS_CODE_STRINGS = tuple(str(code) for code in _SUCCESS_CODES)


def bearer_headers(api_key: str, with_json: bool = True) -> dict[str, str]:
    """构造带 Bearer 认证的请求头。

    Args:
        api_key: API 密钥。
        with_json: 是否追加 `Content-Type: application/json`，默认 True。

    Returns:
        请求头字典。
    """
    headers: dict[str, str] = {"Authorization": f"Bearer {api_key}"}
    if with_json:
        headers["Content-Type"] = "application/json"
    return headers


def extract_error_message(payload: Any, fallback_text: str = "") -> str:
    """从响应 JSON 提取错误信息。

    优先取 `message`、`error`、`detail`、`reason` 中第一个非空值，否则回退到
    `fallback_text`（调用方通常传入 `response.text`，以保留原始错误体）。
    用于兼容不同平台返回的错误字段。

    Args:
        payload: 已解析的响应字典。
        fallback_text: 无法提取时的回退文本。

    Returns:
        错误信息字符串。
    """
    if not isinstance(payload, dict):
        return fallback_text
    for key in ("message", "error", "detail", "reason"):
        value = payload.get(key)
        if value:
            return str(value)
    return fallback_text


def has_business_error(payload: Any) -> bool:
    """判断 HTTP 200 响应体是否携带业务错误。

    按类型分别判定，修掉两类典型误判：

    - 成功码不能按真值判断：字符串 ``"0"`` 是真值，``if data.get("code")``
      会把成功响应当成错误短路请求；数值 ``0`` 本就 falsy，真正的 bug 是字符串
      ``"0"``。数值 / 字符串 ``200`` 同理视为成功。
    - ``bool`` 不参与数值比较：``False == 0`` 会让 ``code: false`` 落进成功码集合
      被当成成功；这里把 bool 一律视为错误码（既非文档里的成功码，也非合法错误码）。

    Args:
        payload: 已解析的响应 JSON。

    Returns:
        True 表示业务错误；False 表示成功、或没有可判定的错误码。
    """
    if not isinstance(payload, dict):
        return False
    if payload.get("error"):
        return True
    code = payload.get("code")
    if code is None or code == "":
        return False
    if isinstance(code, bool):
        return True
    if isinstance(code, (int, float)):
        return code not in _SUCCESS_CODES
    if isinstance(code, str):
        return code.strip() not in _SUCCESS_CODE_STRINGS
    return True
