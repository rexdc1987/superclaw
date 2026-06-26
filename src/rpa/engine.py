"""
SuperClaw RPA 引擎 - 核心引擎

整合 ActionRegistry、DAGExecutor、ContextManager，提供统一的 Workflow 执行接口。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from rpa.actions import get_registry, init_registry
from rpa.context import ContextManager
from rpa.dag_engine import DAGExecutor, DAGValidationError
from rpa.interfaces import (
    ActionRegistryInterface,
    WorkflowEngineInterface,
)
from rpa.models import (
    NodeRunRecord,
    WorkflowDefinition,
    WorkflowRunRecord,
    WorkflowStatus,
)

logger = logging.getLogger(__name__)


class WorkflowEngine(WorkflowEngineInterface):
    """
    RPA Workflow 引擎核心。
    
    整合所有组件，提供：
    - Workflow 加载和验证
    - Workflow 执行和状态追踪
    - 运行记录管理
    - 事件回调
    """
    
    def __init__(
        self,
        registry: Optional[ActionRegistryInterface] = None,
        max_workers: int = 4,
        auto_init: bool = True,
    ):
        """
        初始化引擎。
        
        Args:
            registry: Action 注册表（默认使用全局注册表）
            max_workers: 并行执行最大线程数
            auto_init: 是否自动初始化注册表
        """
        if registry is None:
            if auto_init:
                self.registry = init_registry()
            else:
                self.registry = get_registry()
        else:
            self.registry = registry
        
        self.dag_executor = DAGExecutor(
            registry=self.registry,
            max_workers=max_workers,
        )
        
        # 已加载的 Workflow
        self._workflows: Dict[str, WorkflowDefinition] = {}
        # 运行记录
        self._runs: Dict[str, WorkflowRunRecord] = {}
        # 事件回调
        self._on_node_complete: Optional[Callable] = None
        self._on_node_error: Optional[Callable] = None
        self._on_workflow_complete: Optional[Callable] = None
        
        logger.info("WorkflowEngine 初始化完成")
    
    # ---- 事件回调注册 ----
    
    def on_node_complete(self, callback: Callable[[str, NodeRunRecord], None]) -> None:
        """注册节点完成回调"""
        self._on_node_complete = callback
    
    def on_node_error(self, callback: Callable[[str, Exception], None]) -> None:
        """注册节点错误回调"""
        self._on_node_error = callback
    
    def on_workflow_complete(self, callback: Callable[[str, str, bool], None]) -> None:
        """注册 Workflow 完成回调"""
        self._on_workflow_complete = callback
    
    # ---- Workflow 管理 ----
    
    def load_workflow(self, workflow_def: Dict[str, Any]) -> str:
        """
        加载 Workflow 定义。
        
        Args:
            workflow_def: Workflow JSON 定义
            
        Returns:
            workflow_id
        """
        workflow = WorkflowDefinition(**workflow_def)
        
        # 验证 DAG
        errors = self.dag_executor.validate(workflow)
        if errors:
            raise DAGValidationError(f"Workflow 验证失败: {'; '.join(errors)}")
        
        self._workflows[workflow.id] = workflow
        logger.info(f"加载 Workflow: {workflow.id} ({workflow.name})")
        return workflow.id
    
    def load_workflow_from_file(self, path: str) -> str:
        """从 JSON 文件加载 Workflow"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return self.load_workflow(data)
    
    def get_workflow(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        """获取 Workflow 定义"""
        return self._workflows.get(workflow_id)
    
    def list_workflows(self) -> List[Dict[str, Any]]:
        """列出所有已加载的 Workflow"""
        return [
            {
                "id": wf.id,
                "name": wf.name,
                "version": wf.version,
                "node_count": len(wf.nodes),
                "tags": wf.tags,
            }
            for wf in self._workflows.values()
        ]
    
    def remove_workflow(self, workflow_id: str) -> bool:
        """移除 Workflow"""
        if workflow_id in self._workflows:
            del self._workflows[workflow_id]
            logger.info(f"移除 Workflow: {workflow_id}")
            return True
        return False
    
    # ---- 执行 ----
    
    def execute(
        self,
        workflow_id: str,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        执行 Workflow。
        
        Args:
            workflow_id: Workflow ID
            inputs: 输入参数
            
        Returns:
            run_id
        """
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            raise ValueError(f"Workflow '{workflow_id}' 未加载")
        
        run_id = str(uuid.uuid4())
        
        # 创建上下文
        context = ContextManager()
        
        # 加载输入参数
        if inputs:
            for key, value in inputs.items():
                context.set(f"input.{key}", value)
                context.set(key, value)  # 也放到顶层方便引用
        
        # 包装回调
        def on_node_complete(node_id: str, record: NodeRunRecord):
            if self._on_node_complete:
                self._on_node_complete(node_id, record)
        
        def on_node_error(node_id: str, error: Exception):
            if self._on_node_error:
                self._on_node_error(node_id, error)
        
        logger.info(f"开始执行 Workflow: {workflow_id} (run={run_id})")
        
        # 执行
        run_record = self.dag_executor.execute(
            workflow=workflow,
            context=context,
            on_node_complete=on_node_complete,
            on_node_error=on_node_error,
        )
        
        # 保存运行记录
        run_record.run_id = run_id
        self._runs[run_id] = run_record
        
        # 输出结果
        run_record.outputs = context.get_all()
        
        success = run_record.status == WorkflowStatus.COMPLETED
        logger.info(
            f"Workflow 执行完成: {workflow_id} -> {run_record.status.value}"
        )
        
        # 触发完成回调
        if self._on_workflow_complete:
            self._on_workflow_complete(workflow_id, run_id, success)
        
        return run_id
    
    def execute_workflow(
        self,
        workflow: WorkflowDefinition,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> WorkflowRunRecord:
        """
        直接执行 Workflow 定义（不经过 load 阶段）。
        
        Returns:
            WorkflowRunRecord
        """
        # 先加载
        self._workflows[workflow.id] = workflow
        
        run_id = self.execute(workflow.id, inputs)
        return self._runs[run_id]
    
    # ---- 状态查询 ----
    
    def get_status(self, run_id: str) -> Dict[str, Any]:
        """获取运行状态"""
        record = self._runs.get(run_id)
        if not record:
            return {"error": f"Run '{run_id}' 不存在"}
        
        return {
            "run_id": record.run_id,
            "workflow_id": record.workflow_id,
            "status": record.status.value,
            "started_at": record.started_at.isoformat() if record.started_at else None,
            "completed_at": record.completed_at.isoformat() if record.completed_at else None,
            "duration_ms": record.duration_ms,
            "error": record.error,
            "node_count": len(record.node_records),
            "node_statuses": {
                nid: rec.status.value
                for nid, rec in record.node_records.items()
            },
        }
    
    def get_run_record(self, run_id: str) -> Optional[WorkflowRunRecord]:
        """获取完整运行记录"""
        return self._runs.get(run_id)
    
    def list_runs(
        self,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """列出运行记录"""
        results = []
        for record in reversed(list(self._runs.values())):
            if workflow_id and record.workflow_id != workflow_id:
                continue
            if status and record.status.value != status:
                continue
            results.append({
                "run_id": record.run_id,
                "workflow_id": record.workflow_id,
                "status": record.status.value,
                "started_at": record.started_at.isoformat() if record.started_at else None,
                "duration_ms": record.duration_ms,
            })
            if len(results) >= limit:
                break
        return results
    
    def cancel(self, run_id: str) -> bool:
        """取消运行"""
        if self.dag_executor.is_running:
            self.dag_executor.cancel()
            record = self._runs.get(run_id)
            if record:
                record.status = WorkflowStatus.CANCELLED
                record.completed_at = datetime.now()
            logger.info(f"取消运行: {run_id}")
            return True
        return False
    
    # ---- 清理 ----
    
    def cleanup(self) -> None:
        """清理所有运行记录"""
        self._runs.clear()
        logger.info("清理运行记录")


# TASK_COMPLETE: phase2_rpa_engine


# TASK_COMPLETE: phase1_rpa_design
