"""src/sub_agent.py 单元测试 —— Provider 选择、工具调用解析与降级。"""

from astrbot_plugin_tts_enhancer.src.sub_agent import TTSSubAgent
from conftest import DummyContext, DummyEvent, DummyProvider, DummyResponse


def _agent(config=None, context=None):
    return TTSSubAgent(context or DummyContext(), config or {})


class TestProviderSelection:
    async def test_no_provider_returns_none(self):
        agent = _agent()
        assert await agent.call(DummyEvent(), "sys", "你好") is None

    async def test_named_provider_used(self):
        provider = DummyProvider(
            DummyResponse(
                tools_call_name=["tts_enhance"], tools_call_args=[{"text": "你好"}]
            )
        )
        ctx = DummyContext(provider=provider, provider_by_id=provider)
        agent = _agent({"enhance_llm_provider": "my-provider"}, ctx)
        result = await agent.call(DummyEvent(), "sys", "你好")
        assert result == {"text": "你好"}

    async def test_missing_named_provider_falls_back(self):
        """配置指定但不存在的增强模型应降级到会话模型，而非直接失败。"""
        provider = DummyProvider(DummyResponse(completion_text="ok"))
        ctx = DummyContext(provider=provider, provider_by_id=None)
        agent = _agent({"enhance_llm_provider": "ghost"}, ctx)
        result = await agent.call(DummyEvent(), "sys", "你好")
        assert result == {"text": "ok"}

    async def test_wrong_provider_type_returns_none(self):
        """非 Provider 实例的对象应被拒绝并记录日志。"""
        ctx = DummyContext(provider=object())
        agent = _agent({}, ctx)
        assert await agent.call(DummyEvent(), "sys", "你好") is None


class TestToolCallParsing:
    async def test_returns_tts_enhance_args(self):
        provider = DummyProvider(
            DummyResponse(
                tools_call_name=["tts_enhance"],
                tools_call_args=[{"text": "hi", "speed": 1.2}],
            )
        )
        agent = _agent({}, DummyContext(provider=provider))
        assert await agent.call(DummyEvent(), "sys", "hi") == {
            "text": "hi",
            "speed": 1.2,
        }

    async def test_unexpected_tool_name_returns_none(self):
        provider = DummyProvider(
            DummyResponse(
                tools_call_name=["weather"], tools_call_args=[{"city": "北京"}]
            )
        )
        agent = _agent({}, DummyContext(provider=provider))
        assert await agent.call(DummyEvent(), "sys", "hi") is None

    async def test_multiple_tool_calls_picks_tts_enhance(self):
        provider = DummyProvider(
            DummyResponse(
                tools_call_name=["weather", "tts_enhance"],
                tools_call_args=[{"city": "北京"}, {"text": "选我"}],
            )
        )
        agent = _agent({}, DummyContext(provider=provider))
        assert await agent.call(DummyEvent(), "sys", "hi") == {"text": "选我"}

    async def test_mismatched_name_args_length_is_truncated(self):
        """tools_call_name 比 args 长时 zip 截断，多余项被静默忽略。"""
        provider = DummyProvider(
            DummyResponse(
                tools_call_name=["tts_enhance", "orphan"],
                tools_call_args=[{"text": "hi"}],
            )
        )
        agent = _agent({}, DummyContext(provider=provider))
        assert await agent.call(DummyEvent(), "sys", "hi") == {"text": "hi"}


class TestTextFallback:
    async def test_completion_text_wrapped_as_text_key(self):
        provider = DummyProvider(DummyResponse(completion_text="  纯文本回复  "))
        agent = _agent({}, DummyContext(provider=provider))
        assert await agent.call(DummyEvent(), "sys", "hi") == {"text": "纯文本回复"}

    async def test_empty_completion_text_returns_none(self):
        provider = DummyProvider(DummyResponse(completion_text="   "))
        agent = _agent({}, DummyContext(provider=provider))
        assert await agent.call(DummyEvent(), "sys", "hi") is None

    async def test_no_tool_and_no_text_returns_none(self):
        agent = _agent({}, DummyContext(provider=DummyProvider(DummyResponse())))
        assert await agent.call(DummyEvent(), "sys", "hi") is None


class TestPromptAssembly:
    async def test_persona_included_in_prompt(self):
        provider = DummyProvider(DummyResponse(completion_text="ok"))
        agent = _agent({}, DummyContext(provider=provider))
        await agent.call(DummyEvent(), "sys", "目标文本", persona="温柔姐姐")
        prompt = provider.calls[0]["prompt"]
        assert "温柔姐姐" in prompt
        assert "目标文本" in prompt

    async def test_context_messages_included(self):
        provider = DummyProvider(DummyResponse(completion_text="ok"))
        agent = _agent({}, DummyContext(provider=provider))
        await agent.call(
            DummyEvent(),
            "sys",
            "目标文本",
            context_messages=[
                {"role": "user", "content": "今天天气如何"},
                {"role": "assistant", "content": "晴"},
                {"role": "user", "content": ""},  # 空内容应被跳过
            ],
        )
        prompt = provider.calls[0]["prompt"]
        assert "[user] 今天天气如何" in prompt
        assert "[assistant] 晴" in prompt
        # 空内容那条必须整条跳过：原断言 "[]" not in prompt 抓不到它——
        # 渲染格式是 "[角色] 内容"，空内容会变成 "[user] "（方括号并不相邻）。
        assert prompt.count("[user]") == 1
        assert prompt.count("[assistant]") == 1

    async def test_system_prompt_forwarded(self):
        provider = DummyProvider(DummyResponse(completion_text="ok"))
        agent = _agent({}, DummyContext(provider=provider))
        await agent.call(DummyEvent(), "SYS_MARKER", "hi")
        assert provider.calls[0]["system_prompt"] == "SYS_MARKER"

    async def test_session_id_forwarded(self):
        provider = DummyProvider(DummyResponse(completion_text="ok"))
        agent = _agent({}, DummyContext(provider=provider))
        event = DummyEvent(umo="my-session")
        await agent.call(event, "sys", "hi")
        assert provider.calls[0]["session_id"] == "my-session"


class TestExceptionIsolation:
    async def test_provider_exception_returns_none(self):
        agent = _agent({}, DummyContext(provider=DummyProvider(raise_on_call=True)))
        assert await agent.call(DummyEvent(), "sys", "hi") is None

    async def test_tool_set_forwarded(self):
        from astrbot.core.agent.tool import ToolSet

        provider = DummyProvider(DummyResponse(completion_text="ok"))
        agent = _agent({}, DummyContext(provider=provider))
        tool_set = ToolSet(tools=[])
        await agent.call(DummyEvent(), "sys", "hi", tool_set=tool_set)
        assert provider.calls[0]["func_tool"] is tool_set
