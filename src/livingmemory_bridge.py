"""TTS Enhancer ↔ LivingMemory 桥接：合成语音前召回长期记忆作为 SubAgent 上下文。

设计约束（与 astrobot_plugin_watchdoc 的 livingmemory_bridge 保持一致）：
- 仅依赖 AstrBot 公共 API 与 LivingMemory 运行时实例（经 Context.get_registered_star
  拿到插件类对象、取其 initializer.memory_engine）。
- 作用域 / 白名单 / 身份解析逻辑在此按 LivingMemory core/memory_scope.py 的语义复刻
  （resolve_memory_scope / is_event_memory_allowed / resolve_event_identity），
  以免对其包结构产生硬依赖；复刻以「行为一致」为目标，不要求逐字符相同。
- 人格 ID 解析逻辑较繁，采用「仅当已确认 LivingMemory 实例存在时」惰性导入其
  core.utils.get_persona_id 的方式，并做 ImportError / 运行时异常兜底。
- 全程优雅降级：LivingMemory 未安装 / 未激活 / 未初始化 / 检索异常 / 白名单不命中 /
  需按人格却解析不到人格，均返回空串，不阻塞 TTS 合成。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from astrbot.api import logger

if TYPE_CHECKING:
    from astrbot.core.star.context import Context

GLOBAL_MEMORY_SCOPE = "livingmemory:global"


def _lm_section(config: Any, section: str, default: Any = None) -> Any:
    """安全读取 LivingMemory 配置中的嵌套段落（如 filtering_settings / access_control）。

    兼容 dict 与带 .get 方法的配置对象（LivingMemory 的 ConfigManager）。
    """
    getter = getattr(config, "get", None)
    if callable(getter):
        try:
            val = getter(section, default)
        except TypeError:
            val = default
        return val if val is not None else default
    if isinstance(config, dict):
        return config.get(section, default)
    return default


def _as_dict(value: Any) -> dict:
    """把可能为 None / 配置对象的值归一为 dict。"""
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    d = getattr(value, "__dict__", None)
    return d if isinstance(d, dict) else {}


def _as_id_list(value: Any) -> list[str]:
    """把白名单 / 隔离会话条目归一为字符串列表。

    与 LivingMemory core.memory_scope.parse_value_list 保持一致：
    按逗号 / 分号 / 换行切分并去重（不去大小写，大小写不敏感在比对处处理）。
    """
    if isinstance(value, list):
        items = [str(x).strip() for x in value]
    else:
        items = re.split(r"[,;\n]", str(value or ""))
    return list(dict.fromkeys(x.strip() for x in items if x.strip()))


def _parse_identity_aliases(value: Any) -> dict[str, str]:
    """解析 `source=canonical` 每行一条的别名映射；与 LivingMemory 一致（key 小写化）。"""
    aliases: dict[str, str] = {}
    for line in str(value or "").splitlines():
        source, sep, target = line.partition("=")
        if not sep:
            continue
        source = source.strip()
        target = target.strip()
        if source and target:
            aliases[source.casefold()] = target
    return aliases


class _UmoEvent:
    """极简事件替身，仅暴露 LivingMemory 白名单 / 作用域判定所需的访问器。

    AstrBot 的 unified_msg_origin 格式为 platform:message_type:session_id；
    群聊时 session_id 为群 ID，私聊时为发送者 ID。复刻时严格对齐 LivingMemory
    对 get_sender_id / get_group_id / get_sender_name / get_platform_name 的取值。
    """

    def __init__(self, umo: str) -> None:
        self.unified_msg_origin = umo
        parts = umo.split(":", 2)
        self._platform = parts[0] if len(parts) == 3 else ""
        self._sid = parts[2] if len(parts) == 3 else umo
        self._type = parts[1] if len(parts) == 3 else ""

    def get_platform_name(self) -> str:
        return self._platform

    def get_sender_id(self) -> str:
        return self._sid if self._type != "group" else ""

    def get_group_id(self) -> str:
        return self._sid if self._type == "group" else ""

    def get_sender_name(self) -> str:
        return ""


def _resolve_event_identity(ac: dict, umo: str) -> str:
    """复刻 LivingMemory resolve_event_identity：按 identity_aliases 归并出规范身份。"""
    ev = _UmoEvent(umo)
    sender_id = ev.get_sender_id()
    sender_name = ev.get_sender_name()
    platform = ev.get_platform_name().casefold()
    aliases = _parse_identity_aliases(ac.get("identity_aliases", ""))
    candidates = (
        f"{platform}:{sender_id}" if platform and sender_id else "",
        sender_id,
        sender_name,
    )
    for candidate in candidates:
        if candidate and candidate.casefold() in aliases:
            return aliases[candidate.casefold()]
    return sender_id or sender_name or umo


def resolve_memory_scope(lm_config: Any, umo: str) -> str | None:
    """复刻 LivingMemory core/memory_scope.py:128 resolve_memory_scope 的会话侧解析。

    入参为 LivingMemory 配置（dict 或 ConfigManager），内部读取 filtering_settings 与
    access_control.identity_aliases。返回检索时应使用的 session_id；返回 None 表示不按
    作用域过滤（legacy 关闭会话过滤时）。
    """
    filtering = _as_dict(_lm_section(lm_config, "filtering_settings"))
    ac = _as_dict(_lm_section(lm_config, "access_control"))
    ev = _UmoEvent(umo)
    session_id = umo
    # 与上游一致：isolated_sessions 不做大小写归一，比对也用原始 UMO，保持单向一致
    isolated = set(_as_id_list(filtering.get("isolated_sessions", "")))
    if session_id in isolated:
        return session_id
    mode = str(filtering.get("memory_scope_mode", "legacy")).casefold()
    if mode == "session":
        return session_id
    if mode == "global":
        return GLOBAL_MEMORY_SCOPE
    if mode == "user":
        platform = ev.get_platform_name().casefold()
        identity = _resolve_event_identity(ac, umo).casefold()
        return f"livingmemory:user:{platform or 'unknown'}:{identity}"
    use_session = bool(filtering.get("use_session_filtering", True))
    if use_session:
        return session_id
    return GLOBAL_MEMORY_SCOPE if isolated else None


def is_event_memory_allowed(lm_config: Any, umo: str) -> bool:
    """复刻 LivingMemory core/memory_scope.py:98 的白名单候选匹配。

    入参为 LivingMemory 配置（dict 或 ConfigManager）。候选集覆盖：
    裸用户 / 群组 ID、平台:用户 ID、完整会话 ID（UMO）、按 identity_aliases 归并后的身份。
    群聊时 session_id 为群 ID，get_sender_id 为空、get_group_id 为群 ID，因此白名单按
    群 ID 或 平台:群ID 配置时也能命中。
    """
    ac = _as_dict(_lm_section(lm_config, "access_control"))
    if not bool(ac.get("whitelist_enabled", False)):
        return True
    allowed = {a.casefold() for a in _as_id_list(ac.get("allowed_ids", ""))}
    if not allowed:
        return False
    ev = _UmoEvent(umo)
    sender_id = ev.get_sender_id()
    platform = ev.get_platform_name()
    session_id = umo
    group_id = ev.get_group_id()
    identity = _resolve_event_identity(ac, umo)
    candidates = {
        sender_id,
        identity,
        session_id,
        group_id,
        f"{platform}:{sender_id}" if platform and sender_id else "",
    }
    return any(c and c.casefold() in allowed for c in candidates)


async def get_lm_persona_id(context: Context, umo: str) -> str | None:
    """取会话人格 ID：优先复用 LivingMemory 的实现，缺失 / 异常时回退 None。

    返回 None 表示「无法解析人格」——调用方需据此 fail closed（跳过召回），
    而非以 persona_id=None 调用 search_memories（那会被 LivingMemory 解释为
    「不过滤人格」，从而把其他人格的记忆混进来）。
    """
    try:
        from astrbot_plugin_livingmemory.core.utils import get_persona_id
    except ImportError:  # LivingMemory 未安装时跳过人格过滤
        return None

    class _MinEvent:
        unified_msg_origin = umo

    try:
        return await get_persona_id(context, _MinEvent())  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[tts_enhancer] 取 LivingMemory 人格 ID 失败: {exc}")
        return None


def _format_results(results: list[Any]) -> str:
    """把检索结果格式化为可并入 SubAgent prompt 的文本块；无结果返回空串。

    兼容对象（带 .content 属性）与 dict（带 "content" 键）两种形态，
    以便桥接 LivingMemory 不同版本的返回结构。
    """
    lines: list[str] = []
    for r in results:
        if isinstance(r, dict):
            content = r.get("content") or ""
        else:
            content = getattr(r, "content", "") or ""
        if content:
            lines.append(f"- {content}")
    if not lines:
        return ""
    return "【LivingMemory 长期记忆参考】\n" + "\n".join(lines)


class LivingMemoryBridge:
    """封装 TTS Enhancer 调用 LivingMemory 检索的全部决策逻辑，对调用方只暴露一个方法。"""

    def __init__(self, context: Context) -> None:
        self._context = context
        self._cache: dict[tuple, list] = {}

    def clear_cache(self) -> None:
        """清空检索缓存（当前每次合成独立检索，保留接口以备后续批量场景复用）。"""
        self._cache.clear()

    async def _get_engine(self) -> tuple[Any, Any]:
        """拿到 LivingMemory 的 MemoryEngine；未就绪则惰性等待初始化。

        Returns:
            (插件类对象, engine)；任一不可用返回 (None, None)。
        """
        # P0：按插件目录名（metadata.name）精确匹配，而非显示名
        meta = self._context.get_registered_star("astrbot_plugin_livingmemory")
        if meta is None:
            # 兜底：部分环境用显示名而非插件目录名注册
            meta = next(
                (
                    s
                    for s in self._context.get_all_stars()
                    if (getattr(s, "display_name", "") or "").casefold()
                    == "livingmemory"
                ),
                None,
            )
        if meta is None:
            logger.debug("[tts_enhancer] 未找到 LivingMemory 插件，跳过记忆召回")
            return None, None
        if not getattr(meta, "star_cls", None) or not getattr(meta, "activated", False):
            logger.debug("[tts_enhancer] LivingMemory 未激活，跳过记忆召回")
            return None, None
        lm = meta.star_cls
        # 防御：initializer 可能尚未绑定
        initializer = getattr(lm, "initializer", None)
        if initializer is None:
            logger.debug(
                "[tts_enhancer] LivingMemory 未初始化（无 initializer），跳过记忆召回"
            )
            return None, None
        engine = getattr(initializer, "memory_engine", None)
        if engine is None:
            try:
                await initializer.ensure_initialized()
                engine = getattr(initializer, "memory_engine", None)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[tts_enhancer] LivingMemory 初始化等待失败: {exc}")
                return lm, None
        return lm, engine

    async def recall_for_tts(self, *, event, query: str, top_k: int = 5) -> str:
        """召回与本次 TTS 相关的长期记忆，返回可注入 SubAgent prompt 的文本；不可用时返回空串。

        Args:
            event: 触发合成的 AstrMessageEvent，用于解析作用域 / 白名单 / 人格。
            query: 检索关键词（由调用方按 memory_retrieval 配置构造）。
            top_k: 召回条数；<=0 视为关闭。

        Returns:
            记忆文本块（【LivingMemory 长期记忆参考】 开头）；不满足检索条件 / top_k<=0 /
            检索失败时返回空串。
        """
        lm, engine = await self._get_engine()
        if engine is None:
            return ""
        if top_k <= 0:  # 配置为 0 表示关闭长期记忆参考
            return ""

        cfg = lm.config_manager
        fs = _as_dict(_lm_section(cfg, "filtering_settings"))
        ac = _as_dict(_lm_section(cfg, "access_control"))
        wl_on = bool(ac.get("whitelist_enabled", False))
        lm_persona_filter = bool(fs.get("use_persona_filtering", True))

        umo = event.unified_msg_origin

        # 作用域：与 LivingMemory 自身一致——解析失败（legacy 未开会话过滤）回退到当前会话
        session_id = resolve_memory_scope(cfg, umo) or umo

        # 白名单闸门：当前会话不在白名单内则跳过
        if wl_on and not is_event_memory_allowed(cfg, umo):
            logger.debug(
                "[tts_enhancer] LivingMemory 白名单未覆盖当前会话，跳过记忆召回"
            )
            return ""

        # 人格：要求过滤却解析不到 ID → fail closed，避免把其他人格记忆混进来
        persona_id: str | None = None
        if lm_persona_filter:
            persona_id = await get_lm_persona_id(self._context, umo)
            if persona_id is None:
                logger.warning(
                    "[tts_enhancer] 需按人格过滤但无法解析人格 ID，跳过记忆召回"
                )
                return ""

        # 检索（按条件缓存，避免同查询重复命中引擎）
        cache_key = (query, session_id, persona_id)
        cached = self._cache.get(cache_key)
        if cached is not None:
            results = cached
        else:
            try:
                results = await engine.search_memories(
                    query=query, k=top_k, session_id=session_id, persona_id=persona_id
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(f"[tts_enhancer] 召回 LivingMemory 失败: {exc}")
                return ""
            self._cache[cache_key] = results

        return _format_results(results)
