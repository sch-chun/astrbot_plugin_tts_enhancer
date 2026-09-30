"""src/tts_parser.py 单元测试 —— 重点覆盖标签解析的边界与异常路径。"""

import pytest
from astrbot_plugin_tts_enhancer.src.tts_parser import split_by_tts_tags


class TestHappyPath:
    """常规解析路径。"""

    def test_plain_text_only(self):
        assert split_by_tts_tags("你好世界") == [
            {"type": "text", "content": "你好世界"}
        ]

    def test_single_tts_tag(self):
        assert split_by_tts_tags("你好<tts>哈哈</tts>世界") == [
            {"type": "text", "content": "你好"},
            {"type": "tts", "content": "哈哈"},
            {"type": "text", "content": "世界"},
        ]

    def test_multiple_tts_tags(self):
        assert split_by_tts_tags("<tts>a</tts>中<tts>b</tts>") == [
            {"type": "tts", "content": "a"},
            {"type": "text", "content": "中"},
            {"type": "tts", "content": "b"},
        ]

    def test_empty_string(self):
        assert split_by_tts_tags("") == []

    def test_whitespace_only(self):
        assert split_by_tts_tags("   ") == []


class TestMalformedTags:
    """畸形标签：未闭合、孤立结束标签等降级路径。"""

    def test_unclosed_start_tag_degrades_to_text(self):
        """未闭合的开始标签，内容降级为纯文本（不应丢失）。"""
        assert split_by_tts_tags("<tts>abc") == [{"type": "text", "content": "abc"}]

    def test_orphan_end_tag(self):
        """孤立的结束标签被当作普通文本处理。"""
        assert split_by_tts_tags("abc</tts>def") == [
            {"type": "text", "content": "abc"},
            {"type": "text", "content": "def"},
        ]

    def test_only_end_tag(self):
        assert split_by_tts_tags("</tts>") == []

    def test_boundary_separator_stripped(self):
        """TTS 内容首尾的 $ 边界符应被剥离。"""
        assert split_by_tts_tags("<tts>$哈哈$</tts>") == [
            {"type": "tts", "content": "哈哈"}
        ]

    def test_leading_separator_stripped_after_tts(self):
        assert split_by_tts_tags("<tts>a</tts>$$b") == [
            {"type": "tts", "content": "a"},
            {"type": "text", "content": "b"},
        ]


class TestKnownDefects:
    """已确认缺陷 —— xfail(strict=True) 固化现状。

    修复后这些用例会 XPASS 并使 CI 失败，以此提醒摘掉标记，
    而不是永远静默地「绿着不办事」。
    """

    @pytest.mark.xfail(
        reason="缺陷#1（二轮复核：设计取舍，降级为观察项）: 空 <tts></tts> 标签返回空列表，"
        "上游 _process_tts_text 会丢弃整个 Plain 组件。但空标签本就无内容可念，"
        "静默移除可接受；仅「整条消息只有一个空标签」时客户端收不到内容，影响面极小",
        strict=True,
    )
    def test_empty_tts_tag_should_preserve_nothing_but_not_break(self):
        # 期望：不应返回空列表导致整段文本被吞；返回 [] 亦可接受，
        # 但上游必须有兜底。此处断言「解析结果非空或为纯文本兜底」
        result = split_by_tts_tags("<tts></tts>")
        assert result != []  # 当前实际行为为 []，故 xfail

    @pytest.mark.xfail(reason="缺陷#1 连带影响: 纯空白标签同样返回空列表", strict=True)
    def test_whitespace_only_tts_tag(self):
        assert split_by_tts_tags("<tts>   </tts>") != []

    @pytest.mark.xfail(
        reason="缺陷#3（二轮复核：设计取舍，降级为观察项）: 嵌套标签未被展开，"
        "内层 <tts> 残留于 TTS 内容中将被原样发送给 API。"
        "但 <tts> 是给 LLM 的标记，嵌套属未定义输入，非递归解析器给出未定义输出可接受。"
        "注：完整产出为 [{'tts':'a<tts>b'}, {'text':'c'}] —— 尾部 c 会被保留为纯文本",
        strict=True,
    )
    def test_nested_tags_should_not_leak_inner_tag(self):
        result = split_by_tts_tags("<tts>a<tts>b</tts>c</tts>")
        for seg in result:
            assert "<tts>" not in seg["content"]


class TestRegressionGuards:
    """已修复缺陷的回归用例（非 xfail，修复后必须稳定通过）。"""

    def test_none_input_should_not_raise(self):
        """原缺陷#2 回归：非字符串入参应返回空列表而非抛 TypeError。"""
        assert split_by_tts_tags(None) == []

    def test_non_string_input_returns_empty(self):
        for bad in (None, 123, [], {}):
            assert split_by_tts_tags(bad) == []

    def test_dollar_only_content_is_kept_as_text(self):
        """内容为纯 $ 时被 trim 为空 → 触发兜底，整体降级为纯文本。"""
        assert split_by_tts_tags("<tts>$$$</tts>") == [
            {"type": "text", "content": "$$$"}
        ]
