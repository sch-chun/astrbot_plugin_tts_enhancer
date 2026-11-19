"""StepFun StepAudio 3 TTS 适配器离线测试（不依赖网络）。

覆盖：自动发现、能力文档、工具/提示词契约、参数校验与清洗、call_api 的请求
构造与错误语义、只读 list_voice 的归一化与短音色 ID，以及 mixin 只读能力。
"""

import os

import pytest
from astrbot_plugin_tts_enhancer.providers import ProviderFactory
from astrbot_plugin_tts_enhancer.providers.base import TTSProviderAdapter
from astrbot_plugin_tts_enhancer.providers.mixins import VoiceManageable
from astrbot_plugin_tts_enhancer.providers.stepfun_stepaudio_3_tts import (
    StepfunStepaudio3TtsAdapter,
)
from astrbot_plugin_tts_enhancer.providers.stepfun_stepaudio_3_tts import (
    logger as sf_logger,
)

KEY = "stepfun_stepaudio_3_tts"
ENTRY = {"__template_key": KEY, "api_key": "test-key", "voice": "cixingnansheng"}


def _make_adapter(**overrides):
    return StepfunStepaudio3TtsAdapter(dict(ENTRY, **overrides))


# ---------- 发现与契约 ----------


def test_discovery():
    ProviderFactory._discover_adapters()
    assert KEY in ProviderFactory._adapters
    cls = ProviderFactory._adapters[KEY]
    assert issubclass(cls, TTSProviderAdapter)
    assert issubclass(cls, VoiceManageable)
    assert cls.__name__ == "StepfunStepaudio3TtsAdapter"


def test_docs_loaded():
    assert _make_adapter().docs_content.strip()


def test_display_name():
    assert StepfunStepaudio3TtsAdapter.DISPLAY_NAME == "StepFun StepAudio 3 TTS"


def test_tool_schema_contract():
    tool = _make_adapter().get_tool_schema()
    assert tool.name == "tts_enhance"
    props = tool.parameters["properties"]
    assert set(props) == {"text", "instruction", "speed", "volume", "text_normalization"}
    assert tool.parameters["required"] == ["text"]
    assert props["text_normalization"]["enum"] == ["standard", "enhanced"]


def test_system_prompt_nonempty():
    assert _make_adapter().get_subagent_system_prompt().strip()


# ---------- 参数校验 / 清洗 ----------


def test_validate_accepts_empty():
    assert _make_adapter().validate_params({}) == (True, "")


@pytest.mark.parametrize(
    "params",
    [
        {"text": "x" * 1001},
        {"instruction": "x" * 501},
        {"instruction": 123},
        {"speed": 0.4},
        {"speed": 2.1},
        {"speed": True},
        {"volume": 0.05},
        {"volume": 2.1},
        {"text_normalization": "bogus"},
    ],
)
def test_validate_rejects_bad_params(params):
    ok, msg = _make_adapter().validate_params(params)
    assert ok is False and msg


def test_validate_accepts_numeric_strings():
    assert _make_adapter().validate_params({"speed": "1.2", "volume": "0.8"}) == (True, "")


def test_sanitize_only_present_allowed_keys():
    # {'text':'hi'} 必须原样输出（冒烟硬约束）；超范围/未知字段丢弃。
    assert _make_adapter().sanitize_params({"text": "hi"}) == {"text": "hi"}
    out = _make_adapter().sanitize_params(
        {"text": " hi ", "instruction": " 温柔 ", "speed": 1.2, "volume": 9, "junk": 1}
    )
    assert out == {"text": "hi", "instruction": "温柔", "speed": 1.2}


# ---------- HTTP 工具 ----------


def test_http_kwargs_injects_proxy():
    assert _make_adapter()._http_kwargs(60) == {"timeout": 60}
    adapter = _make_adapter(proxy="http://127.0.0.1:7890")
    assert adapter._http_kwargs(30) == {"timeout": 30, "proxy": "http://127.0.0.1:7890"}
    assert _make_adapter(proxy="   ")._http_kwargs(10) == {"timeout": 10}


# ---------- mock httpx ----------


class _FakeResp:
    def __init__(self, content, status=200, json_data=None):
        self._content = content
        self.status_code = status
        self._json = json_data if json_data is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            from httpx import HTTPStatusError

            raise HTTPStatusError("err", request=None, response=self)

    @property
    def content(self):
        return self._content

    @property
    def text(self):
        if isinstance(self._content, (bytes, bytearray)):
            return self._content.decode("utf-8", errors="replace")
        return str(self._content)

    def json(self):
        return self._json


class _FakeClient:
    def __init__(self, resp, get_resp=None):
        self._resp = resp
        self._get_resp = get_resp
        self.last_kwargs = None
        self.get_kwargs = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        self.last_kwargs = k
        return self._resp

    async def get(self, *a, **k):
        self.get_kwargs = k
        return self._get_resp if self._get_resp is not None else self._resp


def _patch_client(monkeypatch, fake):
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.stepfun_stepaudio_3_tts.httpx.AsyncClient",
        lambda *a, **k: fake,
    )


# ---------- call_api ----------


@pytest.mark.asyncio
async def test_call_api_payload_and_headers(tmp_path, monkeypatch):
    adapter = _make_adapter()
    entry = dict(adapter.entry, _data_dir=str(tmp_path))
    fake = _FakeClient(_FakeResp(b"\x00\x01" * 2000))
    _patch_client(monkeypatch, fake)

    path = await adapter.call_api(
        text="你好",
        raw_params={
            "text": "你好",
            "instruction": "语气轻柔",
            "speed": 1.2,
            "volume": 0.8,
            "text_normalization": "enhanced",
        },
        config=entry,
        voice_id="preview-voice",
    )
    assert path and path.endswith(".mp3") and os.path.exists(path)

    headers = fake.last_kwargs["headers"]
    assert headers["Authorization"] == "Bearer test-key"

    payload = fake.last_kwargs["json"]
    assert payload["model"] == "stepaudio-3-tts"
    assert payload["input"] == "你好"
    assert payload["voice"] == "preview-voice"  # voice_id 覆盖 config.voice
    assert payload["response_format"] == "mp3"
    assert payload["sample_rate"] == 24000
    assert payload["markdown_filter"] is True
    assert payload["instruction"] == "语气轻柔"
    assert payload["speed"] == 1.2
    assert payload["volume"] == 0.8
    assert payload["text_normalization"] == "enhanced"
    # 只含本接口支持的字段，不残留未白名单键
    assert "voice_label" not in payload
    assert "stream_format" not in payload


@pytest.mark.asyncio
async def test_call_api_empty_params_minimal_payload(tmp_path, monkeypatch):
    adapter = _make_adapter()
    entry = dict(adapter.entry, _data_dir=str(tmp_path))
    fake = _FakeClient(_FakeResp(b"\x00\x01" * 100))
    _patch_client(monkeypatch, fake)

    await adapter.call_api(text="你好", raw_params={}, config=entry)
    payload = fake.last_kwargs["json"]
    for k in ("instruction", "speed", "volume", "text_normalization", "pronunciation_map"):
        assert k not in payload
    assert payload["voice"] == "cixingnansheng"


@pytest.mark.asyncio
async def test_call_api_pronunciation_and_markdown(tmp_path, monkeypatch):
    adapter = _make_adapter()
    entry = dict(adapter.entry, _data_dir=str(tmp_path), pronunciation_tone="阿胶/e1胶,扁舟/偏舟", markdown_filter=False)
    fake = _FakeClient(_FakeResp(b"\x00\x01" * 100))
    _patch_client(monkeypatch, fake)

    await adapter.call_api(text="hi", raw_params={}, config=entry)
    payload = fake.last_kwargs["json"]
    assert payload["pronunciation_map"] == {"tone": ["阿胶/e1胶", "扁舟/偏舟"]}
    assert payload["markdown_filter"] is False


@pytest.mark.asyncio
async def test_call_api_missing_key_or_voice_returns_empty():
    assert await _make_adapter().call_api(text="hi", raw_params={}, config={}) == ""
    assert (
        await StepfunStepaudio3TtsAdapter(
            {"__template_key": KEY, "api_key": "k"}
        ).call_api(text="hi", raw_params={}, config={"api_key": "k"})
        == ""
    )


@pytest.mark.asyncio
async def test_call_api_text_too_long_no_http(tmp_path, monkeypatch):
    adapter = _make_adapter()
    fake = _FakeClient(_FakeResp(b""))
    _patch_client(monkeypatch, fake)
    path = await adapter.call_api(
        text="x" * 1001, raw_params={}, config=dict(adapter.entry, _data_dir=str(tmp_path))
    )
    assert path == ""
    assert fake.last_kwargs is None  # 未发起 HTTP


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 402, 429, 451, 500, 503])
async def test_call_api_http_errors_return_empty(status, monkeypatch):
    adapter = _make_adapter()
    fake = _FakeClient(_FakeResp(b"", status=status, json_data={"message": "boom"}))
    _patch_client(monkeypatch, fake)
    path = await adapter.call_api(
        text="hi", raw_params={}, config=dict(adapter.entry, _data_dir="/tmp/x")
    )
    assert path == ""


@pytest.mark.asyncio
async def test_call_api_empty_content_returns_empty(tmp_path, monkeypatch):
    fake = _FakeClient(_FakeResp(b""))
    _patch_client(monkeypatch, fake)
    path = await _make_adapter().call_api(
        text="hi", raw_params={}, config=dict(ENTRY, _data_dir=str(tmp_path))
    )
    assert path == ""


@pytest.mark.asyncio
async def test_call_api_http_error_message_logged(monkeypatch):
    captured = {}
    monkeypatch.setattr(sf_logger, "error", lambda m, *a, **k: captured.setdefault("msg", m))
    fake = _FakeClient(_FakeResp(b"", status=402, json_data={"message": "no credit"}))
    _patch_client(monkeypatch, fake)
    await _make_adapter().call_api(
        text="hi", raw_params={}, config=dict(ENTRY, _data_dir="/tmp/x")
    )
    assert "no credit" in captured["msg"]


# ---------- 只读音色列表 ----------


def _voices_payload():
    return {
        "voices": ["Jake", "Nick", "cixingnansheng", "elegantgentle-female", "wenrounansheng"],
        "voices-details": {
            "cixingnansheng": {
                "voice-name": "磁性男声",
                "voice-description": "深情厚重，有感染力",
                "recommended_scene": "有声书、情感陪伴",
            },
            "elegantgentle-female": {
                "voice-name": "气质温婉",
                "voice-description": "温柔优雅",
                "recommended-scene": "客服与业务办理、口播",
            },
        },
    }


@pytest.mark.asyncio
async def test_list_voice_normalizes_and_keeps_short_ids(monkeypatch):
    adapter = _make_adapter()
    get_resp = _FakeResp(b"", json_data=_voices_payload())
    fake = _FakeClient(None, get_resp=get_resp)
    _patch_client(monkeypatch, fake)

    result = await adapter.list_voice()
    assert result["total"] == len(result["items"]) == 5
    ids = {v["voice_id"] for v in result["items"]}
    # 短音色 ID（< 8）必须保留——适配器不调用 validate_voice_id
    assert {"Jake", "Nick"} <= ids
    by_id = {v["voice_id"]: v for v in result["items"]}
    assert by_id["cixingnansheng"]["voice_name"] == "磁性男声"
    assert by_id["cixingnansheng"]["description"] == "深情厚重，有感染力"
    assert by_id["cixingnansheng"]["type"] == "system"
    # 推荐场景：官方 recommended_scene 与连字符 recommended-scene 两种字段名都要兼容
    assert by_id["cixingnansheng"]["recommended_scene"] == "有声书、情感陪伴"
    assert by_id["elegantgentle-female"]["recommended_scene"] == "客服与业务办理、口播"
    # 详情缺失时用 voice_id 兜底名称、空描述、空场景
    assert by_id["wenrounansheng"]["voice_name"] == "wenrounansheng"
    assert by_id["wenrounansheng"]["description"] == ""
    assert by_id["wenrounansheng"]["recommended_scene"] == ""
    # GET 带 model 参数与 Bearer 头
    assert fake.get_kwargs["params"] == {"model": "stepaudio-3-tts"}
    assert fake.get_kwargs["headers"]["Authorization"] == "Bearer test-key"


@pytest.mark.asyncio
async def test_list_voice_missing_key_returns_empty():
    result = await StepfunStepaudio3TtsAdapter(
        {"__template_key": KEY}
    ).list_voice()
    assert result == {"items": [], "total": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 429, 500])
async def test_list_voice_http_error_returns_empty(status, monkeypatch):
    fake = _FakeClient(None, get_resp=_FakeResp(b"", status=status, json_data={"message": "x"}))
    _patch_client(monkeypatch, fake)
    assert await _make_adapter().list_voice() == {"items": [], "total": 0}


@pytest.mark.asyncio
async def test_list_voice_handles_dict_voices(monkeypatch):
    # 兼容 voices 为 {id: ...} 的形态
    payload = {
        "voices": {"cixingnansheng": {}, "Jake": {}},
        "voices-details": {"cixingnansheng": {"voice-name": "磁性男声"}},
    }
    fake = _FakeClient(None, get_resp=_FakeResp(b"", json_data=payload))
    _patch_client(monkeypatch, fake)
    result = await _make_adapter().list_voice()
    assert result["total"] == 2
    assert {v["voice_id"] for v in result["items"]} == {"cixingnansheng", "Jake"}


# ---------- 已复刻音色列表（voice_type=cloned） ----------


def _cloned_payload():
    return {
        "object": "list",
        "data": [
            {"id": "voice-tone-aaa", "file_id": "file-aaa", "created_at": 1742374363},
            {"id": "voice-tone-bbb", "file_id": "file-bbb", "created_at": 1742374400},
        ],
        "has_more": False,
        "first_id": "voice-tone-aaa",
        "last_id": "voice-tone-bbb",
    }


@pytest.mark.asyncio
async def test_list_voice_cloned_normalizes(monkeypatch):
    adapter = _make_adapter()
    fake = _FakeClient(None, get_resp=_FakeResp(b"", json_data=_cloned_payload()))
    _patch_client(monkeypatch, fake)

    result = await adapter.list_voice(voice_type="cloned")
    assert result["total"] == len(result["items"]) == 2
    first = result["items"][0]
    assert first == {
        "voice_id": "voice-tone-aaa",
        "file_id": "file-aaa",
        "created_at": 1742374363,
        "type": "cloned",
    }
    # GET /v1/audio/voices 带 limit=100（字符串）与 Bearer 头
    assert fake.get_kwargs["params"] == {"limit": "100"}
    assert fake.get_kwargs["headers"]["Authorization"] == "Bearer test-key"


@pytest.mark.asyncio
async def test_list_voice_cloned_skips_bad_entries(monkeypatch):
    payload = {
        "data": [
            {"id": "v1"},                       # 缺 file_id/created_at → 空串/None 兜底
            {"file_id": "no-id"},               # 无 id → 跳过
            "not-a-dict",                       # 非 dict → 跳过
            {"voice_id": "alt-id"},             # 兼容 voice_id 字段
        ]
    }
    fake = _FakeClient(None, get_resp=_FakeResp(b"", json_data=payload))
    _patch_client(monkeypatch, fake)
    result = await _make_adapter().list_voice(voice_type="cloned")
    ids = [v["voice_id"] for v in result["items"]]
    assert ids == ["v1", "alt-id"]
    assert result["items"][0]["file_id"] == ""
    assert all(v["type"] == "cloned" for v in result["items"])


@pytest.mark.asyncio
async def test_list_voice_cloned_empty_when_no_data(monkeypatch):
    fake = _FakeClient(None, get_resp=_FakeResp(b"", json_data={"object": "list", "data": []}))
    _patch_client(monkeypatch, fake)
    assert await _make_adapter().list_voice(voice_type="cloned") == {"items": [], "total": 0}


@pytest.mark.asyncio
async def test_list_voice_cloned_missing_key_returns_empty():
    result = await StepfunStepaudio3TtsAdapter(
        {"__template_key": KEY}
    ).list_voice(voice_type="cloned")
    assert result == {"items": [], "total": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 429, 500])
async def test_list_voice_cloned_http_error_returns_empty(status, monkeypatch):
    fake = _FakeClient(None, get_resp=_FakeResp(b"", status=status, json_data={"message": "x"}))
    _patch_client(monkeypatch, fake)
    assert await _make_adapter().list_voice(voice_type="cloned") == {"items": [], "total": 0}


@pytest.mark.asyncio
async def test_list_voice_system_default_unchanged(monkeypatch):
    # 未传 voice_type 仍走 system_voices，且参数只带 model（不带 limit）
    fake = _FakeClient(None, get_resp=_FakeResp(b"", json_data=_voices_payload()))
    _patch_client(monkeypatch, fake)
    result = await _make_adapter().list_voice()
    assert fake.get_kwargs["params"] == {"model": "stepaudio-3-tts"}
    assert all(v["type"] == "system" for v in result["items"])


# ---------- 只读能力（create/delete 未覆写） ----------


@pytest.mark.asyncio
async def test_create_delete_raise_not_implemented():
    adapter = _make_adapter()
    with pytest.raises(NotImplementedError):
        await adapter.create_voice({})
    with pytest.raises(NotImplementedError):
        await adapter.delete_voice(voice_id="x")
