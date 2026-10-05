"""src/tts_service.py 单元测试 —— 供应商选择、重试、降级与失败隔离。"""

import json

import pytest
from astrbot_plugin_tts_enhancer.src.config import TTSEnhancerConfig
from astrbot_plugin_tts_enhancer.src.tts_service import TTSService
from conftest import (
    DummyContext,
    DummyConversation,
    DummyConversationManager,
    DummyEvent,
    DummyPersonaManager,
    RecordingAdapter,
)



class FakeSubAgent:
    """TTSSubAgent 替身，记录调用并返回预设结果。"""

    def __init__(self, results=None, raise_exc=None):
        self.results = results if results is not None else [{"text": "增强文本"}]
        self.raise_exc = raise_exc
        self.calls: list[dict] = []

    async def call(
        self, event, sys_prompt, user_message, context_messages, persona, tool_set=None, **kwargs
    ):
        self.calls.append({"tool_set": tool_set, "persona": persona})
        if self.raise_exc:
            raise self.raise_exc
        # 每次调用返回结果列表中的第 n 项，超出则重复最后一项
        idx = min(len(self.calls) - 1, len(self.results) - 1)
        return self.results[idx]


def _make_service(monkeypatch, providers, raw_config=None, adapter=None, **ctx_kw):
    """构建一个 TTSService，并把 ProviderFactory.get_adapter 指向给定适配器。"""
    cfg = TTSEnhancerConfig(raw_config or {})
    ctx = DummyContext(**ctx_kw)
    service = TTSService(
        context=ctx,
        providers=providers,
        config=cfg,
        audio_data_dir=None,
    )
    if adapter is not None:
        import astrbot_plugin_tts_enhancer.providers as prov_mod

        monkeypatch.setattr(
            prov_mod.ProviderFactory, "get_adapter", lambda entry: adapter
        )
    return service


@pytest.fixture
def conv_mgr():
    return DummyConversationManager()


@pytest.fixture
def persona_mgr():
    return DummyPersonaManager(persona={"prompt": "温柔"}, persona_id="p-default")


class TestContextMessages:
    """get_context_messages 的窗口控制与容错。"""

    async def test_invalid_window_returns_empty(self, conv_mgr, persona_mgr):
        service = _make_service(
            pytest.MonkeyPatch(),
            [],
            {"context_window": "10"},
            conversation_manager=conv_mgr,
            persona_manager=persona_mgr,
        )
        assert await service.get_context_messages(DummyEvent()) == []

    @pytest.mark.parametrize("window", [0, -1, -100])
    async def test_non_positive_window_returns_empty(
        self, conv_mgr, persona_mgr, window
    ):
        service = _make_service(
            pytest.MonkeyPatch(),
            [],
            {"context_window": window},
            conversation_manager=conv_mgr,
            persona_manager=persona_mgr,
        )
        assert await service.get_context_messages(DummyEvent()) == []

    async def test_missing_conversation_manager_returns_empty(self, persona_mgr):
        service = _make_service(
            pytest.MonkeyPatch(),
            [],
            {"context_window": 10},
            conversation_manager=None,
            persona_manager=persona_mgr,
        )
        assert await service.get_context_messages(DummyEvent()) == []

    async def test_corrupt_history_is_swallowed(self, persona_mgr):
        conv = DummyConversation(history="{not json")
        service = _make_service(
            pytest.MonkeyPatch(),
            [],
            {"context_window": 10},
            conversation_manager=DummyConversationManager(conversation=conv),
            persona_manager=persona_mgr,
        )
        assert await service.get_context_messages(DummyEvent()) == []

    async def test_counts_user_turns_not_messages(self, persona_mgr):
        history = json.dumps(
            [
                {"role": "user", "content": "u1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "u2"},
                {"role": "assistant", "content": "a2"},
                {"role": "user", "content": "u3"},
            ]
        )
        conv = DummyConversation(history=history)
        service = _make_service(
            pytest.MonkeyPatch(),
            [],
            {"context_window": 2},
            conversation_manager=DummyConversationManager(conversation=conv),
            persona_manager=persona_mgr,
        )
        msgs = await service.get_context_messages(DummyEvent())
        roles = [m["role"] for m in msgs]
        # 从最近的 user 消息向前取 2 轮
        assert msgs[0]["content"] == "u2"
        assert msgs[-1]["content"] == "u3"
        assert len([r for r in roles if r == "user"]) == 2

    async def test_empty_messages_skipped_in_counting(self, persona_mgr):
        """content 为空的消息不参与 user 轮次计数。"""
        history = json.dumps(
            [
                {"role": "user", "content": ""},
                {"role": "user", "content": "有内容"},
            ]
        )
        conv = DummyConversation(history=history)
        service = _make_service(
            pytest.MonkeyPatch(),
            [],
            {"context_window": 1},
            conversation_manager=DummyConversationManager(conversation=conv),
            persona_manager=persona_mgr,
        )
        msgs = await service.get_context_messages(DummyEvent())
        assert [m["content"] for m in msgs] == ["有内容"]

    async def test_history_as_list_is_handled(self, persona_mgr):
        """history 已经是 list 而非 JSON 字符串时，json.loads 会抛错并被吞掉。"""
        conv = DummyConversation(history=None)
        service = _make_service(
            pytest.MonkeyPatch(),
            [],
            {"context_window": 5},
            conversation_manager=DummyConversationManager(conversation=conv),
            persona_manager=persona_mgr,
        )
        assert await service.get_context_messages(DummyEvent()) == []


class TestSynthesizeSelection:
    async def test_no_providers_returns_none(self, monkeypatch, audio_tmp_dir):
        service = _make_service(monkeypatch, [], {})
        assert await service.synthesize("hi", DummyEvent(), []) is None

    async def test_adapter_creation_failure_continues(
        self, monkeypatch, conv_mgr, persona_mgr
    ):
        service = _make_service(
            monkeypatch,
            [{"__template_key": "unknown_provider"}],
            {},
            adapter=None,
            conversation_manager=conv_mgr,
            persona_manager=persona_mgr,
        )
        assert await service.synthesize("hi", DummyEvent(), []) is None

    async def test_all_providers_bound_to_other_persona_returns_none(
        self, monkeypatch, conv_mgr
    ):
        """所有供应商都绑定到其它人格时不应静默合成，也不应抛异常。"""
        adapter = RecordingAdapter(docs="# docs", return_path="/tmp/a.mp3")
        service = _make_service(
            monkeypatch,
            [{"__template_key": "x", "persona_id": "someone-else"}],
            {},
            adapter=adapter,
            conversation_manager=conv_mgr,
            persona_manager=DummyPersonaManager(
                persona={"prompt": "p"}, persona_id="current-persona"
            ),
        )
        assert await service.synthesize("hi", DummyEvent(), []) is None
        assert adapter.call_api_calls == []

    async def test_bound_provider_preferred(self, monkeypatch, conv_mgr):
        """绑定当前人格的供应商应排在通用供应商之前。"""
        adapter = RecordingAdapter(docs="# docs", return_path="/tmp/bound.mp3")
        service = _make_service(
            monkeypatch,
            [
                {"__template_key": "generic", "priority": 1},
                {"__template_key": "bound", "persona_id": "cur", "priority": 2},
            ],
            {},
            adapter=adapter,
            conversation_manager=conv_mgr,
            persona_manager=DummyPersonaManager(
                persona={"prompt": "p"}, persona_id="cur"
            ),
        )
        await service.synthesize("hi", DummyEvent(), [])
        assert adapter.call_api_calls[0]["config"]["__template_key"] == "bound"

    async def test_persona_resolution_failure_degrades_to_unbound(
        self, monkeypatch, conv_mgr
    ):
        """人格解析异常时应降级为空人格，而非中断整次合成。"""
        adapter = RecordingAdapter(docs="# docs", return_path="/tmp/x.mp3")
        service = _make_service(
            monkeypatch,
            [{"__template_key": "generic"}],
            {},
            adapter=adapter,
            conversation_manager=conv_mgr,
            persona_manager=DummyPersonaManager(raise_on_call=True),
        )
        result = await service.synthesize("hi", DummyEvent(), [])
        assert result is not None

    async def test_uses_enhanced_text_from_subagent(
        self, monkeypatch, conv_mgr, persona_mgr
    ):
        adapter = RecordingAdapter(docs="# docs", return_path="/tmp/x.mp3")
        service = _make_service(
            monkeypatch,
            [{"__template_key": "x"}],
            {},
            adapter=adapter,
            conversation_manager=conv_mgr,
            persona_manager=persona_mgr,
        )
        service.sub_agent = FakeSubAgent(results=[{"text": "增强后的文本"}])
        await service.synthesize("原始文本", DummyEvent(), [])
        assert adapter.call_api_calls[0]["text"] == "增强后的文本"


class TestSubAgentResultHandling:
    """sub_agent 返回结果的处理（重试已下沉到 sub_agent 内部）。"""

    async def test_subagent_valid_dict_used_as_enhanced(
        self, monkeypatch, conv_mgr, persona_mgr
    ):
        adapter = RecordingAdapter(docs="# docs", return_path="/tmp/x.mp3")
        service = _make_service(
            monkeypatch,
            [{"__template_key": "x"}],
            {},
            adapter=adapter,
            conversation_manager=conv_mgr,
            persona_manager=persona_mgr,
        )
        service.sub_agent = FakeSubAgent(results=[{"text": "增强文本"}])
        await service.synthesize("原始文本", DummyEvent(), [])
        assert adapter.call_api_calls[0]["text"] == "增强文本"
        # 重试已下沉：sub_agent 每供应商仅被调用一次
        assert len(service.sub_agent.calls) == 1

    async def test_subagent_none_falls_back_to_raw(
        self, monkeypatch, conv_mgr, persona_mgr
    ):
        adapter = RecordingAdapter(docs="# docs", return_path="/tmp/x.mp3")
        service = _make_service(
            monkeypatch,
            [{"__template_key": "x"}],
            {},
            adapter=adapter,
            conversation_manager=conv_mgr,
            persona_manager=persona_mgr,
        )
        service.sub_agent = FakeSubAgent(results=[None])
        await service.synthesize("原始", DummyEvent(), [])
        # 返回 None → 回退到原始文本（不增强）
        assert adapter.call_api_calls[0]["text"] == "原始"
        assert len(service.sub_agent.calls) == 1

    async def test_subagent_exception_falls_back_to_raw(
        self, monkeypatch, conv_mgr, persona_mgr
    ):
        adapter = RecordingAdapter(docs="# docs", return_path="/tmp/x.mp3")
        service = _make_service(
            monkeypatch,
            [{"__template_key": "x"}],
            {},
            adapter=adapter,
            conversation_manager=conv_mgr,
            persona_manager=persona_mgr,
        )
        service.sub_agent = FakeSubAgent(raise_exc=RuntimeError("LLM 炸了"))
        await service.synthesize("原始", DummyEvent(), [])
        assert adapter.call_api_calls[0]["text"] == "原始"
        assert len(service.sub_agent.calls) == 1

    async def test_api_failure_falls_through_to_next_provider(
        self, monkeypatch, conv_mgr, persona_mgr
    ):
        """单个供应商调用失败不应中断整次合成。"""
        failing = RecordingAdapter(docs="# docs", raise_on_call=True)
        good = RecordingAdapter(docs="# docs", return_path="/tmp/good.mp3")

        import astrbot_plugin_tts_enhancer.providers as prov_mod

        adapters = iter([failing, good])
        service = _make_service(
            monkeypatch,
            [{"__template_key": "a"}, {"__template_key": "b"}],
            {},
            conversation_manager=conv_mgr,
            persona_manager=persona_mgr,
        )
        monkeypatch.setattr(
            prov_mod.ProviderFactory, "get_adapter", lambda entry: next(adapters)
        )
        result = await service.synthesize("hi", DummyEvent(), [])
        assert result is not None
        assert len(good.call_api_calls) == 1


class TestKnownDefects:
    """已确认缺陷 —— 以 xfail(strict=True) 固化现状。

    这些缺陷经复核判定为「设计取舍 / 上游担保 / 不可达」，暂不修复。
    strict=True：一旦有人真的修好它们，用例会由 xfail 变 XPASS 并使 CI 失败，
    以此提醒把标记摘掉，而不是永远静默地「绿着不办事」。
    """

    @pytest.mark.xfail(
        reason="缺陷#14（二轮复核：不可达，降级为观察项）: log_enhanced_params "
        "开启后 json.dumps 不在 try 内，遇到不可序列化对象会中断整个 synthesize。"
        "但 api_params 的三个来源（sub_agent.py:117/129/131）均为 JSON 原生类型，"
        "实际无法构造不可序列化入参。此用例保留为行为记录，非必修项",
        strict=True,
    )
    async def test_unserializable_params_should_not_abort_synthesis(
        self, monkeypatch, conv_mgr, persona_mgr
    ):
        adapter = RecordingAdapter(docs="# docs", return_path="/tmp/x.mp3")
        service = _make_service(
            monkeypatch,
            [{"__template_key": "x"}],
            {"log_enhanced_params": True},
            adapter=adapter,
            conversation_manager=conv_mgr,
            persona_manager=persona_mgr,
        )
        service.sub_agent = FakeSubAgent(results=[{"text": "hi", "junk": object()}])
        result = await service.synthesize("原始", DummyEvent(), [])
        assert result is not None

    @pytest.mark.xfail(
        reason="缺陷#15（二轮复核：配置侧归上游担保，降级为观察项）: "
        "context_window 的类型检查使用 isinstance(x, int)，bool 是 int 子类故 True 会静默通过。"
        "但该入参来自配置且 schema 声明 int，属 AstrBot 校验范围；且此处已有 isinstance 防护。"
        "对照 P3-3a：LLM 输出路径的 validate_params 不受上游覆盖，应自行排 bool",
        strict=True,
    )
    async def test_bool_window_should_be_rejected(self, persona_mgr):
        history = json.dumps([{"role": "user", "content": "u1"}])
        service = _make_service(
            pytest.MonkeyPatch(),
            [],
            {"context_window": True},
            conversation_manager=DummyConversationManager(
                conversation=DummyConversation(history=history)
            ),
            persona_manager=persona_mgr,
        )
        assert await service.get_context_messages(DummyEvent()) == []



class TestRegressionGuards:
    """已修复缺陷的回归守卫（非 xfail，修复后必须稳定通过）。"""

    async def test_no_docs_should_not_invoke_subagent(
        self, monkeypatch, conv_mgr, persona_mgr
    ):
        """原缺陷#12 回归：无文档供应商的降级分支必须结束于 continue。

        call_api 返回空串（而非抛异常）时若 fall-through，会白白调用一次 LLM
        并二次请求 TTS API，既浪费额度也违背「缺文档就不增强」的设计初衷。
        """
        adapter = RecordingAdapter(docs="", return_path="")
        service = _make_service(
            monkeypatch,
            [{"__template_key": "x"}],
            {},
            adapter=adapter,
            conversation_manager=conv_mgr,
            persona_manager=persona_mgr,
        )
        sub = FakeSubAgent(results=[{"text": "abc"}])
        service.sub_agent = sub
        await service.synthesize("原始", DummyEvent(), [])
        assert len(sub.calls) == 0

    async def test_empty_enhanced_text_should_fall_back_to_raw(
        self, monkeypatch, conv_mgr, persona_mgr
    ):
        """原缺陷#13 回归：SubAgent 返回空 text 时应回退到原始文本。

        否则会带着空字符串去请求 TTS API（浪费额度且必然失败）。
        """
        adapter = RecordingAdapter(docs="# docs", return_path="/tmp/x.mp3")
        service = _make_service(
            monkeypatch,
            [{"__template_key": "x"}],
            {},
            adapter=adapter,
            conversation_manager=conv_mgr,
            persona_manager=persona_mgr,
        )
        service.sub_agent = FakeSubAgent(results=[{"text": ""}])
        await service.synthesize("原始文本", DummyEvent(), [])
        assert adapter.call_api_calls[0]["text"] == "原始文本"

    async def test_get_current_persona_should_tolerate_missing_conv_mgr(
        self, monkeypatch
    ):
        """原缺陷#16 回归：conv_mgr / persona_mgr 未就绪时不应抛 AttributeError。

        两个 manager 都可能为 None（与 get_context_messages 保持一致的防御风格）。
        """
        service = _make_service(
            monkeypatch, [], {}, conversation_manager=None, persona_manager=None
        )
        prompt, persona_id = await service.get_current_persona(DummyEvent())
        assert prompt == ""
