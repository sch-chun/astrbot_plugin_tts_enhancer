"""合成记录管理路由（synthesis-records*）测试。

直接驱动 main.py 中注册的路由闭包（与线上同一份 handler），覆盖：
列表 / 取音频 / 删除 / 清空 / 回传记录 的 happy path 与关键错误分支，
以及「synthesis_store 未启用 / 未配置」时的降级返回。

无需启动 AstrBot 主程序：用替身 context 捕获注册项，再经 request contextvar
注入 JSON 请求体驱动 handler。
"""

import base64
import json
from pathlib import Path

import pytest
from astrbot_plugin_tts_enhancer.main import (
    SOURCE_PREVIEW,
    TTSEnhancerPlugin,
)
from astrbot_plugin_tts_enhancer.src.config import TTSEnhancerConfig
from astrbot_plugin_tts_enhancer.src.synthesis_store import SynthesisRecordStore

from astrbot.api import web as web_mod


class _RecordingContext:
    """register_web_api 替身：捕获全部注册项，按路径取出 handler。"""

    def __init__(self):
        self.routes = {}

    def register_web_api(self, path, handler, methods=None, desc=""):
        self.routes[path] = handler


class _FakeJsonRequest:
    """Web API 请求替身，只提供合成记录路由用到的 json()。"""

    def __init__(self, payload):
        self._payload = payload

    async def json(self, default=None):
        return self._payload


SAMPLE = b"\x00\x01\x02ID3fake-audio-bytes"


class FakeKV:
    """内存版 KV，模拟 AstrBot 官方 KV 的 get_kv_data / put_kv_data 接口。"""

    def __init__(self) -> None:
        self._data: dict = {}

    async def get_kv_data(self, key: str, default):
        return self._data.get(key, default)

    async def put_kv_data(self, key: str, value) -> None:
        self._data[key] = value


def _make_plugin(tmp_path, raw_config=None):
    """构造插件并注册全部路由，返回 plugin 与 routes 字典。"""
    plugin = object.__new__(TTSEnhancerPlugin)
    plugin.config = TTSEnhancerConfig(raw_config or {})
    plugin.providers = plugin.config.get_providers()
    plugin.plugin_data_path = Path(tmp_path)
    plugin.name = "astrbot_plugin_tts_enhancer"
    ctx = _RecordingContext()
    plugin.context = ctx
    plugin._register_routes()
    return plugin, ctx.routes


def _handler(routes, suffix):
    handler = next((h for p, h in routes.items() if p.endswith(suffix)), None)
    assert handler is not None, f"{suffix} 路由未注册"
    return handler


async def _call(handler, payload):
    token = web_mod._request_var.set(_FakeJsonRequest(payload))
    try:
        return await handler()
    finally:
        web_mod._request_var.reset(token)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


@pytest.fixture
def store_plugin(tmp_path):
    """已挂载 SynthesisRecordStore 的插件与三条合成记录路由 handler。"""
    plugin, routes = _make_plugin(tmp_path, {})
    store = SynthesisRecordStore(
        records_dir=tmp_path / "synthesis_records", kv=FakeKV(), max_records=50
    )
    plugin.synthesis_store = store
    return {
        "plugin": plugin,
        "store": store,
        "list": _handler(routes, "/synthesis-records"),
        "audio": _handler(routes, "/synthesis-records/audio"),
        "delete": _handler(routes, "/synthesis-records/delete"),
        "clear": _handler(routes, "/synthesis-records/clear"),
        "record": _handler(routes, "/synthesis-records/record"),
    }


class TestListRoute:
    async def test_empty_when_store_unset(self, tmp_path):
        """synthesis_store 未配置（None）：列表降级为空结果，不应 500。"""
        _, routes = _make_plugin(tmp_path, {})
        resp = await _call(_handler(routes, "/synthesis-records"), {})
        assert resp.status_code == 200
        assert json.loads(resp.body) == {"code": 0, "data": []}

    async def test_returns_seeded_records(self, store_plugin):
        await store_plugin["store"].add(
            audio_bytes=SAMPLE,
            source="chat",
            provider="MiniMax",
            text="你好",
            fmt="mp3",
        )
        resp = await _call(store_plugin["list"], {})
        body = json.loads(resp.body)
        assert body["code"] == 0
        assert len(body["data"]) == 1
        assert body["data"][0]["source"] == "chat"
        assert body["data"][0]["text"] == "你好"
        # 列表不含音频字节
        assert "audio_base64" not in body["data"][0]


class TestRecordEndpoint:
    async def test_creates_record(self, store_plugin):
        resp = await _call(
            store_plugin["record"],
            {
                "audio_base64": _b64(SAMPLE),
                "format": "wav",
                "source": SOURCE_PREVIEW,
                "provider": "Bailian",
                "text": "preview text",
            },
        )
        body = json.loads(resp.body)
        assert body["code"] == 0
        rec_id = body["data"]["id"]
        # 落盘后可被列表读到
        listed = json.loads((await _call(store_plugin["list"], {})).body)
        assert any(r["id"] == rec_id for r in listed["data"])

    async def test_missing_base64_400(self, store_plugin):
        resp = await _call(store_plugin["record"], {"format": "mp3"})
        assert resp.status_code == 400

    async def test_invalid_base64_400(self, store_plugin):
        resp = await _call(
            store_plugin["record"],
            {"audio_base64": "###notbase64###", "format": "mp3"},
        )
        assert resp.status_code == 400

    async def test_disabled_store_404(self, store_plugin):
        # max_records == 0 表示关闭落盘
        store_plugin["store"].set_max_records(0)
        resp = await _call(
            store_plugin["record"],
            {"audio_base64": _b64(SAMPLE), "format": "mp3"},
        )
        assert resp.status_code == 404


class TestAudioEndpoint:
    async def test_returns_base64_and_format(self, store_plugin):
        rec = await store_plugin["store"].add(
            audio_bytes=SAMPLE,
            source="chat",
            provider="p",
            text="x",
            fmt="wav",
        )
        resp = await _call(store_plugin["audio"], {"id": rec["id"]})
        body = json.loads(resp.body)
        assert body["code"] == 0
        assert body["data"]["format"] == "wav"
        assert base64.b64decode(body["data"]["audio_base64"]) == SAMPLE

    async def test_missing_id_404(self, store_plugin):
        resp = await _call(store_plugin["audio"], {})
        assert resp.status_code == 404

    async def test_unknown_id_404(self, store_plugin):
        resp = await _call(store_plugin["audio"], {"id": "rec_unknown"})
        assert resp.status_code == 404


class TestDeleteEndpoint:
    async def test_deletes_existing(self, store_plugin):
        rec = await store_plugin["store"].add(
            audio_bytes=SAMPLE,
            source="chat",
            provider="p",
            text="x",
            fmt="mp3",
        )
        resp = await _call(store_plugin["delete"], {"id": rec["id"]})
        body = json.loads(resp.body)
        assert body["code"] == 0
        assert body["data"]["success"] is True
        # 删除后列表为空
        listed = json.loads((await _call(store_plugin["list"], {})).body)
        assert listed["data"] == []

    async def test_missing_id_404(self, store_plugin):
        resp = await _call(store_plugin["delete"], {"id": "rec_unknown"})
        assert resp.status_code == 404


class TestClearEndpoint:
    async def test_clears_all_and_reports_count(self, store_plugin):
        await store_plugin["store"].add(
            audio_bytes=SAMPLE, source="chat", provider="p", text="a", fmt="mp3"
        )
        await store_plugin["store"].add(
            audio_bytes=SAMPLE, source="chat", provider="p", text="b", fmt="mp3"
        )
        resp = await _call(store_plugin["clear"], {})
        body = json.loads(resp.body)
        assert body["code"] == 0
        assert body["data"]["deleted"] == 2
        listed = json.loads((await _call(store_plugin["list"], {})).body)
        assert listed["data"] == []
