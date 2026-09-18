"""HTTP 请求辅助函数，供各 TTS 供应商适配器复用。"""

from typing import Any


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

    优先取 `message`、`error`、`detail` 中第一个非空值，否则回退到
    `fallback_text`。用于兼容不同平台返回的错误字段。

    Args:
        payload: 已解析的响应字典。
        fallback_text: 无法提取时的回退文本。

    Returns:
        错误信息字符串。
    """
    if not isinstance(payload, dict):
        return fallback_text
    for key in ("message", "error", "detail"):
        value = payload.get(key)
        if value:
            return str(value)
    return fallback_text
