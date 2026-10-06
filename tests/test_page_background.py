"""管理页背景图路由（get_page_background）的单元测试。

直接驱动 ``_build_page_background_response`` 纯函数，覆盖非 happy path：
配置缺失 / 类型异常 / 路径穿越 / 文件缺失，以及正常返回 Data URL。
无需启动 AstrBot 主程序。
"""

import base64

import pytest

pytest.importorskip("astrbot.api.star")

from astrbot_plugin_tts_enhancer.main import _build_page_background_response


def _data_url_bytes(data_url: str) -> bytes:
    """从 Data URL 解出原始字节。"""
    _, b64 = data_url.split(",", 1)
    return base64.b64decode(b64)


class TestNoBackgroundReturnsEmpty:
    def test_none_config(self):
        resp = _build_page_background_response(None, "/tmp/x")
        assert resp["data"]["data_url"] == ""
        assert resp["data"]["opacity"] == 1.0

    def test_missing_key(self):
        assert _build_page_background_response({}, "/tmp/x")["data"]["data_url"] == ""

    def test_non_list_value(self):
        cfg = {"page_background": "not-a-list"}
        assert _build_page_background_response(cfg, "/tmp/x")["data"]["data_url"] == ""

    def test_empty_list(self):
        cfg = {"page_background": []}
        assert _build_page_background_response(cfg, "/tmp/x")["data"]["data_url"] == ""

    def test_first_element_not_str(self):
        cfg = {"page_background": [None]}
        assert _build_page_background_response(cfg, "/tmp/x")["data"]["data_url"] == ""


class TestPathTraversalBlocked:
    def test_escapes_plugin_data_dir(self, tmp_path):
        cfg = {"page_background": ["../../../escape.png"]}
        resp = _build_page_background_response(cfg, tmp_path)
        assert resp["data"]["data_url"] == ""

    def test_absolute_path_outside(self, tmp_path):
        cfg = {"page_background": ["/etc/passwd"]}
        resp = _build_page_background_response(cfg, tmp_path)
        assert resp["data"]["data_url"] == ""


class TestMissingFile:
    def test_missing_file(self, tmp_path):
        cfg = {"page_background": ["does_not_exist.png"]}
        assert _build_page_background_response(cfg, tmp_path)["data"]["data_url"] == ""


class TestNoHardSizeLimit:
    def test_large_file_over_old_cap_still_returned(self, tmp_path):
        # 旧上限为 4 MiB；去掉硬限制后即便超过也应正常返回 Data URL
        f = tmp_path / "big.png"
        f.write_bytes(b"\x89PNG" + b"x" * (5 * 1024 * 1024))
        cfg = {"page_background": ["big.png"]}
        data = _build_page_background_response(cfg, tmp_path)["data"]
        assert data["data_url"].startswith("data:image/png;base64,")


class TestValidBackground:
    def test_returns_png_data_url_with_defaults(self, tmp_path):
        f = tmp_path / "bg.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
        cfg = {"page_background": ["bg.png"]}
        resp = _build_page_background_response(cfg, tmp_path)
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
        data = _build_page_background_response(cfg, tmp_path)["data"]
        assert data["opacity"] == 0.3
        assert data["blur"] == 5

    def test_no_extension_falls_back_to_octet_stream(self, tmp_path):
        # 无扩展名在任何平台都让 mimetypes 返回 None，稳定走 octet-stream 兜底；
        # 不用 .xyz 之类「看似未知」的扩展名——Linux 的 /etc/mime.types 可能已映射它。
        f = tmp_path / "bg"
        f.write_bytes(b"abc")
        cfg = {"page_background": ["bg"]}
        data = _build_page_background_response(cfg, tmp_path)["data"]
        assert data["data_url"].startswith("data:application/octet-stream;base64,")

    def test_subdir_relative_path_allowed(self, tmp_path):
        sub = tmp_path / "files" / "page_background"
        sub.mkdir(parents=True)
        f = sub / "nested.png"
        f.write_bytes(b"\x89PNG")
        cfg = {"page_background": ["files/page_background/nested.png"]}
        data = _build_page_background_response(cfg, tmp_path)["data"]
        assert data["data_url"].startswith("data:image/png;base64,")
