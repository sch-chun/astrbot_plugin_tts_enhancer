"""管理页背景图路由（get_page_background）的单元测试。

直接驱动 ``_build_page_background_response`` 纯函数，覆盖非 happy path：
配置缺失 / 类型异常 / 路径穿越 / 文件缺失，正常返回 Data URL，
以及 ETag 语义（稳定 / 随内容变化 / 空响应无 ETag）。

路由闭包 ``get_page_background`` 写在 ``_register_routes`` 里，经替身
context 捕获真实注册的 handler 后驱动，覆盖缓存头附加、If-None-Match
解析（RFC 7232 弱比较：多值列表 / W/ 前缀）与 304 分支。
无需启动 AstrBot 主程序。
"""

import base64
import json
import re
from pathlib import Path

import pytest
from starlette.datastructures import Headers

pytest.importorskip("astrbot.api.star")

from astrbot_plugin_tts_enhancer.main import (
    TTSEnhancerPlugin,
    _build_page_background_response,
    _if_none_match_matches,
)
from astrbot_plugin_tts_enhancer.src.config import TTSEnhancerConfig

from astrbot.api import web as web_mod


def _data_url_bytes(data_url: str) -> bytes:
    """从 Data URL 解出原始字节。"""
    _, b64 = data_url.split(",", 1)
    return base64.b64decode(b64)


class TestNoBackgroundReturnsEmpty:
    def test_none_config(self):
        resp, etag = _build_page_background_response(None, "/tmp/x")
        assert resp["data"]["data_url"] == ""
        assert resp["data"]["opacity"] == 1.0
        assert etag is None

    def test_missing_key(self):
        resp, _ = _build_page_background_response({}, "/tmp/x")
        assert resp["data"]["data_url"] == ""

    def test_non_list_value(self):
        cfg = {"page_background": "not-a-list"}
        resp, _ = _build_page_background_response(cfg, "/tmp/x")
        assert resp["data"]["data_url"] == ""

    def test_empty_list(self):
        cfg = {"page_background": []}
        resp, _ = _build_page_background_response(cfg, "/tmp/x")
        assert resp["data"]["data_url"] == ""

    def test_first_element_not_str(self):
        cfg = {"page_background": [None]}
        resp, _ = _build_page_background_response(cfg, "/tmp/x")
        assert resp["data"]["data_url"] == ""


class TestPathTraversalBlocked:
    def test_escapes_plugin_data_dir(self, tmp_path):
        cfg = {"page_background": ["../../../escape.png"]}
        resp, etag = _build_page_background_response(cfg, tmp_path)
        assert resp["data"]["data_url"] == ""
        assert etag is None

    def test_absolute_path_outside(self, tmp_path):
        cfg = {"page_background": ["/etc/passwd"]}
        resp, etag = _build_page_background_response(cfg, tmp_path)
        assert resp["data"]["data_url"] == ""
        assert etag is None


class TestMissingFile:
    def test_missing_file(self, tmp_path):
        cfg = {"page_background": ["does_not_exist.png"]}
        resp, etag = _build_page_background_response(cfg, tmp_path)
        assert resp["data"]["data_url"] == ""
        assert etag is None


class TestNoHardSizeLimit:
    def test_large_file_over_old_cap_still_returned(self, tmp_path):
        # 旧上限为 4 MiB；去掉硬限制后即便超过也应正常返回 Data URL
        f = tmp_path / "big.png"
        f.write_bytes(b"\x89PNG" + b"x" * (5 * 1024 * 1024))
        cfg = {"page_background": ["big.png"]}
        resp, etag = _build_page_background_response(cfg, tmp_path)
        assert resp["data"]["data_url"].startswith("data:image/png;base64,")
        assert etag is not None


class TestValidBackground:
    def test_returns_png_data_url_with_defaults(self, tmp_path):
        f = tmp_path / "bg.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
        cfg = {"page_background": ["bg.png"]}
        resp, _ = _build_page_background_response(cfg, tmp_path)
        data = resp["data"]
        assert data["data_url"].startswith("data:image/png;base64,")
        assert _data_url_bytes(data["data_url"]) == b"\x89PNG\r\n\x1a\nFAKE"
        assert data["opacity"] == 0.5  # 缺省兜底
        assert data["blur"] == 0

    def test_reflects_configured_opacity_and_blur(self, tmp_path):
        f = tmp_path / "bg.png"
        f.write_bytes(b"\x89PNG")
        cfg = {
            "page_background": ["bg.png"],
            "page_background_opacity": 0.3,
            "page_background_blur": 5,
        }
        resp, _ = _build_page_background_response(cfg, tmp_path)
        assert resp["data"]["opacity"] == 0.3
        assert resp["data"]["blur"] == 5

    def test_no_extension_falls_back_to_octet_stream(self, tmp_path):
        # 无扩展名在任何平台都让 mimetypes 返回 None，稳定走 octet-stream 兜底；
        # 不用 .xyz 之类「看似未知」的扩展名——Linux 的 /etc/mime.types 可能已映射它。
        f = tmp_path / "bg"
        f.write_bytes(b"abc")
        cfg = {"page_background": ["bg"]}
        resp, _ = _build_page_background_response(cfg, tmp_path)
        assert resp["data"]["data_url"].startswith(
            "data:application/octet-stream;base64,"
        )

    def test_subdir_relative_path_allowed(self, tmp_path):
        sub = tmp_path / "files" / "page_background"
        sub.mkdir(parents=True)
        f = sub / "nested.png"
        f.write_bytes(b"\x89PNG")
        cfg = {"page_background": ["files/page_background/nested.png"]}
        resp, _ = _build_page_background_response(cfg, tmp_path)
        assert resp["data"]["data_url"].startswith("data:image/png;base64,")


class TestEtagForConditionalRequests:
    """ETag 供路由应答 If-None-Match：内容不变则稳定，内容变则失效。"""

    def test_etag_stable_across_calls(self, tmp_path):
        f = tmp_path / "bg.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
        cfg = {"page_background": ["bg.png"]}
        _, etag1 = _build_page_background_response(cfg, tmp_path)
        _, etag2 = _build_page_background_response(cfg, tmp_path)
        assert etag1 == etag2

    def test_etag_changes_when_file_content_changes(self, tmp_path):
        f = tmp_path / "bg.png"
        f.write_bytes(b"\x89PNG-A")
        cfg = {"page_background": ["bg.png"]}
        _, etag_before = _build_page_background_response(cfg, tmp_path)
        f.write_bytes(b"\x89PNG-B")
        _, etag_after = _build_page_background_response(cfg, tmp_path)
        assert etag_before != etag_after

    def test_etag_changes_when_opacity_changes(self, tmp_path):
        """只调透明度不换图：ETag 必须变，否则 304 会把旧透明度发给前端。"""
        f = tmp_path / "bg.png"
        f.write_bytes(b"\x89PNG")
        _, etag_before = _build_page_background_response(
            {"page_background": ["bg.png"], "page_background_opacity": 0.2},
            tmp_path,
        )
        _, etag_after = _build_page_background_response(
            {"page_background": ["bg.png"], "page_background_opacity": 0.6},
            tmp_path,
        )
        assert etag_before != etag_after

    def test_etag_changes_when_blur_changes(self, tmp_path):
        """只调模糊度不换图：ETag 同样必须变。"""
        f = tmp_path / "bg.png"
        f.write_bytes(b"\x89PNG")
        _, etag_before = _build_page_background_response(
            {"page_background": ["bg.png"], "page_background_blur": 0},
            tmp_path,
        )
        _, etag_after = _build_page_background_response(
            {"page_background": ["bg.png"], "page_background_blur": 12},
            tmp_path,
        )
        assert etag_before != etag_after

    def test_etag_is_quoted_hex(self, tmp_path):
        f = tmp_path / "bg.png"
        f.write_bytes(b"\x89PNG")
        cfg = {"page_background": ["bg.png"]}
        _, etag = _build_page_background_response(cfg, tmp_path)
        assert re.fullmatch(r'"[0-9a-f]{16}"', etag)

    def test_etag_none_when_not_configured(self, tmp_path):
        _, etag = _build_page_background_response({}, tmp_path)
        assert etag is None


class TestIfNoneMatchParsing:
    """If-None-Match 解析：按 RFC 7232 弱比较，兼容多值与 W/ 前缀。"""

    def test_missing_header_does_not_match(self):
        assert _if_none_match_matches(None, '"abc"') is False

    def test_empty_header_does_not_match(self):
        assert _if_none_match_matches("", '"abc"') is False

    def test_exact_match(self):
        assert _if_none_match_matches('"abc"', '"abc"') is True

    def test_different_etag_does_not_match(self):
        assert _if_none_match_matches('"xyz"', '"abc"') is False

    def test_matches_inside_comma_separated_list(self):
        """规范允许头为逗号分隔多值：任一项命中即命中。"""
        inm = '"other", "abc" , "third"'
        assert _if_none_match_matches(inm, '"abc"') is True

    def test_no_match_inside_comma_separated_list(self):
        inm = '"other", "third"'
        assert _if_none_match_matches(inm, '"abc"') is False

    def test_matches_weak_validator_prefix(self):
        """If-None-Match 用弱比较：W/ 前缀的弱验证器与强 ETag 等价。"""
        assert _if_none_match_matches('W/"abc"', '"abc"') is True

    def test_weak_validator_inside_list(self):
        inm = '"other", W/"abc"'
        assert _if_none_match_matches(inm, '"abc"') is True

    def test_unquoted_value_does_not_match(self):
        """etag 恒带引号；未加引号的裸值不得误命中。"""
        assert _if_none_match_matches("abc", '"abc"') is False


class RecordingRouteContext:
    """register_web_api 替身：捕获全部注册项，按路径取出 handler。"""

    def __init__(self):
        self.routes = {}

    def register_web_api(self, path, handler, methods=None, desc=""):
        self.routes[path] = handler


class FakeHeaderRequest:
    """Web API 请求替身，只提供背景图 handler 用到的 headers。

    用 starlette 的 Headers 而非普通 dict：HTTP 头名大小写不敏感，
    与生产环境 PluginRequest 包装的真实 Headers 行为一致。
    """

    def __init__(self, headers=None):
        self.headers = Headers(headers or {})


def _make_route_plugin(tmp_path, raw_config=None):
    """构造插件并抓取已注册的 page-background 路由 handler。

    用 ``object.__new__`` 绕过 __init__ 的副作用（建目录、注册 Tool、
    全量路由初始化），只单独驱动 ``_register_routes()``：闭包在注册时才
    创建，由替身 context 捕获后按路径取回——驱动的就是线上同一个 handler。
    """
    plugin = object.__new__(TTSEnhancerPlugin)
    plugin.config = TTSEnhancerConfig(raw_config or {})
    plugin.providers = plugin.config.get_providers()
    plugin.plugin_data_path = Path(tmp_path)
    plugin.name = "astrbot_plugin_tts_enhancer"
    ctx = RecordingRouteContext()
    plugin.context = ctx
    plugin._register_routes()
    suffix = f"/{plugin.name}/page-background"
    handler = next((h for p, h in ctx.routes.items() if p.endswith(suffix)), None)
    assert handler is not None, "page-background 路由未注册"
    return plugin, handler


async def _call_page_background(handler, headers=None):
    """在绑好请求上下文的前提下调用背景图接口。"""
    token = web_mod._request_var.set(FakeHeaderRequest(headers))
    try:
        return await handler()
    finally:
        web_mod._request_var.reset(token)


class TestPageBackgroundRouteConditionalRequest:
    """路由层：ETag/Cache-Control 响应头与 If-None-Match → 304 的端到端行为。"""

    async def test_route_attaches_etag_and_cache_headers(self, tmp_path):
        (tmp_path / "bg.png").write_bytes(b"\x89PNG\r\n\x1a\nROUTE")
        _, handler = _make_route_plugin(
            tmp_path, {"page_background": ["bg.png"], "page_background_opacity": 0.4}
        )
        resp = await _call_page_background(handler)
        expected_etag = _build_page_background_response(
            {"page_background": ["bg.png"], "page_background_opacity": 0.4},
            tmp_path,
        )[1]
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "private, no-cache"
        assert resp.headers["etag"] == expected_etag
        body = json.loads(resp.body)
        assert body["data"]["data_url"].startswith("data:image/png;base64,")

    async def test_route_returns_304_on_matching_if_none_match(self, tmp_path):
        (tmp_path / "bg.png").write_bytes(b"\x89PNG\r\n\x1a\nROUTE")
        _, handler = _make_route_plugin(tmp_path, {"page_background": ["bg.png"]})
        first = await _call_page_background(handler)
        etag = first.headers["etag"]
        second = await _call_page_background(handler, {"If-None-Match": etag})
        assert second.status_code == 304
        assert second.headers["etag"] == etag
        assert second.body == b""

    async def test_route_returns_304_on_multi_value_if_none_match(self, tmp_path):
        """If-None-Match 可能是逗号分隔多值：任一项含当前 etag 即回 304。"""
        (tmp_path / "bg.png").write_bytes(b"\x89PNG\r\n\x1a\nROUTE")
        _, handler = _make_route_plugin(tmp_path, {"page_background": ["bg.png"]})
        first = await _call_page_background(handler)
        etag = first.headers["etag"]
        second = await _call_page_background(
            handler, {"If-None-Match": f'"other-tag", {etag}'}
        )
        assert second.status_code == 304
        assert second.body == b""

    async def test_route_returns_304_on_weak_if_none_match(self, tmp_path):
        """If-None-Match 弱比较：W/ 前缀的弱验证器与强 ETag 等价。"""
        (tmp_path / "bg.png").write_bytes(b"\x89PNG\r\n\x1a\nROUTE")
        _, handler = _make_route_plugin(tmp_path, {"page_background": ["bg.png"]})
        first = await _call_page_background(handler)
        etag = first.headers["etag"]
        second = await _call_page_background(handler, {"If-None-Match": f"W/{etag}"})
        assert second.status_code == 304
        assert second.body == b""

    async def test_route_304_does_not_resend_payload(self, tmp_path):
        """304 响应不得带 body：省流量正是条件请求的目的。"""
        (tmp_path / "bg.png").write_bytes(b"\x89PNG\r\n\x1a\nROUTE")
        _, handler = _make_route_plugin(tmp_path, {"page_background": ["bg.png"]})
        first = await _call_page_background(handler)
        second = await _call_page_background(
            handler, {"If-None-Match": first.headers["etag"]}
        )
        assert len(first.body) > 0
        assert second.body == b""

    async def test_route_omits_cache_headers_when_unconfigured(self, tmp_path):
        _, handler = _make_route_plugin(tmp_path, {})
        resp = await _call_page_background(handler)
        assert resp.status_code == 200
        assert resp.headers.get("etag") is None
        assert resp.headers.get("cache-control") is None
        assert json.loads(resp.body)["data"]["data_url"] == ""

    async def test_route_serves_new_params_after_opacity_change(self, tmp_path):
        """调完透明度重进页面，不得被 304 旧响应挡住。

        首次请求拿到 ETag（含旧 opacity）→ 配置改透明度 → 带旧 If-None-Match
        再请求：ETag 已随参数变化，必须回 200 新值而非 304 旧值。
        """
        (tmp_path / "bg.png").write_bytes(b"\x89PNG\r\n\x1a\nROUTE")
        plugin, handler = _make_route_plugin(
            tmp_path, {"page_background": ["bg.png"], "page_background_opacity": 0.2}
        )
        first = await _call_page_background(handler)
        old_etag = first.headers["etag"]

        plugin.config = TTSEnhancerConfig(
            {"page_background": ["bg.png"], "page_background_opacity": 0.6}
        )
        second = await _call_page_background(handler, {"If-None-Match": old_etag})

        assert second.status_code == 200
        assert second.headers["etag"] != old_etag
        assert json.loads(second.body)["data"]["opacity"] == 0.6
