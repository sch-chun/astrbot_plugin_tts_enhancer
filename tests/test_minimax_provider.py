"""providers/minimax_speech_2_8.py 单元测试。

以 MiniMax 适配器为代表验证供应商层契约：API 调用降级、参数校验、
音色克隆/设计的参数处理与错误传播。所有 HTTP 交互均被替换以避免真实请求。
"""

from datetime import datetime

import httpx
import pytest
from astrbot_plugin_tts_enhancer.providers.minimax_speech_2_8 import (
    MinimaxSpeech2_8Adapter,
)

MODULE = "astrbot_plugin_tts_enhancer.providers.minimax_speech_2_8"
TEMPLATE_KEY = "minimax_speech_2_8"


class FakeResponse:
    """httpx.Response 替身。"""

    def __init__(self, payload: dict, raise_status: Exception | None = None):
        self._payload = payload
        self._raise = raise_status

    def raise_for_status(self):
        if self._raise:
            raise self._raise

    def json(self):
        return self._payload

    @property
    def content(self):
        return b"fake-audio-bytes"


class FakeAsyncClient:
    """httpx.AsyncClient 替身，记录所有请求以便断言。"""

    def __init__(self, response: FakeResponse, *args, **kwargs):
        self._response = response
        self.requests: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        self.requests.append({"method": "POST", "url": url, **kwargs})
        return self._response

    async def get(self, url, **kwargs):
        self.requests.append({"method": "GET", "url": url, **kwargs})
        return self._response


def _install_fake_httpx(monkeypatch, response: FakeResponse, recorder: dict):
    """将 httpx.AsyncClient 替换为替身，并把实例存入 recorder['client']。"""

    def _factory(*args, **kwargs):
        client = FakeAsyncClient(response, *args, **kwargs)
        recorder["client"] = client
        return client

    monkeypatch.setattr(httpx, "AsyncClient", _factory)
    return recorder


@pytest.fixture
def recorder():
    return {}


@pytest.fixture
def adapter():
    return MinimaxSpeech2_8Adapter({"__template_key": TEMPLATE_KEY})


@pytest.fixture
def ok_resp():
    """MiniMax 成功的 base_resp + 音频 hex。"""
    return FakeResponse(
        {"base_resp": {"status_code": 0}, "data": {"audio": "deadbeef"}}
    )


class TestCallApiGuards:
    """call_api 的前置校验与降级。"""

    async def test_missing_api_key_returns_empty(
        self, adapter, monkeypatch, recorder, ok_resp
    ):
        _install_fake_httpx(monkeypatch, ok_resp, recorder)
        result = await adapter.call_api(
            text="hi", raw_params={}, config={"voice_id": "Testvoice1"}
        )
        assert result == ""
        assert recorder.get("client") is None  # 未发起任何请求

    async def test_missing_voice_id_raises(self, adapter):
        with pytest.raises(ValueError, match="未提供音色 ID"):
            await adapter.call_api(text="hi", raw_params={}, config={"api_key": "k"})

    async def test_empty_text_returns_empty(
        self, adapter, monkeypatch, recorder, ok_resp
    ):
        _install_fake_httpx(monkeypatch, ok_resp, recorder)
        result = await adapter.call_api(
            text="", raw_params={}, config={"api_key": "k", "voice_id": "Testvoice1"}
        )
        assert result == ""

    async def test_explicit_text_none_in_params_returns_empty(
        self, adapter, monkeypatch, recorder, ok_resp
    ):
        """raw_params 中存在 text 但为 None 时不应回落到入参 text。"""
        _install_fake_httpx(monkeypatch, ok_resp, recorder)
        result = await adapter.call_api(
            text="fallback",
            raw_params={"text": None},
            config={"api_key": "k", "voice_id": "Testvoice1"},
        )
        assert result == ""

    async def test_data_dir_missing_returns_empty(
        self, adapter, monkeypatch, recorder, ok_resp
    ):
        """缺少 _data_dir 时 save_audio_bytes 返回空串。"""
        _install_fake_httpx(monkeypatch, ok_resp, recorder)
        result = await adapter.call_api(
            text="hi", raw_params={}, config={"api_key": "k", "voice_id": "Testvoice1"}
        )
        assert result == ""


class TestCallApiSuccess:
    async def test_saves_and_returns_path(
        self, adapter, monkeypatch, recorder, ok_resp, tmp_path
    ):
        _install_fake_httpx(monkeypatch, ok_resp, recorder)
        path = await adapter.call_api(
            text="你好",
            raw_params={"speed": 1.2},
            config={
                "api_key": "k",
                "voice_id": "Testvoice1",
                "_data_dir": str(tmp_path),
            },
        )
        assert path.endswith(".mp3")
        from pathlib import Path

        assert Path(path).read_bytes() == bytes.fromhex("deadbeef")

    async def test_unsupported_model_falls_back_to_hd(
        self, adapter, monkeypatch, recorder, ok_resp, tmp_path
    ):
        _install_fake_httpx(monkeypatch, ok_resp, recorder)
        await adapter.call_api(
            text="hi",
            raw_params={},
            config={
                "api_key": "k",
                "voice_id": "Testvoice1",
                "model": "Ultra",
                "_data_dir": str(tmp_path),
            },
        )
        payload = recorder["client"].requests[0]["json"]
        assert payload["model"] == "speech-2.8-hd"

    async def test_api_error_returns_empty(self, adapter, monkeypatch, recorder):
        resp = FakeResponse(
            {"base_resp": {"status_code": 2049, "status_msg": "内部错误"}}
        )
        _install_fake_httpx(monkeypatch, resp, recorder)
        result = await adapter.call_api(
            text="hi",
            raw_params={},
            config={"api_key": "k", "voice_id": "Testvoice1", "_data_dir": "/tmp"},
        )
        assert result == ""

    async def test_missing_audio_field_returns_empty(
        self, adapter, monkeypatch, recorder
    ):
        resp = FakeResponse({"base_resp": {"status_code": 0}, "data": {}})
        _install_fake_httpx(monkeypatch, resp, recorder)
        result = await adapter.call_api(
            text="hi",
            raw_params={},
            config={"api_key": "k", "voice_id": "Testvoice1", "_data_dir": "/tmp"},
        )
        assert result == ""

    async def test_invalid_hex_returns_empty(self, adapter, monkeypatch, recorder):
        resp = FakeResponse(
            {"base_resp": {"status_code": 0}, "data": {"audio": "zzzz"}}
        )
        _install_fake_httpx(monkeypatch, resp, recorder)
        result = await adapter.call_api(
            text="hi",
            raw_params={},
            config={"api_key": "k", "voice_id": "Testvoice1", "_data_dir": "/tmp"},
        )
        assert result == ""

    async def test_timeout_returns_empty(self, adapter, monkeypatch, recorder):
        resp = FakeResponse({}, raise_status=httpx.TimeoutException("timeout"))
        _install_fake_httpx(monkeypatch, resp, recorder)
        result = await adapter.call_api(
            text="hi",
            raw_params={},
            config={"api_key": "k", "voice_id": "Testvoice1", "_data_dir": "/tmp"},
        )
        assert result == ""

    async def test_latex_read_forces_chinese(
        self, adapter, monkeypatch, recorder, ok_resp, tmp_path
    ):
        _install_fake_httpx(monkeypatch, ok_resp, recorder)
        await adapter.call_api(
            text="$x^2$",
            raw_params={"latex_read": True, "language_boost": "English"},
            config={
                "api_key": "k",
                "voice_id": "Testvoice1",
                "_data_dir": str(tmp_path),
            },
        )
        payload = recorder["client"].requests[0]["json"]
        assert payload["language_boost"] == "Chinese"
        assert payload["latex_read"] is True


class TestValidateParams:
    """参数校验的合法/非法分支。"""

    @pytest.mark.parametrize(
        "params",
        [
            {"speed": 1.0},
            {"speed": 0.5},
            {"speed": 2.0},
            {"vol": 0.0},
            {"vol": 10.0},
            {"pitch": -12},
            {"pitch": 12},
            {"emotion": "happy"},
            {"language_boost": "auto"},
            {"language_boost": "Chinese,Yue"},
        ],
    )
    def test_valid_boundaries(self, adapter, params):
        ok, msg = adapter.validate_params(params)
        assert ok is True
        assert msg == ""

    @pytest.mark.parametrize(
        "params",
        [
            {"speed": 0.4},
            {"speed": 2.1},
            {"vol": -0.1},
            {"vol": 10.1},
            {"pitch": -13},
            {"pitch": 13},
            {"emotion": "euphoric"},
            {"language_boost": "Klingon"},
        ],
    )
    def test_invalid_values(self, adapter, params):
        ok, msg = adapter.validate_params(params)
        assert ok is False
        assert msg

    def test_empty_params_valid(self, adapter):
        assert adapter.validate_params({}) == (True, "")


class TestSanitizeParams:
    def test_keeps_valid_and_drops_invalid(self, adapter):
        out = adapter.sanitize_params(
            {"text": "hi", "speed": 1.5, "emotion": "bogus", "vol": 99}
        )
        assert out["text"] == "hi"
        assert out["speed"] == 1.5
        assert "emotion" not in out
        assert "vol" not in out

    def test_coerces_string_numbers_to_float(self, adapter):
        """P1-5 回归：LLM 以字符串返回的 speed/vol/pitch 应在 sanitize 阶段转成数值，
        否则会以字符串原样进入 voice_setting 传给 API（与百炼归一行为不对称）。"""
        out = adapter.sanitize_params(
            {"text": "hi", "speed": "1.5", "vol": "2", "pitch": "-3"}
        )
        assert out["speed"] == 1.5
        assert out["vol"] == 2.0
        assert out["pitch"] == -3.0

    def test_always_contains_text_key(self, adapter):
        assert adapter.sanitize_params({})["text"] == ""


class TestCreateVoiceRouting:
    async def test_infers_clone_from_file_id(self, adapter, monkeypatch):
        called = {}

        async def fake_clone(params):
            called["clone"] = params
            return {"voice_id": "x"}

        monkeypatch.setattr(adapter, "_create_voice_by_clone", fake_clone)
        await adapter.create_voice({"file_id": 123})
        assert called["clone"]["file_id"] == 123

    async def test_infers_design_from_prompt(self, adapter, monkeypatch):
        called = {}

        async def fake_design(params):
            called["design"] = params
            return {"voice_id": "x"}

        monkeypatch.setattr(adapter, "_create_voice_by_design", fake_design)
        await adapter.create_voice({"prompt": "温柔女声", "preview_text": "你好"})
        assert called["design"]["prompt"] == "温柔女声"

    async def test_uninferable_mode_raises(self, adapter):
        with pytest.raises(ValueError, match="无法推断创建模式"):
            await adapter.create_voice({})

    async def test_unknown_mode_raises(self, adapter):
        with pytest.raises(ValueError, match="未知模式"):
            await adapter.create_voice({"mode": "telepathy"})


class TestCloneRequirements:
    async def test_missing_api_key_raises(self, adapter):
        with pytest.raises(ValueError, match="API Key 未配置"):
            await adapter._create_voice_by_clone({"file_id": 1})

    async def test_missing_file_id_raises(self, adapter):
        ad = MinimaxSpeech2_8Adapter({"__template_key": TEMPLATE_KEY, "api_key": "k"})
        with pytest.raises(ValueError, match="file_id 为必填"):
            await ad._create_voice_by_clone({})

    async def test_invalid_custom_voice_id_raises(self, adapter):
        ad = MinimaxSpeech2_8Adapter({"__template_key": TEMPLATE_KEY, "api_key": "k"})
        with pytest.raises(ValueError, match="voice_id"):
            await ad._create_voice_by_clone({"file_id": 1, "voice_id": "短"})

    async def test_prompt_file_without_text_raises(self, adapter):
        ad = MinimaxSpeech2_8Adapter({"__template_key": TEMPLATE_KEY, "api_key": "k"})
        with pytest.raises(ValueError, match="prompt_text"):
            await ad._create_voice_by_clone(
                {"file_id": 1, "prompt_file_id": 2, "prompt_text": "   "}
            )


class TestVoiceQueryGuards:
    async def test_list_voice_bad_type_raises(self, adapter):
        ad = MinimaxSpeech2_8Adapter({"__template_key": TEMPLATE_KEY, "api_key": "k"})
        with pytest.raises(ValueError, match="voice_type"):
            await ad.list_voice(voice_type="bogus")

    async def test_delete_voice_requires_voice_id(self, adapter):
        ad = MinimaxSpeech2_8Adapter({"__template_key": TEMPLATE_KEY, "api_key": "k"})
        with pytest.raises(ValueError, match="voice_id 为必填"):
            await ad.delete_voice(voice_type="voice_cloning")

    async def test_delete_voice_requires_voice_type(self, adapter):
        ad = MinimaxSpeech2_8Adapter({"__template_key": TEMPLATE_KEY, "api_key": "k"})
        with pytest.raises(ValueError, match="voice_type 为必填"):
            await ad.delete_voice(voice_id="Testvoice1")


class TestToolSchema:
    def test_schema_shape(self, adapter):
        tool = adapter.get_tool_schema()
        assert tool.name == "tts_enhance"
        props = tool.parameters["properties"]
        assert "text" in props
        assert tool.parameters["required"] == ["text"]
        assert props["speed"]["minimum"] == 0.5
        assert props["pitch"]["type"] == "integer"


class TestParamValidationRegression:
    """参数校验回归用例（非 xfail，修复后必须稳定通过）。"""

    def test_string_number_should_be_accepted_gracefully(self, adapter):
        """原缺陷#8 回归：LLM 以字符串返回数字时不应抛 TypeError。

        值合法则接受（"1.5" → 1.5），值非法则友好返回校验失败。
        """
        ok, msg = adapter.validate_params({"speed": "1.5"})
        assert ok is True, msg

    def test_invalid_string_number_rejected_gracefully(self, adapter):
        ok, _ = adapter.validate_params({"speed": "abc"})
        assert ok is False

    def test_none_value_rejected_gracefully(self, adapter):
        """None 应返回校验失败而非抛 TypeError。"""
        ok, _ = adapter.validate_params({"speed": None})
        assert ok is False

    def test_bool_speed_should_be_rejected(self, adapter):
        """原缺陷#9（P3-3a）回归：bool 是 int 子类，True 不应被当作 1 通过。

        该入参来自 LLM Function Calling 输出，AstrBot 的 schema 校验不覆盖此路径，
        因此排 bool 属本仓库责任。
        """
        assert adapter.validate_params({"speed": True})[0] is False
        assert adapter.validate_params({"speed": False})[0] is False

    async def test_mode_should_be_case_insensitive(self, adapter):
        """原缺陷#10 回归：mode 大小写不敏感。"""
        ad = MinimaxSpeech2_8Adapter({"__template_key": TEMPLATE_KEY, "api_key": "k"})
        for variant in ("Clone", "clone", "CLONE"):
            with pytest.raises(ValueError, match="file_id 为必填"):  # 已进入 clone 分支
                await ad.create_voice({"mode": variant})

    def test_generated_voice_id_should_be_unique(self, adapter, monkeypatch):
        """原缺陷#11 回归：自动生成的 voice_id 必须含随机熵。

        调用真实生成方法（而非在测试里复现公式），
        确保同一实例在同一秒内重复生成也不会碰撞。
        """

        class _FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 1, 1, 0, 0, 0)

        monkeypatch.setattr(f"{MODULE}.datetime", _FrozenDatetime)
        ad = MinimaxSpeech2_8Adapter({"__template_key": TEMPLATE_KEY, "api_key": "k"})
        seen = set()
        for _ in range(5):
            seen.add(ad._generate_voice_id())
        assert len(seen) == 5

    def test_generated_voice_id_matches_naming_rule(self, adapter):
        """自动生成的 voice_id 必须满足命名规则（首字母+末字母数字）。"""
        import re

        vid = adapter._generate_voice_id()
        assert re.match(r"^[A-Za-z][A-Za-z0-9\-_]*[A-Za-z0-9]$", vid), vid
