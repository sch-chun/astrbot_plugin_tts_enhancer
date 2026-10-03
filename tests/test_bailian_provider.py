"""providers/_bailian_speech_synthesizer.py 单元测试。

验证百炼适配器的参数处理与 Data URL 音色复刻契约：
- LLM 以字符串返回数字时正常接受（修复前一律被 isinstance 守卫拒掉）；
- bool 不再泄漏为 1（修复前 isinstance(x, (int, float)) 放过了 bool）；
- 越界 / 非法值友好拒绝而非抛 TypeError；
- 复刻链路只接受受支持 MIME、有效 Base64 且不超过 10MB 的 Data URL。
"""

import base64

import httpx
import pytest
from astrbot_plugin_tts_enhancer.providers import _bailian_speech_synthesizer as bailian_module
from astrbot_plugin_tts_enhancer.providers._bailian_speech_synthesizer import (
    BailianSpeechSynthesizerAdapter,
    _validate_clone_data_url,
)
from astrbot_plugin_tts_enhancer.providers.bailian_qwen_audio_3_0_tts import (
    BailianQwenAudio3_0TTSAdapter,
)

TEMPLATE_KEY = "bailian_speech_synthesizer"


@pytest.fixture
def adapter():
    return BailianSpeechSynthesizerAdapter({"__template_key": TEMPLATE_KEY})


class TestValidateParams:
    @pytest.mark.parametrize(
        "params",
        [
            {"volume": 50},
            {"volume": 0},
            {"volume": 100},
            {"volume": 50.0},  # 整型浮点接受
            {"rate": 1.0},
            {"rate": 0.5},
            {"rate": 2.0},
            {"pitch": 1.5},
            {"pitch": 0.5},
            {"pitch": 2.0},
            {"language_hints": ["zh"]},
        ],
    )
    def test_valid(self, adapter, params):
        ok, msg = adapter.validate_params(params)
        assert ok is True, msg

    @pytest.mark.parametrize(
        "params",
        [
            {"volume": -1},
            {"volume": 101},
            {"volume": 50.5},  # 非整型浮点拒绝
            {"rate": 0.4},
            {"rate": 2.1},
            {"pitch": 0.4},
            {"pitch": 2.1},
            {"language_hints": "zh"},  # 非列表
            {"language_hints": ["klingon"]},
        ],
    )
    def test_invalid(self, adapter, params):
        ok, msg = adapter.validate_params(params)
        assert ok is False
        assert msg

    def test_empty_valid(self, adapter):
        assert adapter.validate_params({}) == (True, "")


class TestValidateParamsTypeTolerance:
    """引入 _as_int / _as_float 后的类型收敛。"""

    def test_string_number_accepted(self, adapter):
        """LLM 以字符串返回数字时不再被 isinstance 守卫拒掉。"""
        assert adapter.validate_params({"rate": "1.5"})[0] is True
        assert adapter.validate_params({"pitch": "1.5"})[0] is True
        assert adapter.validate_params({"volume": "50"})[0] is True

    def test_string_number_rejected_when_out_of_range(self, adapter):
        ok, _ = adapter.validate_params({"rate": "9.9"})
        assert ok is False

    def test_invalid_string_rejected(self, adapter):
        assert adapter.validate_params({"rate": "abc"})[0] is False
        assert adapter.validate_params({"volume": "abc"})[0] is False

    def test_bool_not_treated_as_one(self, adapter):
        """bool 是 int 子类，修复前 isinstance(x, (int, float)) 会放过 True 当作 1。"""
        assert adapter.validate_params({"rate": True})[0] is False
        assert adapter.validate_params({"pitch": True})[0] is False
        assert adapter.validate_params({"volume": True})[0] is False


class TestSanitizeParams:
    def test_string_number_converted_to_real_number(self, adapter):
        out = adapter.sanitize_params({"rate": "1.5", "volume": "50", "pitch": "1.0"})
        assert out["rate"] == 1.5
        assert out["volume"] == 50
        assert out["pitch"] == 1.0

    def test_invalid_dropped(self, adapter):
        out = adapter.sanitize_params({"rate": "abc", "volume": 200})
        assert "rate" not in out
        assert "volume" not in out

    def test_bool_dropped(self, adapter):
        out = adapter.sanitize_params({"rate": True})
        assert "rate" not in out


class FakeResponse:
    """百炼音色管理响应替身。"""

    def __init__(self, payload: dict, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload


class FakeAsyncClient:
    """记录发往百炼的请求，避免测试触发真实网络。"""

    def __init__(self, response: FakeResponse, recorder: dict, *args, **kwargs):
        self._response = response
        self._recorder = recorder

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        self._recorder["request"] = {"url": url, **kwargs}
        return self._response


def _install_fake_httpx(monkeypatch, recorder, response=None):
    response = response or FakeResponse(
        {"output": {"voice_id": "qwen-audio-3.0-tts-flash-test-123456"}}
    )

    def factory(*args, **kwargs):
        return FakeAsyncClient(response, recorder, *args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def _data_url(mime_type="audio/wav", content=b"voice sample"):
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


class TestCloneDataUrlValidation:
    @pytest.mark.parametrize("mime_type", ["audio/wav", "audio/mpeg", "audio/mp4"])
    def test_accepts_documented_audio_mime_types(self, mime_type):
        assert _validate_clone_data_url(_data_url(mime_type)) == (
            mime_type,
            len(b"voice sample"),
        )

    @pytest.mark.parametrize(
        "value, message",
        [
            ("https://example.com/voice.wav", "必须是 Base64 Data URL"),
            ("data:audio/ogg;base64,dm9pY2U=", "不支持的复刻音频 MIME"),
            ("data:audio/wav;base64,%%%", "无效的 Base64"),
            ("data:audio/wav;base64,", "格式错误"),
        ],
    )
    def test_rejects_legacy_url_and_malformed_data(self, value, message):
        with pytest.raises(ValueError, match=message):
            _validate_clone_data_url(value)

    @pytest.mark.parametrize("value", [None, 123, {}, []])
    def test_rejects_non_string_input(self, value):
        with pytest.raises(ValueError, match="必须是 Base64 Data URL"):
            _validate_clone_data_url(value)

    def test_accepts_decoded_audio_at_limit(self, monkeypatch):
        monkeypatch.setattr(bailian_module, "_MAX_CLONE_AUDIO_BYTES", 3)
        assert _validate_clone_data_url(_data_url(content=b"abc"))[1] == 3

    def test_rejects_decoded_audio_over_limit(self, monkeypatch):
        monkeypatch.setattr(bailian_module, "_MAX_CLONE_AUDIO_BYTES", 2)
        with pytest.raises(ValueError, match="不得超过 10MB"):
            _validate_clone_data_url(_data_url(content=b"abc"))


class TestCreateVoiceWithDataUrl:
    @pytest.fixture
    def clone_adapter(self):
        return BailianQwenAudio3_0TTSAdapter(
            {
                "__template_key": "bailian_qwen_audio_3_0_tts",
                "workspace_id": "workspace-test",
                "api_key": "sk-test",
                "model": "flash",
            }
        )

    async def test_sends_data_url_without_logging_base64(
        self, clone_adapter, monkeypatch
    ):
        recorder = {}
        _install_fake_httpx(monkeypatch, recorder)
        debug_messages = []
        monkeypatch.setattr(
            bailian_module.logger,
            "debug",
            lambda message: debug_messages.append(str(message)),
        )
        audio_data_url = _data_url(content=b"sensitive voice bytes")

        result = await clone_adapter.create_voice(
            {
                "mode": "clone",
                "audio_data_url": audio_data_url,
                "prefix": "sample",
                "language_hints": ["zh"],
                "enable_volume_normalization": True,
                "enable_preprocess": True,
                "max_prompt_audio_length": 10,
                "model": "flash",
            }
        )

        request_payload = recorder["request"]["json"]
        assert result["voice_id"] == "qwen-audio-3.0-tts-flash-test-123456"
        assert request_payload["model"] == "voice-enrollment"
        assert request_payload["input"]["action"] == "create_voice"
        assert request_payload["input"]["url"] == audio_data_url
        assert request_payload["input"]["enable_volume_normalization"] == "true"
        assert request_payload["input"]["enable_preprocess"] is True
        assert request_payload["input"]["max_prompt_audio_length"] == 10.0
        assert all(audio_data_url not in message for message in debug_messages)
        assert any("<Data URL audio/wav" in message for message in debug_messages)

    async def test_redacts_data_url_from_upstream_error(
        self, clone_adapter, monkeypatch
    ):
        recorder = {}
        audio_data_url = _data_url(content=b"must not leak")
        response = FakeResponse(
            {"message": f"invalid input: {audio_data_url}"},
            status_code=400,
            text=f"invalid input: {audio_data_url}",
        )
        _install_fake_httpx(monkeypatch, recorder, response)

        with pytest.raises(RuntimeError) as exc_info:
            await clone_adapter.create_voice(
                {
                    "mode": "clone",
                    "audio_data_url": audio_data_url,
                    "prefix": "sample",
                    "model": "flash",
                }
            )

        error_text = str(exc_info.value)
        assert audio_data_url not in error_text
        assert "<Data URL omitted>" in error_text

    async def test_rejects_removed_legacy_audio_url_contract(
        self, clone_adapter, monkeypatch
    ):
        recorder = {}
        _install_fake_httpx(monkeypatch, recorder)

        with pytest.raises(ValueError, match="audio_data_url 为必填参数"):
            await clone_adapter.create_voice(
                {
                    "mode": "clone",
                    "audio_url": "https://example.com/voice.wav",
                    "prefix": "sample",
                    "model": "flash",
                }
            )

        assert "request" not in recorder
