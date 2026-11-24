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


class TestHasBusinessError:
    """HTTP 200 响应体的业务错误判定（按类型分别处理）。"""

    def test_numeric_zero_is_success(self):
        """数值 0 本就 falsy，不会触发真值判断的误判分支。"""
        assert http.has_business_error({"code": 0}) is False

    def test_string_zero_is_success(self):
        """字符串 "0" 是 truthy —— 这才是原 bug 的真正来源，不得当错误。"""
        assert http.has_business_error({"code": "0"}) is False

    def test_numeric_200_is_success(self):
        assert http.has_business_error({"code": 200}) is False

    def test_string_200_is_success(self):
        assert http.has_business_error({"code": "200"}) is False

    def test_string_zero_with_spaces_is_success(self):
        assert http.has_business_error({"code": " 0 "}) is False

    def test_bool_false_is_error(self):
        """False == 0 的陷阱：bool 不参与数值比较，不能被当成成功码。"""
        assert http.has_business_error({"code": False}) is True

    def test_bool_true_is_error(self):
        assert http.has_business_error({"code": True}) is True

    def test_absent_code_is_success(self):
        assert http.has_business_error({}) is False

    def test_empty_string_code_is_success(self):
        assert http.has_business_error({"code": ""}) is False

    def test_error_field_is_error(self):
        assert http.has_business_error({"error": "server_busy"}) is True

    def test_unknown_string_code_is_error(self):
        assert http.has_business_error({"code": "CLIENT_ERROR"}) is True

    def test_unknown_numeric_code_is_error(self):
        assert http.has_business_error({"code": 1001}) is True

    def test_non_dict_payload_is_not_error(self):
        assert http.has_business_error("boom") is False
        assert http.has_business_error(None) is False


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

    def test_ffprobe_preferred(self, monkeypatch, tmp_path):
        """ffprobe 可用时优先用其结果，不调用 pydub。"""
        f = tmp_path / "a.wav"
        f.write_bytes(b"fake")
        monkeypatch.setattr(
            audio_utils, "mediainfo", lambda p: {"duration": "12.5"}
        )

        class ForbiddenPydub:
            @staticmethod
            def from_file(*_args, **_kwargs):
                raise AssertionError("ffprobe 成功时不应调用 pydub")

        monkeypatch.setattr(audio_utils, "AudioSegment", ForbiddenPydub)
        assert audio_utils.get_audio_duration(str(f)) == 12.5

    def test_pydub_fallback_for_wav_without_ffmpeg(self, monkeypatch, tmp_path):
        """ffprobe 失败时用 pydub 兜底：WAV 走标准库后端，无需 ffmpeg。"""
        import wave

        f = tmp_path / "sample.wav"
        with wave.open(str(f), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x00\x00" * (8000 * 3))  # 3 秒

        def broken_ffprobe(_path):
            raise RuntimeError("ffprobe missing")

        monkeypatch.setattr(audio_utils, "mediainfo", broken_ffprobe)
        duration = audio_utils.get_audio_duration(str(f))
        assert duration is not None
        assert 2.9 <= duration <= 3.1


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
        assert c.QWEN_AUDIO_NEXT_MAX == 30.0


def _missing_path():
    from pathlib import Path

    return Path(__file__).parent / "__no_such_file__.mp3"


class TestPydubAvailability:
    def test_import_degrades_consistently(self):
        """pydub 缺失时 AudioSegment 与 mediainfo 必须同时降级为 None。"""
        assert (audio_utils.AudioSegment is None) == (audio_utils.mediainfo is None)

    def test_trim_reports_missing_pydub(self, monkeypatch, tmp_path):
        """真正驱动降级分支：pydub 不可用时必须抛出明确的 RuntimeError。"""
        monkeypatch.setattr(audio_utils, "AudioSegment", None)
        f = tmp_path / "a.mp3"
        f.write_bytes(b"not audio")
        with pytest.raises(RuntimeError, match="pydub 未安装"):
            audio_utils.trim_audio_to_max(str(f), max_sec=10)


class TestBase64FileCache:
    def _source(self, tmp_path, name="sample.wav", data=b"RIFFdata"):
        f = tmp_path / name
        f.write_bytes(data)
        return f

    def test_roundtrip_and_hit(self, tmp_path):
        src = self._source(tmp_path)
        cache_dir = tmp_path / "cache"
        cache = audio_utils.Base64FileCache(cache_dir, key_parts={"bytes": 100})
        assert cache.load(src) is None
        cache.save(src, "QUJD")
        assert cache.load(src) == "QUJD"

    def test_key_parts_change_invalidates_cache(self, tmp_path):
        src = self._source(tmp_path)
        cache_dir = tmp_path / "cache"
        audio_utils.Base64FileCache(cache_dir, key_parts={"bytes": 100}).save(src, "first")
        assert audio_utils.Base64FileCache(cache_dir, key_parts={"bytes": 100}).load(src) == "first"
        # 业务参数变化后不命中旧缓存
        assert audio_utils.Base64FileCache(cache_dir, key_parts={"bytes": 50}).load(src) is None

    def test_save_is_atomic_no_tmp_left(self, tmp_path):
        src = self._source(tmp_path)
        cache_dir = tmp_path / "cache"
        audio_utils.Base64FileCache(cache_dir).save(src, "QUJD")
        assert list(cache_dir.glob("*.tmp")) == []

    def test_lru_prunes_oldest(self, tmp_path):
        import time

        cache_dir = tmp_path / "cache"
        cache = audio_utils.Base64FileCache(cache_dir, max_entries=2)
        sources = []
        for i in range(3):
            src = self._source(tmp_path, name=f"s{i}.wav", data=bytes([65 + i]) * 8)
            sources.append(src)
            cache.save(src, f"v{i}")
            time.sleep(0.01)  # 保证 mtime 递增
        files = list(cache_dir.glob("*.b64"))
        assert len(files) == 2
        # 第一个源文件（s0）的缓存应被淘汰，后两个保留
        assert cache.load(sources[0]) is None
        assert cache.load(sources[1]) == "v1"
        assert cache.load(sources[2]) == "v2"

    def test_corrupt_cache_is_ignored(self, tmp_path):
        src = self._source(tmp_path)
        cache_dir = tmp_path / "cache"
        cache = audio_utils.Base64FileCache(cache_dir)
        path = cache.save(src, "QUJD")
        path.write_bytes(b"\xff\xfe")  # 非 ASCII 半截文件
        assert cache.load(src) is None

    def test_key_contains_version_marker_and_parts(self, tmp_path):
        """键里固定带 v2 段，并包含业务参数段。"""
        src = self._source(tmp_path)
        cache_dir = tmp_path / "cache"
        cache = audio_utils.Base64FileCache(
            cache_dir, key_parts={"bytes": 100, "margin": 0.5}
        )
        path = cache.save(src, "QUJD")
        stem = path.name[: -len(".b64")]
        parts = stem.split("_")
        assert parts[3] == "v2"
        assert "bytes100" in parts
        assert "margin0.5" in parts

    def test_legacy_key_files_are_pruned(self, tmp_path):
        """旧键格式文件（无 v2 段）在写入时顺手清理。"""
        src = self._source(tmp_path)
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        legacy_mimo = cache_dir / "abcdef123456_111_222.b64"
        legacy_qwen = cache_dir / "abcdef123456_111_222_trim.b64"
        legacy_mimo.write_text("QUJD", encoding="ascii")
        legacy_qwen.write_text("QUJD", encoding="ascii")

        cache = audio_utils.Base64FileCache(cache_dir)
        cache.save(src, "QUJD")

        assert not legacy_mimo.exists()
        assert not legacy_qwen.exists()
        # 新键文件保留
        assert len(list(cache_dir.glob("*.b64"))) == 1

    def test_unrelated_files_are_not_touched(self, tmp_path):
        """只清理 *.b64，且只在本缓存目录顶层；其它文件不受影响。"""
        src = self._source(tmp_path)
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        keep = cache_dir / "notes.txt"
        keep.write_text("user data", encoding="utf-8")
        nested = cache_dir / "nested"
        nested.mkdir()
        nested_b64 = nested / "abcdef123456_111_222.b64"
        nested_b64.write_text("QUJD", encoding="ascii")

        cache = audio_utils.Base64FileCache(cache_dir)
        cache.save(src, "QUJD")

        assert keep.exists()
        assert nested_b64.exists()  # 不递归、不越层

    def test_corrupt_cache_file_is_deleted(self, tmp_path):
        """坏缓存（内容不是合法 Base64）被删除，随后重新编码。"""
        src = self._source(tmp_path)
        cache_dir = tmp_path / "cache"
        cache = audio_utils.Base64FileCache(cache_dir)
        path = cache.save(src, "QUJD")
        path.write_text("not-base64!!", encoding="utf-8")
        assert cache.load(src) is None
        assert not path.exists()
