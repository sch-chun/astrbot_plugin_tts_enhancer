"""
main.py 中模块级辅助函数的单元测试。

覆盖 0.3.3 引入的安全加固与类型容错：
- ``_validate_file_id`` / ``_resolve_uploads_path`` 的白名单与穿越防护；
- ``_parse_entry_id`` 的索引校验（含 bool 子类陷阱）。

注意：``_parse_entry_id`` / 上传路由本身需要完整插件实例，此处仅测试可独立
调用的纯函数；插件类方法的集成测试依赖更重的 AstrBot Context 替身，暂未覆盖。
"""

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("astrbot.core.star")

_MAIN_PY = Path(__file__).resolve().parents[1] / "main.py"


def _load_main_module():
    """以独立模块名导入 main.py，避免与插件加载器的包内导入冲突。"""
    spec = importlib.util.spec_from_file_location("_tts_enhancer_main_under_test", _MAIN_PY)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def main_mod():
    return _load_main_module()


class TestValidateFileId:
    """_validate_file_id：上传文件名的白名单校验。"""

    @pytest.mark.parametrize(
        "file_id",
        [
            "upload_1730000000000.mp3",
            "upload_1.wav",
            "a",
            "A_b-1.2",
            "_leading_underscore.mp3",
            "a" * 128,  # 恰好 128 长度上限
        ],
    )
    def test_accepts_safe_names(self, main_mod, file_id):
        assert main_mod._validate_file_id(file_id) == file_id

    @pytest.mark.parametrize(
        "file_id",
        [
            "",  # 空串
            ".",  # 纯点
            "..",  # 父目录
            ".env",  # 隐藏文件（首字符为点）
            ".hidden.mp3",
            "a/b.mp3",  # 路径分隔符
            "a\\b.mp3",  # Windows 分隔符
            "a..b/c",  # 组合穿越
            "a" * 129,  # 超长
            "upload.mp3 ",  # 尾部空格
        ],
    )
    def test_rejects_unsafe_names(self, main_mod, file_id):
        with pytest.raises(ValueError):
            main_mod._validate_file_id(file_id)

    @pytest.mark.parametrize("bad", [None, 123, b"bytes", ["list"], {"d": 1}])
    def test_rejects_non_string(self, main_mod, bad):
        with pytest.raises(ValueError):
            main_mod._validate_file_id(bad)

    def test_regex_is_real_compiled_pattern(self, main_mod):
        """回归：白名单来自真实编译的正则（而非宽松的字符串判断）。"""
        import re as _re

        assert isinstance(main_mod._SAFE_FILE_ID_RE, _re.Pattern)
        assert main_mod._SAFE_FILE_ID_RE.match("upload_1.mp3")
        assert main_mod._SAFE_FILE_ID_RE.match(".env") is None


class TestParseEntryId:
    """_parse_entry_id：请求体 entry_id 的类型与边界校验。"""

    def test_valid_index(self, main_mod):
        assert main_mod._parse_entry_id(0, 3) == 0
        assert main_mod._parse_entry_id(2, 3) == 2

    def test_out_of_range_returns_none(self, main_mod):
        assert main_mod._parse_entry_id(3, 3) is None  # 上界越界
        assert main_mod._parse_entry_id(-1, 3) is None  # 负值

    def test_empty_providers_returns_none(self, main_mod):
        assert main_mod._parse_entry_id(0, 0) is None

    @pytest.mark.parametrize("bad", [None, "0", "1", 1.0, [], {}])
    def test_non_int_returns_none(self, main_mod, bad):
        assert main_mod._parse_entry_id(bad, 3) is None

    def test_bool_excluded_even_though_int_subclass(self, main_mod):
        """bool 是 int 子类：True 不能被当作索引 1 放行。"""
        assert main_mod._parse_entry_id(True, 3) is None
        assert main_mod._parse_entry_id(False, 3) is None


class TestModuleImportDiscipline:
    """导入纪律：正则与常量应在模块顶层定义，且不因导入而副作用执行。"""

    def test_safe_file_id_re_available(self, main_mod):
        assert hasattr(main_mod, "_SAFE_FILE_ID_RE")

    def test_constants_exist(self, main_mod):
        assert hasattr(main_mod, "TTS_START_TAG")
        assert hasattr(main_mod, "TTS_END_TAG")


class TestValidateFileIdRegexContract:
    """_SAFE_FILE_ID_RE 的正则契约（形状边界）。"""

    def test_allows_dot_not_as_separator(self, main_mod):
        # 点号允许出现在中间（真实文件名 upload_<ts>.mp3 需要它）
        assert main_mod._SAFE_FILE_ID_RE.match("upload_0.mp3")

    def test_rejects_slash(self, main_mod):
        assert main_mod._SAFE_FILE_ID_RE.match("a/b") is None

    def test_rejects_backslash(self, main_mod):
        assert main_mod._SAFE_FILE_ID_RE.match("a\\b") is None

    def test_first_char_class(self, main_mod):
        # 首字符不能是点/横线，避免隐藏文件与边界歧义
        assert main_mod._SAFE_FILE_ID_RE.match("_ok") is not None
        assert main_mod._SAFE_FILE_ID_RE.match("-ok") is None
        assert main_mod._SAFE_FILE_ID_RE.match(".ok") is None
