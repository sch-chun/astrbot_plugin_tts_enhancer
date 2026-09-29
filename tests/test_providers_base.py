"""providers/base.py 单元测试 —— 抽象基类的通用校验工具。"""

import pytest
from astrbot_plugin_tts_enhancer.providers.base import TTSProviderAdapter


class ConcreteAdapter(TTSProviderAdapter):
    """用于实例化抽象基类的最小实现。"""

    def get_subagent_system_prompt(self) -> str:
        return "prompt"

    def get_tool_schema(self):
        return None

    async def call_api(self, text, raw_params, config, voice_id=None):
        return ""


@pytest.fixture
def adapter():
    return ConcreteAdapter({"__template_key": "concrete"})


class TestValidateVoiceId:
    """validate_voice_id 的格式与长度校验。"""

    def test_empty_allowed(self, adapter):
        """空值放行，由调用方决定是否必填。"""
        adapter.validate_voice_id("")

    def test_valid_minimum_length(self, adapter):
        adapter.validate_voice_id("abcdefgh")  # 8 位

    def test_valid_with_hyphen_and_underscore(self, adapter):
        adapter.validate_voice_id("abc-def_gh")

    def test_too_short(self, adapter):
        with pytest.raises(ValueError, match="长度必须为"):
            adapter.validate_voice_id("abcdefg")  # 7 位

    def test_too_long(self, adapter):
        with pytest.raises(ValueError, match="长度必须为"):
            adapter.validate_voice_id("a" * 257)

    def test_max_length_boundary(self, adapter):
        adapter.validate_voice_id("a" + "b" * 254 + "c")  # 256 位

    def test_leading_digit_rejected(self, adapter):
        with pytest.raises(ValueError, match="格式不合法"):
            adapter.validate_voice_id("1abcdefgh")

    def test_trailing_hyphen_rejected(self, adapter):
        with pytest.raises(ValueError, match="格式不合法"):
            adapter.validate_voice_id("abcdefgh-")

    def test_trailing_underscore_rejected(self, adapter):
        with pytest.raises(ValueError, match="格式不合法"):
            adapter.validate_voice_id("abcdefgh_")

    def test_chinese_rejected_when_long_enough(self, adapter):
        """长度达标后，中文仍应被格式规则拒绝。"""
        with pytest.raises(ValueError, match="格式不合法"):
            adapter.validate_voice_id("中文美女音色测试")

    def test_length_checked_before_pattern(self, adapter):
        """校验顺序：先长度后格式，短于下限的中文报长度错误。"""
        with pytest.raises(ValueError, match="长度必须为"):
            adapter.validate_voice_id("中文")

    def test_custom_range(self, adapter):
        adapter.validate_voice_id("ab", min_len=2, max_len=4)


class TestCountTextChars:
    """_count_text_chars 的字符计数规则。"""

    def test_ascii(self, adapter):
        assert adapter._count_text_chars("hello") == 5

    def test_cjk_counts_double(self, adapter):
        assert adapter._count_text_chars("你好") == 4

    def test_mixed(self, adapter):
        assert adapter._count_text_chars("你好ab") == 6

    def test_empty_and_none(self, adapter):
        assert adapter._count_text_chars("") == 0
        assert adapter._count_text_chars(None) == 0


class TestValidateTextLength:
    def test_none_is_noop(self, adapter):
        adapter.validate_text_length(None)

    def test_empty_is_noop(self, adapter):
        adapter.validate_text_length("")

    def test_within_limit(self, adapter):
        adapter.validate_text_length("你好世界", max_len=200)

    def test_exceeds_limit(self, adapter):
        with pytest.raises(ValueError, match="长度必须为"):
            adapter.validate_text_length("你" * 101, max_len=200)  # 202 > 200

    def test_exact_boundary(self, adapter):
        adapter.validate_text_length("你" * 100, max_len=200)  # 恰好 200

    def test_min_len(self, adapter):
        with pytest.raises(ValueError):
            adapter.validate_text_length("ab", min_len=5, max_len=10)


class TestDocsLoading:
    def test_missing_docs_returns_empty(self):
        ad = ConcreteAdapter({"__template_key": "no_such_provider"})
        assert ad.docs_content == ""

    def test_docs_key_falls_back_to_template_key(self):
        ad = ConcreteAdapter({"__template_key": "whatever"})
        assert ad.docs_key == "whatever"


class TestVoiceLifecycleDefaults:
    """基类未实现的音色管理方法应明确抛 NotImplementedError。"""

    async def test_create_voice_not_implemented(self, adapter):
        with pytest.raises(NotImplementedError):
            await adapter.create_voice({})

    async def test_list_voice_not_implemented(self, adapter):
        with pytest.raises(NotImplementedError):
            await adapter.list_voice()

    async def test_delete_voice_not_implemented(self, adapter):
        with pytest.raises(NotImplementedError):
            await adapter.delete_voice()


class TestKnownDefects:
    """已确认缺陷 —— 以 xfail 固化。"""

    def test_fullwidth_punctuation_should_count_double(self, adapter):
        """原缺陷#7 回归：全角标点按 2 计（多数 TTS 厂商按全角计费）。"""
        assert adapter._count_text_chars("你好，世界！") == 12
        assert adapter._count_text_chars("，") == 2

    def test_kana_should_count_double(self, adapter):
        """原缺陷#7 连带回归：日文假名按 2 计。"""
        assert adapter._count_text_chars("こんにちは") == 10

    def test_emoji_should_count_double(self, adapter):
        """原缺陷#7 连带回归：emoji 按 2 计。"""
        assert adapter._count_text_chars("\U0001f600") == 2

    def test_ascii_still_counts_single(self, adapter):
        """ASCII 与半角字符仍按 1 计，避免修复过度。"""
        assert adapter._count_text_chars("hello") == 5
        assert adapter._count_text_chars("a b") == 3


class TestAsNumberHelpers:
    """_as_float / _as_int 的类型收敛（入参来自 LLM 输出，类型不可信）。"""

    # ---- _as_float ----
    @pytest.mark.parametrize(
        "value, expected",
        [
            (1.5, 1.5),
            (1, 1.0),
            (0, 0.0),
            ("1.5", 1.5),
            ("  2 ", 2.0),
            (80.0, 80.0),
        ],
    )
    def test_as_float_accepts(self, adapter, value, expected):
        assert adapter._as_float(value) == expected

    @pytest.mark.parametrize("value", ["abc", "", None, [], {}, "1.2.3"])
    def test_as_float_rejects(self, adapter, value):
        assert adapter._as_float(value) is None

    def test_as_float_rejects_bool(self, adapter):
        """bool 是 int 子类，必须被排除，不能当 1.0 通过。"""
        assert adapter._as_float(True) is None
        assert adapter._as_float(False) is None

    # ---- _as_int ----
    @pytest.mark.parametrize(
        "value, expected",
        [
            (50, 50),
            (50.0, 50),  # 整型浮点接受
            ("50", 50),
            ("  80 ", 80),
        ],
    )
    def test_as_int_accepts(self, adapter, value, expected):
        assert adapter._as_int(value) == expected

    @pytest.mark.parametrize("value", ["abc", "", None, 80.5, "80.5", [], {}])
    def test_as_int_rejects(self, adapter, value):
        """非整型浮点（80.5）与无法解析的值返回 None。"""
        assert adapter._as_int(value) is None

    def test_as_int_rejects_bool(self, adapter):
        assert adapter._as_int(True) is None
        assert adapter._as_int(False) is None
