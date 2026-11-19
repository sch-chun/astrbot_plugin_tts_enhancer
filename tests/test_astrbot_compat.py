"""src/astrbot_compat.py —— AstrBot 新旧签名双兼容测试。

新版快照的 resolve_selected_persona 去掉了 conversation_persona_id，返回值从
4 元组收敛为 3 元组；本套件用两个严格签名替身钉住兼容层的两条分支，任何一条
误传参数都会被替身的 TypeError 立刻暴露。
"""

import inspect

import pytest
from astrbot_plugin_tts_enhancer.src.astrbot_compat import (
    _accepts_conversation_persona_id,
    _parameter_names,
    resolve_current_persona,
)
from conftest import (
    DummyConversation,
    DummyConversationManager,
    DummyPersonaManager,
    DummyPersonaManagerNew,
)


@pytest.fixture(autouse=True)
def _clear_probe_cache():
    """每个用例独立探测，避免 lru_cache 把 monkeypatch 结果带进下一个用例。"""
    _parameter_names.cache_clear()
    yield
    _parameter_names.cache_clear()


class TestSignatureProbe:
    def test_detects_legacy_and_new(self):
        assert _accepts_conversation_persona_id(DummyPersonaManager()) is True
        assert _accepts_conversation_persona_id(DummyPersonaManagerNew()) is False

    def test_cache_is_per_function_not_global(self):
        """两个替身类交替探测，结果不得串味。"""
        assert _accepts_conversation_persona_id(DummyPersonaManager()) is True
        assert _accepts_conversation_persona_id(DummyPersonaManagerNew()) is False
        assert _accepts_conversation_persona_id(DummyPersonaManager()) is True

    def test_unparseable_signature_falls_back_to_new(self, monkeypatch):
        """签名不可解析时按新版调用，不因探测异常中断人格解析。"""

        def _boom(_):
            raise ValueError("no signature")

        monkeypatch.setattr(inspect, "signature", _boom)
        assert _accepts_conversation_persona_id(DummyPersonaManager()) is False


class TestResolveCurrentPersona:
    async def test_legacy_passes_conversation_persona_id(self):
        """旧版：传第三参数，读 conversation.persona_id，4 元组取前两项。"""
        mgr = DummyPersonaManager(
            persona={"prompt": "温柔"},
            persona_id="p-legacy",
        )
        conv_mgr = DummyConversationManager(
            conversation=DummyConversation(persona_id="conv-persona")
        )

        persona_id, persona = await resolve_current_persona(
            persona_mgr=mgr,
            umo="platform:g:1001",
            platform_name="aiocqhttp",
            conv_mgr=conv_mgr,
        )

        assert persona_id == "p-legacy"
        assert persona == {"prompt": "温柔"}
        assert mgr.last_kwargs["conversation_persona_id"] == "conv-persona"
        assert mgr.last_kwargs["umo"] == "platform:g:1001"
        assert mgr.last_kwargs["platform_name"] == "aiocqhttp"

    async def test_new_omits_conversation_persona_id_and_skips_conv_mgr(self):
        """新版：不传第三参数；conv_mgr 是投毒对象，一旦被碰就炸。"""

        class ExplodingConvMgr:
            def __getattribute__(self, name):
                raise AssertionError(f"新版路径不应访问 conversation manager: {name}")

        mgr = DummyPersonaManagerNew(
            persona={"prompt": "冷静"},
            persona_id="p-new",
        )

        persona_id, persona = await resolve_current_persona(
            persona_mgr=mgr,
            umo="platform:g:1001",
            platform_name="aiocqhttp",
            conv_mgr=ExplodingConvMgr(),
        )

        assert persona_id == "p-new"
        assert persona == {"prompt": "冷静"}
        assert mgr.last_kwargs == {
            "umo": "platform:g:1001",
            "platform_name": "aiocqhttp",
        }

    async def test_legacy_without_conv_mgr_passes_none(self):
        """旧版路径下 conv_mgr 未就绪时，第三参数为 None 而非抛 AttributeError。"""
        mgr = DummyPersonaManager(persona_id="p-legacy")
        persona_id, _ = await resolve_current_persona(
            persona_mgr=mgr,
            umo="u",
            platform_name="p",
            conv_mgr=None,
        )
        assert persona_id == "p-legacy"
        assert mgr.last_kwargs["conversation_persona_id"] is None

    async def test_legacy_without_conversation_yields_none_id(self):
        """旧版对话为空时同样传 None。"""
        mgr = DummyPersonaManager(persona_id="p-legacy")
        await resolve_current_persona(
            persona_mgr=mgr,
            umo="u",
            platform_name="p",
            conv_mgr=DummyConversationManager(conversation=None, conv_id=None),
        )
        assert mgr.last_kwargs["conversation_persona_id"] is None
