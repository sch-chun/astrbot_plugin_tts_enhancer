"""TTS Provider 适配器工厂 —— 自动发现机制"""

import importlib
import importlib.util
import inspect
from pathlib import Path

from typing import Type, Optional

from .base import TTSProviderAdapter

from astrbot.api import logger


class ProviderFactory:
    """TTS Provider适配器工厂类，用于自动发现、加载和管理TTS提供者适配器。

    该类实现了自动发现机制，能够扫描当前目录下的所有Python文件，
    自动加载并继承自TTSProviderAdapter的适配器类。

    使用示例：
        # 获取适配器实例
        config = {"__template_key": "google", "api_key": "your-api-key"}
        adapter = ProviderFactory.get_adapter(config)
        if adapter:
            text = "Hello, world!"
            audio_data = adapter.synthesize(text)
    """
    _adapters: Optional[dict[str, Type[TTSProviderAdapter]]] = None

    @classmethod
    def _discover_adapters(cls) -> None:
        """扫描当前目录，自动发现所有TTSProviderAdapter子类。

        该方法会遍历当前目录下的所有Python文件（排除以'_'开头的文件和base.py），
        动态导入每个模块并查找其中继承自TTSProviderAdapter的类。
        发现的适配器会被缓存在类变量_adapters中。

        导入方式优先走包内正常导入（``importlib.import_module``），保证适配器
        模块**唯一实例**：早前用 ``spec_from_file_location`` 动态执行模块时，
        会另起一份模块对象，导致模块级状态（如 Eleven 的 ``_CATALOG_CACHE``）
        被复制成两份——工厂创建的适配器与 ``from . import elevenlabs_v4`` 拿到的
        模块互不可见，缓存注入、跨模块 isinstance 判断都会失真。
        仅当包内导入失败（插件目录不在可导入包内）时，才回退到按文件路径加载。

        Returns:
            None: 该方法没有返回值，结果存储在类变量_adapters中
        """
        if cls._adapters is not None:
            return

        discovered: dict[str, Type[TTSProviderAdapter]] = {}
        package_dir = Path(__file__).parent

        for py_file in package_dir.glob("*.py"):
            if py_file.name.startswith("_") or py_file.name == "base.py":
                continue

            module_name = py_file.stem
            try:
                module = cls._import_adapter_module(module_name, py_file)

                # 查找继承 TTSProviderAdapter 的具体类
                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if (
                        issubclass(obj, TTSProviderAdapter)
                        and obj is not TTSProviderAdapter
                        and obj.__module__ == module.__name__
                    ):

                        # 使用模块名作为映射 key（与 __template_key 一致）
                        discovered[module_name] = obj
            except Exception as e:
                logger.warning(f"Failed to load TTS Provider adapter: {module_name}: {e}")
                pass

        cls._adapters = discovered

    @classmethod
    def _import_adapter_module(cls, module_name: str, py_file: Path):
        """导入单个适配器模块，优先保证模块唯一实例。

        Args:
            module_name: 模块名（= 文件名 = ``__template_key``）。
            py_file: 适配器模块的绝对路径。

        Returns:
            导入后的模块对象。
        """
        try:
            # 包内正常导入：复用 sys.modules 中的模块实例（唯一实例）。
            return importlib.import_module(f"{__package__}.{module_name}")
        except Exception:
            # 回退：按文件路径加载（插件目录不在可导入包内时的兜底路径）。
            spec = importlib.util.spec_from_file_location(
                f"{__package__}.{module_name}", py_file
            )
            if spec is None or spec.loader is None:
                raise ImportError(f"无法加载适配器模块: {py_file}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

    @classmethod
    def get_adapter(cls, entry: dict) -> TTSProviderAdapter | None:
        """根据配置条目获取适配器实例。

        该方法会先自动发现所有可用的适配器，然后根据配置中的__template_key
        来查找并返回对应的适配器类。

        Args:
            entry: 配置字典，必须包含__template_key字段来指定要使用的适配器类型

        Returns:
            TTSProviderAdapter | None: 如果找到对应的适配器类，返回其实例；否则返回None
        """
        cls._discover_adapters()
        # entry 可能为空（配置缺失或传入 None），先做防御再取字段
        if not isinstance(entry, dict):
            return None

        template_key = entry.get("__template_key")
        if not template_key or cls._adapters is None:
            return None

        adapter_cls = cls._adapters.get(template_key)
        if adapter_cls:
            return adapter_cls(entry)
        return None
