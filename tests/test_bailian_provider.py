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
from unittest.mock import AsyncMock, MagicMock

from astrbot_plugin_tts_enhancer.providers import (
    _bailian_speech_synthesizer as bailian_module,
)
from astrbot_plugin_tts_enhancer.providers._bailian_speech_synthesizer import (
    BailianSpeechSynthesizerAdapter,
    _validate_clone_data_url,
)
from astrbot_plugin_tts_enhancer.providers.bailian_qwen_audio_3_0_tts import (
    BailianQwenAudio3_0TTSAdapter,
)
from astrbot_plugin_tts_enhancer.providers.bailian_qwen_audio_3_1_tts import (
    BailianQwenAudio3_1TTSAdapter,
)
from astrbot_plugin_tts_enhancer.providers.bailian_cosyvoice_v3_5 import (
    BailianCosyVoiceV3_5Adapter,
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
            {"enable_markdown_filter": True},
            {"enable_markdown_filter": False},
            {"enable_markdown_filter": "true"},  # LLM 字符串写法兼容
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
            {"enable_markdown_filter": 1},  # 数值 bool 陷阱
            {"enable_markdown_filter": "maybe"},
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

    def test_markdown_filter_kept_as_bool(self, adapter):
        out = adapter.sanitize_params({"enable_markdown_filter": True})
        assert out["enable_markdown_filter"] is True
        out = adapter.sanitize_params({"enable_markdown_filter": "false"})
        assert out["enable_markdown_filter"] is False

    def test_markdown_filter_invalid_dropped(self, adapter):
        out = adapter.sanitize_params({"enable_markdown_filter": 1})
        assert "enable_markdown_filter" not in out


class TestGetToolSchema:
    """tts_enhance 工具 schema 应暴露 Markdown 过滤开关。"""

    def test_markdown_filter_exposed(self, adapter):
        schema = adapter.get_tool_schema().parameters
        props = schema["properties"]
        assert props["enable_markdown_filter"]["type"] == "boolean"
        assert "Markdown" in props["enable_markdown_filter"]["description"]
        assert schema["required"] == ["text"]

    def test_markdown_filter_exposed_in_all_bailian_adapters(self):
        for cls in (
            BailianQwenAudio3_0TTSAdapter,
            BailianQwenAudio3_1TTSAdapter,
            BailianCosyVoiceV3_5Adapter,
        ):
            schema = cls({"__template_key": cls.__name__}).get_tool_schema().parameters
            assert "enable_markdown_filter" in schema["properties"]


class FakeResponse:
    """百炼音色管理响应替身。"""

    def __init__(self, payload: dict, status_code=200, text="", content=b""):
        self._payload = payload
        self.status_code = status_code
        self.text = text
        self.content = content

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "fake error", request=None, response=self
            )


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
        self._recorder.setdefault("requests", []).append({"url": url, **kwargs})
        self._recorder["request"] = self._recorder["requests"][-1]
        return self._response


def _install_fake_httpx(monkeypatch, recorder, response=None):
    # 默认桩模拟「创建即返回 voice_id、尚未带部署状态」的真实响应：部署状态
    # 应在 query_voice 中查询，而非出现在 create 响应里。
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

        # 创建后会额外轮询 query_voice，取 action=create_voice 的请求做断言。
        create_request = next(
            r for r in recorder["requests"]
            if r["json"]["input"]["action"] == "create_voice"
        )
        request_payload = create_request["json"]
        assert result["voice_id"] == "qwen-audio-3.0-tts-flash-test-123456"
        assert request_payload["model"] == "voice-enrollment"
        assert request_payload["input"]["action"] == "create_voice"
        assert request_payload["input"]["audio"] == audio_data_url
        assert request_payload["input"]["enable_volume_normalization"] == "true"
        assert request_payload["input"]["enable_preprocess"] is True
        assert request_payload["input"]["max_prompt_audio_length"] == 10.0
        assert all(audio_data_url not in message for message in debug_messages)
        assert any("<Data URL audio/wav" in message for message in debug_messages)

        # 后端创建即返回初始状态 DEPLOYING，不再轮询 query_voice（进度交由前端）。
        assert result["status"] == "DEPLOYING"
        query_requests = [
            r for r in recorder["requests"]
            if r["json"]["input"]["action"] == "query_voice"
        ]
        assert query_requests == [], "create_voice 不应发起 query_voice 轮询"

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


    async def test_create_returns_initial_status_without_querying(
        self, clone_adapter, monkeypatch
    ):
        """创建即返回初始 DEPLOYING 状态，且不发起 query_voice 轮询。"""
        recorder = {}
        _install_fake_httpx(monkeypatch, recorder)
        query_spy = AsyncMock()
        monkeypatch.setattr(clone_adapter, "query_voice", query_spy)

        result = await clone_adapter.create_voice(
            {
                "mode": "clone",
                "audio_data_url": _data_url(),
                "prefix": "sample",
                "model": "flash",
            }
        )

        # 后端不阻塞等待部署，也不主动查询状态；真实进度由前端轮询 /voice/query。
        assert query_spy.await_count == 0, "create_voice 不应查询音色状态"
        assert result["voice_id"] == "qwen-audio-3.0-tts-flash-test-123456"
        assert result["status"] == "DEPLOYING"
        query_requests = [
            r for r in recorder["requests"]
            if r["json"]["input"]["action"] == "query_voice"
        ]
        assert query_requests == [], "create_voice 不应发起 query_voice 请求"

    async def test_create_returns_upstream_status_when_present(
        self, clone_adapter, monkeypatch
    ):
        """若 create 响应已带 output.status（如秒回 OK），应原样返回，不盲等一轮。"""
        recorder = {}
        response = FakeResponse(
            {"output": {"voice_id": "qwen-audio-3.0-tts-flash-test-123456", "status": "OK"}}
        )
        _install_fake_httpx(monkeypatch, recorder, response)
        query_spy = AsyncMock()
        monkeypatch.setattr(clone_adapter, "query_voice", query_spy)

        result = await clone_adapter.create_voice(
            {
                "mode": "clone",
                "audio_data_url": _data_url(),
                "prefix": "sample",
                "model": "flash",
            }
        )

        assert query_spy.await_count == 0, "create_voice 不应查询音色状态"
        assert result["voice_id"] == "qwen-audio-3.0-tts-flash-test-123456"
        assert result["status"] == "OK", "应原样返回 create 响应的 output.status"
        query_requests = [
            r for r in recorder["requests"]
            if r["json"]["input"]["action"] == "query_voice"
        ]
        assert query_requests == [], "create_voice 不应发起 query_voice 请求"


class TestVoiceDesignDeploymentPolling:
    """_create_voice_by_design 创建后同样需轮询 query_voice 直到 OK。"""

    @pytest.fixture
    def design_adapter(self):
        return BailianQwenAudio3_0TTSAdapter(
            {
                "__template_key": "bailian_qwen_audio_3_0_tts",
                "workspace_id": "workspace-test",
                "api_key": "sk-test",
                "model": "flash",
            }
        )

    async def test_design_creates_without_polling(self, design_adapter, monkeypatch):
        recorder = {}
        _install_fake_httpx(monkeypatch, recorder)

        result = await design_adapter.create_voice(
            {
                "mode": "design",
                "voice_prompt": "温柔清晰的中文女声",
                "preview_text": "这是一段预览文本",
                "prefix": "design",
                "language_hints": ["zh"],
                "model": "flash",
            }
        )

        assert result["voice_id"] == "qwen-audio-3.0-tts-flash-test-123456"
        assert result["status"] == "DEPLOYING"

        # 设计路径创建请求体不含 audio 字段（参考音频只用于复刻）。
        create_request = next(
            r for r in recorder["requests"]
            if r["json"]["input"]["action"] == "create_voice"
        )
        assert "audio" not in create_request["json"]["input"]
        assert create_request["json"]["input"]["voice_prompt"] == "温柔清晰的中文女声"

        # 设计路径创建后同样不发起 query_voice（进度交由前端轮询 /voice/query）。
        query_requests = [
            r for r in recorder["requests"]
            if r["json"]["input"]["action"] == "query_voice"
        ]
        assert query_requests == [], "设计路径 create_voice 不应发起 query_voice"

    async def test_design_create_returns_initial_status_without_querying(
        self, design_adapter, monkeypatch
    ):
        """设计路径同样创建即返回 DEPLOYING，不发起 query_voice，且带回预览音频。"""
        recorder = {}
        _install_fake_httpx(monkeypatch, recorder)
        query_spy = AsyncMock()
        monkeypatch.setattr(design_adapter, "query_voice", query_spy)

        result = await design_adapter.create_voice(
            {
                "mode": "design",
                "voice_prompt": "温柔清晰的中文女声",
                "preview_text": "预览文本",
                "prefix": "design",
                "language_hints": ["zh"],
                "model": "flash",
            }
        )
        assert query_spy.await_count == 0, "create_voice 不应查询音色状态"
        assert result["voice_id"] == "qwen-audio-3.0-tts-flash-test-123456"
        assert result["status"] == "DEPLOYING"
        assert "preview_audio" in result
        query_requests = [
            r for r in recorder["requests"]
            if r["json"]["input"]["action"] == "query_voice"
        ]
        assert query_requests == [], "设计路径 create_voice 不应发起 query_voice"

    async def test_design_create_returns_upstream_status_when_present(
        self, design_adapter, monkeypatch
    ):
        """设计路径同样应原样返回 create 响应的 output.status（如秒回 OK）。"""
        recorder = {}
        response = FakeResponse(
            {
                "output": {
                    "voice_id": "qwen-audio-3.0-tts-flash-test-123456",
                    "preview_audio": "https://example.com/preview.mp3",
                    "status": "OK",
                }
            }
        )
        _install_fake_httpx(monkeypatch, recorder, response)
        query_spy = AsyncMock()
        monkeypatch.setattr(design_adapter, "query_voice", query_spy)

        result = await design_adapter.create_voice(
            {
                "mode": "design",
                "voice_prompt": "温柔清晰的中文女声",
                "preview_text": "预览文本",
                "prefix": "design",
                "language_hints": ["zh"],
                "model": "flash",
            }
        )
        assert query_spy.await_count == 0, "create_voice 不应查询音色状态"
        assert result["voice_id"] == "qwen-audio-3.0-tts-flash-test-123456"
        assert result["status"] == "OK", "应原样返回 create 响应的 output.status"
        assert result["preview_audio"] == "https://example.com/preview.mp3"


class TestCallApiMarkdownFilter:
    """合成请求 payload 中 enable_markdown_filter 的透传。"""

    @pytest.fixture
    def qwen_adapter(self):
        return BailianQwenAudio3_0TTSAdapter(
            {"__template_key": "bailian_qwen_audio_3_0_tts"}
        )

    @pytest.fixture
    def config(self):
        return {
            "api_key": "sk-test",
            "workspace_id": "workspace-test",
            "voice": "longanhuan_v3.6",
            "model": "flash",
            "format": "wav",
            "sample_rate": 24000,
            "_data_dir": "/tmp/tts-enhancer-test",
        }

    @staticmethod
    def _install_client(monkeypatch):
        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)
        fake_client.post = AsyncMock(
            return_value=FakeResponse(
                {"output": {"audio": {"url": "https://example.test/audio.wav"}}}
            )
        )
        fake_client.get = AsyncMock(
            return_value=FakeResponse({}, content=b"fake-audio")
        )
        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: fake_client)
        monkeypatch.setattr(
            bailian_module, "save_audio_bytes", lambda *a, **k: "/tmp/out.wav"
        )
        return fake_client

    async def test_true_reaches_payload(self, qwen_adapter, config, monkeypatch):
        fake_client = self._install_client(monkeypatch)
        result = await qwen_adapter.call_api(
            text="原始文本",
            raw_params={
                "text": "# 标题\n\n| a | b |\n|---|---|\n| 1 | 2 |",
                "enable_markdown_filter": True,
            },
            config=config,
        )

        assert result == "/tmp/out.wav"
        payload = fake_client.post.call_args.kwargs["json"]
        assert payload["input"]["text"].startswith("# 标题")
        assert payload["input"]["enable_markdown_filter"] is True

    async def test_false_reaches_payload(self, qwen_adapter, config, monkeypatch):
        fake_client = self._install_client(monkeypatch)
        await qwen_adapter.call_api(
            text="普通文本",
            raw_params={"text": "普通文本", "enable_markdown_filter": False},
            config=config,
        )

        payload = fake_client.post.call_args.kwargs["json"]
        assert payload["input"]["enable_markdown_filter"] is False

    async def test_absent_omits_key(self, qwen_adapter, config, monkeypatch):
        fake_client = self._install_client(monkeypatch)
        await qwen_adapter.call_api(
            text="普通文本", raw_params={"text": "普通文本"}, config=config
        )

        payload = fake_client.post.call_args.kwargs["json"]
        assert "enable_markdown_filter" not in payload["input"]


class TestBailianConfSchema:
    """三个百炼模板的采样率与 AIGC 配置。"""

    @staticmethod
    def _items(template: str) -> dict:
        import json

        with open("_conf_schema.json", encoding="utf-8") as f:
            schema = json.load(f)
        return schema["providers"]["templates"][template]["items"]

    @pytest.mark.parametrize(
        "template",
        [
            "bailian_qwen_audio_3_0_tts",
            "bailian_qwen_audio_3_1_tts",
            "bailian_cosyvoice_v3_5",
        ],
    )
    def test_sample_rate_options_and_opus_hint(self, template):
        items = self._items(template)
        assert 12000 in items["sample_rate"]["options"]
        assert "opus_sample_rate" not in items
        assert "OPUS" in items["sample_rate"]["hint"]

    def test_cosyvoice_has_no_aigc_items(self):
        items = self._items("bailian_cosyvoice_v3_5")
        assert not [key for key in items if "aigc" in key]

    @pytest.mark.parametrize(
        "template", ["bailian_qwen_audio_3_0_tts", "bailian_qwen_audio_3_1_tts"]
    )
    def test_aigc_hint_states_pcm_unsupported(self, template):
        items = self._items(template)
        assert "pcm" in items["enable_aigc_tag"]["hint"]

    @pytest.mark.parametrize(
        "template", ["bailian_qwen_audio_3_0_tts", "bailian_qwen_audio_3_1_tts"]
    )
    def test_aigc_fields_conditioned_on_toggle(self, template):
        items = self._items(template)
        for key in ("aigc_propagator", "aigc_propagate_id"):
            assert items[key]["condition"] == {"enable_aigc_tag": True}


class TestBailianConfigI18n:
    """百炼配置文案的四语 i18n 覆盖，防止非中文用户回退到中文原文。"""

    LANGS = ["zh-CN", "en-US", "ja-JP", "ru-RU"]
    TEMPLATES = [
        "bailian_qwen_audio_3_0_tts",
        "bailian_qwen_audio_3_1_tts",
        "bailian_cosyvoice_v3_5",
    ]

    @classmethod
    def _schema_items(cls, template: str) -> dict:
        import json

        with open("_conf_schema.json", encoding="utf-8") as f:
            schema = json.load(f)
        return schema["providers"]["templates"][template]["items"]

    @classmethod
    def _i18n_template(cls, lang: str, template: str) -> dict:
        import json

        with open(
            f".astrbot-plugin/i18n/{lang}.json", encoding="utf-8"
        ) as f:
            data = json.load(f)
        return data["config"]["providers"]["templates"][template]

    @pytest.mark.parametrize("lang", LANGS)
    @pytest.mark.parametrize("template", TEMPLATES)
    def test_schema_hint_fields_all_translated(self, lang, template):
        """schema 里带 hint 的字段，i18n 必须也有 hint（否则回退中文）。"""
        schema_items = self._schema_items(template)
        i18n_items = self._i18n_template(lang, template)
        for field, meta in schema_items.items():
            if "hint" not in meta:
                continue
            assert field in i18n_items, f"{lang}/{template} 缺少 i18n 字段 {field}"
            assert "hint" in i18n_items[field], (
                f"{lang}/{template}/{field} 缺少 i18n hint，将回退中文"
            )

    @pytest.mark.parametrize("lang", LANGS)
    def test_cosyvoice_has_no_aigc_i18n(self, lang):
        i18n_items = self._i18n_template(lang, "bailian_cosyvoice_v3_5")
        assert not [key for key in i18n_items if "aigc" in key]

    @pytest.mark.parametrize("lang", LANGS)
    def test_aigc_i18n_hint_mentions_pcm(self, lang):
        for template in self.TEMPLATES[:2]:
            i18n_items = self._i18n_template(lang, template)
            for field in ("enable_aigc_tag", "aigc_propagator", "aigc_propagate_id"):
                assert "pcm" in i18n_items[field]["hint"].lower(), (
                    f"{lang}/{template}/{field} 的 i18n hint 未提及 pcm"
                )


class TestCallApiFormatGuards:
    """Opus 采样率与 AIGC 支持范围的 payload 兜底。"""

    @pytest.fixture
    def qwen_adapter(self):
        return BailianQwenAudio3_0TTSAdapter(
            {"__template_key": "bailian_qwen_audio_3_0_tts"}
        )

    @pytest.fixture
    def cosy_adapter(self):
        return BailianCosyVoiceV3_5Adapter(
            {"__template_key": "bailian_cosyvoice_v3_5"}
        )

    @staticmethod
    def _config(**overrides) -> dict:
        config = {
            "api_key": "sk-test",
            "workspace_id": "workspace-test",
            "voice": "longanhuan_v3.6",
            "model": "flash",
            "format": "wav",
            "sample_rate": 24000,
            "_data_dir": "/tmp/tts-enhancer-test",
        }
        config.update(overrides)
        return config

    @staticmethod
    async def _payload(adapter, config, monkeypatch) -> dict:
        fake_client = TestCallApiMarkdownFilter._install_client(monkeypatch)
        await adapter.call_api(
            text="测试文本",
            raw_params={"text": "测试文本"},
            config=config,
        )
        return fake_client.post.call_args.kwargs["json"]["input"]

    async def test_opus_uses_sample_rate(self, qwen_adapter, monkeypatch):
        config = self._config(format="opus", sample_rate=48000)
        payload_input = await self._payload(qwen_adapter, config, monkeypatch)
        assert payload_input["sample_rate"] == 48000

    async def test_opus_illegal_rate_falls_back(self, qwen_adapter, monkeypatch):
        config = self._config(format="opus", sample_rate=22050)
        payload_input = await self._payload(qwen_adapter, config, monkeypatch)
        assert payload_input["sample_rate"] == 24000

    async def test_wav_keeps_full_rate_range(self, qwen_adapter, monkeypatch):
        config = self._config(format="wav", sample_rate=44100)
        payload_input = await self._payload(qwen_adapter, config, monkeypatch)
        assert payload_input["sample_rate"] == 44100

    async def test_pcm_drops_aigc(self, qwen_adapter, monkeypatch):
        config = self._config(
            format="pcm",
            enable_aigc_tag=True,
            aigc_propagator="me",
            aigc_propagate_id="req-1",
        )
        payload_input = await self._payload(qwen_adapter, config, monkeypatch)
        assert "enable_aigc_tag" not in payload_input
        assert "aigc_propagator" not in payload_input
        assert "aigc_propagate_id" not in payload_input

    async def test_wav_keeps_aigc(self, qwen_adapter, monkeypatch):
        config = self._config(format="wav", enable_aigc_tag=True, aigc_propagator="me")
        payload_input = await self._payload(qwen_adapter, config, monkeypatch)
        assert payload_input["enable_aigc_tag"] is True
        assert payload_input["aigc_propagator"] == "me"

    @pytest.mark.parametrize("raw", ["false", "0", "no", "FALSE", " false "])
    async def test_aigc_string_false_drops(self, qwen_adapter, monkeypatch, raw):
        """旧配置里残留字符串 'false' 不能被 bool() 误判为 True。"""
        config = self._config(format="wav", enable_aigc_tag=raw, aigc_propagator="me")
        payload_input = await self._payload(qwen_adapter, config, monkeypatch)
        assert "enable_aigc_tag" not in payload_input
        assert "aigc_propagator" not in payload_input

    @pytest.mark.parametrize("raw", ["true", "1", "yes", "TRUE"])
    async def test_aigc_string_true_keeps(self, qwen_adapter, monkeypatch, raw):
        """字符串 'true' 等真值写法仍应正确开启 AIGC。"""
        config = self._config(format="wav", enable_aigc_tag=raw, aigc_propagator="me")
        payload_input = await self._payload(qwen_adapter, config, monkeypatch)
        assert payload_input["enable_aigc_tag"] is True
        assert payload_input["aigc_propagator"] == "me"

    async def test_cosyvoice_ignores_legacy_aigc(self, cosy_adapter, monkeypatch):
        config = self._config(enable_aigc_tag=True, aigc_propagator="me")
        payload_input = await self._payload(cosy_adapter, config, monkeypatch)
        assert "enable_aigc_tag" not in payload_input
        assert "aigc_propagator" not in payload_input
