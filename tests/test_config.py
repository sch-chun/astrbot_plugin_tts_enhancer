"""src/config.py 单元测试 —— 覆盖排序、去重、命名回退与异常配置。"""

from astrbot_plugin_tts_enhancer.src.config import TTSEnhancerConfig


def _prov(*items):
    return {"providers": list(items)}


class TestProviderLoading:
    def test_empty_config_warns_and_returns_empty(self):
        cfg = TTSEnhancerConfig(None)
        assert cfg.get_providers() == []
        assert cfg.has_providers() is False

    def test_missing_providers_key(self):
        cfg = TTSEnhancerConfig({"other": 1})
        assert cfg.get_providers() == []

    def test_empty_providers_list(self):
        cfg = TTSEnhancerConfig({"providers": []})
        assert cfg.get_providers() == []

    def test_sorted_by_priority_ascending(self):
        cfg = TTSEnhancerConfig(
            _prov(
                {"priority": 30, "k": "c"},
                {"priority": 10, "k": "a"},
                {"priority": 20, "k": "b"},
            )
        )
        assert [e["k"] for e in cfg.get_providers()] == ["a", "b", "c"]

    def test_default_priority_is_100(self):
        cfg = TTSEnhancerConfig(_prov({"priority": 200, "k": "late"}, {"k": "default"}))
        assert [e["k"] for e in cfg.get_providers()] == ["default", "late"]

    def test_stable_order_for_equal_priority(self):
        """相同 priority 时保持配置书写顺序。"""
        cfg = TTSEnhancerConfig(
            _prov(
                {"priority": 5, "k": "first"},
                {"priority": 5, "k": "second"},
                {"priority": 5, "k": "third"},
            )
        )
        assert [e["k"] for e in cfg.get_providers()] == ["first", "second", "third"]

    def test_has_providers_true(self):
        cfg = TTSEnhancerConfig(_prov({"priority": 1}))
        assert cfg.has_providers() is True

    def test_mixed_priority_types_does_not_raise(self):
        """P1-4 回归：priority 数值/字符串混排不再触发 TypeError。

        原先 int/str 混排会在 sorted 时抛 TypeError；现由 _to_priority_int 兜底为 100
        （非数值告警但不崩溃）。本条曾以 xfail 固化，代码修复后改为普通回归用例。
        """
        cfg = TTSEnhancerConfig(_prov({"priority": 1}, {"priority": "5"}))
        providers = cfg.get_providers()
        assert len(providers) == 2


class TestDisplayNameDeduplication:
    def test_duplicate_display_name_gets_suffix(self):
        cfg = TTSEnhancerConfig(
            _prov(
                {"display_name": "小明"},
                {"display_name": "小明"},
                {"display_name": "小明"},
            )
        )
        names = [cfg.get_entry_name(e) for e in cfg.get_providers()]
        assert names == ["小明", "小明 #2", "小明 #3"]

    def test_unique_display_name_unchanged(self):
        cfg = TTSEnhancerConfig(_prov({"display_name": "小红"}))
        assert cfg.get_entry_name(cfg.get_providers()[0]) == "小红"

    def test_blank_display_name_is_skipped_in_dedup(self):
        cfg = TTSEnhancerConfig(
            _prov({"display_name": "   "}, {"display_name": "小明"})
        )
        assert cfg.get_entry_name(cfg.get_providers()[1]) == "小明"


class TestGetEntryNameFallback:
    def test_falls_back_to_template_key_and_voice(self):
        cfg = TTSEnhancerConfig({})
        entry = {"__template_key": "minimax", "voice": "male-qn"}
        assert cfg.get_entry_name(entry) == "minimax (male-qn)"

    def test_falls_back_to_template_key_and_index(self):
        cfg = TTSEnhancerConfig({})
        entry = {"__template_key": "minimax"}
        assert cfg.get_entry_name(entry, 2) == "minimax #2"

    def test_falls_back_to_template_key_only(self):
        cfg = TTSEnhancerConfig({})
        assert cfg.get_entry_name({"__template_key": "minimax"}) == "minimax"

    def test_unknown_template_key_when_missing(self):
        cfg = TTSEnhancerConfig({})
        assert cfg.get_entry_name({}) == "unknown"

    def test_index_zero_boundary(self):
        """index=0 是有效索引（>=0），不应被当作「无索引」。"""
        cfg = TTSEnhancerConfig({})
        assert cfg.get_entry_name({"__template_key": "k"}, 0) == "k #0"


class TestGet:
    def test_get_returns_default(self):
        cfg = TTSEnhancerConfig({"a": 1})
        assert cfg.get("a") == 1
        assert cfg.get("missing") is None
        assert cfg.get("missing", "fallback") == "fallback"


class TestAcceptedBehavior:
    """已接受的设计取舍 —— 普通绿测，锁定当前契约行为。

    原 xfail 标记的缺陷#5（设计取舍）经二轮复核降级为观察项，不再计划修复；
    改为断言已接受的「就地写入调用方配置」行为。缺陷#6（上游担保）不可达，已删除用例，
    决策见 docs/zh/KNOWN_LIMITATIONS.md。
    """

    def test_resolves_name_into_caller_config(self):
        """设计取舍（原缺陷#5）：_load_providers 会就地写入调用方传入的 raw_config。

        __resolved_name 仅为去重显示名、非敏感信息，且 AstrBot 对 schema 外字段宽容，
        不会污染保存流程，故接受该行为。
        """
        raw = _prov({"display_name": "小明"})
        TTSEnhancerConfig(raw)
        assert raw["providers"][0]["__resolved_name"] == "小明"
