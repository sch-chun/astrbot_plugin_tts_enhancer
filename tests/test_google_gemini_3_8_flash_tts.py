"""Google Gemini 3.8 Flash TTS 适配器离线测试（不依赖网络）。

验证：自动发现、文档齐备、工具契约、参数清洗、PCM→WAV 封装，
以及 call_api 在 httpx 被 mock 时的行为。
"""

import base64
import struct

import pytest
from astrbot_plugin_tts_enhancer.providers import ProviderFactory
from astrbot_plugin_tts_enhancer.providers.base import TTSProviderAdapter
from astrbot_plugin_tts_enhancer.providers.google_gemini_3_8_flash_tts import (
    GoogleGemini3_8FlashTTSAdapter,
)

KEY = "google_gemini_3_8_flash_tts"
ENTRY = {"__template_key": KEY, "api_key": "test-key", "voice_id": "Kore"}


def _make_adapter(**overrides):
    entry = dict(ENTRY, **overrides)
    return GoogleGemini3_8FlashTTSAdapter(entry)


# ---------- 发现与契约 ----------


def test_discovery():
    ProviderFactory._discover_adapters()
    assert KEY in ProviderFactory._adapters
    # 工厂通过 importlib 动态加载，与测试内 import 的同类名模块不是同一对象，
    # 故按基类 + 类名断言，而非按类身份（issubclass 到具体导入类）比对。
    assert issubclass(ProviderFactory._adapters[KEY], TTSProviderAdapter)
    assert ProviderFactory._adapters[KEY].__name__ == "GoogleGemini3_8FlashTTSAdapter"


def test_docs_loaded():
    adapter = _make_adapter()
    assert adapter.docs_content.strip(), (
        "缺少能力文档 docs/google_gemini_3_8_flash_tts.md"
    )


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


def test_sanitize_only_text_style():
    adapter = _make_adapter()
    out = adapter.sanitize_params({"text": "hi", "style": "温柔地", "speed": 1.2})
    assert out == {"text": "hi", "style": "温柔地"}


# ---------- 纯逻辑 ----------


def test_pcm_to_wav_header():
    pcm = b"\x00\x01" * 100  # 100 个 16bit 样本
    wav = GoogleGemini3_8FlashTTSAdapter.pcm16le_to_wav_bytes(pcm, sample_rate=24000)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    # data chunk size = len(pcm)
    data_size = struct.unpack("<I", wav[40:44])[0]
    assert data_size == len(pcm)
    # 总字节 = 44 头 + pcm
    assert len(wav) == 44 + len(pcm)


def test_build_speech_config():
    adapter = _make_adapter()
    assert adapter._build_speech_config({}, "Kore") == [{"voice": "Kore"}]
    assert adapter._build_speech_config({}, "voice_abc") == [{"voice": "voice_abc"}]


def test_http_kwargs_injects_proxy():
    # 未配置代理：仅 timeout
    adapter = _make_adapter()
    assert adapter._http_kwargs(60) == {"timeout": 60}
    # 配置代理：注入 proxy 键
    adapter = _make_adapter(proxy="http://127.0.0.1:7890")
    assert adapter._http_kwargs(30) == {"timeout": 30, "proxy": "http://127.0.0.1:7890"}
    # 空白代理视为未配置
    adapter = _make_adapter(proxy="   ")
    assert adapter._http_kwargs(10) == {"timeout": 10}


def test_parse_sample_rate():
    assert (
        GoogleGemini3_8FlashTTSAdapter._parse_sample_rate(
            "audio/L16;codec=pcm;rate=24000"
        )
        == 24000
    )
    assert (
        GoogleGemini3_8FlashTTSAdapter._parse_sample_rate("audio/wav") == 24000
    )  # 默认


# ---------- call_api (mock httpx) ----------


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        return self._resp

    async def get(self, *a, **k):
        return self._resp

    async def delete(self, *a, **k):
        return self._resp


def _fake_pcm_response():
    pcm = b"\x00\x01" * 2000
    b64 = base64.b64encode(pcm).decode()
    payload = {
        "steps": [
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "audio",
                        "mimeType": "audio/L16;codec=pcm;rate=24000",
                        "data": b64,
                    }
                ],
            }
        ]
    }
    return _FakeResp(payload)


@pytest.mark.asyncio
async def test_call_api_saves_wav(tmp_path, monkeypatch):
    adapter = _make_adapter()
    entry = dict(ENTRY, _data_dir=str(tmp_path))
    fake = _FakeClient(_fake_pcm_response())
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.google_gemini_3_8_flash_tts.httpx.AsyncClient",
        lambda *a, **k: fake,
    )
    path = await adapter.call_api(text="你好", raw_params={}, config=entry)
    assert path and path.endswith(".wav")
    import os

    assert os.path.exists(path)
    with open(path, "rb") as f:
        assert f.read(4) == b"RIFF"


@pytest.mark.asyncio
async def test_call_api_missing_key_returns_empty():
    adapter = GoogleGemini3_8FlashTTSAdapter({"__template_key": KEY})
    path = await adapter.call_api(
        text="hi", raw_params={}, config={"_data_dir": "/tmp/x"}
    )
    assert path == ""
