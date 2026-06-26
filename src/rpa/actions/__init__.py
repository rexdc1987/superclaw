"""
SuperClaw RPA 引擎 - Action 注册中心

负责 Action 的注册、发现、实例化。
支持装饰器注册、自动扫描、延迟注册。
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Dict, List, Optional, Type

from rpa.interfaces import (
    ActionRegistryInterface,
    BaseAction,
    set_registry,
)

logger = logging.getLogger(__name__)


class ActionRegistry(ActionRegistryInterface):
    """
    Action 注册中心实现。
    
    功能：
    - 注册/注销 Action 类
    - 按名称查找和实例化 Action
    - 自动扫描 actions 包下的模块
    - 延迟注册（处理装饰器先于注册表初始化的场景）
    """
    
    def __init__(self):
        self._actions: Dict[str, Type[BaseAction]] = {}
        self._metadata: Dict[str, Dict[str, str]] = {}
        logger.info("ActionRegistry 初始化")
    
    def register(self, action_class: Type[BaseAction], name: Optional[str] = None) -> str:
        """
        注册 Action 类。
        
        Args:
            action_class: Action 类（非实例）
            name: 覆盖 Action 的 name 属性
            
        Returns:
            注册后的 Action 名称
        """
        action_name = name or action_class.name
        if not action_name:
            raise ValueError(f"Action 类 {action_class.__name__} 未定义 name 属性")
        
        if action_name in self._actions:
            logger.warning(f"Action '{action_name}' 已存在，将被覆盖")
        
        self._actions[action_name] = action_class
        self._metadata[action_name] = {
            "name": action_name,
            "class": action_class.__name__,
            "category": getattr(action_class, "category", "general"),
            "description": getattr(action_class, "description", ""),
            "version": getattr(action_class, "version", "1.0.0"),
        }
        
        logger.info(f"注册 Action: {action_name} ({action_class.__name__})")
        return action_name
    
    def unregister(self, name: str) -> bool:
        """注销 Action"""
        if name in self._actions:
            del self._actions[name]
            del self._metadata[name]
            logger.info(f"注销 Action: {name}")
            return True
        return False
    
    def get(self, name: str) -> Optional[Type[BaseAction]]:
        """获取 Action 类"""
        return self._actions.get(name)
    
    def create(self, name: str) -> Optional[BaseAction]:
        """创建 Action 实例"""
        action_class = self._actions.get(name)
        if action_class:
            return action_class()
        return None
    
    def list_actions(self) -> List[Dict[str, str]]:
        """列出所有已注册的 Action"""
        return list(self._metadata.values())
    
    def has(self, name: str) -> bool:
        """检查 Action 是否已注册"""
        return name in self._actions
    
    def auto_discover(self, package_path: str = "rpa.actions") -> int:
        """
        自动扫描包路径下的所有模块，注册其中的 Action。
        
        Args:
            package_path: Python 包路径
            
        Returns:
            注册的 Action 数量
        """
        count = 0
        try:
            package = importlib.import_module(package_path)
            package_dir = getattr(package, "__path__", None)
            
            if package_dir:
                for importer, modname, ispkg in pkgutil.walk_packages(
                    path=package_dir,
                    prefix=package_path + ".",
                ):
                    if modname.endswith("_action") or modname == "builtin":
                        try:
                            mod = importlib.import_module(modname)
                            count += self._scan_module(mod)
                        except Exception as e:
                            logger.error(f"导入模块 {modname} 失败: {e}")
        except ImportError as e:
            logger.error(f"导入包 {package_path} 失败: {e}")
        
        logger.info(f"自动发现注册了 {count} 个 Action")
        return count
    
    def register_pending(self) -> int:
        """
        注册延迟注册的 Action（装饰器先于注册表初始化的场景）。
        
        Returns:
            注册的 Action 数量
        """
        count = 0
        for name, action_class in self._actions.items():
            if getattr(action_class, "_pending_registration", False):
                delattr(action_class, "_pending_registration")
                count += 1
        
        # 扫描尚未注册的 pending 类
        for name, action_class in list(self._actions.items()):
            if getattr(action_class, "_pending_registration", False):
                delattr(action_class, "_pending_registration")
                count += 1
        
        return count
    
    def _scan_module(self, module) -> int:
        """扫描模块中的 Action 类并注册"""
        count = 0
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseAction)
                and attr is not BaseAction
                and getattr(attr, "name", "")
            ):
                if attr.name not in self._actions:
                    self.register(attr)
                    count += 1
        return count


# ============================================================
# 全局单例
# ============================================================

_global_registry: Optional[ActionRegistry] = None


def get_registry() -> ActionRegistry:
    """获取全局 Action 注册表"""
    global _global_registry
    if _global_registry is None:
        _global_registry = ActionRegistry()
        set_registry(_global_registry)
    return _global_registry


def init_registry(auto_discover: bool = True) -> ActionRegistry:
    """
    初始化全局注册表。
    
    Args:
        auto_discover: 是否自动扫描内置 Actions
        
    Returns:
        ActionRegistry 实例
    """
    registry = get_registry()
    
    if auto_discover:
        registry.auto_discover("rpa.actions")
    
    registry.register_pending()
    
    logger.info(
        f"ActionRegistry 初始化完成，已注册 {len(registry._actions)} 个 Action"
    )
    return registry
