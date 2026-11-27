"""Fish Audio Drama 3 与公共请求层离线测试。"""

import json
from pathlib import Path

import pytest

from astrbot_plugin_tts_enhancer.providers import ProviderFactory
from astrbot_plugin_tts_enhancer.providers._fish_audio import FishAudioAdapter
from astrbot_plugin_tts_enhancer.providers.fish_audio_drama_3 import (
    FishAudioDrama3Adapter,
)
from astrbot_plugin_tts_enhancer.providers.fish_audio_s2 import FishAudioS2Adapter

KEY = "fish_audio_drama_3"
REPO_ROOT = Path(__file__).parents[1]


class _FakeResp:
    def __init__(self, content=b"\x00\x01" * 100, status=200):
        self._content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            from httpx import HTTPStatusError

            raise HTTPStatusError("err", request=None, response=self)

    @property
    def content(self):
        return self._content

    @property
    def text(self):
        return self._content.decode("utf-8", errors="replace")

    def json(self):
        return {"message": "boom", "reason": "test"}


class _FakeClient:
    def __init__(self, response=None):
        self.response = response or _FakeResp()
        self.last_kwargs = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, *args, **kwargs):
        self.last_kwargs = kwargs
        return self.response


def _mock_client(monkeypatch, response=None):
    client = _FakeClient(response)
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers._fish_audio.httpx.AsyncClient",
        lambda *args, **kwargs: client,
    )
    return client


def test_discovery_and_shared_base():
    ProviderFactory._discover_adapters()
    adapter = ProviderFactory.get_adapter({"__template_key": KEY})
    assert isinstance(adapter, FishAudioDrama3Adapter)
    assert isinstance(adapter, FishAudioAdapter)
    assert adapter.SUPPORTED_MODELS == ("drama-3",)
    assert isinstance(
        FishAudioS2Adapter({"__template_key": "fish_audio_s2"}), FishAudioAdapter
    )


def test_docs_and_tool_contract():
    adapter = FishAudioDrama3Adapter({"__template_key": KEY})
    assert "自然语言导演指令" in adapter.docs_content
    tool = adapter.get_tool_schema()
    assert tool.name == "tts_enhance"
    assert set(tool.parameters["properties"]) == {
        "text",
        "speed",
        "volume",
        "language",
    }
    assert adapter.validate_params({}) == (True, "")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("voice-a", "voice-a"),
        ("", None),
        (None, None),
    ],
)
def test_reference_id_resolution(raw, expected):
    adapter = FishAudioDrama3Adapter(
        {"__template_key": KEY, "reference_id": raw}
    )
    assert adapter._resolve_reference_id(None, adapter.entry) == expected


def test_preview_voice_overrides_configured_reference():
    adapter = FishAudioDrama3Adapter(
        {"__template_key": KEY, "api_key": "test-key", "reference_id": "voice-a"}
    )
    assert adapter._resolve_reference_id("preview", adapter.entry) == "preview"


def test_prompt_and_docs_omit_speaker_orchestration():
    adapter = FishAudioDrama3Adapter({"__template_key": KEY})
    schema = adapter.get_tool_schema()
    prompt = adapter.get_subagent_system_prompt()
    combined = (
        adapter.docs_content
        + prompt
        + json.dumps(schema.parameters, ensure_ascii=False)
    )
    assert "speaker" not in combined.lower()
    assert "phoneme" not in combined.lower()
    assert "音素" not in combined
    assert "多角色" not in combined
    assert "超出由适配器裁剪" not in combined
    assert "-20~20" not in combined
    assert "≤35" not in combined
    assert "UTF-8 字节数计费" not in combined
    assert "指令可以与台词同语言" in adapter.docs_content
    assert "<french>" in combined
    assert "实验性" in prompt
    for tag in (
        "<whisper>",
        "<emphasis>",
        "<soft>",
        "<fast>",
        "<slow>",
        "<stress>",
        "<forceful>",
    ):
        assert tag in schema.description
    for tag in (
        "<french>",
        "<spanish>",
        "<german>",
        "<japanese>",
        "<chinese>",
        "<korean>",
        "<italian>",
    ):
        assert tag in schema.description


@pytest.mark.asyncio
async def test_drama3_request_uses_fixed_model_and_single_reference(
    tmp_path, monkeypatch
):
    adapter = FishAudioDrama3Adapter(
        {
            "__template_key": KEY,
            "api_key": "test-key",
            "reference_id": "voice-a",
            "normalize_loudness": True,
        }
    )
    config = dict(adapter.entry, _data_dir=str(tmp_path))
    client = _mock_client(monkeypatch)
    text = "[slow, dangerously quiet]<whisper>Tell me more.</whisper>[short pause]"

    path = await adapter.call_api(
        text=text,
        raw_params={"text": text, "speed": 1.1, "volume": -3},
        config=config,
    )

    assert path and path.endswith(".mp3")
    assert client.last_kwargs["headers"]["model"] == "drama-3"
    payload = client.last_kwargs["json"]
    assert payload["text"] == text
    assert payload["reference_id"] == "voice-a"
    assert payload["prosody"] == {"speed": 1.1, "volume": -3.0}
    assert "normalize_loudness" not in payload["prosody"]


@pytest.mark.asyncio
@pytest.mark.parametrize("configured_model", [None, "bogus", "s2.1-pro"])
async def test_model_is_hardcoded_independently_of_config(
    tmp_path, monkeypatch, configured_model
):
    entry = {"__template_key": KEY, "api_key": "test-key"}
    if configured_model is not None:
        entry["model"] = configured_model
    adapter = FishAudioDrama3Adapter(entry)
    client = _mock_client(monkeypatch)
    await adapter.call_api(
        text="hi",
        raw_params={},
        config=dict(adapter.entry, _data_dir=str(tmp_path)),
    )
    assert client.last_kwargs["headers"]["model"] == "drama-3"


def test_config_template_and_i18n():
    schema = json.loads((REPO_ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    template = schema["providers"]["templates"][KEY]
    assert template["items"]["model"]["options"] == ["drama-3"]
    assert "固定使用 drama-3" in template["items"]["model"]["hint"]
    assert "逗号分隔" not in template["items"]["reference_id"]["hint"]
    assert "speaker" not in template["items"]["reference_id"]["hint"].lower()
    assert "normalize_loudness" not in template["items"]

    for language in ("zh-CN", "en-US", "ja-JP", "ru-RU"):
        data = json.loads(
            (REPO_ROOT / ".astrbot-plugin/i18n" / f"{language}.json").read_text(
                encoding="utf-8"
            )
        )
        localized = data["config"]["providers"]["templates"][KEY]
        assert localized["name"] == "Fish Audio Drama 3"
        assert set(localized) == set(template["items"]) | {"name", "hint"}
