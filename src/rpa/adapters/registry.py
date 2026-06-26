"""
SuperClaw RPA - 适配器注册中心

管理平台适配器的注册和发现。
"""

from __future__ import annotations

import importlib
import logging
from typing import Dict, List, Optional, Type

from rpa.adapters.base import BaseAdapter

logger = logging.getLogger(__name__)

# 全局注册表实例
_global_registry: Optional["AdapterRegistry"] = None


class AdapterRegistry:
    """适配器注册中心"""

    def __init__(self):
        self._adapters: Dict[str, Type[BaseAdapter]] = {}

    def register(self, adapter_class: Type[BaseAdapter]) -> str:
        """
        注册适配器类。

        Args:
            adapter_class: 适配器类（必须有 platform 属性）

        Returns:
            注册的平台名称
        """
        platform = adapter_class.platform
        if not platform:
            raise ValueError(f"适配器 {adapter_class.__name__} 未定义 platform 属性")
        self._adapters[platform] = adapter_class
        logger.info(f"注册适配器: {platform} -> {adapter_class.__name__}")
        return platform

    def get(self, platform: str) -> Optional[Type[BaseAdapter]]:
        """获取适配器类"""
        return self._adapters.get(platform)

    def create(self, platform: str, config: Optional[Dict] = None) -> Optional[BaseAdapter]:
        """
        创建适配器实例。

        Args:
            platform: 平台名称
            config: 配置字典

        Returns:
            适配器实例，未注册则返回 None
        """
        cls = self._adapters.get(platform)
        if cls is None:
            return None
        return cls(config=config)

    def has(self, platform: str) -> bool:
        """检查平台是否已注册"""
        return platform in self._adapters

    def list_adapters(self) -> List[Dict[str, str]]:
        """列出所有已注册的适配器"""
        return [
            {"platform": p, "class": cls.__name__}
            for p, cls in self._adapters.items()
        ]

    def discover(self, package_path: str = "rpa.adapters") -> int:
        """
        自动扫描并注册适配器。

        扫描指定包下所有 BaseAdapter 子类并注册。

        Returns:
            新注册的适配器数量
        """
        count = 0
        try:
            package = importlib.import_module(package_path)
            for attr_name in dir(package):
                attr = getattr(package, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseAdapter)
                    and attr is not BaseAdapter
                    and hasattr(attr, "platform")
                    and attr.platform
                    and not self.has(attr.platform)
                ):
                    self.register(attr)
                    count += 1
        except ImportError as e:
            logger.warning(f"无法导入 {package_path}: {e}")
        return count


def get_adapter_registry() -> AdapterRegistry:
    """获取全局适配器注册表"""
    global _global_registry
    if _global_registry is None:
        _global_registry = AdapterRegistry()
    return _global_registry
