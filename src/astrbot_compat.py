"""AstrBot 人格解析 API 的版本兼容层。

上游 ``PersonaManager.resolve_selected_persona`` 在正式版发布前发生了两处
破坏性变更：

* 旧签名 ``(*, umo, conversation_persona_id, platform_name, provider_settings=None)``，
  返回 4 元组 ``(persona_id, persona, force, webchat)``；
* 新签名 ``(*, umo, platform_name)``，
  返回 3 元组 ``(persona_id, persona, use_webchat_default)``。

本模块在运行时探测真实签名：旧版会先从 conversation 取 persona_id 传入，
新版则完全不触碰 conversation manager（新版本身从 effective config 解析）。
返回值统一收敛为前两项 ``(persona_id, persona)``，调用方无需感知元组长度差异。

TODO(上游正式版发布后): 删除旧签名分支与 conv_mgr 参数，并在插件元数据中
声明最低支持的 AstrBot 版本。
"""

from __future__ import annotations

import inspect
from functools import lru_cache
from typing import Any

from astrbot.api import logger


@lru_cache(maxsize=32)
def _parameter_names(func: Any) -> frozenset[str]:
    """缓存方法形参名；以未绑定函数对象为键，避免持有 manager 实例。"""
    return frozenset(inspect.signature(func).parameters)


def _accepts_conversation_persona_id(manager: Any) -> bool:
    """判断 manager 的 resolve_selected_persona 是否接受旧版参数。"""
    try:
        return "conversation_persona_id" in _parameter_names(
            type(manager).resolve_selected_persona
        )
    except (TypeError, ValueError) as exc:
        # 极端情况：动态代理 / C 实现导致签名不可解析。按新版调用（未来方向），
        # 并留下可诊断的 warning，避免静默吞掉真实问题。
        logger.warning(
            f"无法解析 resolve_selected_persona 签名（{exc}），"
            "按新版签名调用；若运行在旧版 AstrBot 上请反馈此问题。"
        )
        return False


async def resolve_current_persona(
    *,
    persona_mgr: Any,
    umo: str,
    platform_name: str,
    conv_mgr: Any = None,
) -> tuple[str | None, Any]:
    """解析当前生效人格，返回 ``(persona_id, persona)``。

    Args:
        persona_mgr: 真实或替身的 PersonaManager，须提供
            ``resolve_selected_persona``。
        umo: 统一消息来源标识。
        platform_name: 平台名（新版用于 WebChat 默认人格判断）。
        conv_mgr: 旧版专用，用于取 conversation 绑定的 persona_id；
            新版路径不会访问它。

    Returns:
        ``(persona_id, persona)``；persona 为 None 表示未生效人格。
    """
    kwargs: dict[str, Any] = {"umo": umo, "platform_name": platform_name}

    if _accepts_conversation_persona_id(persona_mgr):
        conversation_persona_id = None
        # conv_mgr 可能未就绪（与 get_context_messages 的防御风格保持一致）
        if conv_mgr is not None:
            conv_id = await conv_mgr.get_curr_conversation_id(umo)
            conversation = (
                await conv_mgr.get_conversation(umo, conv_id) if conv_id else None
            )
            conversation_persona_id = (
                conversation.persona_id if conversation is not None else None
            )
        kwargs["conversation_persona_id"] = conversation_persona_id

    result = await persona_mgr.resolve_selected_persona(**kwargs)
    # 旧版 4 元组 / 新版 3 元组，前两项含义一致；只取前两项完成归一化。
    return result[0], result[1]
