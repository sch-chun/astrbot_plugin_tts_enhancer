"""Offline tests for the Volcengine Doubao Seed TTS 3.0 adapter."""

import base64
import json
import re
import wave
from io import BytesIO
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from astrbot_plugin_tts_enhancer.providers import ProviderFactory
from astrbot_plugin_tts_enhancer.providers.base import TTSProviderAdapter
from astrbot_plugin_tts_enhancer.providers.volcengine_seed_tts_3_0 import (
    CLONE_LANGUAGE_IDS,
    CLONE_PROMPT_TEXT_REQUIRED_IDS,
    CLONE_PROSODY_UNSUPPORTED_IDS,
    CONTROL_TAGS,
    FINAL_REASON,
    LANGUAGE_CODES,
    MAX_INPUT_CHARS,
    MODEL_ID,
    PARALINGUISTIC_TAGS,
    VolcengineSeedTts30Adapter,
)

KEY = "volcengine_seed_tts_3_0"
REPO_ROOT = Path(__file__).parents[1]


def _entry(tmp_path, **overrides):
    entry = {
        "__template_key": KEY,
        "api_key": "test-key",
        "voice_id": "test-voice",
        "timeout": 180,
        "proxy": "",
        "format": "mp3",
        "sample_rate": 24000,
        "bit_rate": 64000,
        "text_normalization": True,
        "enable_markdown_filter": True,
        "silence_duration": 0,
        "max_input_chars": MAX_INPUT_CHARS,
        "similarity_boost": False,
        "dialect_boost": False,
        "aigc_watermark": False,
        "aigc_metadata_enable": False,
        "aigc_content_producer": "",
        "aigc_produce_id": "",
        "aigc_content_propagator": "",
        "aigc_propagate_id": "",
        "_data_dir": str(tmp_path / "audio"),
    }
    entry.update(overrides)
    return entry


def _audio_event(data):
    return {"event": "audio", "audio": base64.b64encode(data).decode("ascii")}


def _final_event():
    return {"event": "final", "is_final": True, "reason": FINAL_REASON}


def _jsonl(*events):
    return b"".join(
        json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        + b"\n"
        for event in events
    )


class _FakeResponse:
    def __init__(self, chunks=None, status_code=200, body=b"", headers=None):
        self.chunks = list(chunks or [])
        self.status_code = status_code
        self.body = body
        self.content = body
        self.text = body.decode("utf-8", errors="replace")
        self.headers = headers or {}
        self.read = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def aiter_bytes(self):
        for chunk in self.chunks:
            yield chunk

    async def aread(self):
        self.read = True
        return self.body


class _FakeClient:
    def __init__(self, response=None, stream_exc=None):
        self.response = response or _FakeResponse()
        self.stream_exc = stream_exc
        self.init_kwargs = None
        self.stream_calls = []
        self.post_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def stream(self, method, url, **kwargs):
        self.stream_calls.append((method, url, kwargs))
        if self.stream_exc:
            raise self.stream_exc
        return self.response

    async def post(self, url, **kwargs):
        self.post_calls.append(("POST", url, kwargs))
        return self.response


def _install(monkeypatch, client):
    def factory(*args, **kwargs):
        client.init_kwargs = kwargs
        return client

    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.volcengine_seed_tts_3_0.httpx.AsyncClient",
        factory,
    )
    return client


def _capture_errors(monkeypatch):
    messages = []

    def error(message, *args, **kwargs):
        messages.append(message % args if args else message)

    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.volcengine_seed_tts_3_0.logger.error",
        error,
    )
    return messages


def test_discovery_and_display_name():
    ProviderFactory._discover_adapters()
    cls = ProviderFactory._adapters[KEY]
    assert issubclass(cls, TTSProviderAdapter)
    assert cls.__name__ == "VolcengineSeedTts30Adapter"
    assert cls.DISPLAY_NAME == "豆包 Seed TTS 3.0"


def test_docs_and_formal_tag_whitelist():
    adapter = VolcengineSeedTts30Adapter({"__template_key": KEY})
    assert len(CONTROL_TAGS) == 54
    assert len(PARALINGUISTIC_TAGS) == 28
    assert len(CONTROL_TAGS | PARALINGUISTIC_TAGS) == 82
    for tag in CONTROL_TAGS | PARALINGUISTIC_TAGS:
        assert f"[{tag}]" in adapter.docs_content
    assert "[desperately]" not in adapter.docs_content
    assert "[sobbing]" not in adapter.docs_content
    assert "[nervously]" not in adapter.docs_content
    assert "[stammers]" not in adapter.docs_content


def test_language_codes_include_official_dialects():
    assert "auto" in LANGUAGE_CODES
    assert {"zh", "en", "en-GB", "pt-BR", "es-MX", "yue"} <= LANGUAGE_CODES
    dialects = {code for code in LANGUAGE_CODES if code.startswith("zh-CN-x-")}
    assert len(dialects) == 16
    assert "zh-CN-x-sichuan" in dialects
    assert "zh-CN-x-tianjin" in dialects


def test_docs_map_every_synthesis_language_code():
    adapter = VolcengineSeedTts30Adapter({"__template_key": KEY})
    rows = re.findall(r"^\| `([^`]+)` \| ([^|]+) \|$", adapter.docs_content, re.M)
    mapping = {code: name.strip() for code, name in rows if code in LANGUAGE_CODES}
    assert len(LANGUAGE_CODES) == 120
    assert set(mapping) == LANGUAGE_CODES
    assert all(mapping.values())
    assert mapping["auto"] == "自动识别"
    assert mapping["yue"] == "粤语"
    assert mapping["zh-CN-x-sichuan"] == "四川话"
    assert all("（" not in name and "）" not in name for name in mapping.values())
    assert "seed-tts-3-0-language-support" not in adapter.docs_content


def test_clone_language_mapping_matches_backend_validation():
    source = (
        REPO_ROOT / "pages/tts_studio/components/volcengine_seed_tts_3_0.js"
    ).read_text(encoding="utf-8")
    block = re.search(r"const CLONE_LANGUAGES = \[(.*?)\n\];", source, re.S)
    assert block is not None
    rows = re.findall(
        r"\{ id: (\d+), code: '([^']+)', name: '[^']+', "
        r"promptTextRequired: (true|false), prosodySupported: (true|false) \}",
        block.group(1),
    )
    codes = {code for _, code, _, _ in rows}
    assert len(rows) == 102
    assert len(codes) == 102
    assert codes <= LANGUAGE_CODES - {"auto"}
    assert "zh" in codes
    assert "yue" not in codes
    assert not any(code.startswith("zh-CN-x-") for code in codes)
    language_ids = {int(language_id) for language_id, _, _, _ in rows}
    assert len(language_ids) == 102
    assert language_ids == CLONE_LANGUAGE_IDS
    assert {
        int(language_id)
        for language_id, _, prompt_required, _ in rows
        if prompt_required == "true"
    } == CLONE_PROMPT_TEXT_REQUIRED_IDS
    prosody_supported = {
        int(language_id) for language_id, _, _, supported in rows if supported == "true"
    }
    assert CLONE_LANGUAGE_IDS - prosody_supported == CLONE_PROSODY_UNSUPPORTED_IDS


def test_clone_ui_hides_api_field_names_in_all_locales():
    source = (
        REPO_ROOT / "pages/tts_studio/components/volcengine_seed_tts_3_0.js"
    ).read_text(encoding="utf-8")
    block = re.search(r"const I18N_DEFS = \{(.*?)\n\};", source, re.S)
    assert block is not None
    keys = set(re.findall(r"^    (\w+):", block.group(1), re.M))
    api_fields = (
        "entry_id",
        "voice_id",
        "speaker_id",
        "custom_speaker_id",
        "prompt_text",
        "prosody_boost",
        "demo_text",
        "enable_audio_denoise",
        "disable_volume_normalization",
        "fee_confirmed",
    )
    for locale in ("zh-CN", "en-US", "ja-JP", "ru-RU"):
        data = json.loads(
            (REPO_ROOT / ".astrbot-plugin/i18n" / f"{locale}.json").read_text(
                encoding="utf-8"
            )
        )
        components = data["views"]["tts_studio"]["components"]
        for key in keys:
            for field in api_fields:
                assert field not in components[key], f"{locale}.{key} exposes {field}"


def test_tool_schema_contract():
    adapter = VolcengineSeedTts30Adapter({"__template_key": KEY})
    tool = adapter.get_tool_schema()
    props = tool.parameters["properties"]
    assert tool.name == "tts_enhance"
    assert set(props) == {
        "text",
        "instructions",
        "speed",
        "volume",
        "pitch",
        "language_code",
    }
    assert set(props) == {"text", *adapter.tool_extra_fields()}
    assert tool.parameters["required"] == ["text"]
    assert props["instructions"]["items"]["type"] == "string"
    assert props["speed"]["minimum"] == props["volume"]["minimum"] == 0.5
    assert props["speed"]["maximum"] == props["volume"]["maximum"] == 2.0
    assert props["pitch"]["minimum"] == -12
    assert props["pitch"]["maximum"] == 12
    assert "由 SubAgent 按需提供" in props["language_code"]["description"]
    assert "省略时使用配置值" not in props["language_code"]["description"]
    assert "省略时由服务端使用" not in adapter.docs_content
    assert "省略时使用插件配置" not in adapter.docs_content
    assert adapter.get_subagent_system_prompt().strip()


def test_config_schema_contract():
    schema = json.loads((REPO_ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    template = schema["providers"]["templates"][KEY]
    items = template["items"]
    assert template["display_item"] == "display_name"
    assert items["display_name"]["default"] == "Seed TTS 3.0"
    assert items["voice_id"]["default"] == ""
    assert items["api_key"]["secret"] is True
    assert items["format"]["options"] == ["mp3", "pcm", "ogg_opus"]
    assert items["sample_rate"]["default"] == 24000
    assert items["bit_rate"]["options"] == [64000, 160000]
    assert (
        items["bit_rate"]["hint"] == "单位 bps；仅 MP3 和 OGG Opus 生效，PCM 会自动忽略"
    )
    assert "language_code" not in items
    assert "pronunciation_dictionary" not in items
    assert items["max_input_chars"]["default"] == MAX_INPUT_CHARS
    assert items["similarity_boost"]["default"] is False
    assert items["dialect_boost"]["default"] is False
    assert not {"speed", "volume", "pitch", "voice_type", "model_id"} & set(items)
    for field in (
        "aigc_content_producer",
        "aigc_produce_id",
        "aigc_content_propagator",
        "aigc_propagate_id",
    ):
        assert items[field]["condition"] == {"aigc_metadata_enable": True}


@pytest.mark.parametrize(
    "params",
    [
        {"text": ""},
        {"text": "   "},
        {"text": 123},
        {"text": "x" * (MAX_INPUT_CHARS + 1)},
        {"instructions": "温柔"},
        {"instructions": ["温柔", 1]},
        {"speed": 0.4},
        {"speed": 2.1},
        {"speed": True},
        {"volume": 0.4},
        {"volume": False},
        {"pitch": -13},
        {"pitch": 13},
        {"pitch": 1.5},
        {"pitch": True},
        {"language_code": "zh_CN"},
        {"language_code": 1},
    ],
)
def test_validate_rejects_bad_params(params):
    adapter = VolcengineSeedTts30Adapter({"__template_key": KEY})
    valid, message = adapter.validate_params(params)
    assert valid is False
    assert message


def test_validate_accepts_empty_and_numeric_strings():
    adapter = VolcengineSeedTts30Adapter({"__template_key": KEY})
    assert adapter.validate_params({}) == (True, "")
    assert adapter.validate_params(
        {
            "text": "你好",
            "instructions": [],
            "speed": "1.2",
            "volume": "0.8",
            "pitch": "3",
            "language_code": "zh-CN-x-sichuan",
        }
    ) == (True, "")


def test_sanitize_preserves_only_supplied_valid_fields():
    adapter = VolcengineSeedTts30Adapter({"__template_key": KEY})
    assert adapter.sanitize_params({"text": "hi"}) == {"text": "hi"}
    assert adapter.sanitize_params(
        {
            "text": " [happy] 你好 ",
            "instructions": [" 温柔 ", "", "   ", "自然"],
            "speed": "1.2",
            "volume": 0.8,
            "pitch": "3",
            "language_code": " zh ",
            "junk": 1,
        }
    ) == {
        "text": "[happy] 你好",
        "instructions": ["温柔", "自然"],
        "speed": 1.2,
        "volume": 0.8,
        "pitch": 3,
        "language_code": "zh",
    }
    assert adapter.sanitize_params({"speed": 9, "pitch": 1.5}) == {}


@pytest.mark.asyncio
async def test_streaming_success_handles_fragmented_jsonl_and_saves_audio(
    tmp_path, monkeypatch
):
    wire = _jsonl(
        {"event": "ready", "session_id": "session-1"},
        _audio_event(b"abc"),
        {"event": "alignment", "text": "ignored"},
        _audio_event(b"def"),
        _final_event(),
    )
    chunks = [wire[:17], wire[17:83], wire[83:149], wire[149:]]
    response = _FakeResponse(chunks)
    client = _install(monkeypatch, _FakeClient(response))
    entry = _entry(tmp_path)
    adapter = VolcengineSeedTts30Adapter(entry)

    path = await adapter.call_api(
        "你好", {"text": "你好"}, entry, voice_id="preview/voice ?"
    )

    assert path and path.endswith(".mp3")
    assert Path(path).read_bytes() == b"abcdef"
    method, url, kwargs = client.stream_calls[0]
    assert method == "POST"
    assert url == (
        "https://voice.cn-beijing.volces.com/api/v3/text-to-speech/"
        "preview%2Fvoice%20%3F/streaming"
    )
    assert kwargs["headers"]["X-Api-Key"] == "test-key"
    assert kwargs["headers"]["Content-Type"] == "application/json"
    UUID(kwargs["headers"]["X-Request-Id"])
    assert kwargs["json"] == {
        "model_id": MODEL_ID,
        "text": "你好",
        "output_format": {"format": "mp3", "sample_rate": 24000, "bit_rate": 64000},
        "text_normalization": True,
        "enable_markdown_filter": True,
        "silence_duration": 0,
    }
    assert client.init_kwargs == {"timeout": 180}


@pytest.mark.asyncio
async def test_omitted_language_does_not_read_stale_config(tmp_path, monkeypatch):
    client = _install(
        monkeypatch,
        _FakeClient(_FakeResponse([_jsonl(_audio_event(b"audio"), _final_event())])),
    )
    entry = _entry(tmp_path, language_code="en")
    assert await VolcengineSeedTts30Adapter(entry).call_api("hi", {}, entry)
    assert "language_code" not in client.stream_calls[0][2]["json"]


@pytest.mark.asyncio
async def test_payload_uses_tool_overrides_and_watermark(tmp_path, monkeypatch):
    client = _install(
        monkeypatch,
        _FakeClient(_FakeResponse([_jsonl(_audio_event(b"audio"), _final_event())])),
    )
    entry = _entry(
        tmp_path,
        language_code="en",
        similarity_boost=True,
        dialect_boost=True,
        pronunciation_dictionary=(
            "北京/(bei3)(jing1)\n\nomg/oh my god\ninvalid-rule\n/empty-source"
        ),
        aigc_watermark=True,
        aigc_metadata_enable=True,
        aigc_content_producer=" producer ",
        aigc_produce_id="produce-1",
        aigc_content_propagator="   ",
        aigc_propagate_id="propagate-1",
        speed=2.0,
        volume=2.0,
        pitch=12,
    )
    adapter = VolcengineSeedTts30Adapter(entry)
    params = adapter.sanitize_params(
        {
            "text": "你好",
            "instructions": [" 温柔 ", "", "自然"],
            "speed": "1.2",
            "volume": 0.8,
            "pitch": "3",
            "language_code": "zh-CN-x-sichuan",
        }
    )

    assert await adapter.call_api("原文", params, entry)
    payload = client.stream_calls[0][2]["json"]
    assert payload["text"] == "你好"
    assert payload["language_code"] == "zh-CN-x-sichuan"
    assert payload["voice_settings"] == {
        "instructions": ["温柔", "自然"],
        "speed": 1.2,
        "volume": 0.8,
        "pitch": 3,
        "similarity_boost": True,
        "dialect_boost": True,
    }
    assert "pronunciation_dictionary" not in payload
    assert payload["watermark"] == {
        "aigc_watermark": True,
        "aigc_metadata": {
            "enable": True,
            "content_producer": "producer",
            "produce_id": "produce-1",
            "propagate_id": "propagate-1",
        },
    }
    assert not {"ssml", "enable_subtitle", "session_id"} & set(payload)


@pytest.mark.asyncio
async def test_omitted_optional_groups_are_not_sent(tmp_path, monkeypatch):
    client = _install(
        monkeypatch,
        _FakeClient(_FakeResponse([_jsonl(_audio_event(b"audio"), _final_event())])),
    )
    entry = _entry(
        tmp_path,
        dialect_boost=True,
        speed=2.0,
        volume=0.5,
        pitch=12,
        aigc_metadata_enable=False,
        aigc_content_producer="ignored",
    )
    adapter = VolcengineSeedTts30Adapter(entry)

    assert await adapter.call_api("hi", {}, entry)
    payload = client.stream_calls[0][2]["json"]
    assert "voice_settings" not in payload
    assert "watermark" not in payload
    assert "pronunciation_dictionary" not in payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fmt", "sample_rate", "bit_rate", "expected_format", "extension"),
    [
        ("pcm", 16000, 160000, {"format": "pcm", "sample_rate": 16000}, ".pcm"),
        (
            "ogg_opus",
            24000,
            160000,
            {"format": "ogg_opus", "sample_rate": 48000, "bit_rate": 160000},
            ".ogg",
        ),
        (
            "mp3",
            8000,
            160000,
            {"format": "mp3", "sample_rate": 8000, "bit_rate": 64000},
            ".mp3",
        ),
        (
            "wav",
            "invalid",
            123,
            {"format": "mp3", "sample_rate": 24000, "bit_rate": 64000},
            ".mp3",
        ),
    ],
)
async def test_output_format_normalization(
    tmp_path,
    monkeypatch,
    fmt,
    sample_rate,
    bit_rate,
    expected_format,
    extension,
):
    client = _install(
        monkeypatch,
        _FakeClient(_FakeResponse([_jsonl(_audio_event(b"audio"), _final_event())])),
    )
    entry = _entry(tmp_path, format=fmt, sample_rate=sample_rate, bit_rate=bit_rate)
    adapter = VolcengineSeedTts30Adapter(entry)

    path = await adapter.call_api("hi", {}, entry)
    assert path and path.endswith(extension)
    assert Path(path).read_bytes() == b"audio"
    assert client.stream_calls[0][2]["json"]["output_format"] == expected_format


@pytest.mark.asyncio
async def test_proxy_and_timeout_are_used(tmp_path, monkeypatch):
    client = _install(
        monkeypatch,
        _FakeClient(_FakeResponse([_jsonl(_audio_event(b"audio"), _final_event())])),
    )
    entry = _entry(tmp_path, timeout=90, proxy=" http://127.0.0.1:7890 ")
    assert await VolcengineSeedTts30Adapter(entry).call_api("hi", {}, entry)
    assert client.init_kwargs == {"timeout": 90, "proxy": "http://127.0.0.1:7890"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entry_overrides",
    [
        {"api_key": ""},
        {"voice_id": ""},
        {"max_input_chars": 2},
    ],
)
async def test_invalid_request_is_rejected_before_http(
    tmp_path, monkeypatch, entry_overrides
):
    client = _install(monkeypatch, _FakeClient())
    entry = _entry(tmp_path, **entry_overrides)
    text = "long" if "max_input_chars" in entry_overrides else "hi"
    assert await VolcengineSeedTts30Adapter(entry).call_api(text, {}, entry) == ""
    assert client.stream_calls == []


@pytest.mark.asyncio
async def test_config_cannot_raise_api_character_limit(tmp_path, monkeypatch):
    client = _install(monkeypatch, _FakeClient())
    entry = _entry(tmp_path, max_input_chars=MAX_INPUT_CHARS + 1)
    text = "x" * (MAX_INPUT_CHARS + 1)
    assert await VolcengineSeedTts30Adapter(entry).call_api(text, {}, entry) == ""
    assert client.stream_calls == []


@pytest.mark.asyncio
async def test_empty_text_is_rejected_before_http(tmp_path, monkeypatch):
    client = _install(monkeypatch, _FakeClient())
    entry = _entry(tmp_path)
    assert await VolcengineSeedTts30Adapter(entry).call_api("   ", {}, entry) == ""
    assert client.stream_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 429, 500])
async def test_http_errors_return_empty_and_log_structured_fields(
    tmp_path, monkeypatch, status
):
    error = {
        "event": "error",
        "error": {
            "type": "internal_error" if status == 500 else "test_error",
            "code": "internal_error" if status == 500 else f"code-{status}",
            "message": "same human-readable message",
            "param": "text",
            "request_id": "request-1",
        },
    }
    response = _FakeResponse(status_code=status, body=_jsonl(error))
    _install(monkeypatch, _FakeClient(response))
    messages = _capture_errors(monkeypatch)
    entry = _entry(tmp_path)

    assert await VolcengineSeedTts30Adapter(entry).call_api("hi", {}, entry) == ""
    assert response.read is True
    assert not list((tmp_path / "audio").glob("*.mp3"))
    log = "\n".join(messages)
    assert f"status={status}" in log
    assert "type=" in log and "code=" in log
    assert "param=text" in log
    assert "request_id=request-1" in log
    assert "same human-readable message" in log


@pytest.mark.asyncio
async def test_error_guidance_branches_on_code_not_message(tmp_path, monkeypatch):
    messages = _capture_errors(monkeypatch)
    entry = _entry(tmp_path)
    for code in ("insufficient_credits", "voice_not_found"):
        body = _jsonl(
            {
                "event": "error",
                "error": {
                    "type": "test",
                    "code": code,
                    "message": "identical message",
                    "param": None,
                    "request_id": "request-1",
                },
            }
        )
        _install(monkeypatch, _FakeClient(_FakeResponse(status_code=400, body=body)))
        assert await VolcengineSeedTts30Adapter(entry).call_api("hi", {}, entry) == ""
    log = "\n".join(messages)
    assert "Check the account balance." in log
    assert "Check the configured voice_id." in log


@pytest.mark.asyncio
async def test_pretty_printed_json_http_error_is_parsed(tmp_path, monkeypatch):
    body = json.dumps(
        {
            "error": {
                "type": "invalid_request_error",
                "code": "voice_not_found",
                "message": "voice unavailable",
                "param": "voice_id",
                "request_id": "request-pretty",
            }
        },
        indent=2,
    ).encode()
    _install(
        monkeypatch,
        _FakeClient(_FakeResponse(status_code=404, body=body)),
    )
    messages = _capture_errors(monkeypatch)
    entry = _entry(tmp_path)

    assert await VolcengineSeedTts30Adapter(entry).call_api("hi", {}, entry) == ""
    log = "\n".join(messages)
    assert "status=404" in log
    assert "code=voice_not_found" in log
    assert "param=voice_id" in log
    assert "request_id=request-pretty" in log
    assert "Check the configured voice_id." in log


@pytest.mark.asyncio
async def test_non_json_http_error_is_discarded(tmp_path, monkeypatch):
    _install(
        monkeypatch,
        _FakeClient(_FakeResponse(status_code=502, body=b"upstream unavailable")),
    )
    entry = _entry(tmp_path)
    assert await VolcengineSeedTts30Adapter(entry).call_api("hi", {}, entry) == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "wire",
    [
        _jsonl(
            _audio_event(b"partial"),
            {"event": "error", "error": {"code": "internal_error"}},
        ),
        b'{"event":"audio","audio":\n',
        b"[]\n",
        _jsonl({"event": "audio", "audio": "not-base64!"}, _final_event()),
        _jsonl({"event": "audio", "audio": 123}, _final_event()),
        _jsonl(_audio_event(b"partial")),
        _jsonl(
            _audio_event(b"partial"),
            {"event": "final", "is_final": False, "reason": FINAL_REASON},
        ),
        _jsonl(
            _audio_event(b"partial"),
            {"event": "final", "is_final": True, "reason": "OTHER"},
        ),
        _jsonl(_final_event()),
        _jsonl({"event": "audio", "audio": ""}, _final_event()),
    ],
)
async def test_failed_streams_discard_partial_audio(tmp_path, monkeypatch, wire):
    _install(monkeypatch, _FakeClient(_FakeResponse([wire])))
    entry = _entry(tmp_path)
    assert await VolcengineSeedTts30Adapter(entry).call_api("hi", {}, entry) == ""
    assert not list((tmp_path / "audio").glob("*.mp3"))


@pytest.mark.asyncio
async def test_final_event_without_trailing_newline_is_accepted(tmp_path, monkeypatch):
    wire = _jsonl(_audio_event(b"complete"), _final_event()).rstrip(b"\n")
    _install(monkeypatch, _FakeClient(_FakeResponse([wire])))
    entry = _entry(tmp_path)
    path = await VolcengineSeedTts30Adapter(entry).call_api("hi", {}, entry)
    assert path and Path(path).read_bytes() == b"complete"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        httpx.ReadError("stream interrupted"),
        httpx.ReadTimeout("timeout"),
    ],
)
async def test_network_errors_return_empty(tmp_path, monkeypatch, exc):
    _install(monkeypatch, _FakeClient(stream_exc=exc))
    entry = _entry(tmp_path)
    assert await VolcengineSeedTts30Adapter(entry).call_api("hi", {}, entry) == ""


def _wav_bytes(duration=10, sample_rate=24000):
    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\0" * int(duration * sample_rate * 2))
    return buffer.getvalue()


def _audio(data, fmt="wav"):
    return {"data": base64.b64encode(data).decode(), "format": fmt}


def _clone_params(**overrides):
    params = {
        "speaker_id": "S_existing",
        "audio": _audio(_wav_bytes()),
        "language": 0,
        "extra_params": {
            "prompt_text": "测试音频",
            "prosody_boost": False,
            "demo_text": "这是一段试听文本。",
            "enable_audio_denoise": True,
            "disable_volume_normalization": False,
        },
    }
    params.update(overrides)
    return params


@pytest.mark.asyncio
async def test_create_voice_uses_seed_endpoint_and_headers(tmp_path, monkeypatch):
    payload = {"speaker_id": "S_created", "status": 2, "language": 0}
    response = _FakeResponse(
        body=json.dumps(payload).encode(), headers={"X-Tt-Logid": "log-1"}
    )
    client = _install(monkeypatch, _FakeClient(response))
    result = await VolcengineSeedTts30Adapter(_entry(tmp_path)).create_voice(
        _clone_params()
    )
    assert result == payload
    method, url, kwargs = client.post_calls[0]
    assert method == "POST"
    assert url == "https://voice.cn-beijing.volces.com/api/v3/tts/voice_clone"
    assert kwargs["json"]["speaker_id"] == "S_existing"
    assert kwargs["json"]["audio"]["data"] == base64.b64encode(_wav_bytes()).decode()
    assert set(kwargs["json"]["extra_params"]) == {
        "prompt_text",
        "prosody_boost",
        "demo_text",
        "enable_audio_denoise",
        "disable_volume_normalization",
    }
    headers = kwargs["headers"]
    assert headers["X-Api-Key"] == "test-key"
    assert headers["Content-Type"] == "application/json"
    UUID(headers["X-Api-Request-Id"])


@pytest.mark.asyncio
async def test_create_custom_voice_sets_fixed_speaker_id(tmp_path, monkeypatch):
    client = _install(monkeypatch, _FakeClient(_FakeResponse(body=b'{"status":2}')))
    adapter = VolcengineSeedTts30Adapter(_entry(tmp_path))
    await adapter.create_voice(
        _clone_params(
            speaker_id="",
            custom_speaker_id="custom_zh_voice01",
            fee_confirmed=True,
        )
    )
    payload = client.post_calls[0][2]["json"]
    assert payload["speaker_id"] == "custom_speaker_id"
    assert payload["custom_speaker_id"] == "custom_zh_voice01"
    assert "fee_confirmed" not in payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"audio": {"data": "not-base64!", "format": "wav"}},
        {"audio": {"data": "", "format": "wav"}},
        {"audio": {"data": "YQ==", "format": "flac"}},
        {"audio": {"data": "YQ==" * (10 * 1024 * 1024 + 1), "format": "wav"}},
        {"audio": _audio(b"not-a-wav")},
        {"audio": _audio(_wav_bytes(9))},
        {"audio": _audio(_wav_bytes(61))},
        {"audio": _audio(b"\0" * 479999, "pcm")},
        {"audio": _audio(b"\0" * 480001, "pcm")},
        {"speaker_id": ""},
        {"speaker_id": "custom_speaker_id"},
        {"custom_speaker_id": "1bad"},
        {"custom_speaker_id": "bad_name_"},
        {"custom_speaker_id": "zh_voice01"},
        {"custom_speaker_id": "BV_voice01"},
        {"custom_speaker_id": "s_voice01"},
        {"custom_speaker_id": "custom_voice01_streaming"},
        {
            "speaker_id": "S_existing",
            "custom_speaker_id": "custom_zh_voice01",
            "fee_confirmed": True,
        },
        {"custom_speaker_id": "custom_zh_voice01"},
        {
            "custom_speaker_id": "custom_zh_voice01",
            "fee_confirmed": "true",
        },
        {"language": -1},
        {"language": True},
        {"language": "1"},
        {"language": 101},
        {"language": 119},
        {"language": 21, "extra_params": {}},
        {
            "language": 21,
            "extra_params": {"prompt_text": "测试音频", "prosody_boost": True},
        },
        {"language": 62, "extra_params": {"prosody_boost": True}},
        {"extra_params": {"voice_clone_enable_mss": True}},
        {"extra_params": {"prosody_boost": "true"}},
        {"extra_params": {"demo_text": "abc"}},
        {"extra_params": {"demo_text": "a" * 301}},
    ],
)
async def test_create_voice_rejects_invalid_params(tmp_path, monkeypatch, overrides):
    client = _install(monkeypatch, _FakeClient(_FakeResponse(body=b"{}")))
    adapter = VolcengineSeedTts30Adapter(_entry(tmp_path))
    with pytest.raises(ValueError) as exc_info:
        await adapter.create_voice(_clone_params(**overrides))
    message = str(exc_info.value)
    for field in (
        "speaker_id",
        "custom_speaker_id",
        "prompt_text",
        "prosody_boost",
        "demo_text",
        "extra_params",
        "audio.data",
    ):
        assert field not in message
    assert client.post_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("language_id", [0, 1, 21, 62, 100, 118])
async def test_create_voice_accepts_official_language_ids(
    tmp_path, monkeypatch, language_id
):
    client = _install(monkeypatch, _FakeClient(_FakeResponse(body=b"{}")))
    await VolcengineSeedTts30Adapter(_entry(tmp_path)).create_voice(
        _clone_params(language=language_id)
    )
    assert client.post_calls[0][2]["json"]["language"] == language_id


@pytest.mark.asyncio
@pytest.mark.parametrize("duration", [10, 60])
async def test_create_voice_accepts_wav_duration_boundaries(
    tmp_path, monkeypatch, duration
):
    client = _install(monkeypatch, _FakeClient(_FakeResponse(body=b"{}")))
    await VolcengineSeedTts30Adapter(_entry(tmp_path)).create_voice(
        _clone_params(audio=_audio(_wav_bytes(duration)))
    )
    assert len(client.post_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "audio",
    [
        _audio(b"\0" * (24000 * 2 * 10), "pcm"),
        _audio(b"compressed-audio", "mp3"),
    ],
)
async def test_create_voice_accepts_valid_pcm_and_defers_compressed_duration(
    tmp_path, monkeypatch, audio
):
    client = _install(monkeypatch, _FakeClient(_FakeResponse(body=b"{}")))
    await VolcengineSeedTts30Adapter(_entry(tmp_path)).create_voice(
        _clone_params(audio=audio)
    )
    assert len(client.post_calls) == 1


@pytest.mark.asyncio
async def test_create_voice_reports_api_error_and_log_id(tmp_path, monkeypatch):
    response = _FakeResponse(
        status_code=400,
        body=json.dumps(
            {"error": {"code": "invalid_audio", "message": "bad audio"}}
        ).encode(),
        headers={"X-Tt-Logid": "log-error"},
    )
    _install(monkeypatch, _FakeClient(response))
    messages = _capture_errors(monkeypatch)
    adapter = VolcengineSeedTts30Adapter(_entry(tmp_path))
    with pytest.raises(RuntimeError, match="bad audio"):
        await adapter.create_voice(_clone_params())
    assert "log-error" in "\n".join(messages)


@pytest.mark.asyncio
async def test_query_voice_uses_get_voice_endpoint(tmp_path, monkeypatch):
    payload = {"speaker_id": "S_created", "status": 4}
    client = _install(
        monkeypatch, _FakeClient(_FakeResponse(body=json.dumps(payload).encode()))
    )
    result = await VolcengineSeedTts30Adapter(_entry(tmp_path)).query_voice(
        " S_created "
    )
    assert result == payload
    method, url, kwargs = client.post_calls[0]
    assert method == "POST"
    assert url == "https://voice.cn-beijing.volces.com/api/v3/tts/get_voice"
    assert kwargs["json"] == {"speaker_id": "S_created"}
    assert "X-Api-Request-Id" in kwargs["headers"]


@pytest.mark.asyncio
async def test_query_custom_voice_uses_official_name_payload(tmp_path, monkeypatch):
    payload = {"speaker_id": "S_created", "status": 2}
    client = _install(
        monkeypatch, _FakeClient(_FakeResponse(body=json.dumps(payload).encode()))
    )
    result = await VolcengineSeedTts30Adapter(_entry(tmp_path)).query_voice(
        "custom_speaker_id", " custom_zh_voice01 "
    )
    assert result == payload
    assert client.post_calls[0][2]["json"] == {
        "speaker_id": "custom_speaker_id",
        "custom_speaker_id": "custom_zh_voice01",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("voice_id", "custom_speaker_id"),
    [
        ("S_created", "custom_zh_voice01"),
        ("custom_speaker_id", "zh_voice01"),
        ("custom_speaker_id", ""),
        ("custom_speaker_id", 123),
    ],
)
async def test_query_voice_rejects_invalid_custom_name_payload(
    tmp_path, monkeypatch, voice_id, custom_speaker_id
):
    client = _install(monkeypatch, _FakeClient(_FakeResponse(body=b"{}")))
    adapter = VolcengineSeedTts30Adapter(_entry(tmp_path))
    with pytest.raises(ValueError):
        await adapter.query_voice(voice_id, custom_speaker_id)
    assert client.post_calls == []


@pytest.mark.asyncio
async def test_seed_voice_list_and_delete_remain_unsupported(tmp_path):
    adapter = VolcengineSeedTts30Adapter(_entry(tmp_path))
    with pytest.raises(NotImplementedError):
        await adapter.list_voice()
    with pytest.raises(NotImplementedError):
        await adapter.delete_voice(voice_id="S_created")
