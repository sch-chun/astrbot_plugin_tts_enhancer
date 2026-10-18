"""管理页背景图路由（get_page_background）的单元测试。

直接驱动 ``_build_page_background_response`` 纯函数，覆盖非 happy path：
配置缺失 / 类型异常 / 路径穿越 / 文件缺失，正常返回 Data URL，
以及 ETag 语义（稳定 / 随内容变化 / 空响应无 ETag）。
无需启动 AstrBot 主程序。
"""

import base64
import re

import pytest

pytest.importorskip("astrbot.api.star")

from astrbot_plugin_tts_enhancer.main import _build_page_background_response


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
