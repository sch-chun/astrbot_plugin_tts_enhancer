import logging
from pathlib import Path
from aiohttp import web

from typing import Optional


logger = logging.getLogger(__name__)


_MIME_MAP = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
}
"""文件后缀名到 MIME 类型的映射字典。"""


class TempFileServer:
    """临时文件服务器，用于在指定端口上提供单个文件的 HTTP 访问服务。"""
    def __init__(self, file_path: Path, internal_port: int) -> None:
        """初始化 TempFileServer 实例。

        Args:
            file_path (Path): 要提供服务的文件路径。
            internal_port (int): 服务器监听的内部端口号。
        """
        self.file_path = file_path
        self.internal_port = internal_port
        self._content_type = _MIME_MAP.get(file_path.suffix.lower(), "application/octet-stream")
        self._app = None
        self._runner = None
        self._site = None

    async def start(self) -> bool:
        """启动服务器，绑定到 0.0.0.0:internal_port。

        Returns:
            bool: 服务器是否成功启动。

        Raises:
            FileNotFoundError: 如果指定的文件不存在。
        """
        if not self.file_path.exists():
            raise FileNotFoundError(f"文件不存在: {self.file_path}")
        self._app = web.Application()
        self._app.router.add_get('/', self._handle_file)
        self._app.router.add_get('/{filename}', self._handle_file)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host='0.0.0.0', port=self.internal_port)
        await self._site.start()
        logger.info(f"临时文件服务器已启动，内部端口: {self.internal_port}")
        return True

    async def _handle_file(self, request: web.Request) -> web.Response:
        """处理文件请求，读取并返回文件内容。

        Args:
            request (web.Request): aiohttp 请求对象。

        Returns:
            web.Response: 包含文件内容的响应对象，如果读取失败则返回 500 状态码。
        """
        try:
            content = self.file_path.read_bytes()
            return web.Response(body=content, content_type=self._content_type)
        except Exception as e:
            logger.error(f"文件读取失败: {e}")
            return web.Response(status=500)

    async def stop(self) -> None:
        """停止服务器并清理相关资源。"""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            logger.info("临时文件服务器已停止")


# 全局服务器管理
_servers = {}


def get_server(file_id: str) -> Optional[TempFileServer]:
    """根据文件 ID 获取对应的临时文件服务器实例。

    Args:
        file_id (str): 文件的唯一标识符。

    Returns:
        Optional[TempFileServer]: 对应的服务器实例，如果不存在则返回 None。
    """
    return _servers.get(file_id)


def add_server(file_id: str, server: TempFileServer) -> None:
    """将临时文件服务器实例添加到全局管理字典中。

    Args:
        file_id (str): 文件的唯一标识符。
        server (TempFileServer): 要添加的服务器实例。
    """
    _servers[file_id] = server


def remove_server(file_id: str) -> None:
    """从全局管理字典中移除指定文件 ID 的服务器实例。

    Args:
        file_id (str): 文件的唯一标识符。
    """
    _servers.pop(file_id, None)
    