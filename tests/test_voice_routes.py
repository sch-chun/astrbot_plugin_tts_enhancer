"""`/voice/query` 路由测试：验证 main.py 只做转发，不耦合供应商特有的查询逻辑。

后端创建即返回初始 DEPLOYING 状态，真实部署进度由前端轮询 `/voice/query` 获取；
该路由必须仅把请求委托给适配器的 ``query_voice``，且适配器未实现时返回 501。
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from astrbot_plugin_tts_enhancer.main import TTSEnhancerPlugin
from astrbot_plugin_tts_enhancer.src.config import TTSEnhancerConfig
from astrbot_plugin_tts_enhancer.providers import ProviderFactory
from astrbot.api import web as web_mod


class _RecordingContext:
    """register_web_api 替身：捕获全部注册项，按路径取出 handler。"""

    def __init__(self):
        self.routes = {}

    def register_web_api(self, path, handler, methods=None, desc=""):
        self.routes[path] = handler


class _FakeJsonRequest:
    """Web API 请求替身，只提供 voice/query 路由用到的 json()。"""

    def __init__(self, payload):
        self._payload = payload

    async def json(self, default=None):
        return self._payload


PROVIDER_ENTRY = {
    "type": "bailian_qwen_audio_3_0_tts",
    "workspace_id": "workspace-test",
    "api_key": "sk-test",
    "model": "flash",
}


def _make_voice_query_plugin(tmp_path, raw_config):
    """构造插件并抓取已注册的 voice-query 路由 handler。"""
    plugin = object.__new__(TTSEnhancerPlugin)
    plugin.config = TTSEnhancerConfig(raw_config)
    plugin.providers = plugin.config.get_providers()
    plugin.plugin_data_path = Path(tmp_path)
    plugin.name = "astrbot_plugin_tts_enhancer"
    ctx = _RecordingContext()
    plugin.context = ctx
    plugin._register_routes()
    suffix = f"/{plugin.name}/voice/query"
    handler = next((h for p, h in ctx.routes.items() if p.endswith(suffix)), None)
    assert handler is not None, "voice-query 路由未注册"
    return handler


async def _call(handler, payload):
    token = web_mod._request_var.set(_FakeJsonRequest(payload))
    try:
        return await handler()
    finally:
        web_mod._request_var.reset(token)


@pytest.fixture
def patched_adapter(monkeypatch):
    """get_adapter 返回带 query_voice 的适配器替身。"""
    adapter = MagicMock()
    adapter.query_voice = MagicMock()
    monkeypatch.setattr(ProviderFactory, "get_adapter", lambda entry: adapter)
    return adapter


class TestVoiceQueryRoute:
    async def test_returns_status_delegated_to_adapter(self, tmp_path, patched_adapter):
        """路由应把 voice_id 转给适配器并返回其 status，不做任何供应商特有逻辑。"""

        async def _q(voice_id):
            return "DEPLOYING"

        patched_adapter.query_voice = _q
        handler = _make_voice_query_plugin(tmp_path, {"providers": [PROVIDER_ENTRY]})
        resp = await _call(handler, {"entry_id": 0, "voice_id": "vid-1"})
        body = json.loads(resp.body)
        assert resp.status_code == 200
        assert body["code"] == 0
        assert body["data"]["voice_id"] == "vid-1"
        assert body["data"]["status"] == "DEPLOYING"

    async def test_returns_501_when_adapter_unsupported(self, tmp_path, monkeypatch):
        """适配器未实现 query_voice 时应返回 501，而非把错误耦合进路由。"""
        unsupported = MagicMock(spec=[])  # 没有任何方法，query_voice 不存在
        monkeypatch.setattr(ProviderFactory, "get_adapter", lambda entry: unsupported)
        handler = _make_voice_query_plugin(tmp_path, {"providers": [PROVIDER_ENTRY]})
        resp = await _call(handler, {"entry_id": 0, "voice_id": "vid-1"})
        assert resp.status_code == 501

    async def test_returns_400_when_voice_id_missing(self, tmp_path, patched_adapter):
        handler = _make_voice_query_plugin(tmp_path, {"providers": [PROVIDER_ENTRY]})
        resp = await _call(handler, {"entry_id": 0})
        assert resp.status_code == 400
