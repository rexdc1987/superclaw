"""
SuperClaw RPA 引擎 - 接口定义

定义 Action 基类、Registry 接口、Executor 接口、Context 接口。
所有 Action 插件必须继承 BaseAction 并实现 execute() 方法。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


# ============================================================
# 枚举定义
# ============================================================

class ActionStatus(str, Enum):
    """Action 执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class FailureStrategy(str, Enum):
    """失败处理策略"""
    FAIL = "fail"          # 立即终止 Workflow
    SKIP = "skip"          # 跳过当前节点
    RETRY = "retry"        # 重试
    FALLBACK = "fallback"  # 执行降级 Action


# ============================================================
# 数据模型（前向声明，完整定义在 models.py）
# ============================================================

class ActionParams(BaseModel):
    """Action 参数基类"""
    model_config = ConfigDict(extra="allow")

    def get(self, key: str, default: Any = None) -> Any:
        """获取参数值"""
        return getattr(self, key, default)


class ActionResult(BaseModel):
    """Action 执行结果"""
    status: ActionStatus
    outputs: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    duration_ms: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ============================================================
# Action 基类
# ============================================================

class BaseAction(ABC):
    """
    Action 插件基类。
    
    所有自定义 Action 必须继承此类并实现：
    - name: Action 唯一标识（如 "web.click", "file.copy"）
    - execute(): 执行逻辑
    
    可选覆写：
    - validate_params(): 参数校验
    - on_success(): 成功回调
    - on_error(): 失败回调
    - cleanup(): 清理资源
    
    使用示例：
        @register_action("web.click")
        class WebClickAction(BaseAction):
            name = "web.click"
            description = "点击网页元素"
            
            def execute(self, params: ActionParams, context: "ContextManager") -> ActionResult:
                selector = params.get("selector")
                # ... 点击逻辑
                return ActionResult(status=ActionStatus.SUCCESS, outputs={"clicked": True})
    """
    
    name: str = ""
    description: str = ""
    category: str = "general"
    version: str = "1.0.0"
    
    def __init__(self):
        self.logger = logging.getLogger(f"rpa.action.{self.name}")

    @abstractmethod
    def execute(self, params: ActionParams, context: Any) -> ActionResult:
        """
        执行 Action。
        
        Args:
            params: Action 参数
            context: 上下文管理器，可读写变量
            
        Returns:
            ActionResult: 执行结果
        """
        ...

    def validate_params(self, params: ActionParams) -> bool:
        """
        参数校验（可选覆写）。
        
        Args:
            params: 待校验的参数
            
        Returns:
            True 表示校验通过
            
        Raises:
            ValueError: 参数校验失败时抛出
        """
        return True

    def on_success(self, result: ActionResult, context: Any) -> None:
        """成功回调（可选覆写）"""
        pass

    def on_error(self, error: Exception, params: ActionParams, context: Any) -> None:
        """失败回调（可选覆写）"""
        self.logger.error(f"Action {self.name} failed: {error}")

    def cleanup(self) -> None:
        """清理资源（可选覆写）"""
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"


# ============================================================
# Action 注册表接口
# ============================================================

class ActionRegistryInterface(ABC):
    """
    Action 注册中心接口。
    
    负责 Action 的注册、发现、实例化。
    """
    
    @abstractmethod
    def register(self, action_class: Type[BaseAction], name: Optional[str] = None) -> str:
        """
        注册 Action 类。
        
        Args:
            action_class: Action 类（非实例）
            name: 覆盖 Action 的 name 属性
            
        Returns:
            注册后的 Action 名称
        """
        ...

    @abstractmethod
    def unregister(self, name: str) -> bool:
        """注销 Action"""
        ...

    @abstractmethod
    def get(self, name: str) -> Optional[Type[BaseAction]]:
        """获取 Action 类"""
        ...

    @abstractmethod
    def create(self, name: str) -> Optional[BaseAction]:
        """创建 Action 实例"""
        ...

    @abstractmethod
    def list_actions(self) -> List[Dict[str, str]]:
        """列出所有已注册的 Action"""
        ...

    @abstractmethod
    def has(self, name: str) -> bool:
        """检查 Action 是否已注册"""
        ...


# ============================================================
# Context 接口
# ============================================================

class ContextInterface(ABC):
    """
    上下文管理器接口。
    
    管理 Workflow 级和 Node 级变量的读写。
    """
    
    @abstractmethod
    def get(self, key: str, default: Any = None) -> Any:
        """获取变量值，支持点号路径（如 'fetch_user.email'）"""
        ...

    @abstractmethod
    def set(self, key: str, value: Any) -> None:
        """设置变量值"""
        ...

    @abstractmethod
    def get_node_outputs(self, node_id: str) -> Dict[str, Any]:
        """获取指定节点的输出"""
        ...

    @abstractmethod
    def set_node_outputs(self, node_id: str, outputs: Dict[str, Any]) -> None:
        """设置节点输出"""
        ...

    @abstractmethod
    def resolve_template(self, template: str) -> Any:
        """
        解析模板字符串。
        
        支持语法：
        - {{variable_name}}
        - {{node_id.output_field}}
        - {{env.API_KEY}}
        """
        ...

    @abstractmethod
    def get_all(self) -> Dict[str, Any]:
        """获取所有变量的快照"""
        ...


# ============================================================
# Workflow Engine 接口
# ============================================================

class WorkflowEngineInterface(ABC):
    """
    Workflow 引擎接口。
    
    负责解析 DAG、调度执行、管理生命周期。
    """
    
    @abstractmethod
    def load_workflow(self, workflow_def: Dict[str, Any]) -> str:
        """
        加载 Workflow 定义。
        
        Args:
            workflow_def: Workflow JSON 定义
            
        Returns:
            workflow_id
        """
        ...

    @abstractmethod
    def execute(self, workflow_id: str, inputs: Optional[Dict[str, Any]] = None) -> str:
        """
        执行 Workflow。
        
        Args:
            workflow_id: Workflow ID
            inputs: 输入参数
            
        Returns:
            run_id
        """
        ...

    @abstractmethod
    def get_status(self, run_id: str) -> Dict[str, Any]:
        """获取 Workflow 运行状态"""
        ...

    @abstractmethod
    def cancel(self, run_id: str) -> bool:
        """取消 Workflow 运行"""
        ...

    @abstractmethod
    def list_workflows(self) -> List[Dict[str, Any]]:
        """列出所有已加载的 Workflow"""
        ...


# ============================================================
# Handler 接口（可选扩展）
# ============================================================

class EventHandlerInterface(ABC):
    """
    事件处理器接口。
    
    用于监听 Action/Workflow 生命周期事件。
    """
    
    @abstractmethod
    def on_action_start(self, node_id: str, action_name: str) -> None:
        """Action 开始执行"""
        ...

    @abstractmethod
    def on_action_complete(self, node_id: str, action_name: str, result: ActionResult) -> None:
        """Action 执行完成"""
        ...

    @abstractmethod
    def on_action_error(self, node_id: str, action_name: str, error: Exception) -> None:
        """Action 执行出错"""
        ...

    @abstractmethod
    def on_workflow_complete(self, workflow_id: str, run_id: str, success: bool) -> None:
        """Workflow 执行完成"""
        ...


# ============================================================
# 注册装饰器
# ============================================================

# 全局注册表（延迟初始化）
_global_registry: Optional[ActionRegistryInterface] = None


def set_registry(registry: ActionRegistryInterface) -> None:
    """设置全局注册表实例"""
    global _global_registry
    _global_registry = registry


def register_action(name: Optional[str] = None, category: Optional[str] = None):
    """
    Action 注册装饰器。
    
    使用示例：
        @register_action(name="web.click", category="web")
        class WebClickAction(BaseAction):
            ...
    
    Args:
        name: Action 名称（默认使用类的 name 属性）
        category: 分类（默认使用类的 category 属性）
    """
    def decorator(cls: Type[BaseAction]):
        # 设置类属性
        if name:
            cls.name = name
        if category:
            cls.category = category
        
        # 注册到全局注册表
        if _global_registry is not None:
            _global_registry.register(cls)
        else:
            # 延迟注册：存储在类上，等注册表初始化时再注册
            if not hasattr(cls, '_pending_registration'):
                cls._pending_registration = True
        
        return cls
    return decorator
