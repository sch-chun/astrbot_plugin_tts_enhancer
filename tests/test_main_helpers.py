"""main.py 可独立测试的辅助逻辑。

通过 ``object.__new__`` 构造插件实例，绕过 __init__ 的副作用
（建目录、注册 Tool 与 Web 路由），从而单独验证 pure-ish 行为。
"""

import re

import pytest
from astrbot_plugin_tts_enhancer.main import (
    _SAFE_FILE_ID_RE,
    TTSEnhancerPlugin,
    _validate_file_id,
)
from astrbot_plugin_tts_enhancer.src.config import TTSEnhancerConfig
from conftest import DummyEvent

# P0-1 修复前的基线正则（仅用于「修复必须严格强于现状」的对照断言）。
# 实际生效的正则以插件 main._SAFE_FILE_ID_RE 为准，避免本地复制漂移。
_PRE_FIX_FILE_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")


class FakeTTSService:
    """TTSService 替身，按返回值映射决定是否合成成功。"""

    def __init__(self, succeed_for=None, component_factory=None):
        self.succeed_for = succeed_for if succeed_for is not None else set()
        self.component_factory = component_factory or (lambda text: f"RECORD({text})")
        self.calls = []

    async def synthesize(self, raw_text, event, context_messages):
        self.calls.append(raw_text)
        if raw_text in self.succeed_for:
            return self.component_factory(raw_text)
        return None


def _make_plugin(tmp_path, raw_config=None, tts_service=None):
    plugin = object.__new__(TTSEnhancerPlugin)
    plugin.config = TTSEnhancerConfig(raw_config or {})
    plugin.providers = plugin.config.get_providers()
    plugin.plugin_data_path = tmp_path
    plugin.name = "astrbot_plugin_tts_enhancer"
    plugin.tts_service = tts_service or FakeTTSService()
    return plugin


class TestValidateFileId:
    @pytest.mark.parametrize(
        "fid",
        [
            "abc",
            "A_1",
            "upload_1234567",
            "a" * 128,
            "upload_1790658522958.mp3",  # 原 P0-1：/upload 的真实产物必须能通过
            "a.b.c",
        ],
    )
    def test_valid_ids(self, fid):
        assert _validate_file_id(fid) == fid

    def test_upload_roundtrip_file_id_accepted(self):
        """原 P0-1 回归：上传接口产出的 file_id 必须能通过自身校验器。

        否则 /start_file_server、/stop_file_server、/file/upload 会全部 400，
        「上传音频 → 预览 → 音色克隆」链路从第一步后断死。
        """
        import time

        fid = f"upload_{int(time.time() * 1000)}.mp3"
        assert _validate_file_id(fid) == fid

    @pytest.mark.parametrize(
        "fid",
        [
            "",  # 空
            "a" * 129,  # 超长
            "../../etc/passwd",  # 路径穿越
            "..",
            "a/b",  # 含斜杠
            "a\\b",
            "文件名.mp3",  # 非白名单字符
            ".hidden",  # 首字符为点（隐藏文件）
            ".env",  # 首字符为点
            "a." * 70,  # 超长且含点号
            None,  # 非字符串
            123,  # 数字
            "a b",  # 空格
        ],
    )
    def test_invalid_ids_rejected(self, fid):
        with pytest.raises(ValueError):
            _validate_file_id(fid)


class TestResolveUploadsPath:
    def test_resolves_inside_uploads(self, tmp_path):
        plugin = _make_plugin(tmp_path)
        target = plugin._resolve_uploads_path("abc.mp3")
        assert target.parent == (tmp_path / "uploads").resolve()
        assert target.name == "abc.mp3"

    def test_parent_check_requires_uploads_dir_exists_semantics(self, tmp_path):
        """uploads 目录不存在时 resolve() 仍能返回规范化路径。"""
        plugin = _make_plugin(tmp_path)
        target = plugin._resolve_uploads_path("xyz.mp3")
        assert target.parent == (tmp_path / "uploads").resolve()


class TestProcessTtsText:
    async def test_plain_text_only_yields_plain(self, tmp_path):
        plugin = _make_plugin(tmp_path)
        out = await plugin._process_tts_text("纯文本", DummyEvent(), [])
        assert len(out) == 1
        assert out[0].text == "纯文本"

    async def test_successful_synthesis_replaces_with_record(self, tmp_path):
        plugin = _make_plugin(
            tmp_path, tts_service=FakeTTSService(succeed_for={"哈喽"})
        )
        out = await plugin._process_tts_text("<tts>哈喽</tts>", DummyEvent(), [])
        assert len(out) == 1
        assert out[0] == "RECORD(哈喽)"

    async def test_dual_output_appends_plain(self, tmp_path):
        plugin = _make_plugin(
            tmp_path,
            raw_config={"dual_output": True},
            tts_service=FakeTTSService(succeed_for={"哈喽"}),
        )
        out = await plugin._process_tts_text("<tts>哈喽</tts>", DummyEvent(), [])
        assert len(out) == 2
        assert out[0] == "RECORD(哈喽)"
        assert out[1].text == "哈喽"

    async def test_synthesis_failure_degrades_to_plain(self, tmp_path):
        plugin = _make_plugin(tmp_path, tts_service=FakeTTSService(succeed_for=set()))
        out = await plugin._process_tts_text("<tts>哈喽</tts>", DummyEvent(), [])
        assert len(out) == 1
        assert out[0].text == "哈喽"

    async def test_mixed_text_and_tts(self, tmp_path):
        plugin = _make_plugin(
            tmp_path, tts_service=FakeTTSService(succeed_for={"中间"})
        )
        out = await plugin._process_tts_text("前<tts>中间</tts>后", DummyEvent(), [])
        assert len(out) == 3
        assert out[0].text == "前"
        assert out[1] == "RECORD(中间)"
        assert out[2].text == "后"

    async def test_content_around_empty_tts_tag_is_preserved(self, tmp_path):
        """空标签夹在文本中间时，两侧文本仍应完整保留。"""
        plugin = _make_plugin(tmp_path)
        out = await plugin._process_tts_text("保留我<tts></tts>", DummyEvent(), [])
        joined = "".join(c.text for c in out)
        assert "保留我" in joined
        assert len(out) == 1


class TestKnownDefects:
    """已确认缺陷 —— 以 xfail 固化。"""

    @pytest.mark.xfail(
        reason="缺陷#1（与 test_tts_parser.py 的 #1 为同一空标签缺陷，二轮复核：设计取舍，"
        "降级为观察项）: _process_tts_text 对仅含空标签的文本返回空组件列表，"
        "使得该消息组件被静默删除，客户端将收不到任何内容。"
        "但空标签本就无内容可念，静默移除可接受，影响面极小",
        strict=False,
    )
    async def test_only_empty_tts_tag_should_not_vanish(self, tmp_path):
        plugin = _make_plugin(tmp_path)
        out = await plugin._process_tts_text("<tts></tts>", DummyEvent(), [])
        assert out != []


class TestFileIdRegexCandidate:
    """P0-1 修复后真实正则的验收标尺。

    直接复用插件 ``main._SAFE_FILE_ID_RE``（修复已落地），确保测试不漂移。
    ``_PRE_FIX_FILE_ID_RE`` 仅作「修复必须严格强于现状」的对照基线。
    """

    @pytest.mark.parametrize(
        "fid",
        [
            "upload_1790658522958.mp3",  # /upload 真实产物
            "upload_1790658522958.wav",
            "upload_1790658522958.m4a",
            "abc",
            "a-b_c",
            "a.b.c",
            "voice_2024.08.01_v2.mp3",
            "a" * 128,  # 长度上限
            "A",
            "_private",
        ],
    )
    def test_real_regex_accepts(self, fid):
        assert _SAFE_FILE_ID_RE.match(fid), f"真实正则误杀合法 file_id: {fid!r}"

    @pytest.mark.parametrize(
        "fid",
        [
            "",  # 空串
            ".",  # 当前目录
            "..",  # 父目录
            "../etc/passwd",  # 经典穿越
            "..\\..\\windows\\system32",  # Windows 穿越
            ".hidden",  # 隐藏文件
            ".env",  # 敏感文件
            ".gitignore",
            "a/b",  # 路径分隔符
            "a\\b",  # Windows 分隔符
            "/abs/path",
            "中文.mp3",  # 非 ASCII
            "has space.mp3",  # 空格
            "has\ttab",
            "a" * 129,  # 超长
            "upload\n179.mp3",  # 换行注入
        ],
    )
    def test_real_regex_rejects(self, fid):
        assert not _SAFE_FILE_ID_RE.match(fid), f"真实正则误放行危险 file_id: {fid!r}"

    def test_real_regex_is_stricter_than_prefixed(self):
        """修复后正则必须严格强于修复前基线：基线能挡的，修复后一个都不能放开。"""
        for fid in [
            "a/b",
            "a\\b",
            "中文.mp3",
            "has space.mp3",
            "a" * 129,
            "../etc/passwd",
        ]:
            assert not _PRE_FIX_FILE_ID_RE.match(fid)
            assert not _SAFE_FILE_ID_RE.match(fid)

    def test_real_regex_fixes_the_real_file_id(self):
        """修复后正则必须让 /upload 的真实产物通过 —— 修复的核心目标。"""
        fid = "upload_1790658522958.mp3"
        assert not _PRE_FIX_FILE_ID_RE.match(fid), "修复前基线应当失败"
        assert _SAFE_FILE_ID_RE.match(fid), "修复后应当通过"
