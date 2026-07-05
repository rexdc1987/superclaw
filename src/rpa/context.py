"""
SuperClaw RPA 引擎 - 上下文管理器

管理 Workflow 级和 Node 级变量的读写与模板解析。
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict

from rpa.interfaces import ContextInterface

logger = logging.getLogger(__name__)

# 模板变量匹配正则：{{variable_name}} 或 ${variable_name}
_TEMPLATE_PATTERN = re.compile(r"\{\{(.+?)\}\}|\$\{(.+?)\}")


class ContextManager(ContextInterface):
    """
    上下文管理器实现。
    
    作用域层次：
    - env.*     : 环境变量
    - input.*   : Workflow 输入参数
    - global.*  : Workflow 级自定义变量
    - <node_id>.* : 节点输出
    """
    
    def __init__(self):
        self._variables: Dict[str, Any] = {}
        self._node_outputs: Dict[str, Dict[str, Any]] = {}
        logger.debug("ContextManager 初始化")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取变量值，支持点号路径。
        
        查找顺序：
        1. 直接匹配 key
        2. 前缀匹配 node_id.field
        3. env.* 前缀匹配环境变量
        """
        # 直接匹配
        if key in self._variables:
            return self._variables[key]
        
        # 点号路径解析
        parts = key.split(".", 1)
        if len(parts) == 2:
            prefix, field = parts
            
            # 环境变量
            if prefix == "env":
                return os.environ.get(field, default)
            
            # 节点输出
            if prefix in self._node_outputs:
                return self._node_outputs[prefix].get(field, default)
            
            # 嵌套变量
            parent = self._variables.get(prefix)
            if isinstance(parent, dict):
                return parent.get(field, default)
        
        return default
    
    def set(self, key: str, value: Any) -> None:
        """设置变量值"""
        self._variables[key] = value
        logger.debug(f"设置变量: {key} = {value}")
    
    def get_node_outputs(self, node_id: str) -> Dict[str, Any]:
        """获取指定节点的输出"""
        return self._node_outputs.get(node_id, {})
    
    def set_node_outputs(self, node_id: str, outputs: Dict[str, Any]) -> None:
        """设置节点输出"""
        if node_id not in self._node_outputs:
            self._node_outputs[node_id] = {}
        self._node_outputs[node_id].update(outputs)
        logger.debug(f"设置节点输出: {node_id} -> {outputs}")
    
    def resolve_template(self, template: str) -> Any:
        """
        解析模板字符串。
        
        支持语法：
        - {{variable_name}}     → 引用变量
        - {{node_id.field}}     → 引用其他节点的输出
        - {{env.API_KEY}}       → 引用环境变量
        - ${variable_name}      → 同上（另一种语法）
        
        如果整个字符串就是一个模板引用，返回原始类型（不转为字符串）。
        """
        if not isinstance(template, str):
            return template
        
        # 检查是否是纯模板（整个字符串就是一个引用）
        match = _TEMPLATE_PATTERN.fullmatch(template)
        if match:
            var_name = match.group(1) or match.group(2)
            return self.get(var_name.strip())
        
        # 混合模板：替换所有引用为字符串值
        def replacer(m):
            var_name = (m.group(1) or m.group(2)).strip()
            value = self.get(var_name, "")
            return str(value) if value is not None else ""
        
        return _TEMPLATE_PATTERN.sub(replacer, template)
    
    def get_all(self) -> Dict[str, Any]:
        """获取所有变量的快照"""
        snapshot = dict(self._variables)
        
        # 合并节点输出到顶层（便于模板引用）
        for node_id, outputs in self._node_outputs.items():
            for field, value in outputs.items():
                snapshot[f"{node_id}.{field}"] = value
        
        return snapshot
    
    def snapshot(self) -> Dict[str, Any]:
        """获取完整快照（包括 env）"""
        snap = self.get_all()
        # 添加环境变量
        for key, value in os.environ.items():
            snap[f"env.{key}"] = value
        return snap
    
    def clear(self) -> None:
        """清空所有变量"""
        self._variables.clear()
        self._node_outputs.clear()
    
    def __repr__(self) -> str:
        var_count = len(self._variables)
        node_count = len(self._node_outputs)
        return f"<ContextManager vars={var_count} nodes={node_count}>"
