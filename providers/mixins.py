"""可选的供应商能力 mixin。

``TTSProviderAdapter`` 只承载所有适配器都需要的「核心合成 + 参数校验 + 能力文档」
契约；音色管理、供应商侧文件管理等属于可选能力，抽离到本模块，由真正支持的
适配器按需多继承，从而避免基类臃肿、让「不支持」成为结构上的能力缺失，而非
仅靠运行时的 ``NotImplementedError`` 兜底。

路由侧统一用 ``hasattr`` 检测能力，缺失即返回 501，与适配器显式抛
``NotImplementedError`` 的语义一致。
"""


class VoiceManageable:
    """可选能力：音色管理（创建 / 列表 / 删除）。

    仅「支持音色创建」的供应商（如百炼、MiniMax）继承本 mixin 并覆写下列方法。
    未覆写时默认抛 ``NotImplementedError``，路由据此返回 501。
    """

    async def create_voice(self, params: dict) -> dict:
        """创建语音。未实现的适配器应抛 NotImplementedError。"""
        raise NotImplementedError

    async def list_voice(self, **kwargs) -> dict:
        """列出语音。未实现的适配器应抛 NotImplementedError。"""
        raise NotImplementedError

    async def delete_voice(self, **kwargs) -> bool:
        """删除语音。未实现的适配器应抛 NotImplementedError。"""
        raise NotImplementedError


class FileManageable:
    """可选能力：供应商侧文件管理（上传 / 列表 / 获取 / 删除）。

    仅需要「先把本地音频传到供应商再引用」的适配器（如 MiniMax）继承并覆写。
    未覆写时默认抛 ``NotImplementedError``，路由据此返回 501。
    """

    async def upload_file(self, file_path: str, **kwargs) -> dict:
        """上传本地文件到供应商。未实现的适配器应抛 NotImplementedError。"""
        raise NotImplementedError

    async def list_files(self, **kwargs) -> dict:
        """列出供应商侧文件。未实现的适配器应抛 NotImplementedError。"""
        raise NotImplementedError

    async def get_file_content(self, file_id: int) -> bytes:
        """按 id 获取供应商侧文件内容。未实现的适配器应抛 NotImplementedError。"""
        raise NotImplementedError

    async def delete_file(self, file_id: int, **kwargs) -> bool:
        """删除供应商侧文件。未实现的适配器应抛 NotImplementedError。"""
        raise NotImplementedError
