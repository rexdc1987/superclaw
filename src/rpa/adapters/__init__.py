"""
SuperClaw RPA - 平台适配器模块

提供各社媒平台的标准化适配器实现。
"""

from rpa.adapters.base import BaseAdapter, AdapterResult, AdapterError
from rpa.adapters.registry import AdapterRegistry, get_adapter_registry

__all__ = [
    "BaseAdapter",
    "AdapterResult",
    "AdapterError",
    "AdapterRegistry",
    "get_adapter_registry",
]
