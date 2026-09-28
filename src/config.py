"""TTS Enhancer 插件配置管理模块。"""

from astrbot.api import logger


class TTSEnhancerConfig:
    """TTS Enhancer 插件配置管理类。

    该类负责加载和管理TTS供应商配置，提供配置访问和供应商管理功能。
    配置数据通过字典形式传入，支持优先级排序和供应商条目命名。

    Attributes:
        raw_config (dict): 原始配置数据字典
        _providers (list): 已排序的供应商列表，按优先级从低到高排序
    """

    def __init__(self, raw_config: dict | None = None) -> None:
        """初始化配置管理器。

        Args:
            raw_config (Optional[dict]): 原始配置数据字典，包含 providers 等配置项。
                                         如果为None，将使用空字典作为默认配置。
        """
        self.raw_config = raw_config or {}
        self._providers = None
        self._load_providers()

    def _load_providers(self) -> None:
        """加载 providers，并检测 display_name 重名与 priority 重复。

        从 raw_config 中获取 providers 配置后：
        1. 检测 priority 重复并告警，相同 priority 时按配置顺序保持稳定排序；
        2. 检测 display_name 重名并告警，后续重名条目自动追加数字后缀。

        排序规则：priority 值越小，优先级越高，默认优先级为 100。
        """
        providers_raw = self.raw_config.get("providers", [])
        if not providers_raw:
            logger.warning(
                "TTS Enhancer: 配置中未找到任何 TTS 供应商（providers 为空），请检查插件配置。"
            )
            self._providers = []
            return

        # 检测 priority 重复：仅告警，稳定排序会保持配置顺序
        priority_counts: dict[int, int] = {}
        for entry in providers_raw:
            priority = entry.get("priority", 100)
            priority_counts[priority] = priority_counts.get(priority, 0) + 1
        for priority, count in priority_counts.items():
            if count > 1:
                logger.warning(
                    f"TTS Enhancer: 有 {count} 个供应商使用了相同优先级 {priority}，将按配置顺序依次尝试。"
                )

        # 稳定排序：priority 越小越优先，priority 相同时保持配置顺序
        self._providers = sorted(providers_raw, key=lambda x: x.get("priority", 100))

        # 检测 display_name 重名：后续重名条目自动追加数字后缀，并写入私有字段
        display_name_counts: dict[str, int] = {}
        for entry in self._providers:
            name = str(entry.get("display_name", "")).strip()
            if not name:
                continue
            count = display_name_counts.get(name, 0) + 1
            display_name_counts[name] = count
            if count > 1:
                resolved = f"{name} #{count}"
                logger.warning(
                    f"TTS Enhancer: 供应商显示名称「{name}」重复（第 {count} 个），已自动重命名为「{resolved}」。"
                )
            else:
                resolved = name
            entry["__resolved_name"] = resolved

    def get_providers(self) -> list:
        """获取已排序的 providers 列表。

        Returns:
            list: 返回已按优先级排序的 providers 列表。
                  如果没有配置 providers，返回空列表。
        """
        return self._providers if self._providers else []

    def get_entry_name(self, entry: dict, index: int = -1) -> str:
        """获取供应商条目的显示名称。

        命名规则：
        1. 优先使用用户自定义的 display_name（重名时已自动追加数字后缀）
        2. 如果没有 display_name，但有 voice 信息，返回 "template_key (voice)"
        3. 如果没有 voice 但有 index，返回 "template_key #index"
        4. 默认返回 template_key

        Args:
            entry (dict): 供应商配置条目，包含 display_name、voice 等字段
            index (int): 可选的索引号，用于生成显示名称

        Returns:
            str: 生成的显示名称字符串
        """
        # 优先返回初始化时写入的（已去重）私有字段名
        precomputed = entry.get("__resolved_name")
        if precomputed:
            return precomputed
        name = entry.get("display_name", "")
        if name:
            return name
        voice = entry.get("voice", "")
        template_key = entry.get("__template_key", "unknown")
        if voice:
            return f"{template_key} ({voice})"
        if index >= 0:
            return f"{template_key} #{index}"
        return template_key

    def get(self, key: str, default=None):
        """获取配置值。

        Args:
            key (str): 配置项的键名
            default: 如果配置项不存在时返回的默认值，默认为 None

        Returns:
            配置项的值，如果不存在则返回默认值
        """
        return self.raw_config.get(key, default)

    def has_providers(self) -> bool:
        """检查是否有任何供应商配置。

        Returns:
            bool: 如果有配置的 providers 返回 True，否则返回 False
        """
        return bool(self.get_providers())
