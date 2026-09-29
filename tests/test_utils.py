"""providers/utils 单元测试 —— HTTP 辅助与音频处理工具。"""

import pytest
from astrbot_plugin_tts_enhancer.providers.utils import audio as audio_utils
from astrbot_plugin_tts_enhancer.providers.utils import http


class TestBearerHeaders:
    def test_includes_authorization_and_json_by_default(self):
        h = http.bearer_headers("SECRET")
        assert h["Authorization"] == "Bearer SECRET"
        assert h["Content-Type"] == "application/json"

    def test_without_json(self):
        h = http.bearer_headers("SECRET", with_json=False)
        assert h == {"Authorization": "Bearer SECRET"}

    def test_empty_key_still_builds_header(self):
        """空 key 不会被拦截，调用方需自行校验。"""
        assert http.bearer_headers("")["Authorization"] == "Bearer "


class TestExtractErrorMessage:
    def test_message_priority(self):
        assert http.extract_error_message({"message": "A", "error": "B"}) == "A"

    def test_error_second(self):
        assert http.extract_error_message({"error": "B", "detail": "C"}) == "B"

    def test_detail_third(self):
        assert http.extract_error_message({"detail": "C"}) == "C"

    def test_empty_value_skipped(self):
        assert http.extract_error_message({"message": "", "error": "B"}) == "B"

    def test_fallback_when_absent(self):
        assert http.extract_error_message({}, "回退文本") == "回退文本"

    def test_non_dict_payload_returns_fallback(self):
        assert http.extract_error_message("boom", "回退") == "回退"
        assert http.extract_error_message(None, "回退") == "回退"
        assert http.extract_error_message([1], "回退") == "回退"

    def test_non_string_value_coerced(self):
        assert http.extract_error_message({"message": 12345}) == "12345"


class TestSaveAudioBytes:
    def test_empty_data_dir_returns_empty(self):
        assert audio_utils.save_audio_bytes("", b"abc") == ""

    def test_writes_file_and_returns_path(self, tmp_path):
        path = audio_utils.save_audio_bytes(str(tmp_path), b"audio-bytes", "mp3")
        from pathlib import Path

        p = Path(path)
        assert p.exists()
        assert p.suffix == ".mp3"
        assert p.read_bytes() == b"audio-bytes"

    def test_custom_format_extension(self, tmp_path):
        path = audio_utils.save_audio_bytes(str(tmp_path), b"x", "wav")
        assert path.endswith(".wav")

    def test_creates_missing_directory(self, tmp_path):
        target = tmp_path / "nested" / "dir"
        path = audio_utils.save_audio_bytes(str(target), b"x", "mp3")
        assert path.startswith(str(target))

    def test_unwritable_path_returns_empty(self, tmp_path):
        """写入失败时应返回空串而非抛异常。"""
        blocker = tmp_path / "blocker"
        blocker.write_text("not a dir")
        result = audio_utils.save_audio_bytes(str(blocker), b"x", "mp3")
        assert result == ""


class TestGetAudioDuration:
    def test_missing_file_returns_none(self):
        assert audio_utils.get_audio_duration(str(_missing_path())) is None

    def test_non_audio_file_returns_none(self, tmp_path):
        """无法解析的文件应返回 None 而非抛异常。"""
        junk = tmp_path / "junk.mp3"
        junk.write_bytes(b"not really audio")
        assert audio_utils.get_audio_duration(str(junk)) is None


class TestValidateAudioDuration:
    def test_unknown_duration_is_invalid(self):
        ok, msg = audio_utils.validate_audio_duration(str(_missing_path()))
        assert ok is False
        assert "无法获取音频时长" in msg

    def test_constraints_not_checked_when_duration_unknown(self):
        """时长未知时即使不设任何约束也应判为非法。"""
        ok, _ = audio_utils.validate_audio_duration(str(_missing_path()))
        assert ok is False


class TestTrimAudioToMax:
    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            audio_utils.trim_audio_to_max(str(_missing_path()), max_sec=10)

    def test_too_small_max_sec_raises(self, tmp_path):
        f = tmp_path / "a.mp3"
        f.write_bytes(b"fake")
        with pytest.raises(ValueError, match="太小"):
            audio_utils.trim_audio_to_max(str(f), max_sec=0.2, margin=0.5)

    def test_exact_margin_boundary_raises(self, tmp_path):
        """max_sec == margin 时 target_ms 为 0，应抛 ValueError。"""
        f = tmp_path / "a.mp3"
        f.write_bytes(b"fake")
        with pytest.raises(ValueError):
            audio_utils.trim_audio_to_max(str(f), max_sec=0.5, margin=0.5)

    def test_unsupported_format_raises_runtime_error(self, tmp_path):
        """无法解码的文件（缺少 ffmpeg 或格式不支持）应包装为 RuntimeError。"""
        f = tmp_path / "a.mp3"
        f.write_bytes(b"definitely not audio")
        with pytest.raises(RuntimeError, match="音频裁剪失败"):
            audio_utils.trim_audio_to_max(str(f), max_sec=10)


class TestAudioConstraints:
    def test_constants_are_consistent(self):
        c = audio_utils.AudioConstraints
        assert c.MINIMAX_CLONE_MIN < c.MINIMAX_CLONE_MAX
        assert c.BAILIAN_CLONE_MIN < c.BAILIAN_CLONE_MAX
        assert c.MINIMAX_PROMPT_MAX < c.MINIMAX_CLONE_MAX


def _missing_path():
    from pathlib import Path

    return Path(__file__).parent / "__no_such_file__.mp3"


class TestPydubAvailability:
    def test_module_reports_availability(self):
        """pydub 缺失时应降级导入而非让整个 providers 包导入失败。"""
        # 模块导入成功本身就证明了 try/except 兜底有效
        assert isinstance(audio_utils.AudioSegment, type) or (
            audio_utils.AudioSegment is None
        )
