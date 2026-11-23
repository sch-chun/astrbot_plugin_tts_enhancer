"""百炼音频生成（qwen-audio-3.1-tts-next）适配器的离线单测。

不依赖网络：通过 monkeypatch 替换 httpx.AsyncClient，断言请求体、参考音频
Base64 编码、错误分支与落盘行为。工具层现在只暴露一个 text_prompt 字段，
由 SubAgent 直接产出完整提示词；有/无参考音频分别注入不同场景文档。
"""

import base64
import json

from pathlib import Path

import pytest

from astrbot_plugin_tts_enhancer.providers.qwen_audio_3_1_tts_next import (
    QwenAudio3_1TTSNextAdapter,
)

REPO_ROOT = Path(__file__).parents[1]


def _make_entry(tmp_path, **overrides):
    """构造 entry，_data_dir 指向 <tmp>/audio，其父目录为插件数据根目录。"""
    data_dir = tmp_path / "audio"
    data_dir.mkdir(exist_ok=True)
    # 包含 schema 会填充的默认值，模拟 AstrBot 注入后的真实 config
    entry = {
        "__template_key": "qwen_audio_3_1_tts_next",
        "api_key": "sk-test",
        "workspace_id": "ws-test",
        "format": "wav",
        "sample_rate": 48000,
        "channels": 2,
        "seed": 42,
        "enable_aigc_tag": False,
        "_data_dir": str(data_dir),
    }
    entry.update(overrides)
    return entry


class _FakeResponse:
    def __init__(self, payload=None, status_code=200, content=b"fake-audio"):
        self._payload = payload or {}
        self.status_code = status_code
        self.content = content
        self.text = json.dumps(self._payload, ensure_ascii=False)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("error", request=None, response=None)


class _FakeClient:
    instances = []

    def __init__(self, post_resp=None, get_resp=None, post_exc=None):
        self._post_resp = post_resp or _FakeResponse(
            {
                "request_id": "req-1",
                "output": {
                    "finish_reason": "stop",
                    "audio": {"url": "https://example.com/audio.wav", "duration": 1.2},
                },
                "usage": {"duration": 1},
            }
        )
        self._get_resp = get_resp or _FakeResponse()
        self._post_exc = post_exc
        self.post_calls = []
        self.get_calls = []
        _FakeClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        if self._post_exc:
            raise self._post_exc
        return self._post_resp

    async def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self._get_resp


@pytest.fixture(autouse=True)
def _reset_clients():
    _FakeClient.instances.clear()


def _install(monkeypatch, client):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: client)
    return client


def _capture_post(monkeypatch):
    """替换 save_audio_bytes 并返回一个捕获请求体的 FakeClient。"""
    captured = {}

    class Capturing(_FakeClient):
        async def post(self, url, **kwargs):
            captured.update(kwargs["json"])
            return await super().post(url, **kwargs)

    client = _install(monkeypatch, Capturing())
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.qwen_audio_3_1_tts_next.save_audio_bytes",
        lambda data_dir, content, fmt: f"/tmp/out.{fmt}",
    )
    return client, captured


@pytest.mark.asyncio
async def test_call_api_success_without_reference(monkeypatch, tmp_path):
    client = _install(monkeypatch, _FakeClient())
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.qwen_audio_3_1_tts_next.save_audio_bytes",
        lambda data_dir, content, fmt: f"/tmp/out.{fmt}",
    )

    adapter = QwenAudio3_1TTSNextAdapter(_make_entry(tmp_path))
    prompt = "单人旁白，三十岁女性，嗓音温柔。说：“你好，欢迎使用。”"
    result = await adapter.call_api("你好", {"text_prompt": prompt}, adapter.entry)

    assert result == "/tmp/out.wav"
    url, kwargs = client.post_calls[0]
    assert url == (
        "https://ws-test.cn-beijing.maas.aliyuncs.com"
        "/api/v1/services/audio/tts/SpeechSynthesizer"
    )
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test"
    payload = kwargs["json"]
    assert payload["model"] == "qwen-audio-3.1-tts-next"
    inp = payload["input"]
    # text_prompt 由 SubAgent 产出，适配器原样透传，不再做模板拼接
    assert inp["text_prompt"] == prompt
    assert "references" not in inp
    assert inp["format"] == "wav"
    assert inp["sample_rate"] == 48000
    assert inp["channels"] == 2
    # volume/rate 只来自 tool，未传时不下发（服务端用默认值）
    assert "volume" not in inp
    assert "rate" not in inp
    assert inp["seed"] == 42
    assert inp["enable_aigc_tag"] is False
    assert client.get_calls[0][0] == "https://example.com/audio.wav"


@pytest.mark.asyncio
async def test_call_api_with_reference_uses_voice1(monkeypatch, tmp_path):
    root = tmp_path
    sample = root / "files" / "voice.wav"
    sample.parent.mkdir(parents=True, exist_ok=True)
    sample.write_bytes(b"RIFFfake")

    client, captured = _capture_post(monkeypatch)
    entry = _make_entry(tmp_path, voice_sample=["files/voice.wav"], format="mp3")
    adapter = QwenAudio3_1TTSNextAdapter(entry)
    prompt = '@voice1 用开心的语气说：“今天天气真好。”背景音是轻柔的海浪声。'
    result = await adapter.call_api("台词", {"text_prompt": prompt}, entry)

    assert result == "/tmp/out.mp3"
    inp = captured["input"]
    # 有参考音频时 @voice1 必须原样保留
    assert inp["text_prompt"] == prompt
    assert len(inp["references"]) == 1
    data_url = inp["references"][0]["audio_data"]
    assert data_url.startswith("data:audio/wav;base64,")
    assert base64.b64decode(data_url.split(",", 1)[1]) == b"RIFFfake"
    assert inp["format"] == "mp3"


@pytest.mark.asyncio
async def test_text_prompt_passed_through_without_template(monkeypatch, tmp_path):
    """不再有 prompt_template 拼接：Arbitrary 提示词原样下发。"""
    client, captured = _capture_post(monkeypatch)
    entry = _make_entry(tmp_path)
    adapter = QwenAudio3_1TTSNextAdapter(entry)
    prompt = "雨夜旁白。@voice1 说：“有些话说不出口。”背景声：窗外细雨。"
    await adapter.call_api("原文", {"text_prompt": prompt}, entry)
    # 无参考音频时 @voiceN 作为兜底被剥离（场景文档本应指导模型不写）
    assert captured["input"]["text_prompt"] == "雨夜旁白。说：“有些话说不出口。”背景声：窗外细雨。"


@pytest.mark.asyncio
async def test_fallback_to_raw_text_when_no_text_prompt(monkeypatch, tmp_path):
    """未走 SubAgent 增强时，raw_params 为空，退回原始 text。"""
    client, captured = _capture_post(monkeypatch)
    entry = _make_entry(tmp_path)
    adapter = QwenAudio3_1TTSNextAdapter(entry)
    await adapter.call_api("原始台词", {}, entry)
    assert captured["input"]["text_prompt"] == "原始台词"


@pytest.mark.asyncio
async def test_tool_volume_rate_are_only_source(monkeypatch, tmp_path):
    """volume/rate 唯一来源是 tool；传了就下发，没传就不下发。"""
    _, captured = _capture_post(monkeypatch)
    entry = _make_entry(tmp_path)  # config 里已无 volume/rate
    adapter = QwenAudio3_1TTSNextAdapter(entry)
    await adapter.call_api(
        "x",
        {"text_prompt": "x", "volume": 80, "rate": 1.5},
        entry,
    )
    inp = captured["input"]
    assert inp["volume"] == 80
    assert inp["rate"] == 1.5

    # 只传 volume，rate 不下发
    _, captured2 = _capture_post(monkeypatch)
    await adapter.call_api("x", {"text_prompt": "x", "volume": 20}, entry)
    assert captured2["input"]["volume"] == 20
    assert "rate" not in captured2["input"]

    # 完全不传，两个都不下发
    _, captured3 = _capture_post(monkeypatch)
    await adapter.call_api("x", {"text_prompt": "x"}, entry)
    assert "volume" not in captured3["input"]
    assert "rate" not in captured3["input"]


def test_validate_and_sanitize_volume_rate():
    adapter = QwenAudio3_1TTSNextAdapter({"__template_key": "qwen_audio_3_1_tts_next"})
    # 合法值通过
    assert adapter.validate_params({"volume": 0, "rate": 0.5}) == (True, "")
    assert adapter.validate_params({"volume": 100, "rate": 2.0}) == (True, "")
    # 越界与类型错误被拒
    assert adapter.validate_params({"volume": 101})[0] is False
    assert adapter.validate_params({"volume": -1})[0] is False
    assert adapter.validate_params({"rate": 0.4})[0] is False
    assert adapter.validate_params({"rate": 2.1})[0] is False
    assert adapter.validate_params({"volume": True})[0] is False  # bool 不是合法数值
    assert adapter.validate_params({"rate": "1.0"})[0] is False
    # sanitize 保留合法值、丢弃非法值
    out = adapter.sanitize_params(
        {"text_prompt": "p", "volume": 70, "rate": 1.2, "junk": 1}
    )
    assert out == {"text_prompt": "p", "volume": 70, "rate": 1.2}
    out2 = adapter.sanitize_params({"volume": 999, "rate": -1})
    assert out2 == {}


@pytest.mark.asyncio
async def test_mp3_cbr_and_vbr_params(monkeypatch, tmp_path):
    """MP3 参数仅 format=mp3 时下发，CBR 与 VBR 二选一。"""
    _, captured = _capture_post(monkeypatch)
    entry = _make_entry(
        tmp_path,
        format="mp3",
        **{"enable_cbr": True, "bit_rate": 192, "quality": 3},
    )
    adapter = QwenAudio3_1TTSNextAdapter(entry)
    await adapter.call_api("x", {"text_prompt": "x"}, entry)
    inp = captured["input"]
    assert inp["enable_cbr"] is True
    assert inp["bit_rate"] == 192
    assert "quality" not in inp  # CBR 时不传 VBR 的 quality

    _, captured2 = _capture_post(monkeypatch)
    entry2 = _make_entry(
        tmp_path,
        format="mp3",
        **{"enable_cbr": False, "bit_rate": 192, "quality": 3},
    )
    adapter2 = QwenAudio3_1TTSNextAdapter(entry2)
    await adapter2.call_api("x", {"text_prompt": "x"}, entry2)
    inp2 = captured2["input"]
    assert inp2["enable_cbr"] is False
    assert inp2["quality"] == 3
    assert "bit_rate" not in inp2  # VBR 时不传 CBR 的 bit_rate


@pytest.mark.asyncio
async def test_mp3_params_ignored_for_wav(monkeypatch, tmp_path):
    """format=wav 时不下发任何 MP3 专属参数。"""
    _, captured = _capture_post(monkeypatch)
    entry = _make_entry(
        tmp_path,
        format="wav",
        **{"enable_cbr": True, "bit_rate": 192, "quality": 3},
    )
    adapter = QwenAudio3_1TTSNextAdapter(entry)
    await adapter.call_api("x", {"text_prompt": "x"}, entry)
    inp = captured["input"]
    assert not any(k in inp for k in ("enable_cbr", "bit_rate", "quality"))


@pytest.mark.asyncio
async def test_seed_minus_one_generates_local_random(monkeypatch, tmp_path):
    """seed=-1 时本地随机一个正整数下发，避免固定用服务端默认 42。"""
    _, captured = _capture_post(monkeypatch)
    entry = _make_entry(tmp_path, seed=-1)
    adapter = QwenAudio3_1TTSNextAdapter(entry)
    await adapter.call_api("x", {"text_prompt": "x"}, entry)
    seed = captured["input"]["seed"]
    assert isinstance(seed, int)
    assert 0 <= seed <= 2**31 - 1

    # 固定值仍原样下发
    _, captured2 = _capture_post(monkeypatch)
    entry2 = _make_entry(tmp_path, seed=123)
    adapter2 = QwenAudio3_1TTSNextAdapter(entry2)
    await adapter2.call_api("x", {"text_prompt": "x"}, entry2)
    assert captured2["input"]["seed"] == 123


def test_tool_schema_exposes_text_prompt_and_optional_vr(tmp_path):
    adapter = QwenAudio3_1TTSNextAdapter(_make_entry(tmp_path))
    tool = adapter.get_tool_schema()
    assert set(tool.parameters["properties"]) == {"text_prompt", "volume", "rate"}
    assert tool.parameters["required"] == ["text_prompt"]
    # volume / rate 的取值范围与 schema 一致
    assert tool.parameters["properties"]["volume"]["minimum"] == 0
    assert tool.parameters["properties"]["volume"]["maximum"] == 100
    assert tool.parameters["properties"]["rate"]["minimum"] == 0.5
    assert tool.parameters["properties"]["rate"]["maximum"] == 2.0


def test_scenario_docs_switch_by_reference(tmp_path):
    """有/无参考音频注入不同场景文档，前者讲 @voice1，后者讲人物音色。"""
    no_ref = QwenAudio3_1TTSNextAdapter(_make_entry(tmp_path))
    no_ref_prompt = no_ref.get_subagent_system_prompt()
    assert "未配置参考音频" in no_ref_prompt
    assert "@voice1" in no_ref_prompt  # 禁令里出现，说明不要写
    assert "不要使用" in no_ref_prompt or "不用任何" in no_ref_prompt

    root = tmp_path
    sample = root / "files" / "voice.wav"
    sample.parent.mkdir(parents=True, exist_ok=True)
    sample.write_bytes(b"RIFFfake")
    with_ref = QwenAudio3_1TTSNextAdapter(
        _make_entry(tmp_path, voice_sample=["files/voice.wav"])
    )
    with_ref_prompt = with_ref.get_subagent_system_prompt()
    assert "已配置参考音频" in with_ref_prompt
    assert "固定使用 `@voice1`" in with_ref_prompt
    assert "不要出现" in with_ref_prompt


def test_reference_sample_path_traversal_blocked(tmp_path):
    entry = _make_entry(tmp_path, voice_sample=["../../etc/passwd"])
    with pytest.raises(ValueError, match="路径越权"):
        QwenAudio3_1TTSNextAdapter(entry)


def _fake_trimmer(content: bytes):
    """构造一个 fake trim_audio_to_max：在 output_dir 写截断文件并返回路径。"""
    calls = []

    def fake_trim(file_path, max_sec, margin=0.5, output_dir=None):
        calls.append({"file": file_path, "max_sec": max_sec, "margin": margin})
        src = Path(file_path)
        out = Path(output_dir) / f"{src.stem}_trimmed{src.suffix}"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(content)
        return str(out)

    return fake_trim, calls


def test_reference_duration_over_limit_auto_trims(monkeypatch, tmp_path):
    """时长 60s 超 30s 限制 → 自动截断到 29.5s，不抛错。"""
    sample = tmp_path / "voice.wav"
    sample.write_bytes(b"RIFF" + b"x" * 100)

    mod = "astrbot_plugin_tts_enhancer.providers.qwen_audio_3_1_tts_next"
    monkeypatch.setattr(f"{mod}.get_audio_duration", lambda p: 60.0)
    fake_trim, calls = _fake_trimmer(b"RIFF" + b"y" * 40)
    monkeypatch.setattr(f"{mod}.trim_audio_to_max", fake_trim)

    adapter = QwenAudio3_1TTSNextAdapter(
        _make_entry(tmp_path, voice_sample=["voice.wav"])
    )
    assert adapter._voice_data_url is not None
    # 时长截断发生，目标 30s（函数内 margin 0.5 → 29.5s）
    assert len(calls) >= 1
    assert calls[0]["max_sec"] == 30.0
    assert calls[0]["margin"] == 0.5
    # 用的是截断后内容（40 字节），不是原始 104 字节
    encoded = adapter._voice_data_url.split(",", 1)[1]
    assert base64.b64decode(encoded) == b"RIFF" + b"y" * 40


def test_reference_size_over_limit_auto_trims(monkeypatch, tmp_path):
    """Base64 后超 10MB 限制 → 按超出比例二次截断，不抛错。"""
    sample = tmp_path / "big.wav"
    sample.write_bytes(b"x" * 5000)

    mod = "astrbot_plugin_tts_enhancer.providers.qwen_audio_3_1_tts_next"
    monkeypatch.setattr(f"{mod}.get_audio_duration", lambda p: 20.0)
    fake_trim, calls = _fake_trimmer(b"short")
    monkeypatch.setattr(f"{mod}.trim_audio_to_max", fake_trim)
    monkeypatch.setattr(QwenAudio3_1TTSNextAdapter, "MAX_VOICE_BASE64_BYTES", 100)

    adapter = QwenAudio3_1TTSNextAdapter(
        _make_entry(tmp_path, voice_sample=["big.wav"])
    )
    assert adapter._voice_data_url is not None
    assert len(calls) >= 1  # 二次截断被调用
    encoded = adapter._voice_data_url.split(",", 1)[1]
    assert base64.b64decode(encoded) == b"short"


def test_reference_duration_unreadable_degrades(monkeypatch, tmp_path):
    """时长读取失败（如无 ffprobe）→ 跳过时长截断、不抛错、不影响合成。"""
    sample = tmp_path / "voice.wav"
    sample.write_bytes(b"RIFFdata")

    mod = "astrbot_plugin_tts_enhancer.providers.qwen_audio_3_1_tts_next"
    monkeypatch.setattr(f"{mod}.get_audio_duration", lambda p: None)
    fake_trim, calls = _fake_trimmer(b"x")
    monkeypatch.setattr(f"{mod}.trim_audio_to_max", fake_trim)

    adapter = QwenAudio3_1TTSNextAdapter(
        _make_entry(tmp_path, voice_sample=["voice.wav"])
    )
    assert adapter._voice_data_url is not None
    assert calls == []  # 未尝试因时长截断
    encoded = adapter._voice_data_url.split(",", 1)[1]
    assert base64.b64decode(encoded) == b"RIFFdata"  # 原文件被编码


def test_reference_trim_failure_degrades(monkeypatch, tmp_path):
    """截断工具失败（如无 ffmpeg）→ 打 warning 回退原文件，不抛错。"""
    sample = tmp_path / "voice.wav"
    sample.write_bytes(b"RIFFdata")

    mod = "astrbot_plugin_tts_enhancer.providers.qwen_audio_3_1_tts_next"
    monkeypatch.setattr(f"{mod}.get_audio_duration", lambda p: 60.0)

    def failing_trim(*args, **kwargs):
        raise RuntimeError("ffmpeg not found")

    monkeypatch.setattr(f"{mod}.trim_audio_to_max", failing_trim)

    adapter = QwenAudio3_1TTSNextAdapter(
        _make_entry(tmp_path, voice_sample=["voice.wav"])
    )
    assert adapter._voice_data_url is not None
    encoded = adapter._voice_data_url.split(",", 1)[1]
    assert base64.b64decode(encoded) == b"RIFFdata"  # 回退原文件


@pytest.mark.asyncio
async def test_missing_api_key_returns_empty(monkeypatch, tmp_path):
    entry = _make_entry(tmp_path, api_key="")
    adapter = QwenAudio3_1TTSNextAdapter(entry)
    assert await adapter.call_api("hi", {"text_prompt": "hi"}, entry) == ""


@pytest.mark.asyncio
async def test_missing_workspace_id_returns_empty(monkeypatch, tmp_path):
    entry = _make_entry(tmp_path, workspace_id="")
    adapter = QwenAudio3_1TTSNextAdapter(entry)
    assert await adapter.call_api("hi", {"text_prompt": "hi"}, entry) == ""


@pytest.mark.asyncio
async def test_api_error_response_returns_empty(monkeypatch, tmp_path):
    client = _install(
        monkeypatch,
        _FakeClient(
            post_resp=_FakeResponse(
                {"code": "CLIENT_ERROR", "message": "text_prompt exceeds limit"},
                status_code=400,
            )
        ),
    )
    entry = _make_entry(tmp_path)
    adapter = QwenAudio3_1TTSNextAdapter(entry)
    assert await adapter.call_api("hi", {"text_prompt": "hi"}, entry) == ""
    assert len(client.post_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("success_code", [0, "0"])
async def test_code_zero_not_treated_as_error(monkeypatch, tmp_path, success_code):
    """服务端成功响应若带 code: 0 / "0"，不应被 truthy 判断误判为错误。"""
    client = _install(monkeypatch, _FakeClient())
    monkeypatch.setattr(
        "astrbot_plugin_tts_enhancer.providers.qwen_audio_3_1_tts_next.save_audio_bytes",
        lambda data_dir, content, fmt: "/tmp/out.wav",
    )
    # 给成功 payload 注入 code: 0 / "0"
    client._post_resp._payload["code"] = success_code

    entry = _make_entry(tmp_path)
    adapter = QwenAudio3_1TTSNextAdapter(entry)
    assert await adapter.call_api("hi", {"text_prompt": "hi"}, entry) == "/tmp/out.wav"
    assert len(client.get_calls) == 1  # 走到音频下载，未被错误分支短路


@pytest.mark.asyncio
async def test_timeout_returns_empty(monkeypatch, tmp_path):
    import httpx

    client = _install(
        monkeypatch,
        _FakeClient(post_exc=httpx.TimeoutException("timeout")),
    )
    entry = _make_entry(tmp_path)
    adapter = QwenAudio3_1TTSNextAdapter(entry)
    assert await adapter.call_api("hi", {"text_prompt": "hi"}, entry) == ""


@pytest.mark.asyncio
async def test_missing_audio_url_returns_empty(monkeypatch, tmp_path):
    _install(monkeypatch, _FakeClient(post_resp=_FakeResponse({"output": {}})))
    entry = _make_entry(tmp_path)
    adapter = QwenAudio3_1TTSNextAdapter(entry)
    assert await adapter.call_api("hi", {"text_prompt": "hi"}, entry) == ""


@pytest.mark.asyncio
async def test_download_failure_returns_empty(monkeypatch, tmp_path):
    _install(
        monkeypatch,
        _FakeClient(get_resp=_FakeResponse(status_code=404)),
    )
    entry = _make_entry(tmp_path)
    adapter = QwenAudio3_1TTSNextAdapter(entry)
    assert await adapter.call_api("hi", {"text_prompt": "hi"}, entry) == ""


@pytest.mark.asyncio
async def test_prompt_over_limit_short_circuits(monkeypatch, tmp_path):
    client = _install(monkeypatch, _FakeClient())
    entry = _make_entry(tmp_path)
    adapter = QwenAudio3_1TTSNextAdapter(entry)
    long_prompt = "字" * 3100
    assert await adapter.call_api(long_prompt, {"text_prompt": long_prompt}, entry) == ""
    assert client.post_calls == []


def test_validate_and_sanitize_params():
    adapter = QwenAudio3_1TTSNextAdapter({"__template_key": "qwen_audio_3_1_tts_next"})
    assert adapter.validate_params({}) == (True, "")
    assert adapter.validate_params({"text_prompt": "  "})[0] is False
    out = adapter.sanitize_params({"text_prompt": "完整提示词", "junk": 1})
    assert out == {"text_prompt": "完整提示词"}


def test_config_schema_template_present():
    schema = json.loads((REPO_ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    items = schema["providers"]["templates"]["qwen_audio_3_1_tts_next"]["items"]
    assert items["voice_sample"]["type"] == "file"
    assert set(items["voice_sample"]["file_types"]) == {"mp3", "wav", "ogg"}
    assert items["api_key"]["secret"] is True
    # 工具层改为 text_prompt + 可选 volume/rate 后，旧配置项应移除
    assert "prompt_template" not in items
    assert "volume" not in items  # volume/rate 现在只存在于 tool schema
    assert "rate" not in items
    # MP3 三参数带条件显示
    assert items["enable_cbr"]["condition"] == {"format": "mp3"}
    assert items["bit_rate"]["condition"] == {"format": "mp3", "enable_cbr": True}
    assert items["quality"]["condition"] == {"format": "mp3", "enable_cbr": False}


@pytest.mark.asyncio
async def test_reference_error_logs_actionable_hint(monkeypatch, tmp_path, caplog):
    """服务端报参考音频相关错误时，日志补可操作的排查提示。"""
    client = _install(
        monkeypatch,
        _FakeClient(
            post_resp=_FakeResponse(
                {"code": "CLIENT_ERROR", "message": "reference audio duration exceeds 30s"},
                status_code=400,
            )
        ),
    )
    entry = _make_entry(tmp_path)
    adapter = QwenAudio3_1TTSNextAdapter(entry)
    with caplog.at_level("WARNING"):
        assert await adapter.call_api("hi", {"text_prompt": "hi"}, entry) == ""
    assert len(client.post_calls) == 1
    assert "30s/10MB" in caplog.text
    assert "ffmpeg" in caplog.text

    # 无关错误（鉴权失败）不应触发参考音频提示
    caplog.clear()
    _install(
        monkeypatch,
        _FakeClient(
            post_resp=_FakeResponse(
                {"code": "AUTH_ERROR", "message": "invalid api key"},
                status_code=401,
            )
        ),
    )
    with caplog.at_level("WARNING"):
        await adapter.call_api("hi", {"text_prompt": "hi"}, entry)
    assert "参考音频" not in caplog.text


def test_wav_duration_fallback_without_ffmpeg(tmp_path):
    """真实 WAV：ffprobe 不可用时 pydub 兜底读时长并自动截断到 29.5s。

    不 mock 时长读取，模拟本机无 ffmpeg/ffprobe 的真实环境。
    """
    import wave

    root = tmp_path
    audio_dir = root / "audio"
    audio_dir.mkdir(exist_ok=True)
    sample = root / "files" / "long.wav"
    sample.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(sample), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * (8000 * 32))  # 32 秒

    entry = _make_entry(tmp_path, voice_sample=["files/long.wav"])
    adapter = QwenAudio3_1TTSNextAdapter(entry)
    assert adapter._voice_data_url is not None

    trimmed = base64.b64decode(adapter._voice_data_url.split(",", 1)[1])
    check = root / "check.wav"
    check.write_bytes(trimmed)
    with wave.open(str(check), "rb") as w:
        duration = w.getnframes() / w.getframerate()
    assert 29.0 < duration < 30.0, f"截断后时长异常: {duration}s"
