"""src/sub_agent.py 单元测试 —— Provider 选择、工具调用解析与降级。"""

import json

from astrbot_plugin_tts_enhancer.src.sub_agent import TTSSubAgent
from conftest import (
    DummyContext,
    DummyEvent,
    DummyProvider,
    DummyResponse,
    RecordingAdapter,
)
from mcp.types import CallToolResult, TextContent

from astrbot.core.agent.tool import FunctionTool, ToolSet


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


def _make_tool(handler) -> FunctionTool:
    """用给定 handler 构造一个 tts_enhance 工具替身。"""
    tool = FunctionTool(
        name="tts_enhance",
        description="测试工具",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "speed": {"type": "number"},
            },
            "required": ["text"],
        },
    )
    tool.handler = handler
    return tool


class TestToolExecutionAndRetry:
    """TTSSubAgent 现在会真正执行 tts_enhance 工具 handler，并以 role:'tool' 回灌校验错误。"""

    async def test_valid_params_returned_directly(self):
        provider = DummyProvider(
            DummyResponse(
                tools_call_name=["tts_enhance"],
                tools_call_args=[{"text": "hi", "speed": 1.2}],
                tools_call_ids=["c1"],
            )
        )

        async def handler(**kw):
            return CallToolResult(
                isError=False,
                content=[
                    TextContent(type="text", text=json.dumps(kw, ensure_ascii=False))
                ],
            )

        agent = _agent({}, DummyContext(provider=provider))
        result = await agent.call(
            DummyEvent(), "sys", "hi", tool_set=ToolSet(tools=[_make_tool(handler)])
        )
        assert result == {"text": "hi", "speed": 1.2}

    async def test_invalid_params_triggers_structured_role_tool_retry(self):
        bad = DummyResponse(
            tools_call_name=["tts_enhance"],
            tools_call_args=[{"text": "abc", "speed": 99}],
            tools_call_ids=["c1"],
        )
        good = DummyResponse(
            tools_call_name=["tts_enhance"],
            tools_call_args=[{"text": "abc", "speed": 1.0}],
            tools_call_ids=["c2"],
        )
        provider = DummyProvider(responses=[bad, good])

        async def handler(**kw):
            if kw.get("speed") == 99:
                return CallToolResult(
                    isError=True,
                    content=[
                        TextContent(type="text", text="speed 必须在 0.5~2.0 之间")
                    ],
                )
            return CallToolResult(
                isError=False,
                content=[
                    TextContent(type="text", text=json.dumps(kw, ensure_ascii=False))
                ],
            )

        agent = _agent({}, DummyContext(provider=provider))
        result = await agent.call(
            DummyEvent(), "sys", "hi", tool_set=ToolSet(tools=[_make_tool(handler)])
        )
        assert result == {"text": "abc", "speed": 1.0}
        assert len(provider.calls) == 2
        # 第二次调用应通过 tool_calls_result 结构化回传
        tcr = provider.calls[1]["tool_calls_result"]
        assert tcr is not None
        # 协议完整：同时携带 assistant 的 tool_calls 与 role:'tool' 的结果
        assert tcr.tool_calls_info.tool_calls[0].id == "c1"
        assert tcr.tool_calls_info.tool_calls[0].function.name == "tts_enhance"
        assert tcr.tool_calls_result[0].tool_call_id == "c1"
        assert tcr.tool_calls_result[0].content == "speed 必须在 0.5~2.0 之间"
        # prompt 中不应再出现拍平的错误文本（避免双重信息）
        assert "speed 必须在 0.5~2.0 之间" not in provider.calls[1]["prompt"]

    async def test_final_invalid_returns_sanitized(self):
        bad = DummyResponse(
            tools_call_name=["tts_enhance"],
            tools_call_args=[{"text": "abc", "speed": 99}],
            tools_call_ids=["c1"],
        )
        provider = DummyProvider(responses=[bad, bad])

        async def handler(**kw):
            return CallToolResult(
                isError=True, content=[TextContent(type="text", text="speed 超范围")]
            )

        agent = _agent({}, DummyContext(provider=provider))
        # RecordingAdapter.sanitize_params 仅保留 text
        adapter = RecordingAdapter()
        result = await agent.call(
            DummyEvent(),
            "sys",
            "hi",
            tool_set=ToolSet(tools=[_make_tool(handler)]),
            adapter=adapter,
        )
        assert result == {"text": "abc"}
        assert len(provider.calls) == 2

    async def test_handler_exception_retries_then_none(self):
        good = DummyResponse(
            tools_call_name=["tts_enhance"],
            tools_call_args=[{"text": "hi"}],
            tools_call_ids=["c1"],
        )
        provider = DummyProvider(responses=[good, good])

        async def handler(**kw):
            raise RuntimeError("boom")

        agent = _agent({}, DummyContext(provider=provider))
        result = await agent.call(
            DummyEvent(), "sys", "hi", tool_set=ToolSet(tools=[_make_tool(handler)])
        )
        assert result is None
        assert len(provider.calls) == 2

    async def test_no_tool_call_returns_none_on_empty(self):
        provider = DummyProvider(DummyResponse())  # 无工具调用、无文本
        agent = _agent({}, DummyContext(provider=provider))
        result = await agent.call(DummyEvent(), "sys", "hi")
        assert result is None

    async def test_handler_exception_uses_structured_tool_result(self):
        bad = DummyResponse(
            tools_call_name=["tts_enhance"],
            tools_call_args=[{"text": "hi"}],
            tools_call_ids=["c1"],
        )
        good = DummyResponse(
            tools_call_name=["tts_enhance"],
            tools_call_args=[{"text": "hi", "speed": 1.0}],
            tools_call_ids=["c2"],
        )
        provider = DummyProvider(responses=[bad, good])

        state = {"n": 0}

        async def handler(**kw):
            state["n"] += 1
            if state["n"] == 1:
                raise RuntimeError("boom")
            return CallToolResult(
                isError=False,
                content=[
                    TextContent(type="text", text=json.dumps(kw, ensure_ascii=False))
                ],
            )

        agent = _agent({}, DummyContext(provider=provider))
        result = await agent.call(
            DummyEvent(), "sys", "hi", tool_set=ToolSet(tools=[_make_tool(handler)])
        )
        assert result == {"text": "hi", "speed": 1.0}
        # 工具执行异常同样以 role:'tool' 结构化回灌
        tcr = provider.calls[1]["tool_calls_result"]
        assert tcr is not None
        assert tcr.tool_calls_result[0].tool_call_id == "c1"
        assert tcr.tool_calls_result[0].content.startswith("工具执行异常：")
