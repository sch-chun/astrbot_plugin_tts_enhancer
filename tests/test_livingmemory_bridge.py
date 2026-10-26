"""LivingMemory 桥接模块的单元测试。

全部用例不依赖 LivingMemory 实际安装：引擎与作用域 / 白名单判定所需配置均以
dict 桩注入，人格解析经 monkeypatch 控制返回值，重点覆盖闸门与边界。风格与
astrbot_plugin_watchdoc 的 test_livingmemory_bridge.py 保持一致。
"""

from types import SimpleNamespace

from astrbot_plugin_tts_enhancer.src import livingmemory_bridge as bridge
from astrbot_plugin_tts_enhancer.src.livingmemory_bridge import (
    GLOBAL_MEMORY_SCOPE,
    LivingMemoryBridge,
    _format_results,
    _resolve_event_identity,
    is_event_memory_allowed,
    resolve_memory_scope,
)

# ---------------------------------------------------------------------------
# 桩对象
# ---------------------------------------------------------------------------


class FakeInitializer:
    def __init__(self, engine):
        self.memory_engine = engine

    async def ensure_initialized(self):
        if self.memory_engine is None:
            self.memory_engine = object()


class FakeLM:
    def __init__(self, config, engine):
        self.config_manager = config
        self.initializer = FakeInitializer(engine)


class FakeStar:
    def __init__(self, name, display_name, activated=True, star_cls=None):
        self.name = name
        self.display_name = display_name
        self.activated = activated
        self.star_cls = star_cls


class FakeContext:
    def __init__(self, stars):
        self._stars = stars

    def get_registered_star(self, name):
        for s in self._stars:
            if s.name == name:
                return s
        return None

    def get_all_stars(self):
        return self._stars


class FakeEngine:
    def __init__(self):
        self.calls = []
        self.results = [SimpleNamespace(content="记忆A")]

    async def search_memories(self, query, k, session_id, persona_id):
        self.calls.append((query, k, session_id, persona_id))
        return self.results


class FakeEvent:
    def __init__(self, umo):
        self.unified_msg_origin = umo


def make_bridge(config, engine):
    lm = FakeLM(config, engine)
    star = FakeStar("astrbot_plugin_livingmemory", "LivingMemory", star_cls=lm)
    ctx = FakeContext([star])
    return LivingMemoryBridge(ctx), engine


async def _persona_none(*_a, **_k):
    return None


async def _persona_p7(*_a, **_k):
    return "p-7"


# ---------------------------------------------------------------------------
# 引擎发现
# ---------------------------------------------------------------------------


async def test_get_engine_finds_by_plugin_name():
    engine = object()
    lm = FakeLM({}, engine)
    star = FakeStar("astrbot_plugin_livingmemory", "LivingMemory", star_cls=lm)
    b = LivingMemoryBridge(FakeContext([star]))
    got_lm, got_engine = await b._get_engine()
    assert got_engine is engine
    assert got_lm is lm


async def test_get_engine_falls_back_to_display_name():
    engine = object()
    lm = FakeLM({}, engine)
    star = FakeStar("wrong-internal-name", "LivingMemory", star_cls=lm)
    b = LivingMemoryBridge(FakeContext([star]))
    got_lm, got_engine = await b._get_engine()
    assert got_lm is lm
    assert got_engine is engine


async def test_get_engine_returns_none_when_absent():
    b = LivingMemoryBridge(FakeContext([]))
    assert await b._get_engine() == (None, None)


async def test_get_engine_skips_unactivated():
    engine = object()
    lm = FakeLM({}, engine)
    star = FakeStar(
        "astrbot_plugin_livingmemory", "LivingMemory", activated=False, star_cls=lm
    )
    b = LivingMemoryBridge(FakeContext([star]))
    assert await b._get_engine() == (None, None)


async def test_get_engine_skips_missing_star_cls():
    star = FakeStar(
        "astrbot_plugin_livingmemory", "LivingMemory", activated=True, star_cls=None
    )
    b = LivingMemoryBridge(FakeContext([star]))
    assert await b._get_engine() == (None, None)


async def test_get_engine_waits_for_init():
    lm = FakeLM({}, None)
    star = FakeStar("astrbot_plugin_livingmemory", "LivingMemory", star_cls=lm)
    b = LivingMemoryBridge(FakeContext([star]))
    got_lm, got_engine = await b._get_engine()
    assert got_lm is lm
    assert got_engine is not None


# ---------------------------------------------------------------------------
# 作用域解析
# ---------------------------------------------------------------------------


def test_scope_session():
    cfg = {"filtering_settings": {"memory_scope_mode": "session"}}
    assert resolve_memory_scope(cfg, "qq:friend:123") == "qq:friend:123"


def test_scope_global():
    cfg = {"filtering_settings": {"memory_scope_mode": "global"}}
    assert resolve_memory_scope(cfg, "qq:friend:123") == GLOBAL_MEMORY_SCOPE


def test_scope_legacy_session_filtering():
    cfg = {
        "filtering_settings": {
            "memory_scope_mode": "legacy",
            "use_session_filtering": True,
        }
    }
    assert resolve_memory_scope(cfg, "qq:friend:123") == "qq:friend:123"


def test_scope_legacy_no_session_filtering_no_isolated():
    cfg = {
        "filtering_settings": {
            "memory_scope_mode": "legacy",
            "use_session_filtering": False,
        }
    }
    assert resolve_memory_scope(cfg, "qq:friend:123") is None


def test_scope_legacy_no_session_filtering_with_isolated():
    cfg = {
        "filtering_settings": {
            "memory_scope_mode": "legacy",
            "use_session_filtering": False,
            "isolated_sessions": "qq:friend:9",
        }
    }
    assert resolve_memory_scope(cfg, "qq:friend:123") == GLOBAL_MEMORY_SCOPE


def test_scope_isolated_match():
    cfg = {"filtering_settings": {"isolated_sessions": "qq:friend:123"}}
    assert resolve_memory_scope(cfg, "qq:friend:123") == "qq:friend:123"


def test_scope_user_mode_with_alias():
    cfg = {
        "filtering_settings": {"memory_scope_mode": "user"},
        "access_control": {"identity_aliases": "qq:123=canonical"},
    }
    assert (
        resolve_memory_scope(cfg, "qq:friend:123") == "livingmemory:user:qq:canonical"
    )


def test_scope_user_mode_no_alias():
    cfg = {"filtering_settings": {"memory_scope_mode": "user"}}
    assert resolve_memory_scope(cfg, "qq:friend:123") == "livingmemory:user:qq:123"


# ---------------------------------------------------------------------------
# 白名单候选匹配
# ---------------------------------------------------------------------------


def test_whitelist_disabled():
    cfg = {"access_control": {"whitelist_enabled": False}}
    assert is_event_memory_allowed(cfg, "qq:friend:123") is True


def test_whitelist_enabled_empty():
    cfg = {"access_control": {"whitelist_enabled": True, "allowed_ids": ""}}
    assert is_event_memory_allowed(cfg, "qq:friend:123") is False


def test_whitelist_by_umo():
    cfg = {
        "access_control": {"whitelist_enabled": True, "allowed_ids": "qq:friend:123"}
    }
    assert is_event_memory_allowed(cfg, "qq:friend:123") is True
    assert is_event_memory_allowed(cfg, "qq:friend:999") is False


def test_whitelist_by_sender_id():
    cfg = {"access_control": {"whitelist_enabled": True, "allowed_ids": "123"}}
    assert is_event_memory_allowed(cfg, "qq:friend:123") is True


def test_whitelist_by_platform_sender():
    cfg = {"access_control": {"whitelist_enabled": True, "allowed_ids": "qq:123"}}
    assert is_event_memory_allowed(cfg, "qq:friend:123") is True


def test_whitelist_group_by_group_id():
    cfg = {"access_control": {"whitelist_enabled": True, "allowed_ids": "gid"}}
    assert is_event_memory_allowed(cfg, "qq:group:gid") is True


def test_whitelist_group_by_platform_group():
    cfg = {"access_control": {"whitelist_enabled": True, "allowed_ids": "qq:group:gid"}}
    assert is_event_memory_allowed(cfg, "qq:group:gid") is True


def test_whitelist_group_platform_group_id_not_a_candidate():
    cfg = {"access_control": {"whitelist_enabled": True, "allowed_ids": "qq:gid"}}
    assert is_event_memory_allowed(cfg, "qq:group:gid") is False


def test_whitelist_group_by_alias():
    cfg = {
        "access_control": {
            "whitelist_enabled": True,
            "allowed_ids": "canonical",
            "identity_aliases": "qq:123=canonical",
        }
    }
    assert is_event_memory_allowed(cfg, "qq:friend:123") is True


# ---------------------------------------------------------------------------
# 结果格式化兼容 dict / 对象
# ---------------------------------------------------------------------------


def test_format_results_object():
    results = [SimpleNamespace(content="记住 A"), SimpleNamespace(content="记住 B")]
    out = _format_results(results)
    assert "记住 A" in out and "记住 B" in out
    assert out.startswith("【LivingMemory 长期记忆参考】")


def test_format_results_dict():
    results = [{"content": "dict A"}, {"content": "dict B"}]
    out = _format_results(results)
    assert "dict A" in out and "dict B" in out


def test_format_results_empty():
    assert _format_results([]) == ""
    assert _format_results([SimpleNamespace(content="")]) == ""


# ---------------------------------------------------------------------------
# 身份归并
# ---------------------------------------------------------------------------


def test_identity_alias():
    ac = {"identity_aliases": "qq:123=canonical"}
    assert _resolve_event_identity(ac, "qq:friend:123") == "canonical"


def test_identity_fallback_sender():
    assert _resolve_event_identity({}, "qq:friend:123") == "123"


def test_identity_group_fallback_umo():
    assert _resolve_event_identity({}, "qq:group:gid") == "qq:group:gid"


# ---------------------------------------------------------------------------
# recall_for_tts：正常路径 + 闸门
# ---------------------------------------------------------------------------


async def test_recall_for_tts_happy_path(monkeypatch):
    engine = FakeEngine()
    cfg = {
        "filtering_settings": {
            "memory_scope_mode": "global",
            "use_persona_filtering": False,
        },
        "access_control": {},
    }
    b, engine = make_bridge(cfg, engine)
    monkeypatch.setattr(bridge, "get_lm_persona_id", _persona_none)
    out = await b.recall_for_tts(
        event=FakeEvent("qq:friend:123"), query="测试", top_k=5
    )
    assert "记忆A" in out
    assert engine.calls[0][2] == GLOBAL_MEMORY_SCOPE
    assert engine.calls[0][3] is None


async def test_recall_for_tts_session_scope(monkeypatch):
    engine = FakeEngine()
    cfg = {
        "filtering_settings": {
            "memory_scope_mode": "session",
            "use_persona_filtering": False,
        },
        "access_control": {},
    }
    b, engine = make_bridge(cfg, engine)
    monkeypatch.setattr(bridge, "get_lm_persona_id", _persona_none)
    out = await b.recall_for_tts(event=FakeEvent("qq:friend:123"), query="x", top_k=5)
    assert "记忆A" in out
    assert engine.calls[0][2] == "qq:friend:123"


async def test_recall_for_tts_fail_closed_when_persona_unresolvable(monkeypatch):
    # 要求按人格过滤却解析不到人格 → 跳过召回，而不是把其他人格记忆混进来
    engine = FakeEngine()
    cfg = {
        "filtering_settings": {
            "memory_scope_mode": "global",
            "use_persona_filtering": True,
        },
        "access_control": {},
    }
    b, engine = make_bridge(cfg, engine)
    monkeypatch.setattr(bridge, "get_lm_persona_id", _persona_none)
    out = await b.recall_for_tts(event=FakeEvent("qq:friend:123"), query="x", top_k=5)
    assert out == ""
    assert engine.calls == []


async def test_recall_for_tts_persona_filter_off_proceeds(monkeypatch):
    # LM 关闭人格过滤：不解析人格，正常召回（persona_id=None 透传给 search_memories）
    engine = FakeEngine()
    cfg = {
        "filtering_settings": {
            "memory_scope_mode": "global",
            "use_persona_filtering": False,
        },
        "access_control": {},
    }
    b, engine = make_bridge(cfg, engine)
    monkeypatch.setattr(bridge, "get_lm_persona_id", _persona_none)
    out = await b.recall_for_tts(event=FakeEvent("qq:friend:123"), query="x", top_k=5)
    assert "记忆A" in out
    assert engine.calls[0][3] is None


async def test_recall_for_tts_top_k_zero_is_noop():
    engine = FakeEngine()
    cfg = {
        "filtering_settings": {
            "memory_scope_mode": "global",
            "use_persona_filtering": False,
        },
        "access_control": {},
    }
    b, engine = make_bridge(cfg, engine)
    out = await b.recall_for_tts(event=FakeEvent("qq:friend:123"), query="x", top_k=0)
    assert out == ""


async def test_recall_for_tts_whitelist_blocks(monkeypatch):
    engine = FakeEngine()
    cfg = {
        "filtering_settings": {
            "memory_scope_mode": "global",
            "use_persona_filtering": False,
        },
        "access_control": {
            "whitelist_enabled": True,
            "allowed_ids": "qq:friend:123",
        },
    }
    b, engine = make_bridge(cfg, engine)
    monkeypatch.setattr(bridge, "get_lm_persona_id", _persona_none)
    out = await b.recall_for_tts(event=FakeEvent("qq:friend:999"), query="x", top_k=5)
    assert out == ""
    assert engine.calls == []


async def test_recall_for_tts_caches(monkeypatch):
    engine = FakeEngine()
    cfg = {
        "filtering_settings": {
            "memory_scope_mode": "global",
            "use_persona_filtering": False,
        },
        "access_control": {},
    }
    b, engine = make_bridge(cfg, engine)
    monkeypatch.setattr(bridge, "get_lm_persona_id", _persona_none)
    ev = FakeEvent("qq:friend:123")
    await b.recall_for_tts(event=ev, query="x", top_k=5)
    await b.recall_for_tts(event=ev, query="x", top_k=5)
    assert len(engine.calls) == 1  # 第二次命中缓存
