"""ElevenLabs v4 适配器离线测试（不依赖网络）。

验证：自动发现、文档齐备、工具契约、参数清洗、output_format 组合、
audio_effects catalog 拉取（mock）、audio_effects 组装，以及 call_api 在
httpx 被 mock 时的行为。
"""

import os
import time

import httpx
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


def test_tool_schema_with_audio_effects_unwarmed_drops_schema(monkeypatch):
    # 缓存未命中（预热前/失败）时，_get_catalog 返回 None，audio_effects 字段不出现
    adapter = _make_adapter(use_audio_effects=True)
    monkeypatch.setattr(adapter, "_get_catalog", lambda: None)
    props = adapter.get_tool_schema().parameters["properties"]
    assert "filter_preset_id" not in props
    assert "environment_id" not in props
    assert "background_noise_id" not in props
    assert "distance" not in props
    assert "send_level" not in props
    assert "pan" not in props


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


def test_system_prompt_with_audio_effects_unwarmed_has_no_fx_block(monkeypatch):
    # 缓存未命中时，不注入 audio_effects 指引（与 schema 行为一致，不暴露猜测 ID）
    adapter = _make_adapter(use_audio_effects=True)
    monkeypatch.setattr(adapter, "_get_catalog", lambda: None)
    prompt = adapter.get_subagent_system_prompt()
    assert "音频效果（audio_effects）" not in prompt
    assert "filter_preset_id（音色滤镜）" not in prompt


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


def test_get_catalog_returns_none_when_unwarmed(catalog_clean):
    # 缓存为空时，_get_catalog 不发起网络、直接返回 None（参数不暴露）
    adapter = _make_adapter()
    assert adapter._get_catalog() is None


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


def test_fetch_catalog_failure_returns_none_and_drops_params(catalog_clean, monkeypatch):
    async def _boom_get(self, *a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(_FakeAsyncClient, "get", _boom_get)
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.elevenlabs_v4.httpx.AsyncClient",
        lambda *a, **k: _FakeAsyncClient(_FakeResp(CATALOG)),
    )
    import asyncio

    asyncio.run(_make_adapter().ensure_catalog_warm())
    # 失败不写缓存，_get_catalog 返回 None，audio_effects 参数从 schema/提示词消失
    assert _make_adapter()._get_catalog() is None
    props = (
        _make_adapter(use_audio_effects=True)
        .get_tool_schema()
        .parameters["properties"]
    )
    assert "filter_preset_id" not in props
    assert "pan" not in props


def test_fetch_catalog_missing_key_no_cache(catalog_clean):
    # 无 api_key 时 _fetch_catalog 直接返回、不写缓存
    import asyncio

    asyncio.run(_make_adapter(api_key="").ensure_catalog_warm())
    assert elevenlabs_v4._CATALOG_CACHE == {}


def test_fetch_catalog_malformed_returns_none(catalog_clean, monkeypatch):
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.elevenlabs_v4.httpx.AsyncClient",
        lambda *a, **k: _FakeAsyncClient(_FakeResp({"unexpected": []})),
    )
    import asyncio

    asyncio.run(_make_adapter().ensure_catalog_warm())
    assert elevenlabs_v4._CATALOG_CACHE == {}
    assert _make_adapter()._get_catalog() is None


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


def test_catalog_config_items_present_in_schema_and_conditional():
    # 用户需求：目录拉取超时与目录缓存时长须暴露为配置，且仅在 use_audio_effects 开启时显示
    import json

    schema = json.load(open("_conf_schema.json"))
    items = (
        schema.get("providers", {})
        .get("templates", {})
        .get("elevenlabs_v4", {})
        .get("items", {})
    )
    for name in ("catalog_fetch_timeout", "catalog_ttl"):
        assert name in items, f"elevenlabs_v4 配置缺少 {name} 项"
        found = items[name]
        assert found["type"] == "int"
        assert found.get("condition") == {"use_audio_effects": True}, (
            f"{name} 应在 use_audio_effects 开启时才显示"
        )
    assert items["catalog_fetch_timeout"]["default"] == 5
    assert items["catalog_ttl"]["default"] == 300


def test_catalog_ttl_config_overrides_default():
    # 未配置 → 模块默认 300；配置合法正值 → 取配置；非法/零/负值 → 回退默认
    assert _make_adapter()._catalog_ttl() == 300
    assert _make_adapter(catalog_ttl=60)._catalog_ttl() == 60
    assert _make_adapter(catalog_ttl=0)._catalog_ttl() == 300
    assert _make_adapter(catalog_ttl=-5)._catalog_ttl() == 300
    assert _make_adapter(catalog_ttl="abc")._catalog_ttl() == 300


def test_catalog_fetch_timeout_config_overrides_default():
    # 未配置 → 模块默认 5；配置合法正值 → 取配置；非法/零/负值 → 回退默认
    assert _make_adapter()._catalog_fetch_timeout() == 5
    assert _make_adapter(catalog_fetch_timeout=42)._catalog_fetch_timeout() == 42
    assert _make_adapter(catalog_fetch_timeout=0)._catalog_fetch_timeout() == 5
    assert _make_adapter(catalog_fetch_timeout=-1)._catalog_fetch_timeout() == 5
    assert _make_adapter(catalog_fetch_timeout="abc")._catalog_fetch_timeout() == 5


def test_get_catalog_respects_configured_ttl(catalog_clean):
    # 缓存新鲜（10s 前）命中；超过配置 TTL（60s 前）判为过期返回 None
    adapter = _make_adapter(catalog_ttl=60)
    key = adapter._catalog_key()
    empty_catalog = {
        "filter_presets": [],
        "environments": [],
        "background_noises": [],
    }
    elevenlabs_v4._CATALOG_CACHE[key] = {
        "catalog": empty_catalog,
        "ts": time.time() - 10,
    }
    assert adapter._get_catalog() is not None
    elevenlabs_v4._CATALOG_CACHE[key]["ts"] = time.time() - 100
    assert adapter._get_catalog() is None


def test_fetch_catalog_uses_configured_timeout(catalog_clean, monkeypatch):
    # _fetch_catalog 拉目录时，httpx 超时须取配置的 catalog_fetch_timeout
    captured: dict = {}

    class _CaptureClient:
        def __init__(self, *a, **k):
            captured.update(k)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _FakeResp(CATALOG)

    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.elevenlabs_v4.httpx.AsyncClient",
        _CaptureClient,
    )
    import asyncio

    asyncio.run(_make_adapter(catalog_fetch_timeout=42).ensure_catalog_warm())
    assert captured.get("timeout") == 42


def test_fetch_catalog_default_timeout(catalog_clean, monkeypatch):
    captured: dict = {}

    class _CaptureClient:
        def __init__(self, *a, **k):
            captured.update(k)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return _FakeResp(CATALOG)

    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.elevenlabs_v4.httpx.AsyncClient",
        _CaptureClient,
    )
    import asyncio

    asyncio.run(_make_adapter().ensure_catalog_warm())
    assert captured.get("timeout") == 5


@pytest.mark.asyncio
async def test_ensure_catalog_ready_noop_when_disabled(catalog_clean, monkeypatch):
    # 未开启 use_audio_effects 时直接返回，绝不触发拉取
    called = []
    async def boom(self):
        called.append(1)
    monkeypatch.setattr(ElevenLabsV4Adapter, "_fetch_catalog", boom)
    await _make_adapter().ensure_catalog_ready(timeout=1)
    assert called == []


@pytest.mark.asyncio
async def test_ensure_catalog_ready_skips_when_already_cached(catalog_clean, monkeypatch):
    # 缓存已命中 → 不触发拉取，直接可用
    called = []
    async def boom(self):
        called.append(1)
    monkeypatch.setattr(ElevenLabsV4Adapter, "_fetch_catalog", boom)
    adapter = _make_adapter(use_audio_effects=True)
    key = adapter._catalog_key()
    elevenlabs_v4._CATALOG_CACHE[key] = {
        "catalog": {"filter_presets": [], "environments": [], "background_noises": []},
        "ts": time.time(),
    }
    await adapter.ensure_catalog_ready(timeout=1)
    assert called == []
    assert adapter._get_catalog() is not None


@pytest.mark.asyncio
async def test_ensure_catalog_ready_waits_and_exposes_on_success(
    catalog_clean, monkeypatch
):
    # 预热能在超时内完成 → 缓存命中，后续 schema/提示词会暴露参数
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.elevenlabs_v4.httpx.AsyncClient",
        lambda *a, **k: _FakeAsyncClient(_FakeResp(CATALOG)),
    )
    adapter = _make_adapter(use_audio_effects=True)
    assert adapter._get_catalog() is None
    await adapter.ensure_catalog_ready(timeout=2)
    assert adapter._get_catalog() is not None


@pytest.mark.asyncio
async def test_ensure_catalog_ready_timeout_keeps_warming(catalog_clean, monkeypatch):
    # 超时只结束等待、不取消底层预热：本次不暴露，但后台继续并最终落地缓存
    import asyncio

    state: dict = {}
    async def slow_fetch(self):
        await asyncio.sleep(0.4)
        key = self._catalog_key()
        elevenlabs_v4._CATALOG_CACHE[key] = {
            "catalog": {
                "filter_presets": [],
                "environments": [],
                "background_noises": [],
            },
            "ts": time.time(),
        }
        state["done"] = True

    monkeypatch.setattr(ElevenLabsV4Adapter, "_fetch_catalog", slow_fetch)
    adapter = _make_adapter(use_audio_effects=True)
    start = time.monotonic()
    await adapter.ensure_catalog_ready(timeout=0.1)
    elapsed = time.monotonic() - start
    # 超时返回不阻塞完整 0.4s 拉取
    assert elapsed < 0.35
    assert adapter._get_catalog() is None
    assert not state.get("done")
    # 后台继续：稍后缓存落地，后续合成可命中
    for _ in range(40):
        if state.get("done"):
            break
        await asyncio.sleep(0.05)
    assert state.get("done") is True
    assert adapter._get_catalog() is not None


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


# ---------- call_api：audio_effects 下架/无效 优雅降级 ----------


def _make_status_error(status: int, body: dict) -> "httpx.HTTPStatusError":
    """构造一个 httpx.HTTPStatusError（带 JSON 错误体），供降级测试。"""
    req = httpx.Request("POST", "https://api.elevenlabs.io/v1/text-to-speech/x")
    resp = httpx.Response(status, json=body, request=req)
    return httpx.HTTPStatusError("error", request=req, response=resp)


class _FakeClientOnceErrThenOK:
    """post 第一次抛错、第二次返回成功的 mock 客户端（验证降级重试）。"""

    def __init__(self, err, ok):
        self._err = err
        self._ok = ok
        self.calls = 0
        self.last_json = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        self.calls += 1
        self.last_json = k.get("json")
        if self.calls == 1:
            raise self._err
        return self._ok


class _FakeClientAlwaysErr:
    """post 始终抛错（验证不该重试的场景：voice 404 / 429）。"""

    def __init__(self, err):
        self._err = err
        self.calls = 0
        self.last_json = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        self.calls += 1
        self.last_json = k.get("json")
        raise self._err


def test_error_references_audio_effects_true():
    # 官方 404 audio_effects 错误体：param 指明字段（顶层或嵌在 detail）
    resp = httpx.Response(
        404,
        json={"detail": {"param": "audio_effects.environment_id", "message": "unknown id"}},
    )
    assert ElevenLabsV4Adapter._error_references_audio_effects(resp) is True
    resp_top = httpx.Response(404, json={"param": "audio_effects", "message": "x"})
    assert ElevenLabsV4Adapter._error_references_audio_effects(resp_top) is True


def test_error_references_audio_effects_false_for_voice_param():
    # param 指向 voice_id（非 audio_effects）；即便 msg 里提到 audio_effects，
    # 也不应误判为 effect 错误触发重试
    resp = httpx.Response(
        404,
        json={"detail": {"param": "voice_id", "message": "not found; check audio_effects usage"}},
    )
    assert ElevenLabsV4Adapter._error_references_audio_effects(resp) is False


def test_error_references_audio_effects_false_on_bad_json():
    class _Bad:
        def json(self):
            raise ValueError("nope")

        @property
        def text(self):
            return "broken"

    assert ElevenLabsV4Adapter._error_references_audio_effects(_Bad()) is False


@pytest.mark.asyncio
async def test_call_api_effect_404_strips_and_retries(tmp_path, monkeypatch):
    adapter = _make_adapter()
    entry = dict(ENTRY, _data_dir=str(tmp_path))
    # 第一次 404，错误体 param 指向 audio_effects 字段（模拟 effect ID 下架）
    err = _make_status_error(
        404,
        {"detail": {"param": "audio_effects.environment_id", "message": "unknown id"}},
    )
    fake = _FakeClientOnceErrThenOK(err, _FakeResp(b"fakeaudio"))
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.elevenlabs_v4.httpx.AsyncClient",
        lambda *a, **k: fake,
    )
    raw = {"text": "hi", "environment_id": "hall", "send_level": 0.5}
    path = await adapter.call_api(text="hi", raw_params=raw, config=entry)
    # 剥除 audio_effects 后重试一次成功（仍拿到干净语音）
    assert path and os.path.exists(path)
    assert fake.calls == 2
    # 重试请求体不再含 audio_effects
    assert "audio_effects" not in fake.last_json


@pytest.mark.asyncio
async def test_call_api_voice_404_does_not_retry(tmp_path, monkeypatch):
    adapter = _make_adapter()
    entry = dict(ENTRY, _data_dir=str(tmp_path))
    # 404 但错误体 param 指向 voice_id（非 audio_effects）→ 不应剥除/重试
    err = _make_status_error(404, {"detail": {"param": "voice_id", "message": "not found"}})
    fake = _FakeClientAlwaysErr(err)
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.elevenlabs_v4.httpx.AsyncClient",
        lambda *a, **k: fake,
    )
    raw = {"text": "hi", "environment_id": "hall"}
    path = await adapter.call_api(text="hi", raw_params=raw, config=entry)
    assert path == ""
    assert fake.calls == 1  # 只调用一次，未重试


@pytest.mark.asyncio
async def test_call_api_429_does_not_retry(tmp_path, monkeypatch):
    adapter = _make_adapter()
    entry = dict(ENTRY, _data_dir=str(tmp_path))
    err = _make_status_error(429, {"detail": "rate limited"})
    fake = _FakeClientAlwaysErr(err)
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.elevenlabs_v4.httpx.AsyncClient",
        lambda *a, **k: fake,
    )
    raw = {"text": "hi", "environment_id": "hall"}
    path = await adapter.call_api(text="hi", raw_params=raw, config=entry)
    assert path == ""
    assert fake.calls == 1  # 429 不重试
