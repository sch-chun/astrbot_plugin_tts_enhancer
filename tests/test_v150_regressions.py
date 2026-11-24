"""v1.5.0 跨供应商回归用例（语义 / 契约兜底）。

覆盖三组此前散落在各适配器里的边界语义：

- **百炼标准 TTS 的 seed**（P2-5 / P2-7）：``0``~``65535`` 固定下发；
  ``-1`` / 缺键 / 越界 / 非法值 → 本地随机一个 ``0``~``65535``；
  字符串数字经 ``_as_int`` 归一（此前字符串会原样下发，且 ``-1`` 时根本不下发，
  服务端退化为固定默认种子，导致同一文本每次结果恒定）。
- **适配器模块唯一实例**：工厂动态发现不得复制模块级状态。
- **tts_enhance 运行时契约**（P2-8）：未声明字段被丢弃，且不进入校验流程。
"""

import json
import sys

import pytest

from astrbot_plugin_tts_enhancer.providers import ProviderFactory
from astrbot_plugin_tts_enhancer.providers._bailian_speech_synthesizer import (
    BailianSpeechSynthesizerAdapter,
)
from astrbot_plugin_tts_enhancer.providers.bailian_qwen_audio_3_0_tts import (
    BailianQwenAudio3_0TTSAdapter,
)
from astrbot_plugin_tts_enhancer.providers.base import TTSProviderAdapter


# ———————————————————————— seed 语义 ————————————————————————


class TestBailianSeedSemantics:
    """百炼 Speech Synthesizer 的 seed 归一规则。"""

    @pytest.fixture
    def adapter(self):
        return BailianSpeechSynthesizerAdapter(
            {"__template_key": "bailian_qwen_audio_3_0_tts"}
        )

    @pytest.mark.parametrize("raw", [0, 1, 42, 65535])
    def test_fixed_seed_passthrough(self, adapter, raw):
        """合法区间内的值原样保留（固定种子语义）。"""
        assert adapter._resolve_seed(raw) == raw

    def test_string_number_is_normalized(self, adapter):
        """字符串数字走 _as_int 归一，不再以字符串形式下发。"""
        assert adapter._resolve_seed("123") == 123

    @pytest.mark.parametrize(
        "raw", [-1, "-1", None, 65536, 999999, "abc", True, False]
    )
    def test_invalid_or_out_of_range_is_randomized(self, adapter, raw):
        """-1 / 缺键 / 越界 / 非法值 → 本地随机 0~65535。"""
        seed = adapter._resolve_seed(raw)
        assert isinstance(seed, int)
        assert 0 <= seed <= 65535


class _FakeResponse:
    def __init__(self, payload=None, content=b""):
        self._payload = payload or {}
        self.content = content
        self.text = ""

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _FakeClient:
    """记录请求体的 httpx.AsyncClient 替身。"""

    def __init__(self, payload):
        self._payload = payload
        self.post_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return _FakeResponse(self._payload)

    async def get(self, url, **kwargs):
        return _FakeResponse({}, content=b"audio")


async def _bailian_payload(monkeypatch, **config_overrides) -> dict:
    """跑一次百炼合成，返回实际下发的请求体 input 段。"""
    import httpx

    from astrbot_plugin_tts_enhancer.providers import (
        _bailian_speech_synthesizer as bailian_module,
    )

    client = _FakeClient({"output": {"audio": {"url": "https://example.test/a.wav"}}})
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: client)
    monkeypatch.setattr(
        bailian_module, "save_audio_bytes", lambda *a, **k: "/tmp/out.wav"
    )

    adapter = BailianQwenAudio3_0TTSAdapter(
        {"__template_key": "bailian_qwen_audio_3_0_tts"}
    )
    config = {
        "api_key": "sk-test",
        "workspace_id": "ws-test",
        "voice": "longanhuan_v3.6",
        "model": "flash",
        "format": "wav",
        "sample_rate": 24000,
        "_data_dir": "/tmp/tts-enhancer-test",
    }
    config.update(config_overrides)
    result = await adapter.call_api(
        text="测试文本", raw_params={"text": "测试文本"}, config=config
    )
    assert result == "/tmp/out.wav"
    return client.post_calls[0][1]["json"]


class TestBailianSeedInPayload:
    """seed 必须真正出现在请求体里，且语义与配置页说明一致。"""

    async def test_seed_always_present(self, monkeypatch):
        payload = await _bailian_payload(monkeypatch)
        assert 0 <= payload["input"]["seed"] <= 65535

    async def test_fixed_seed_is_sent(self, monkeypatch):
        payload = await _bailian_payload(monkeypatch, seed=123)
        assert payload["input"]["seed"] == 123

    async def test_string_seed_is_normalized(self, monkeypatch):
        payload = await _bailian_payload(monkeypatch, seed="321")
        assert payload["input"]["seed"] == 321

    async def test_minus_one_is_randomized(self, monkeypatch):
        payload = await _bailian_payload(monkeypatch, seed=-1)
        assert 0 <= payload["input"]["seed"] <= 65535

    async def test_missing_seed_is_randomized(self, monkeypatch):
        payload = await _bailian_payload(monkeypatch)
        assert 0 <= payload["input"]["seed"] <= 65535


# ———————————————————————— 模块唯一实例 ————————————————————————


def test_provider_factory_uses_single_module_instance():
    """工厂动态发现不得复制适配器模块（模块级状态必须共享）。

    此前 ``ProviderFactory`` 用 ``spec_from_file_location`` 动态执行模块，
    会另起一份模块对象：Eleven 的 ``_CATALOG_CACHE`` 等模块级状态被复制成两份，
    工厂实例与常规 import 的模块互不可见。
    """
    from astrbot_plugin_tts_enhancer.providers import elevenlabs_v4

    ProviderFactory._discover_adapters()
    cls = ProviderFactory._adapters["elevenlabs_v4"]
    assert cls is elevenlabs_v4.ElevenLabsV4Adapter
    assert sys.modules[cls.__module__] is elevenlabs_v4
    assert (
        cls._get_catalog.__globals__["_CATALOG_CACHE"]
        is elevenlabs_v4._CATALOG_CACHE
    )


# ———————————————————————— 运行时契约 ————————————————————————


class _DemoAdapter(TTSProviderAdapter):
    """最小可控适配器：主字段 ``text`` + 一个已声明额外字段 ``instruction``。"""

    TOOL_PROMPT_FIELD = "text"
    TOOL_EXTRA_FIELDS = frozenset({"instruction"})

    def get_subagent_system_prompt(self) -> str:
        return "demo"

    def get_tool_schema(self):
        return self.build_enhance_tool(
            "demo",
            {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "instruction": {"type": "string"},
                },
                "required": ["text"],
            },
        )

    async def call_api(self, text, raw_params, config, voice_id=None):
        return ""


class TestRuntimeToolContract:
    """``_handle_enhance_tool`` 按 ``TOOL_PROMPT_FIELD ∪ tool_extra_fields()`` 过滤。"""

    async def test_undeclared_field_is_dropped(self):
        adapter = _DemoAdapter({"__template_key": "demo"})
        result = await adapter._handle_enhance_tool(
            text="hi", instruction="soft", junk=1
        )
        assert result.isError is False
        payload = json.loads(result.content[0].text)
        assert payload == {"text": "hi", "instruction": "soft"}

    async def test_undeclared_field_never_reaches_validation(self):
        """未声明字段连校验都不进入（否则非法值会把整轮工具调用判为失败）。"""
        adapter = _DemoAdapter({"__template_key": "demo"})
        seen: dict = {}

        def spy(params):
            seen.update(params)
            return True, ""

        adapter.validate_params = spy
        await adapter._handle_enhance_tool(text="hi", junk=1)
        assert "junk" not in seen
        assert seen.get("text") == "hi"

    async def test_prompt_field_alias_is_allowed(self):
        """生成式适配器用 ``text_prompt`` 作主字段时同样生效。"""

        class _PromptDemo(_DemoAdapter):
            TOOL_PROMPT_FIELD = "text_prompt"

        adapter = _PromptDemo({"__template_key": "demo"})
        result = await adapter._handle_enhance_tool(text_prompt="hi", text="no")
        assert result.isError is False
        payload = json.loads(result.content[0].text)
        assert payload == {"text_prompt": "hi"}
