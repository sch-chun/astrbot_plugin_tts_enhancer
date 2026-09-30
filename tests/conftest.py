"""pytest 全局夹具与测试替身。

测试直接依赖真实 AstrBot 运行时符号（``astrbot.api`` 等），因此需要把
AstrBot 源码根目录与 ``data/plugins`` 目录加入 ``sys.path``。

同时提供本插件用到的最小测试替身（Dummy*），用于在不启动 AstrBot 主程序的
前提下驱动 TTSService / TTSSubAgent 等需要 Context 与 MessageEvent 的组件。
"""

import os
import sys
from pathlib import Path

import pytest  # noqa: E402

_PLUGIN_ROOT = (
    Path(__file__).resolve().parents[1]
)  # <astrbot_root>/data/plugins/astrbot_plugin_tts_enhancer

# 向上探测 AstrBot 源码根目录：沿父链查找含 ``astrbot`` 包的目录，
# 不再硬编码 parents[2]，以兼容不同部署布局（插件未必总在 data/plugins 下）。
_ASTRBOT_ROOT = None
for _candidate in [_PLUGIN_ROOT, *_PLUGIN_ROOT.parents]:
    if (_candidate / "astrbot" / "__init__.py").exists():
        _ASTRBOT_ROOT = _candidate
        break

# data/plugins 目录（插件包所在层），确保本插件可作为顶层包被导入。
_PLUGINS_DIR = _PLUGIN_ROOT.parent

for _p in (_ASTRBOT_ROOT, _PLUGINS_DIR):
    if _p is not None and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    from astrbot.core.provider import Provider  # noqa: E402
except ImportError:
    # 本地开发（未装 AstrBot）保持整体 skip；CI 下必须硬失败，
    # 否则缺 AstrBot 会退化成「空套件全 skip → 退出码 0 → 假绿」。
    if os.environ.get("CI"):
        raise RuntimeError(
            "CI 需要已安装的 AstrBot 运行时（pip install astrbot），"
            "但导入 astrbot.core.provider 失败——拒绝静默全 skip。"
        )
    pytest.importorskip("astrbot.core.provider")
    raise


class DummyEvent:
    """最小的 AstrMessageEvent 测试替身。

    仅实现本插件实际访问的属性与方法：unified_msg_origin 与 get_platform_name()。
    """

    def __init__(self, umo: str = "platform:g:1001", platform: str = "aiocqhttp"):
        self.unified_msg_origin = umo
        self._platform = platform

    def get_platform_name(self) -> str:
        return self._platform


class DummyConversation:
    """对话对象替身，history 字段为 JSON 字符串。"""

    def __init__(self, history: str | None = None, persona_id: str | None = None):
        self.history = history
        self.persona_id = persona_id


class DummyConversationManager:
    """ConversationManager 替身，可预设返回值或注入异常。"""

    def __init__(
        self,
        conv_id: str | None = "conv-1",
        conversation: DummyConversation | None = None,
        raise_on_call: bool = False,
    ):
        self.conv_id = conv_id
        self.conversation = conversation
        self.raise_on_call = raise_on_call

    async def get_curr_conversation_id(self, umo: str) -> str | None:
        if self.raise_on_call:
            raise RuntimeError("conversation manager unavailable")
        return self.conv_id

    async def get_conversation(self, umo: str, conv_id: str):
        if self.raise_on_call:
            raise RuntimeError("conversation manager unavailable")
        return self.conversation


class DummyPersonaManager:
    """PersonaManager 替身。"""

    def __init__(
        self,
        persona: dict | None = None,
        persona_id: str = "persona-default",
        raise_on_call: bool = False,
    ):
        self.persona = persona
        self.persona_id = persona_id
        self.raise_on_call = raise_on_call

    async def resolve_selected_persona(
        self,
        umo: str = "",
        conversation_persona_id: str | None = None,
        platform_name: str = "",
    ):
        if self.raise_on_call:
            raise RuntimeError("persona manager unavailable")
        return (self.persona_id, self.persona, False, False)


class DummyContext:
    """最小的 Context 替身。

    只填充 TTSService / TTSSubAgent 会触达的成员。
    """

    def __init__(
        self,
        conversation_manager=None,
        persona_manager=None,
        provider=None,
        provider_by_id=None,
    ):
        self.conversation_manager = conversation_manager
        self.persona_manager = persona_manager
        self._provider = provider
        self._provider_by_id = provider_by_id

    def get_using_provider(self, session_id: str = ""):
        return self._provider

    def get_provider_by_id(self, provider_id: str):
        return self._provider_by_id


class DummyResponse:
    """LLM 响应替身，模拟 AstrBot 的 provider 返回对象。"""

    def __init__(
        self, completion_text: str = "", tools_call_name=None, tools_call_args=None
    ):
        self.completion_text = completion_text
        self.tools_call_name = tools_call_name or []
        self.tools_call_args = tools_call_args or []


class DummyProvider(Provider):
    """LLM Provider 替身，继承自真实 Provider 以便通过 isinstance 校验。"""

    def __init__(self, response: DummyResponse | None = None, raise_on_call=False):
        self.response = response or DummyResponse()
        self.raise_on_call = raise_on_call
        self.calls: list[dict] = []

    async def text_chat(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_on_call:
            raise RuntimeError("LLM 调用失败")
        return self.response

    def get_current_key(self) -> str:
        return "test-key"

    def set_key(self, key: str) -> None:
        self.key = key

    def get_models(self) -> list:
        return ["test-model"]


class RecordingAdapter:
    """TTS 供应商适配器替身，用于隔离测试 TTSService 的决策逻辑。

    Args:
        return_path: call_api 返回值；为 None 时每次调用都返回空字符串。
        raise_on_call: 若为 True，call_api 抛出异常。
        valid: validate_params 是否认为参数合法。
        docs: 文档内容，空字符串表示「无文档」，触发降级路径。
    """

    def __init__(
        self,
        return_path=None,
        raise_on_call=False,
        valid=True,
        docs="# dummy docs",
        validate_raises=None,
    ):
        self.return_path = return_path
        self.raise_on_call = raise_on_call
        self.valid = valid
        self.docs_content = docs
        self.validate_raises = validate_raises
        self.call_api_calls: list[dict] = []
        self.entry = {}

    def get_subagent_system_prompt(self) -> str:
        return "sys"

    def get_tool_schema(self):
        return None

    def validate_params(self, params: dict):
        if self.validate_raises:
            raise self.validate_raises
        if self.valid:
            return True, ""
        return False, "参数非法"

    def sanitize_params(self, params: dict) -> dict:
        return {"text": params.get("text", "")}

    async def call_api(self, text, raw_params, config, voice_id=None):
        self.call_api_calls.append(
            {"text": text, "raw_params": raw_params, "config": config}
        )
        if self.raise_on_call:
            raise RuntimeError("API 爆炸")
        return self.return_path if self.return_path is not None else ""


@pytest.fixture
def dummy_event():
    """提供默认 DummyEvent 实例。"""
    return DummyEvent()


@pytest.fixture
def audio_tmp_dir(tmp_path):
    """提供音频输出临时目录。"""
    d = tmp_path / "audio"
    d.mkdir(parents=True, exist_ok=True)
    return d