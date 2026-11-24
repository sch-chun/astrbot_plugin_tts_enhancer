"""MiMo V2.5 适配器 voiceclone 参考音频缓存与截断的离线单测。

不依赖网络：验证参考音频预编码、缓存命中、超限自动截断与降级路径。
"""

import base64

from pathlib import Path

import pytest

from astrbot_plugin_tts_enhancer.providers.mimo_v2_5_tts import MimoV2_5TTSAdapter


def _make_entry(tmp_path, **overrides):
    data_dir = tmp_path / "audio"
    data_dir.mkdir(exist_ok=True)
    entry = {
        "__template_key": "mimo_v2_5_tts",
        "api_key": "sk-test",
        "model": "mimo-v2.5-tts-voiceclone",
        "_data_dir": str(data_dir),
    }
    entry.update(overrides)
    return entry


def _fake_trimmer(content: bytes):
    calls = []

    def fake_trim(file_path, max_sec, margin=0.5, output_dir=None):
        calls.append({"max_sec": max_sec, "margin": margin})
        src = Path(file_path)
        out = Path(output_dir) / f"{src.stem}_trimmed{src.suffix}"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(content)
        return str(out)

    return fake_trim, calls


def test_voiceclone_encodes_and_caches_sample(tmp_path):
    sample = tmp_path / "voice.wav"
    sample.write_bytes(b"RIFFdata")
    entry = _make_entry(tmp_path, voice_sample=["voice.wav"])

    adapter = MimoV2_5TTSAdapter(entry)
    encoded = adapter._voice_data_url.split(",", 1)[1]
    assert base64.b64decode(encoded) == b"RIFFdata"

    cache_dir = tmp_path / "cache" / "mimo_voiceclone"
    files = list(cache_dir.glob("*.b64"))
    assert len(files) == 1
    assert "bytes10485760" in files[0].name

    # 第二次实例化命中缓存，内容一致
    adapter2 = MimoV2_5TTSAdapter(entry)
    assert adapter2._voice_data_url == adapter._voice_data_url


def test_voiceclone_non_clone_model_skips_sample(tmp_path):
    sample = tmp_path / "voice.wav"
    sample.write_bytes(b"RIFFdata")
    entry = _make_entry(tmp_path, model="mimo-v2.5-tts", voice_sample=["voice.wav"])
    adapter = MimoV2_5TTSAdapter(entry)
    assert not adapter._voice_data_url


def test_over_limit_auto_trims(monkeypatch, tmp_path):
    """编码后超 10MB → 自动截断，不再抛错。"""
    sample = tmp_path / "big.wav"
    sample.write_bytes(b"x" * 5000)
    mod = "astrbot_plugin_tts_enhancer.providers.mimo_v2_5_tts"
    monkeypatch.setattr(f"{mod}.get_audio_duration", lambda p: 20.0)
    fake_trim, calls = _fake_trimmer(b"short")
    monkeypatch.setattr(f"{mod}.trim_audio_to_max", fake_trim)
    monkeypatch.setattr(MimoV2_5TTSAdapter, "MAX_VOICE_BASE64_BYTES", 100)

    adapter = MimoV2_5TTSAdapter(
        _make_entry(tmp_path, voice_sample=["big.wav"])
    )
    assert adapter._voice_data_url is not None
    assert len(calls) >= 1
    encoded = adapter._voice_data_url.split(",", 1)[1]
    assert base64.b64decode(encoded) == b"short"


def test_duration_unreadable_degrades(monkeypatch, tmp_path):
    """读不到时长 → 跳过截断、不抛错、原样编码。"""
    sample = tmp_path / "voice.wav"
    sample.write_bytes(b"RIFFdata")
    mod = "astrbot_plugin_tts_enhancer.providers.mimo_v2_5_tts"
    monkeypatch.setattr(f"{mod}.get_audio_duration", lambda p: None)
    fake_trim, calls = _fake_trimmer(b"x")
    monkeypatch.setattr(f"{mod}.trim_audio_to_max", fake_trim)
    monkeypatch.setattr(MimoV2_5TTSAdapter, "MAX_VOICE_BASE64_BYTES", 4)

    adapter = MimoV2_5TTSAdapter(
        _make_entry(tmp_path, voice_sample=["voice.wav"])
    )
    assert adapter._voice_data_url is not None
    assert calls == []
    encoded = adapter._voice_data_url.split(",", 1)[1]
    assert base64.b64decode(encoded) == b"RIFFdata"


def test_trim_failure_degrades(monkeypatch, tmp_path):
    """截断工具失败 → 打 warning 回退原文件，不抛错。"""
    sample = tmp_path / "voice.wav"
    sample.write_bytes(b"RIFFdata")
    mod = "astrbot_plugin_tts_enhancer.providers.mimo_v2_5_tts"
    monkeypatch.setattr(f"{mod}.get_audio_duration", lambda p: 20.0)

    def failing_trim(*args, **kwargs):
        raise RuntimeError("ffmpeg not found")

    monkeypatch.setattr(f"{mod}.trim_audio_to_max", failing_trim)
    monkeypatch.setattr(MimoV2_5TTSAdapter, "MAX_VOICE_BASE64_BYTES", 4)

    adapter = MimoV2_5TTSAdapter(
        _make_entry(tmp_path, voice_sample=["voice.wav"])
    )
    encoded = adapter._voice_data_url.split(",", 1)[1]
    assert base64.b64decode(encoded) == b"RIFFdata"


def test_sample_path_traversal_blocked(tmp_path):
    entry = _make_entry(tmp_path, voice_sample=["../escape.wav"])
    with pytest.raises(ValueError, match="路径越权"):
        MimoV2_5TTSAdapter(entry)
