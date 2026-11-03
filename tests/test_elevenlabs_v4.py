"""ElevenLabs v4 适配器离线测试（不依赖网络）。

验证：自动发现、文档齐备、工具契约、参数清洗、output_format 组合、
audio_effects catalog 拉取（mock）、audio_effects 组装，以及 call_api 在
httpx 被 mock 时的行为。
"""

import os

import pytest
from astrbot_plugin_tts_enhancer.providers import (
    ProviderFactory,
    elevenlabs_v4,
)
from astrbot_plugin_tts_enhancer.providers.base import TTSProviderAdapter
from astrbot_plugin_tts_enhancer.providers.elevenlabs_v4 import (
    ElevenLabsV4Adapter,
)

KEY = "elevenlabs_v4"
ENTRY = {
    "__template_key": KEY,
    "api_key": "test-key",
    "voice_id": "21m00Tcm4TlvDq8ikWAM",
}


@pytest.fixture
def catalog_clean():
    """隔离类级 catalog 缓存，避免跨测试污染（module 级 dict）。"""
    elevenlabs_v4._CATALOG_CACHE.clear()
    elevenlabs_v4._CATALOG_INFLIGHT.clear()
    yield
    elevenlabs_v4._CATALOG_CACHE.clear()
    elevenlabs_v4._CATALOG_INFLIGHT.clear()


def _make_adapter(**overrides):
    entry = dict(ENTRY, **overrides)
    return ElevenLabsV4Adapter(entry)


# ---------- 发现与契约 ----------


def test_discovery():
    ProviderFactory._discover_adapters()
    assert KEY in ProviderFactory._adapters
    assert issubclass(ProviderFactory._adapters[KEY], TTSProviderAdapter)
    assert ProviderFactory._adapters[KEY].__name__ == "ElevenLabsV4Adapter"


def test_docs_loaded():
    adapter = _make_adapter()
    assert adapter.docs_content.strip(), "缺少能力文档 docs/elevenlabs_v4.md"


def test_tool_schema_contract():
    adapter = _make_adapter()
    tool = adapter.get_tool_schema()
    assert tool is not None
    assert tool.name == "tts_enhance"
    assert "text" in tool.parameters["properties"]
    assert "text" in tool.parameters["required"]


def test_language_code_is_free_string():
    # 官方 spec：language_code 是自由文本（无 enum），模型不支持的代码会被静默忽略
    props = _make_adapter().get_tool_schema().parameters["properties"]
    lang = props["language_code"]
    assert lang["type"] == "string"
    assert "enum" not in lang
    assert "静默忽略" in lang["description"]


def test_tool_schema_without_audio_effects_has_no_effects_fields():
    # use_audio_effects 默认 False
    adapter = _make_adapter()
    props = adapter.get_tool_schema().parameters["properties"]
    assert "filter_preset_id" not in props
    assert "environment_id" not in props
    assert "pan" not in props


def test_tool_schema_with_audio_effects_injects_dynamic_enums(monkeypatch):
    # 开启后应从缓存 catalog 动态注入效果字段，并带上实时 ID 枚举
    adapter = _make_adapter(use_audio_effects=True)
    monkeypatch.setattr(
        adapter,
        "_get_catalog",
        lambda: {
            "filter_presets": ["phone", "old_radio"],
            "environments": ["hall"],
            "background_noises": ["cafe"],
        },
    )
    props = adapter.get_tool_schema().parameters["properties"]
    assert props["filter_preset_id"]["enum"] == ["phone", "old_radio"]
    assert props["environment_id"]["enum"] == ["hall"]
    assert props["background_noise_id"]["enum"] == ["cafe"]
    assert props["distance"]["minimum"] == 0 and props["distance"]["maximum"] == 1
    assert props["send_level"]["minimum"] == 0 and props["send_level"]["maximum"] == 1
    assert props["pan"]["minimum"] == -1 and props["pan"]["maximum"] == 1


def test_tool_schema_with_audio_effects_uses_static_fallback(monkeypatch):
    # 缓存未命中（预热前/失败）时，_get_catalog 返回静态兜底枚举，字段仍出现
    adapter = _make_adapter(use_audio_effects=True)
    monkeypatch.setattr(
        adapter,
        "_get_catalog",
        lambda: elevenlabs_v4.STATIC_FALLBACK_CATALOG,
    )
    props = adapter.get_tool_schema().parameters["properties"]
    assert props["filter_preset_id"]["enum"] == ["phone", "old_radio", "robot"]
    assert props["environment_id"]["enum"] == ["small_room", "hall", "tunnel"]
    assert props["background_noise_id"]["enum"] == ["cafe", "keyboard", "city"]


def test_system_prompt_nonempty():
    adapter = _make_adapter()
    assert adapter.get_subagent_system_prompt().strip()


def test_system_prompt_without_audio_effects_has_no_fx_block():
    # 默认关闭时不应注入 audio_effects 动态指引（SubAgent 看不到配置）
    adapter = _make_adapter()
    prompt = adapter.get_subagent_system_prompt()
    assert "音频效果（audio_effects）" not in prompt
    assert "filter_preset_id（音色滤镜）" not in prompt


def test_system_prompt_with_audio_effects_injects_real_ids(monkeypatch):
    # 开启且有 catalog 时，用实时 ID 动态拼接指引，且不提及「配置」
    adapter = _make_adapter(use_audio_effects=True)
    monkeypatch.setattr(
        adapter,
        "_get_catalog",
        lambda: {
            "filter_presets": ["phone", "old_radio"],
            "environments": ["hall"],
            "background_noises": ["cafe"],
        },
    )
    prompt = adapter.get_subagent_system_prompt()
    assert "音频效果（audio_effects）" in prompt
    assert "phone" in prompt and "old_radio" in prompt
    assert "hall" in prompt and "cafe" in prompt
    assert "配置" not in prompt


def test_system_prompt_with_audio_effects_uses_static_fallback(monkeypatch):
    # 缓存未命中时，用静态兜底枚举拼接指引（不空壳、不报错）
    adapter = _make_adapter(use_audio_effects=True)
    monkeypatch.setattr(
        adapter,
        "_get_catalog",
        lambda: elevenlabs_v4.STATIC_FALLBACK_CATALOG,
    )
    prompt = adapter.get_subagent_system_prompt()
    assert "音频效果（audio_effects）" in prompt
    assert "phone" in prompt and "hall" in prompt


# ---------- 参数校验 / 清洗 ----------


def test_validate_rejects_bad_pan():
    adapter = _make_adapter()
    ok, err = adapter.validate_params({"pan": 5})
    assert ok is False
    assert "pan" in err


def test_validate_accepts_empty():
    adapter = _make_adapter()
    assert adapter.validate_params({}) == (True, "")


def test_sanitize_only_text_and_effects():
    adapter = _make_adapter()
    out = adapter.sanitize_params(
        {"text": "hi", "environment_id": "hall", "pan": 0.5, "junk": 1}
    )
    assert out == {"text": "hi", "environment_id": "hall", "pan": 0.5}


def test_sanitize_keeps_language_code():
    adapter = _make_adapter()
    out = adapter.sanitize_params({"text": "hi", "language_code": "ja"})
    assert out == {"text": "hi", "language_code": "ja"}


def test_validate_rejects_bad_language_code():
    adapter = _make_adapter()
    ok, err = adapter.validate_params({"language_code": 5})
    assert ok is False
    assert "language_code" in err


# ---------- output_format 组合 ----------


def test_compose_output_format_mp3():
    assert (
        _make_adapter()._compose_output_format(
            {"output_codec": "mp3", "mp3_sample_rate": 44100, "mp3_bitrate": 128}
        )
        == "mp3_44100_128"
    )


def test_compose_output_format_wav():
    assert (
        _make_adapter()._compose_output_format(
            {"output_codec": "wav", "wav_sample_rate": 24000}
        )
        == "wav_24000"
    )


def test_compose_output_format_opus():
    assert (
        _make_adapter()._compose_output_format(
            {"output_codec": "opus", "opus_bitrate": 64}
        )
        == "opus_48000_64"
    )


def test_compose_output_format_default():
    assert _make_adapter()._compose_output_format({}) == "mp3_44100_128"


def test_compose_output_format_dirty_fallback():
    # 非法采样率/码率回落到白名单内的值
    assert (
        _make_adapter()._compose_output_format(
            {"output_codec": "mp3", "mp3_sample_rate": 99999, "mp3_bitrate": 7}
        )
        == "mp3_44100_128"
    )


def test_compose_output_format_mp3_low_sample_rate_ignores_bitrate_selector():
    # 22050 / 24000 的码率由采样率固定（UI 不开放位深选项），忽略 mp3_bitrate
    assert (
        _make_adapter()._compose_output_format(
            {"output_codec": "mp3", "mp3_sample_rate": 22050, "mp3_bitrate": 128}
        )
        == "mp3_22050_32"
    )
    assert (
        _make_adapter()._compose_output_format(
            {"output_codec": "mp3", "mp3_sample_rate": 24000, "mp3_bitrate": 128}
        )
        == "mp3_24000_48"
    )


def test_compose_output_format_mp3_44100_uses_selected_bitrate():
    # 44100 才开放位深选项，使用所选码率
    assert (
        _make_adapter()._compose_output_format(
            {"output_codec": "mp3", "mp3_sample_rate": 44100, "mp3_bitrate": 64}
        )
        == "mp3_44100_64"
    )
    # 码率越界时回落到 128（UI 不会产生）
    assert (
        _make_adapter()._compose_output_format(
            {"output_codec": "mp3", "mp3_sample_rate": 44100, "mp3_bitrate": 160}
        )
        == "mp3_44100_128"
    )


# ---------- http kwargs ----------


def test_http_kwargs_injects_proxy():
    assert _make_adapter()._http_kwargs(60) == {"timeout": 60}
    assert _make_adapter(proxy="http://127.0.0.1:7890")._http_kwargs(30) == {
        "timeout": 30,
        "proxy": "http://127.0.0.1:7890",
    }


# ---------- audio_effects catalog 拉取 ----------


class _FakeResp:
    def __init__(self, payload):
        self.content = payload
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


CATALOG = {
    "filter_presets": [
        {"filter_preset_id": "phone"},
        {"filter_preset_id": "old_radio"},
    ],
    "environments": [{"environment_id": "hall"}],
    "background_noises": [{"background_noise_id": "cafe", "description": None}],
}


class _FakeAsyncClient:
    """mock httpx.AsyncClient：get 返回同步 _FakeResp 的异步版本。"""

    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **k):
        return self._resp


def test_get_catalog_returns_static_fallback_when_unwarmed(catalog_clean):
    # 缓存为空时，_get_catalog 不发起网络、直接返回静态兜底（非空）
    adapter = _make_adapter()
    assert adapter._get_catalog() == elevenlabs_v4.STATIC_FALLBACK_CATALOG


def test_fetch_catalog_success_populates_class_cache(catalog_clean, monkeypatch):
    adapter = _make_adapter()
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.elevenlabs_v4.httpx.AsyncClient",
        lambda *a, **k: _FakeAsyncClient(_FakeResp(CATALOG)),
    )
    import asyncio

    asyncio.run(adapter.ensure_catalog_warm())
    # 类级缓存命中，_get_catalog 返回实时目录（不再是静态兜底）
    assert adapter._get_catalog() == {
        "filter_presets": ["phone", "old_radio"],
        "environments": ["hall"],
        "background_noises": ["cafe"],
    }


def test_fetch_catalog_failure_keeps_static_fallback(catalog_clean, monkeypatch):
    async def _boom_get(self, *a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(_FakeAsyncClient, "get", _boom_get)
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.elevenlabs_v4.httpx.AsyncClient",
        lambda *a, **k: _FakeAsyncClient(_FakeResp(CATALOG)),
    )
    import asyncio

    asyncio.run(_make_adapter().ensure_catalog_warm())
    # 失败不写缓存，_get_catalog 仍回退静态兜底
    assert _make_adapter()._get_catalog() == elevenlabs_v4.STATIC_FALLBACK_CATALOG


def test_fetch_catalog_missing_key_no_cache(catalog_clean):
    # 无 api_key 时 _fetch_catalog 直接返回、不写缓存
    import asyncio

    asyncio.run(_make_adapter(api_key="").ensure_catalog_warm())
    assert elevenlabs_v4._CATALOG_CACHE == {}


def test_fetch_catalog_malformed_keeps_static_fallback(catalog_clean, monkeypatch):
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.elevenlabs_v4.httpx.AsyncClient",
        lambda *a, **k: _FakeAsyncClient(_FakeResp({"unexpected": []})),
    )
    import asyncio

    asyncio.run(_make_adapter().ensure_catalog_warm())
    assert elevenlabs_v4._CATALOG_CACHE == {}
    assert _make_adapter()._get_catalog() == elevenlabs_v4.STATIC_FALLBACK_CATALOG


def test_build_audio_effects_none_when_empty():
    assert _make_adapter()._build_audio_effects({}) is None


def test_build_audio_effects_assembles():
    fx = _make_adapter()._build_audio_effects(
        {"filter_preset_id": "phone", "environment_id": "hall", "distance": 0.3}
    )
    assert fx == {
        "filter_preset_id": "phone",
        "environment_id": "hall",
        "distance": 0.3,
    }


# ---------- call_api (mock httpx) ----------


class _FakeClient:
    def __init__(self, resp):
        self._resp = resp
        self.last_json = None
        self.last_url = None
        self.last_params = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        self.last_url = a[0] if a else None
        self.last_json = k.get("json")
        self.last_params = k.get("params")
        return self._resp


@pytest.mark.asyncio
async def test_call_api_saves_mp3(tmp_path, monkeypatch):
    adapter = _make_adapter()
    entry = dict(ENTRY, _data_dir=str(tmp_path), use_voice_settings=True)
    fake = _FakeClient(_FakeResp(b"fakeaudio"))
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.elevenlabs_v4.httpx.AsyncClient",
        lambda *a, **k: fake,
    )
    path = await adapter.call_api(text="你好", raw_params={}, config=entry)
    assert path and path.endswith(".mp3")
    assert os.path.exists(path)
    # 请求体核心契约：模型 + voice_settings；enable_logging 必须在 query（不在 body）
    body = fake.last_json
    assert body["model_id"] == "eleven_v4"
    assert "voice_settings" in body
    assert body["voice_settings"]["use_speaker_boost"] is True
    assert body["voice_settings"]["stability"] == 0.5
    assert body["voice_settings"]["similarity_boost"] == 0.75
    assert "enable_logging" not in body
    # output_format 与 enable_logging 均为 query 参数（官方 spec：enable_logging 在 query）
    assert fake.last_params["output_format"] == "mp3_44100_128"
    assert fake.last_params["enable_logging"] == "true"


@pytest.mark.asyncio
async def test_call_api_enable_logging_false_sent_in_query(tmp_path, monkeypatch):
    adapter = _make_adapter()
    # 零留存开关：用户设 false 时必须在 query 真正发出，否则服务端忽略（仍被记录）
    entry = dict(ENTRY, _data_dir=str(tmp_path), enable_logging=False)
    fake = _FakeClient(_FakeResp(b"fakeaudio"))
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.elevenlabs_v4.httpx.AsyncClient",
        lambda *a, **k: fake,
    )
    await adapter.call_api(text="hi", raw_params={}, config=entry)
    assert "enable_logging" not in fake.last_json
    assert fake.last_params["enable_logging"] == "false"


@pytest.mark.asyncio
async def test_voice_settings_out_of_range_clamped(tmp_path, monkeypatch):
    adapter = _make_adapter()
    # 越界值（程序化/直连配置）必须夹紧到 [0,1]，否则服务端 422
    entry = dict(
        ENTRY,
        _data_dir=str(tmp_path),
        use_voice_settings=True,
        stability=5.0,
        similarity_boost=-3.0,
    )
    fake = _FakeClient(_FakeResp(b"fakeaudio"))
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.elevenlabs_v4.httpx.AsyncClient",
        lambda *a, **k: fake,
    )
    await adapter.call_api(text="hi", raw_params={}, config=entry)
    vs = fake.last_json["voice_settings"]
    assert vs["stability"] == 1.0
    assert vs["similarity_boost"] == 0.0


def test_language_code_config_item_present_in_schema():
    # P2-4：schema 必须提供 language_code 配置项（代码 config.get("language_code") 依赖它）
    import json

    schema = json.load(open("_conf_schema.json"))
    items = (
        schema.get("providers", {})
        .get("templates", {})
        .get("elevenlabs_v4", {})
        .get("items", {})
    )
    assert "language_code" in items, "elevenlabs_v4 配置缺少 language_code 项"
    found = items["language_code"]
    assert found["type"] == "string"
    assert found["default"] == ""


@pytest.mark.asyncio
async def test_call_api_tool_language_overrides_config(tmp_path, monkeypatch):
    adapter = _make_adapter()
    entry = dict(ENTRY, _data_dir=str(tmp_path), language_code="en")
    fake = _FakeClient(_FakeResp(b"fakeaudio"))
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.elevenlabs_v4.httpx.AsyncClient",
        lambda *a, **k: fake,
    )
    await adapter.call_api(text="hi", raw_params={"language_code": "ja"}, config=entry)
    assert fake.last_json["language_code"] == "ja"


@pytest.mark.asyncio
async def test_call_api_falls_back_to_config_language(tmp_path, monkeypatch):
    adapter = _make_adapter()
    entry = dict(ENTRY, _data_dir=str(tmp_path), language_code="fr")
    fake = _FakeClient(_FakeResp(b"fakeaudio"))
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.elevenlabs_v4.httpx.AsyncClient",
        lambda *a, **k: fake,
    )
    await adapter.call_api(text="hi", raw_params={}, config=entry)
    assert fake.last_json["language_code"] == "fr"


@pytest.mark.asyncio
async def test_call_api_no_language_when_empty(tmp_path, monkeypatch):
    adapter = _make_adapter()
    entry = dict(ENTRY, _data_dir=str(tmp_path), language_code="")
    fake = _FakeClient(_FakeResp(b"fakeaudio"))
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.elevenlabs_v4.httpx.AsyncClient",
        lambda *a, **k: fake,
    )
    await adapter.call_api(text="hi", raw_params={}, config=entry)
    assert "language_code" not in fake.last_json


@pytest.mark.asyncio
async def test_call_api_missing_key_returns_empty():
    adapter = ElevenLabsV4Adapter({"__template_key": KEY})
    path = await adapter.call_api(
        text="hi", raw_params={}, config={"_data_dir": "/tmp/x"}
    )
    assert path == ""


@pytest.mark.asyncio
async def test_call_api_with_effects_and_pronunciation(tmp_path, monkeypatch):
    adapter = _make_adapter()
    # 发音词典字段由 call_api 从 config（即 entry）读取，而非 adapter.entry
    entry = dict(
        ENTRY,
        _data_dir=str(tmp_path),
        use_pronunciation_dictionary=True,
        pronunciation_dictionary_id="dict-1",
        pronunciation_dictionary_version="v1",
    )
    fake = _FakeClient(_FakeResp(b"fakeaudio"))
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.elevenlabs_v4.httpx.AsyncClient",
        lambda *a, **k: fake,
    )
    raw = {"text": "hi", "environment_id": "hall", "send_level": 0.5}
    path = await adapter.call_api(text="hi", raw_params=raw, config=entry)
    assert path and os.path.exists(path)
    body = fake.last_json
    assert body["audio_effects"] == {"environment_id": "hall", "send_level": 0.5}
    assert body["pronunciation_dictionary_locators"] == [
        {"pronunciation_dictionary_id": "dict-1", "version_id": "v1"}
    ]


@pytest.mark.asyncio
async def test_call_api_omits_voice_settings_when_toggle_off(tmp_path, monkeypatch):
    adapter = _make_adapter()
    # use_voice_settings 默认关闭 → 不传 voice_settings，使用服务端默认值
    entry = dict(ENTRY, _data_dir=str(tmp_path))
    fake = _FakeClient(_FakeResp(b"fakeaudio"))
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.elevenlabs_v4.httpx.AsyncClient",
        lambda *a, **k: fake,
    )
    await adapter.call_api(text="hi", raw_params={}, config=entry)
    assert "voice_settings" not in fake.last_json


@pytest.mark.asyncio
async def test_seed_minus_one_omitted(tmp_path, monkeypatch):
    adapter = _make_adapter()
    entry = dict(ENTRY, _data_dir=str(tmp_path), use_voice_settings=True, seed=-1)
    fake = _FakeClient(_FakeResp(b"fakeaudio"))
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.elevenlabs_v4.httpx.AsyncClient",
        lambda *a, **k: fake,
    )
    await adapter.call_api(text="hi", raw_params={}, config=entry)
    assert "seed" not in fake.last_json


@pytest.mark.asyncio
async def test_seed_zero_and_positive_passed(tmp_path, monkeypatch):
    adapter = _make_adapter()
    for s in (0, 42, 4294967295):
        entry = dict(ENTRY, _data_dir=str(tmp_path), use_voice_settings=True, seed=s)
        fake = _FakeClient(_FakeResp(b"fakeaudio"))
        monkeypatch.setattr(
            "astrbot_plugin_tts_enhancer.providers.elevenlabs_v4.httpx.AsyncClient",
            lambda *a, **k: fake,
        )
        await adapter.call_api(text="hi", raw_params={}, config=entry)
        assert fake.last_json["seed"] == s
