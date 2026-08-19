import asyncio
import logging
from pathlib import Path
from aiohttp import web

logger = logging.getLogger(__name__)

class TempFileServer:
    def __init__(self, file_path: Path, internal_port: int):
        self.file_path = file_path
        self.internal_port = internal_port
        self._app = None
        self._runner = None
        self._site = None

    async def start(self) -> bool:
        """启动服务器，绑定到 0.0.0.0:internal_port，返回是否成功"""
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

    async def _handle_file(self, request):
        try:
            content = self.file_path.read_bytes()
            return web.Response(body=content, content_type='application/octet-stream')
        except Exception as e:
            logger.error(f"文件读取失败: {e}")
            return web.Response(status=500)

    async def stop(self):
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            logger.info("临时文件服务器已停止")

# 全局服务器管理
_servers = {}

def get_server(file_id: str):
    return _servers.get(file_id)

def add_server(file_id: str, server: TempFileServer):
    _servers[file_id] = server

def remove_server(file_id: str):
    _servers.pop(file_id, None)
    