"""TTS Provider 适配器工厂 —— 自动发现机制"""

import importlib.util
import inspect
from pathlib import Path
from typing import Dict, Type

from .base import TTSProviderAdapter


class ProviderFactory:
    _adapters: Dict[str, Type[TTSProviderAdapter]] = None

    @classmethod
    def _discover_adapters(cls):
        """扫描当前目录，自动发现所有 TTSProviderAdapter 子类。"""
        if cls._adapters is not None:
            return

        cls._adapters = {}
        package_dir = Path(__file__).parent

        for py_file in package_dir.glob("*.py"):
            if py_file.name.startswith("_") or py_file.name == "base.py":
                continue

            module_name = py_file.stem
            try:
                # 动态导入模块
                spec = importlib.util.spec_from_file_location(
                    f"{__package__}.{module_name}", py_file
                )
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # 查找继承 TTSProviderAdapter 的具体类
                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if (
                        issubclass(obj, TTSProviderAdapter)
                        and obj is not TTSProviderAdapter
                    ):
                        # 使用模块名作为映射 key（与 __template_key 一致）
                        cls._adapters[module_name] = obj
                        # 也支持通过类名小写匹配，但优先模块名
                        cls._adapters[obj.__name__.lower()] = obj
            except Exception as e:
                # 静默跳过无法导入的模块，或打印调试日志
                pass

    @classmethod
    def get_adapter(cls, entry: dict) -> TTSProviderAdapter | None:
        """根据配置条目获取适配器实例。"""
        cls._discover_adapters()
        template_key = entry.get("__template_key")
        if not template_key:
            return None

        adapter_cls = cls._adapters.get(template_key)
        if adapter_cls:
            return adapter_cls(entry)
        return None
    