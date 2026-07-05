"""
SuperClaw RPA - Workflow YAML Schema

定义 YAML 工作流的数据结构。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class StepStatus(str, Enum):
    """步骤执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class RetryConfig(BaseModel):
    """重试配置"""
    max_attempts: int = Field(default=3, ge=1, le=10)
    delay_seconds: float = Field(default=5.0, ge=0)
    backoff_multiplier: float = Field(default=2.0, ge=1.0)


class WorkflowStep(BaseModel):
    """
    工作流步骤定义。

    每个步骤可以是：
    - adapter 操作：指定 platform + operation
    - action 操作：指定 action 名称（兼容 DAG 引擎）

    示例:
        # 适配器操作
        - adapter: douyin
          operation: search
          params:
            keyword: "AI"
            count: 10

        # Action 操作（兼容 DAG）
        - action: log.info
          params:
            message: "完成"
    """
    id: Optional[str] = Field(default=None, description="步骤唯一标识（可选，自动生成）")
    name: Optional[str] = Field(default=None, description="步骤显示名称")

    # 操作定义（二选一）
    adapter: Optional[str] = Field(default=None, description="适配器平台名")
    operation: Optional[str] = Field(default=None, description="适配器操作名")
    action: Optional[str] = Field(default=None, description="Action 名称（兼容 DAG 引擎）")

    # 参数
    params: Dict[str, Any] = Field(default_factory=dict, description="操作参数")

    # 依赖
    depends_on: List[str] = Field(default_factory=list, description="依赖的步骤 ID")

    # 条件
    condition: Optional[str] = Field(default=None, description="条件表达式")

    # 错误处理
    on_failure: str = Field(default="fail", description="失败策略: fail/skip/retry")
    retry: Optional[RetryConfig] = Field(default=None, description="重试配置")

    # 超时
    timeout_seconds: Optional[float] = Field(default=None, ge=0, description="超时秒数")

    # 循环
    loop_over: Optional[str] = Field(default=None, description="循环变量引用（如 {{results}}）")
    loop_var: Optional[str] = Field(default=None, description="循环变量名（如 item）")

    def model_post_init(self, __context) -> None:
        if not self.id:
            if self.adapter and self.operation:
                self.id = f"{self.adapter}.{self.operation}"
            elif self.action:
                self.id = self.action
            else:
                self.id = f"step_{id(self)}"


class WorkflowDefinition(BaseModel):
    """
    工作流完整定义。

    YAML 格式:
        name: douyin_engagement
        description: "抖音互动流程"
        version: "1.0.0"

        variables:
          keyword: "Python"
          max_count: 10

        steps:
          - adapter: douyin
            operation: login
            params:
              account: "{{account}}"
          - adapter: douyin
            operation: search
            params:
              keyword: "{{keyword}}"
              count: "{{max_count}}"
          - adapter: douyin
            operation: comment
            params:
              content: "好内容！"
            depends_on: [douyin.search]
            condition: "{{item.likes}} > 100"
    """
    name: str = Field(description="工作流名称")
    description: Optional[str] = Field(default=None, description="描述")
    version: str = Field(default="1.0.0", description="版本号")
    author: Optional[str] = Field(default=None, description="作者")
    tags: List[str] = Field(default_factory=list, description="标签")

    # 步骤
    steps: List[WorkflowStep] = Field(default_factory=list, description="步骤列表")

    # 全局变量
    variables: Dict[str, Any] = Field(default_factory=dict, description="全局变量")

    # 全局配置
    on_failure: str = Field(default="fail", description="全局失败策略")
    max_retries: int = Field(default=3, ge=0, description="全局最大重试次数")
    timeout_seconds: Optional[float] = Field(default=None, ge=0, description="全局超时")

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        """根据 ID 获取步骤"""
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    def get_step_ids(self) -> List[str]:
        """获取所有步骤 ID"""
        return [s.id for s in self.steps]

    def validate_dag(self) -> List[str]:
        """验证 DAG 有效性"""
        errors = []
        step_ids = set(self.get_step_ids())

        # 检查 ID 唯一性
        if len(step_ids) != len(self.steps):
            errors.append("存在重复的步骤 ID")

        # 检查依赖有效性
        for step in self.steps:
            for dep_id in step.depends_on:
                if dep_id not in step_ids:
                    errors.append(f"步骤 '{step.id}' 依赖不存在的步骤 '{dep_id}'")

        # 检查操作定义
        for step in self.steps:
            if not step.adapter and not step.action:
                errors.append(f"步骤 '{step.id}' 必须指定 adapter 或 action")
            if step.adapter and not step.operation:
                errors.append(f"步骤 '{step.id}' 指定了 adapter 但缺少 operation")
            if step.operation and not step.adapter:
                errors.append(f"步骤 '{step.id}' 指定了 operation 但缺少 adapter")

        # 检查循环
        for step in self.steps:
            if step.loop_over and not step.loop_var:
                errors.append(f"步骤 '{step.id}' 指定了 loop_over 但缺少 loop_var")

        # 检查环（DFS）
        if self._has_cycle():
            errors.append("DAG 中存在循环依赖")

        return errors

    def _has_cycle(self) -> bool:
        """检测循环依赖"""
        step_ids = self.get_step_ids()
        visited = set()
        rec_stack = set()

        adj: Dict[str, List[str]] = {sid: [] for sid in step_ids}
        for step in self.steps:
            for dep_id in step.depends_on:
                if dep_id in adj:
                    adj[dep_id].append(step.id)

        def dfs(vertex: str) -> bool:
            visited.add(vertex)
            rec_stack.add(vertex)
            for neighbor in adj.get(vertex, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            rec_stack.discard(vertex)
            return False

        for sid in step_ids:
            if sid not in visited:
                if dfs(sid):
                    return True
        return False

    def topological_sort(self) -> List[str]:
        """拓扑排序"""
        if self._has_cycle():
            raise ValueError("DAG 中存在循环依赖")

        step_ids = self.get_step_ids()
        in_degree: Dict[str, int] = {sid: 0 for sid in step_ids}
        adj: Dict[str, List[str]] = {sid: [] for sid in step_ids}

        for step in self.steps:
            for dep_id in step.depends_on:
                adj[dep_id].append(step.id)
                in_degree[step.id] += 1

        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        result = []

        while queue:
            queue.sort()
            current = queue.pop(0)
            result.append(current)
            for neighbor in adj[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return result

    def get_parallel_groups(self) -> List[List[str]]:
        """获取可并行执行的步骤组"""
        order = self.topological_sort()
        if not order:
            return []

        level: Dict[str, int] = {}

        def get_level(step_id: str) -> int:
            if step_id in level:
                return level[step_id]
            step = self.get_step(step_id)
            if not step or not step.depends_on:
                level[step_id] = 0
                return 0
            max_dep = max(get_level(dep) for dep in step.depends_on)
            level[step_id] = max_dep + 1
            return level[step_id]

        for sid in order:
            get_level(sid)

        groups: Dict[int, List[str]] = {}
        for sid in order:
            lvl = level[sid]
            if lvl not in groups:
                groups[lvl] = []
            groups[lvl].append(sid)

        return [groups[i] for i in sorted(groups.keys())]


# TASK_COMPLETE: phase4_workflow
