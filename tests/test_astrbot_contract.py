"""AstrBot 真实 API 的契约冒烟测试。

``conftest.py`` 里的替身（Dummy*）是照着 AstrBot 的接口形状手写的。上游一旦
改名、改签名或改返回结构，替身不会自己失败，整套测试就会「绿着但失真」——
这正是本套件此前 DummyProvider 过于宽松、DummyContext 形参名对不上的根因。

本文件用反射直接盯住替身所依赖的真实符号，把这些静默漂移变成红色。

注意：AstrBot 内部存在循环导入（``persona_mgr`` → ``astrbot.api`` →
``provider.manager`` → ``persona_mgr``），因此这里一律在测试函数内延迟导入，
与 ``test_sub_agent.py`` 导入 ``ToolSet`` 的做法保持一致。
"""

import inspect


def test_provider_text_chat_is_async_and_takes_plugin_kwargs():
    """sub_agent.py 以关键字调用 text_chat，这些参数名必须依旧存在。"""
    from astrbot.core.provider.provider import Provider

    assert inspect.iscoroutinefunction(Provider.text_chat)
    params = inspect.signature(Provider.text_chat).parameters
    for name in ("prompt", "session_id", "system_prompt", "func_tool"):
        assert name in params, f"Provider.text_chat 缺少参数 {name}"


def test_provider_get_models_is_async():
    """DummyProvider.get_models 是 async，真实基类必须一致。"""
    from astrbot.core.provider.provider import Provider

    assert inspect.iscoroutinefunction(Provider.get_models)


def test_llm_response_exposes_fields_read_by_subagent():
    """sub_agent.py 读取 tools_call_name / tools_call_args / completion_text。"""
    from astrbot.core.provider.entities import LLMResponse

    resp = LLMResponse(role="assistant", completion_text="hi")
    assert resp.completion_text == "hi"
    assert resp.tools_call_name == []
    assert resp.tools_call_args == []


def test_resolve_selected_persona_is_keyword_only():
    """插件以关键字传参调用；上游若去掉 keyword-only 或改名，这里立刻红。"""
    from astrbot.core.persona_mgr import PersonaManager

    params = inspect.signature(PersonaManager.resolve_selected_persona).parameters
    for name in ("umo", "conversation_persona_id", "platform_name"):
        assert name in params, f"resolve_selected_persona 缺少参数 {name}"
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY, (
            f"resolve_selected_persona 的 {name} 不再是 keyword-only"
        )


def test_context_get_using_provider_param_is_umo():
    """插件以位置传参调用 get_using_provider，其真实形参名是 umo。

    位置传参让「形参名不一致」这件事完全无声：一旦上游改名，插件的调用仍能
    跑通，但任何未来的关键字调用会静默失效。这里先把名字钉住。
    """
    from astrbot.core.star.context import Context

    params = inspect.signature(Context.get_using_provider).parameters
    assert "umo" in params, (
        "Context.get_using_provider 的形参不再是 umo，"
        "请检查 sub_agent.py 中按位置传入 session_id 的三处调用"
    )


def test_context_get_provider_by_id_param():
    """sub_agent.py 按位置传参调用，形参名同样钉住。"""
    from astrbot.core.star.context import Context

    params = inspect.signature(Context.get_provider_by_id).parameters
    assert "provider_id" in params
