"""
SuperClaw RPA 引擎 - 数据模型

定义 Workflow、Node、Edge、Variable 等核心数据结构。
使用 Pydantic v2 进行数据验证和序列化。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ============================================================
# 枚举定义
# ============================================================

class WorkflowStatus(str, Enum):
    """Workflow 运行状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class NodeStatus(str, Enum):
    """节点执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class FailureStrategy(str, Enum):
    """失败处理策略"""
    FAIL = "fail"          # 立即终止
    SKIP = "skip"          # 跳过节点
    RETRY = "retry"        # 重试
    FALLBACK = "fallback"  # 执行降级 Action


# ============================================================
# 重试配置
# ============================================================

class RetryConfig(BaseModel):
    """重试配置"""
    max_attempts: int = Field(default=3, ge=1, le=10, description="最大重试次数")
    delay_seconds: float = Field(default=5.0, ge=0, description="重试间隔（秒）")
    backoff_multiplier: float = Field(default=2.0, ge=1.0, description="退避倍数")
    retry_on: List[str] = Field(default_factory=list, description="触发重试的异常类型")
    
    def get_delay(self, attempt: int) -> float:
        """计算第 N 次重试的延迟时间"""
        return self.delay_seconds * (self.backoff_multiplier ** (attempt - 1))


# ============================================================
# 条件分支配置
# ============================================================

class ConditionBranch(BaseModel):
    """条件分支"""
    expression: str = Field(description="条件表达式（Python 表达式）")
    true_nodes: List[str] = Field(default_factory=list, description="条件为真时执行的节点 ID")
    false_nodes: List[str] = Field(default_factory=list, description="条件为假时执行的节点 ID")


# ============================================================
# 节点定义（DAG 中的一个节点）
# ============================================================

class NodeDefinition(BaseModel):
    """
    Workflow 节点定义。
    
    每个节点对应一个 Action 调用。
    
    示例：
        {
            "id": "fetch_user",
            "action": "api.get",
            "params": {"url": "https://api.example.com/users/123"},
            "outputs": {"user_data": "$.result"},
            "depends_on": [],
            "retry": {"max_attempts": 3},
            "timeout_seconds": 30
        }
    """
    id: str = Field(description="节点唯一标识")
    action: str = Field(description="Action 名称（如 'web.click', 'api.get'）")
    params: Dict[str, Any] = Field(default_factory=dict, description="Action 参数")
    outputs: Dict[str, str] = Field(default_factory=dict, description="输出映射：{变量名: JSONPath}")
    depends_on: List[str] = Field(default_factory=list, description="依赖的节点 ID 列表")
    
    # 错误处理
    on_failure: FailureStrategy = Field(default=FailureStrategy.FAIL, description="失败策略")
    fallback_action: Optional[str] = Field(default=None, description="降级 Action 名称")
    retry: Optional[RetryConfig] = Field(default=None, description="重试配置")
    
    # 超时
    timeout_seconds: Optional[float] = Field(default=None, ge=0, description="超时时间（秒）")
    
    # 条件分支
    condition: Optional[ConditionBranch] = Field(default=None, description="条件分支配置")
    
    # 元数据
    name: Optional[str] = Field(default=None, description="节点显示名称")
    description: Optional[str] = Field(default=None, description="节点描述")
    tags: List[str] = Field(default_factory=list, description="标签")

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("节点 ID 不能为空")
        if " " in v:
            raise ValueError("节点 ID 不能包含空格")
        return v.strip()


# ============================================================
# 边定义（节点间依赖）
# ============================================================

class EdgeDefinition(BaseModel):
    """
    DAG 边定义（显式依赖关系）。
    
    通常通过 NodeDefinition.depends_on 隐式定义，
    此处用于需要额外配置的复杂场景。
    """
    source: str = Field(description="源节点 ID")
    target: str = Field(description="目标节点 ID")
    condition: Optional[str] = Field(default=None, description="条件表达式（可选）")
    label: Optional[str] = Field(default=None, description="边标签")


# ============================================================
# Workflow 定义
# ============================================================

class WorkflowDefinition(BaseModel):
    """
    Workflow 完整定义。
    
    定义了整个自动化流程的结构、节点、依赖和配置。
    
    示例：
        {
            "id": "user_onboarding",
            "name": "用户入职流程",
            "version": "1.0.0",
            "nodes": [...],
            "edges": [...],
            "variables": {"api_base": "https://api.example.com"},
            "on_failure": "continue",
            "timeout_seconds": 600
        }
    """
    id: str = Field(description="Workflow 唯一标识")
    name: str = Field(description="Workflow 名称")
    version: str = Field(default="1.0.0", description="版本号")
    description: Optional[str] = Field(default=None, description="描述")
    
    # 节点和边
    nodes: List[NodeDefinition] = Field(default_factory=list, description="节点列表")
    edges: List[EdgeDefinition] = Field(default_factory=list, description="显式边列表")
    
    # 全局变量
    variables: Dict[str, Any] = Field(default_factory=dict, description="全局变量")
    
    # 全局错误处理
    on_failure: str = Field(default="fail", description="全局失败策略: fail/continue")
    timeout_seconds: Optional[float] = Field(default=None, ge=0, description="Workflow 超时")
    
    # 调度配置
    schedule: Optional[Dict[str, Any]] = Field(default=None, description="调度配置（cron/interval）")
    
    # 元数据
    tags: List[str] = Field(default_factory=list, description="标签")
    author: Optional[str] = Field(default=None, description="作者")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Workflow ID 不能为空")
        return v.strip()

    def get_node(self, node_id: str) -> Optional[NodeDefinition]:
        """根据 ID 获取节点"""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def get_node_ids(self) -> List[str]:
        """获取所有节点 ID"""
        return [node.id for node in self.nodes]

    def validate_dag(self) -> List[str]:
        """
        验证 DAG 有效性。
        
        Returns:
            错误列表，空列表表示有效
        """
        errors = []
        node_ids = set(self.get_node_ids())
        
        # 检查节点 ID 唯一性
        if len(node_ids) != len(self.nodes):
            errors.append("存在重复的节点 ID")
        
        # 检查依赖关系有效性
        for node in self.nodes:
            for dep_id in node.depends_on:
                if dep_id not in node_ids:
                    errors.append(f"节点 '{node.id}' 依赖不存在的节点 '{dep_id}'")
        
        # 检查循环依赖（DFS）
        if self._has_cycle():
            errors.append("DAG 中存在循环依赖")
        
        return errors

    def _has_cycle(self) -> bool:
        """检测 DAG 中是否存在循环"""
        node_ids = self.get_node_ids()
        visited = set()
        rec_stack = set()
        
        # 构建邻接表
        adj: Dict[str, List[str]] = {nid: [] for nid in node_ids}
        for node in self.nodes:
            for dep_id in node.depends_on:
                if dep_id in adj:
                    adj[dep_id].append(node.id)
        
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
        
        for nid in node_ids:
            if nid not in visited:
                if dfs(nid):
                    return True
        
        return False

    def topological_sort(self) -> List[str]:
        """
        拓扑排序，返回执行顺序。
        
        Returns:
            排序后的节点 ID 列表
            
        Raises:
            ValueError: 如果存在循环依赖
        """
        if self._has_cycle():
            raise ValueError("DAG 中存在循环依赖，无法拓扑排序")
        
        # Kahn's algorithm
        in_degree: Dict[str, int] = {nid: 0 for nid in self.get_node_ids()}
        adj: Dict[str, List[str]] = {nid: [] for nid in self.get_node_ids()}
        
        for node in self.nodes:
            for dep_id in node.depends_on:
                adj[dep_id].append(node.id)
                in_degree[node.id] += 1
        
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        result = []
        
        while queue:
            queue.sort()  # 稳定排序
            current = queue.pop(0)
            result.append(current)
            
            for neighbor in adj[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        return result

    def get_parallel_groups(self) -> List[List[str]]:
        """
        获取可并行执行的节点组。
        
        Returns:
            按层级分组的节点 ID 列表
            例如：[['fetch_user'], ['send_email', 'create_record'], ['notify']]
        """
        order = self.topological_sort()
        if not order:
            return []
        
        # 计算每个节点的层级（最长路径）
        level: Dict[str, int] = {}
        
        def get_level(node_id: str) -> int:
            if node_id in level:
                return level[node_id]
            
            node = self.get_node(node_id)
            if not node or not node.depends_on:
                level[node_id] = 0
                return 0
            
            max_dep_level = max(get_level(dep) for dep in node.depends_on)
            level[node_id] = max_dep_level + 1
            return level[node_id]
        
        for nid in order:
            get_level(nid)
        
        # 按层级分组
        groups: Dict[int, List[str]] = {}
        for nid in order:
            lvl = level[nid]
            if lvl not in groups:
                groups[lvl] = []
            groups[lvl].append(nid)
        
        return [groups[i] for i in sorted(groups.keys())]


# ============================================================
# 运行时模型
# ============================================================

class NodeRunRecord(BaseModel):
    """节点运行记录"""
    node_id: str
    action: str
    status: NodeStatus = NodeStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[float] = None
    outputs: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    retry_count: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class WorkflowRunRecord(BaseModel):
    """Workflow 运行记录"""
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id: str
    status: WorkflowStatus = WorkflowStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[float] = None
    inputs: Dict[str, Any] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    node_records: Dict[str, NodeRunRecord] = Field(default_factory=dict)
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def get_node_record(self, node_id: str) -> Optional[NodeRunRecord]:
        return self.node_records.get(node_id)

    def create_node_record(self, node_id: str, action: str) -> NodeRunRecord:
        record = NodeRunRecord(node_id=node_id, action=action)
        self.node_records[node_id] = record
        return record

    def to_json(self) -> str:
        """序列化为 JSON"""
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, data: str) -> "WorkflowRunRecord":
        """从 JSON 反序列化"""
        return cls.model_validate_json(data)


# ============================================================
# 辅助函数
# ============================================================

def load_workflow_from_file(path: str) -> WorkflowDefinition:
    """从 JSON 文件加载 Workflow 定义"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return WorkflowDefinition(**data)


def save_workflow_to_file(workflow: WorkflowDefinition, path: str) -> None:
    """保存 Workflow 定义到 JSON 文件"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(workflow.model_dump(), f, indent=2, ensure_ascii=False, default=str)


def create_sample_workflow() -> WorkflowDefinition:
    """创建示例 Workflow"""
    return WorkflowDefinition(
        id="sample_workflow",
        name="示例工作流",
        description="一个简单的示例 Workflow",
        nodes=[
            NodeDefinition(
                id="step_1",
                action="api.get",
                name="获取数据",
                params={"url": "https://jsonplaceholder.typicode.com/todos/1"},
                outputs={"data": "$"},
                retry=RetryConfig(max_attempts=3, delay_seconds=2),
            ),
            NodeDefinition(
                id="step_2",
                action="file.write",
                name="保存文件",
                params={"path": "output.json", "content": "{{step_1.data}}"},
                depends_on=["step_1"],
            ),
            NodeDefinition(
                id="step_3",
                action="log.info",
                name="记录日志",
                params={"message": "流程完成"},
                depends_on=["step_2"],
            ),
        ],
        variables={"output_dir": "./output"},
        tags=["sample", "demo"],
    )
