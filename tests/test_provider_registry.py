"""ProviderFactory 自动发现机制与全部供应商的冒烟测试。

这些用例不依赖网络，仅验证：适配器能被发现、可实例化、文档齐备、
工具 Schema 符合契约，以及参数校验不会在常规输入下崩溃。
"""

import time
from pathlib import Path
import json

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
    """自动发现以模块名为 key，因此配置里的 __template_key 必须等于文件名。

    ``base.py`` 与 ``mixins.py`` 为支撑模块而非适配器，不参与自动发现，须排除。
    """
    py_files = {
        p.stem
        for p in (Path(__file__).parents[1] / "providers").glob("*.py")
        if not p.name.startswith("_")
        and p.name != "base.py"
        and p.name != "mixins.py"
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
        # 主字段名由 provider 声明（生成式音频类用 text_prompt，其余用 text）
        prompt_field = adapter.TOOL_PROMPT_FIELD
        assert prompt_field in params["properties"], (
            f"{key} 工具缺少主字段 {prompt_field}"
        )
        assert prompt_field in params["required"], (
            f"{key} 工具主字段 {prompt_field} 非必填"
        )
        # 声明的额外字段必须与工具 schema 一致，防止声明漂移。
        # 用动态方法读取：Eleven 等适配器会按运行时状态返回不同的字段集合。
        schema_extra = set(params["properties"]) - {prompt_field}
        declared = set(adapter.tool_extra_fields())
        assert schema_extra == declared, (
            f"{key} tool_extra_fields() 与工具 schema 不一致: "
            f"声明={sorted(declared)}, schema={sorted(schema_extra)}"
        )

    def test_system_prompt_is_non_empty(self, entry_and_adapter):
        _key, adapter = entry_and_adapter
        prompt = adapter.get_subagent_system_prompt()
        assert isinstance(prompt, str) and prompt.strip()

    def test_validate_params_accepts_empty_dict(self, entry_and_adapter):
        """空参数字典应被接受且不带错误信息（实测 6 个适配器一致）。"""
        key, adapter = entry_and_adapter
        assert adapter.validate_params({}) == (True, ""), f"{key} 空参数未被接受"

    def test_sanitize_params_preserves_text(self, entry_and_adapter):
        """清洗后必须保留主字段，且不得混入该适配器未声明的多余字段。"""
        key, adapter = entry_and_adapter
        prompt_field = adapter.TOOL_PROMPT_FIELD
        out = adapter.sanitize_params({prompt_field: "hi"})
        assert out[prompt_field] == "hi", f"{key} 丢失了 {prompt_field}"
        allowed = {prompt_field, *adapter.tool_extra_fields()}
        assert set(out) <= allowed, (
            f"{key} 出现未声明字段: {sorted(set(out) - allowed)}"
        )


class TestRuntimeToolContract:
    """契约真正落到运行时：未声明的工具参数必须被丢弃（P2-8）。"""

    @pytest.fixture(params=ALL_KEYS)
    def entry_and_adapter(self, request):
        key = request.param
        entry = {
            "__template_key": key,
            "api_key": "test-key",
            "voice_id": "Testvoice1",
        }
        return key, _adapters()[key](entry)

    async def test_undeclared_params_are_dropped(self, entry_and_adapter):
        """tts_enhance 传入未声明字段时，该字段不得出现在返回参数里。"""
        key, adapter = entry_and_adapter
        prompt_field = adapter.TOOL_PROMPT_FIELD
        result = await adapter._handle_enhance_tool(
            **{prompt_field: "hi", "junk_field": 1, "another_junk": "x"}
        )
        assert result.isError is False, f"{key} 合法参数不应报错"
        payload = json.loads(result.content[0].text)
        assert payload.get(prompt_field) == "hi"
        assert "junk_field" not in payload
        assert "another_junk" not in payload
        allowed = {prompt_field, *adapter.tool_extra_fields()}
        assert set(payload) <= allowed, (
            f"{key} 运行时泄漏未声明字段: {sorted(set(payload) - allowed)}"
        )

    async def test_undeclared_params_never_reach_validation(
        self, entry_and_adapter, monkeypatch
    ):
        """未声明字段连校验都不应进入（否则非法值会把整轮工具调用判为失败）。"""
        key, adapter = entry_and_adapter
        prompt_field = adapter.TOOL_PROMPT_FIELD
        seen: dict = {}
        original = adapter.validate_params

        def spy(params):
            seen.update(params)
            return original(params)

        monkeypatch.setattr(adapter, "validate_params", spy)
        await adapter._handle_enhance_tool(
            **{prompt_field: "hi", "junk_field": 1}
        )
        assert "junk_field" not in seen, f"{key} 未声明字段进入了校验流程"

    async def test_declared_params_are_kept(self, entry_and_adapter, monkeypatch):
        """已声明的额外字段必须原样保留（过滤不能误伤）。"""
        key, adapter = entry_and_adapter
        prompt_field = adapter.TOOL_PROMPT_FIELD
        extra = sorted(adapter.tool_extra_fields())
        if not extra:
            pytest.skip(f"{key} 无额外字段")
        seen: dict = {}
        original = adapter.validate_params

        def spy(params):
            seen.update(params)
            return original(params)

        monkeypatch.setattr(adapter, "validate_params", spy)
        await adapter._handle_enhance_tool(**{prompt_field: "hi", extra[0]: "keep-me"})
        assert extra[0] in seen, f"{key} 已声明字段 {extra[0]} 被误丢弃"


def test_eleven_tool_extra_fields_follows_injected_catalog_cache():
    """注入 catalog 类级缓存后，Eleven 的声明与工具 schema 同步扩展（P1-1）。

    之前这里只 monkeypatch 了 ``_get_catalog``，未真正走「类级缓存就绪」这条
    路径；本次直接写入 ``_CATALOG_CACHE``，验证声明与 schema 都随缓存状态变化。
    """
    from astrbot_plugin_tts_enhancer.providers import elevenlabs_v4 as eleven_mod

    adapter_cls = _adapters()["elevenlabs_v4"]
    entry = {
        "__template_key": "elevenlabs_v4",
        "api_key": "test-key",
        "voice_id": "Testvoice1",
        "use_audio_effects": True,
    }
    adapter = adapter_cls(entry)
    cache_key = adapter._catalog_key()
    eleven_mod._CATALOG_CACHE[cache_key] = {
        "catalog": {
            "filter_presets": ["phone"],
            "environments": ["hall"],
            "background_noises": ["cafe"],
        },
        "ts": time.time(),
    }
    try:
        declared = set(adapter.tool_extra_fields())
        schema_extra = set(adapter.get_tool_schema().parameters["properties"]) - {"text"}
        assert declared == schema_extra
        assert "filter_preset_id" in declared
        assert "language_code" in declared
        assert len(declared) == len(adapter.AUDIO_EFFECT_FIELDS) + 1
    finally:
        eleven_mod._CATALOG_CACHE.pop(cache_key, None)


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


class TestBailian3_1ModelWhitelist:
    """文档变更回归：qwen-audio-3.1-tts-plus 已上线，3.1 提供商模型白名单必须包含 plus。

    此前 3.1 刻意隐藏 plus（仅暴露 flash），plus 上线后若白名单仍硬编码 flash，
    用户即使配置 plus 也会被插件拦截。本组用例直接校验配置 schema 与前端组件，
    不依赖网络或 astrbot 运行时。
    """

    _REPO_ROOT = Path(__file__).parents[1]

    def test_conf_schema_3_1_model_options_include_plus(self):
        schema = json.loads(
            (self._REPO_ROOT / "_conf_schema.json").read_text(encoding="utf-8")
        )
        tmpl = schema["providers"]["templates"]["bailian_qwen_audio_3_1_tts"]
        model_opts = tmpl["items"]["model"]["options"]
        assert "plus" in model_opts, f"3.1 模型选项缺少 plus: {model_opts}"

    def test_frontend_3_1_component_exposes_plus(self):
        js_path = (
            self._REPO_ROOT
            / "pages"
            / "tts_studio"
            / "components"
            / "bailian_qwen_audio_3_1_tts.js"
        )
        content = js_path.read_text(encoding="utf-8")
        assert (
            "availableModels: ['flash', 'plus']" in content
        ), "3.1 前端组件 availableModels 未放开 plus"

    def test_3_1_plus_composes_full_model_name(self):
        """后端按 MODEL_NAME + 后缀拼装，plus 应得到 qwen-audio-3.1-tts-plus。"""
        from astrbot_plugin_tts_enhancer.providers.bailian_qwen_audio_3_1_tts import (
            BailianQwenAudio3_1TTSAdapter,
        )

        adapter = BailianQwenAudio3_1TTSAdapter(
            {"__template_key": "bailian_qwen_audio_3_1_tts", "model": "plus"}
        )
        assert adapter.MODEL_NAME == "qwen-audio-3.1-tts"
        version = adapter._extract_model_from_voice_id(
            "qwen-audio-3.1-tts-plus-myprefix-abc123"
        )
        assert version == "plus"
