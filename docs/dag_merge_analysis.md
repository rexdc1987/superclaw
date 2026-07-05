# DAG 模块合并分析

> 分析人：曹操 | 日期：2026-06-20

## 现状

| 模块 | 类名 | 行数 | 被引用 |
|------|------|------|--------|
| dag.py | DAGExecutor, DAGValidationError | 484 | engine.py, test_rpa_engine.py, test_e2e.py |
| dag_engine.py | DagEngine, Node, NodeType, NodeResult, NodeStatus | 523 | orchestrator.py, test_e2e.py |

## 差异分析

### dag.py (DAGExecutor)
- 核心类：DAGExecutor — 执行DAG工作流
- 依赖：models.py (Workflow, Node, Edge)
- 功能：拓扑排序、节点执行、错误处理、重试
- 使用者：engine.py (WorkflowEngine)

### dag_engine.py (DagEngine)
- 核心类：DagEngine — DAG执行引擎
- 自定义：Node, NodeType, NodeResult, NodeStatus (不依赖models.py)
- 功能：拓扑排序、并行执行、条件分支、子流程
- 使用者：orchestrator.py (WorkflowOrchestrator)

## 问题

1. **两套DAG实现**：dag.py和dag_engine.py功能高度重叠
2. **两套节点模型**：dag.py用models.py的Node，dag_engine.py自定义Node
3. **引用分裂**：engine.py引用dag.py，orchestrator.py引用dag_engine.py
4. **workflow/runner.py**：又是一套独立的工作流执行逻辑

## 建议

### 方案A：保留dag_engine.py，删除dag.py（推荐）
- dag_engine.py功能更完整（并行、条件、子流程）
- 将engine.py改为引用dag_engine.py
- 迁移dag.py中独有的功能到dag_engine.py
- 预计减少 ~480 行重复代码

### 方案B：保留dag.py，删除dag_engine.py
- dag.py与models.py集成更好
- 需要将orchestrator.py改为引用dag.py
- 需要将dag_engine.py的并行/条件功能迁移过来

### 方案C：统一到workflow/runner.py
- 将DAG逻辑合并到workflow模块
- 最彻底但改动最大

## 建议执行方案A，改动最小，风险最低。
