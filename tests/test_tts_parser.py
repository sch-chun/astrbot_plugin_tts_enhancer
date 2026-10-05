"""src/tts_parser.py 单元测试 —— 重点覆盖标签解析的边界与异常路径。"""

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


class TestAcceptedBehavior:
    """已接受的设计取舍 —— 普通绿测，锁定当前契约行为。

    原 xfail 标记的缺陷（#1 / #1 连带 / #3）经二轮复核判定为设计取舍，降级为观察项，
    不再计划修复。改为直接断言已接受的实际行为，避免用 xfail 持续发出「这是 bug」
    的误导信号，也避免 strict=True 在正常重构时误挂 CI。
    """

    def test_empty_tts_tag_yields_empty(self):
        """设计取舍（原缺陷#1）：空 <tts></tts> 标签无内容可念，解析返回空列表。

        上游 _process_tts_text 会据此丢弃整个 Plain 组件；仅当整条消息只有一个
        空标签时客户端收不到内容，影响面极小，接受该行为。
        """
        assert split_by_tts_tags("<tts></tts>") == []

    def test_whitespace_only_tts_tag_yields_empty(self):
        """设计取舍（原缺陷#1 连带）：纯空白标签同样返回空列表，接受。"""
        assert split_by_tts_tags("<tts>   </tts>") == []

    def test_nested_tags_leak_inner_tag(self):
        """设计取舍（原缺陷#3）：嵌套标签不递归展开，内层 <tts> 残留于 TTS 内容。

        <tts> 是给 LLM 的标记，嵌套属未定义输入，非递归解析器给出未定义输出可接受；
        尾部 c 仍被保留为纯文本。
        """
        assert split_by_tts_tags("<tts>a<tts>b</tts>c</tts>") == [
            {"type": "tts", "content": "a<tts>b"},
            {"type": "text", "content": "c"},
        ]


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
