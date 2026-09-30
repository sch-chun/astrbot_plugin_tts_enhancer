"""ProviderFactory 自动发现机制与全部供应商的冒烟测试。

这些用例不依赖网络，仅验证：适配器能被发现、可实例化、文档齐备、
工具 Schema 符合契约，以及参数校验不会在常规输入下崩溃。
"""

from pathlib import Path

import pytest
from astrbot_plugin_tts_enhancer.providers import ProviderFactory
from astrbot_plugin_tts_enhancer.providers.base import TTSProviderAdapter

ProviderFactory._discover_adapters()
ALL_KEYS = sorted(ProviderFactory._adapters)


def _adapters():
    return ProviderFactory._adapters


def test_discovery_finds_expected_adapters():
    adapters = _adapters()
    assert adapters, "未发现任何供应商适配器"
    for key, cls in adapters.items():
        assert issubclass(cls, TTSProviderAdapter), f"{key} 未继承基类"
        assert isinstance(key, str) and key


def test_module_name_matches_template_key_convention():
    """自动发现以模块名为 key，因此配置里的 __template_key 必须等于文件名。"""
    py_files = {
        p.stem
        for p in (Path(__file__).parents[1] / "providers").glob("*.py")
        if not p.name.startswith("_") and p.name != "base.py"
    }
    assert set(_adapters().keys()) == py_files


class TestGetAdapter:
    def test_unknown_template_key_returns_none(self):
        assert ProviderFactory.get_adapter({"__template_key": "nope"}) is None

    def test_missing_template_key_returns_none(self):
        assert ProviderFactory.get_adapter({}) is None

    def test_none_entry_returns_none(self):
        """原缺陷#19 回归：None 及非 dict 入参应返回 None 而非抛 AttributeError。"""
        assert ProviderFactory.get_adapter(None) is None

    @pytest.mark.parametrize("bad", [None, "x", 123, []])
    def test_non_dict_entry_returns_none(self, bad):
        assert ProviderFactory.get_adapter(bad) is None

    def test_returns_instance_for_known_key(self):
        key = ALL_KEYS[0]
        adapter = ProviderFactory.get_adapter({"__template_key": key})
        assert isinstance(adapter, TTSProviderAdapter)

    def test_adapter_is_recreated_each_call(self):
        """get_adapter 每次返回新实例（Adapter 持有配置，不应跨调用共享）。"""
        key = ALL_KEYS[0]
        a = ProviderFactory.get_adapter({"__template_key": key})
        b = ProviderFactory.get_adapter({"__template_key": key})
        assert a is not b


class TestAllProvidersSmoke:
    """对每一个已发现供应商执行最小契约检查。"""

    @pytest.fixture(params=ALL_KEYS)
    def entry_and_adapter(self, request):
        key = request.param
        entry = {
            "__template_key": key,
            "api_key": "test-key",
            "voice_id": "Testvoice1",
        }
        return key, _adapters()[key](entry)

    def test_docs_content_is_loaded(self, entry_and_adapter):
        key, adapter = entry_and_adapter
        assert adapter.docs_content, f"{key} 缺少能力文档 docs/{adapter.docs_key}.md"

    def test_tool_schema_is_function_tool_with_tts_enhance(self, entry_and_adapter):
        key, adapter = entry_and_adapter
        tool = adapter.get_tool_schema()
        assert tool is not None, f"{key} 未实现 get_tool_schema"
        assert tool.name == "tts_enhance", f"{key} 工具名不是 tts_enhance"
        params = tool.parameters
        assert params["type"] == "object"
        assert "text" in params["properties"]
        assert "text" in params["required"]

    def test_system_prompt_is_non_empty(self, entry_and_adapter):
        _key, adapter = entry_and_adapter
        prompt = adapter.get_subagent_system_prompt()
        assert isinstance(prompt, str) and prompt.strip()

    def test_validate_params_accepts_empty_dict(self, entry_and_adapter):
        """空参数字典应被接受且不带错误信息（实测 6 个适配器一致）。"""
        key, adapter = entry_and_adapter
        assert adapter.validate_params({}) == (True, ""), f"{key} 空参数未被接受"

    def test_sanitize_params_preserves_text(self, entry_and_adapter):
        """清洗后必须保留 text，且不得混入未声明的多余字段。"""
        key, adapter = entry_and_adapter
        out = adapter.sanitize_params({"text": "hi"})
        assert out["text"] == "hi", f"{key} 丢失了 text"
        assert set(out) <= {"text", "instruction"}, f"{key} 出现意外字段: {sorted(out)}"


class TestDocsDiscovery:
    def test_docs_directory_contains_all_docs_keys(self):
        docs_dir = Path(__file__).parents[1] / "providers" / "docs"
        missing = []
        for key, cls in _adapters().items():
            adapter = cls({"__template_key": key})
            expected = docs_dir / f"{adapter.docs_key}.md"
            if not expected.exists():
                missing.append((key, str(expected)))
        assert missing == [], f"以下供应商缺少能力文档: {missing}"
