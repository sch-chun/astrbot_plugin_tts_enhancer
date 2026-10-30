"""Fish Audio (S2) TTS 适配器离线测试（不依赖网络）。

验证：自动发现、文档齐备、工具契约、参数清洗、prosody 构造，
以及 call_api 在 httpx 被 mock 时的行为（含发音词典、格式相关编码参数）。
"""

import os

import pytest
from astrbot_plugin_tts_enhancer.providers import ProviderFactory
from astrbot_plugin_tts_enhancer.providers.base import TTSProviderAdapter
from astrbot_plugin_tts_enhancer.providers.fish_audio_s2 import (
    FishAudioS2Adapter,
)

KEY = "fish_audio_s2"
ENTRY = {"__template_key": KEY, "api_key": "test-key", "reference_id": "voice-abc"}


def _make_adapter(**overrides):
    entry = dict(ENTRY, **overrides)
    return FishAudioS2Adapter(entry)


# ---------- 发现与契约 ----------


def test_discovery():
    ProviderFactory._discover_adapters()
    assert KEY in ProviderFactory._adapters
    assert issubclass(ProviderFactory._adapters[KEY], TTSProviderAdapter)
    assert ProviderFactory._adapters[KEY].__name__ == "FishAudioS2Adapter"


def test_docs_loaded():
    adapter = _make_adapter()
    assert adapter.docs_content.strip(), "缺少能力文档 docs/fish_audio_s2.md"


def test_tool_schema_contract():
    adapter = _make_adapter()
    tool = adapter.get_tool_schema()
    assert tool is not None
    assert tool.name == "tts_enhance"
    assert "text" in tool.parameters["properties"]
    assert "text" in tool.parameters["required"]


def test_system_prompt_nonempty():
    adapter = _make_adapter()
    assert adapter.get_subagent_system_prompt().strip()


def test_validate_accepts_empty():
    adapter = _make_adapter()
    assert adapter.validate_params({}) == (True, "")


def test_validate_rejects_bad_speed():
    adapter = _make_adapter()
    assert adapter.validate_params({"speed": 5}) == (False, "speed 必须在 0.5~2.0 之间")
    assert adapter.validate_params({"speed": 1.0}) == (True, "")


def test_sanitize_only_allowed_keys():
    adapter = _make_adapter()
    out = adapter.sanitize_params(
        {"text": "hi", "speed": 1.2, "volume": -3, "language": "en", "junk": 9}
    )
    assert out == {"text": "hi", "speed": 1.2, "volume": -3, "language": "en"}


def test_sanitize_drops_out_of_range_speed():
    adapter = _make_adapter()
    out = adapter.sanitize_params({"text": "hi", "speed": 9})
    assert out == {"text": "hi"}


# ---------- 纯逻辑 ----------


def test_http_kwargs_injects_proxy():
    adapter = _make_adapter()
    assert adapter._http_kwargs(60) == {"timeout": 60}
    adapter = _make_adapter(proxy="http://127.0.0.1:7890")
    assert adapter._http_kwargs(30) == {"timeout": 30, "proxy": "http://127.0.0.1:7890"}
    adapter = _make_adapter(proxy="   ")
    assert adapter._http_kwargs(10) == {"timeout": 10}


@pytest.mark.asyncio
async def test_model_fallback_for_unknown(tmp_path, monkeypatch):
    # 未知模型应回退到 s2.1-pro-free（FISH_AUDIO_MODELS[1]）
    adapter = _make_adapter(model="bogus")
    entry = dict(adapter.entry, _data_dir=str(tmp_path))
    fake = _FakeClient(_FakeResp(b"\x00\x01" * 100))
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.fish_audio_s2.httpx.AsyncClient",
        lambda *a, **k: fake,
    )
    path = await adapter.call_api(text="hi", raw_params={}, config=entry)
    assert path
    assert fake.last_kwargs["headers"]["model"] == "s2.1-pro-free"


# ---------- call_api (mock httpx) ----------


class _FakeResp:
    def __init__(self, content, status=200):
        self._content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            from httpx import HTTPStatusError

            raise HTTPStatusError("err", request=None, response=self)

    @property
    def content(self):
        return self._content

    def json(self):
        return {"message": "boom", "reason": "test"}


class _FakeClient:
    def __init__(self, resp):
        self._resp = resp
        self.last_kwargs = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        self.last_kwargs = k
        return self._resp


@pytest.mark.asyncio
async def test_call_api_saves_audio(tmp_path, monkeypatch):
    adapter = _make_adapter()
    entry = dict(ENTRY, _data_dir=str(tmp_path))
    fake = _FakeClient(_FakeResp(b"\x00\x01" * 2000))
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.fish_audio_s2.httpx.AsyncClient",
        lambda *a, **k: fake,
    )
    path = await adapter.call_api(
        text="你好", raw_params={"text": "你好", "speed": 1.2}, config=entry
    )
    assert path and path.endswith(".mp3")
    assert os.path.exists(path)
    # 校验 model 头与 Bearer 鉴权
    headers = fake.last_kwargs["headers"]
    assert headers["Authorization"] == "Bearer test-key"
    assert headers["model"] == "s2.1-pro-free"
    # 校验 prosody / speed 进入请求体
    payload = fake.last_kwargs["json"]
    assert payload["text"] == "你好"
    assert payload["format"] == "mp3"
    assert payload["prosody"]["speed"] == 1.2
    assert payload["reference_id"] == "voice-abc"
    assert payload["mp3_bitrate"] == 128


@pytest.mark.asyncio
async def test_call_api_missing_key_returns_empty():
    adapter = FishAudioS2Adapter({"__template_key": KEY})
    path = await adapter.call_api(
        text="hi", raw_params={}, config={"_data_dir": "/tmp/x"}
    )
    assert path == ""


@pytest.mark.asyncio
async def test_call_api_http_error_returns_empty(monkeypatch):
    adapter = _make_adapter()
    entry = dict(ENTRY, _data_dir="/tmp/x")
    fake = _FakeClient(_FakeResp(b"", status=402))
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.fish_audio_s2.httpx.AsyncClient",
        lambda *a, **k: fake,
    )
    path = await adapter.call_api(text="hi", raw_params={}, config=entry)
    assert path == ""


@pytest.mark.asyncio
async def test_call_api_pronunciation_dictionary(tmp_path, monkeypatch):
    adapter = _make_adapter(
        use_pronunciation_dictionary=True,
        pronunciation_dictionary_id="dict-1",
        pronunciation_dictionary_version="v2",
    )
    entry = dict(adapter.entry, _data_dir=str(tmp_path))
    fake = _FakeClient(_FakeResp(b"\x00\x01" * 100))
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.fish_audio_s2.httpx.AsyncClient",
        lambda *a, **k: fake,
    )
    path = await adapter.call_api(text="hi", raw_params={}, config=entry)
    assert path
    payload = fake.last_kwargs["json"]
    assert payload["pronunciation_dictionary"] == [{"id": "dict-1", "version": "v2"}]


@pytest.mark.asyncio
async def test_call_api_opus_uses_opus_bitrate(tmp_path, monkeypatch):
    adapter = _make_adapter()
    entry = dict(adapter.entry, _data_dir=str(tmp_path), format="opus")
    fake = _FakeClient(_FakeResp(b"\x00\x01" * 100))
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.fish_audio_s2.httpx.AsyncClient",
        lambda *a, **k: fake,
    )
    path = await adapter.call_api(text="hi", raw_params={}, config=entry)
    assert path and path.endswith(".opus")
    payload = fake.last_kwargs["json"]
    assert "opus_bitrate" in payload
    assert "mp3_bitrate" not in payload
