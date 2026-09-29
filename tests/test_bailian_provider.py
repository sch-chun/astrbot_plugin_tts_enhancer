"""providers/_bailian_speech_synthesizer.py 单元测试。

验证百炼适配器在引入基类共享的 ``_as_int`` / ``_as_float`` 之后的参数处理：
- LLM 以字符串返回数字时正常接受（修复前一律被 isinstance 守卫拒掉）；
- bool 不再泄漏为 1（修复前 isinstance(x, (int, float)) 放过了 bool）；
- 越界 / 非法值友好拒绝而非抛 TypeError。
"""

import pytest
from astrbot_plugin_tts_enhancer.providers._bailian_speech_synthesizer import (
    BailianSpeechSynthesizerAdapter,
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
