# DAG 流程编排技术 - 学习笔记

> 作者：诸葛亮  
> 阶段：第二阶段 - DAG 流程编排技术  
> 开始日期：2026-06-18

---

## 1. DAG 理论基础

### 1.1 有向无环图（Directed Acyclic Graph）

**定义**：
- **有向图**：边有方向，从节点 A → B 表示 A 在 B 之前执行
- **无环**：不存在 A → B → C → A 这样的循环路径
- **拓扑序**：所有节点可以线性排列，使得每条边都从前面的节点指向后面的节点

**在 RPA 流程中的意义**：
- 任务依赖关系天然形成 DAG（A 完成后才能执行 B）
- 无环保证流程一定能结束，不会死循环
- 支持并行执行无依赖关系的节点

### 1.2 拓扑排序

**Kahn 算法**（BFS）：
```python
from collections import deque

def topological_sort_kahn(graph: dict) -> list:
    """
    Kahn 拓扑排序算法
    graph: {node: [successor_nodes]}
    返回拓扑序列表，若有环则返回空列表
    """
    # 计算入度
    in_degree = {node: 0 for node in graph}
    for node in graph:
        for neighbor in graph[node]:
            in_degree[neighbor] = in_degree.get(neighbor, 0) + 1
    
    # 入度为0的节点入队
    queue = deque([node for node in in_degree if in_degree[node] == 0])
    result = []
    
    while queue:
        node = queue.popleft()
        result.append(node)
        
        for neighbor in graph.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
    
    # 如果结果数量不等于节点数，说明有环
    if len(result) != len(graph):
        return []  # 存在环
    return result

# 示例
dag = {
    'search': ['filter', 'collect'],
    'filter': ['comment'],
    'collect': ['comment'],
    'comment': ['dm', 'follow'],
    'dm': [],
    'follow': []
}
print(topological_sort_kahn(dag))
# 输出: ['search', 'filter', 'collect', 'comment', 'dm', 'follow']
```

**DFS 拓扑排序**：
```python
def topological_sort_dfs(graph: dict) -> list:
    """DFS 拓扑排序（逆后序）"""
    visited = set()
    result = []
    has_cycle = False
    
    def dfs(node):
        nonlocal has_cycle
        if node in visited:
            return
        visited.add(node)
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                dfs(neighbor)
        result.append(node)
    
    for node in graph:
        if node not in visited:
            dfs(node)
    
    return result[::-1]  # 逆后序
```

### 1.3 关键路径分析

**概念**：DAG 中从起点到终点的最长路径（按权重/耗时），决定流程最短完成时间。

**应用场景**：
- 瓶颈任务识别
- 资源调度优化
- 并行度评估

```python
def critical_path(graph, weights):
    """
    关键路径分析
    graph: {node: [successor_nodes]}
    weights: {node: execution_time}
    """
    topo_order = topological_sort_kahn(graph)
    if not topo_order:
        return None, 0
    
    # 计算最早开始时间（ES）
    earliest = {node: 0 for node in topo_order}
    for node in topo_order:
        for successor in graph.get(node, []):
            earliest[successor] = max(
                earliest[successor],
                earliest[node] + weights[node]
            )
    
    # 计算关键路径
    max_time = max(earliest[node] + weights[node] for node in topo_order)
    end_node = max(topo_order, key=lambda n: earliest[n] + weights[n])
    
    # 回溯关键路径
    critical = [end_node]
    current = end_node
    while True:
        predecessors = [n for n in topo_order if current in graph.get(n, [])]
        if not predecessors:
            break
        # 找到导致当前节点最早开始时间的前驱
        for pred in predecessors:
            if earliest[pred] + weights[pred] == earliest[current]:
                critical.append(pred)
                current = pred
                break
    
    critical.reverse()
    return critical, max_time
```

---

## 2. 流程编排模式

### 2.1 条件分支（If/Else）

```python
class ConditionalNode:
    """条件分支节点"""
    
    def __init__(self, node_id, condition_func, true_branch, false_branch):
        self.node_id = node_id
        self.condition_func = condition_func
        self.true_branch = true_branch
        self.false_branch = false_branch
    
    def evaluate(self, context):
        """评估条件，返回下一步节点"""
        if self.condition_func(context):
            return self.true_branch
        return self.false_branch

# 使用示例
def is_high_value_user(context):
    return context.get('user_score', 0) > 80

branch = ConditionalNode(
    node_id='check_user_value',
    condition_func=is_high_value_user,
    true_branch='send_vip_message',   # 高价值用户走VIP路径
    false_branch='send_normal_message' # 普通用户走标准路径
)
```

### 2.2 循环（For/While）

```python
class LoopNode:
    """循环节点"""
    
    def __init__(self, node_id, iterator_func, body_node, max_iterations=100):
        self.node_id = node_id
        self.iterator_func = iterator_func  # 生成迭代数据
        self.body_node = body_node          # 循环体节点
        self.max_iterations = max_iterations
    
    def get_iterations(self, context):
        """获取迭代列表"""
        items = self.iterator_func(context)
        return items[:self.max_iterations]

# 使用示例
def get_keyword_list(context):
    return context.get('keywords', [])

loop = LoopNode(
    node_id='search_keywords',
    iterator_func=get_keyword_list,
    body_node='search_and_collect',
    max_iterations=50  # 最多搜索50个关键词
)
```

### 2.3 并行执行（Parallel Split/Join）

```python
import asyncio
from typing import List, Callable

class ParallelNode:
    """并行执行节点"""
    
    def __init__(self, node_id, tasks: List[Callable], join_mode='all'):
        """
        join_mode:
        - 'all': 等待所有任务完成
        - 'any': 任一任务完成即可
        - 'majority': 超过半数完成
        """
        self.node_id = node_id
        self.tasks = tasks
        self.join_mode = join_mode
        self.completed = []
        self.failed = []
    
    async def execute(self, context):
        """并行执行所有任务"""
        results = []
        for task in self.tasks:
            results.append(asyncio.create_task(self._run_task(task, context)))
        
        if self.join_mode == 'all':
            return await asyncio.gather(*results, return_exceptions=True)
        elif self.join_mode == 'any':
            done, pending = await asyncio.wait(
                results, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            return [r.result() for r in done]
    
    async def _run_task(self, task, context):
        try:
            result = await task(context) if asyncio.iscoroutinefunction(task) else task(context)
            self.completed.append(result)
            return result
        except Exception as e:
            self.failed.append(e)
            raise

# 使用示例
async def collect_from_douyin(context):
    pass

async def collect_from_xiaohongshu(context):
    pass

parallel = ParallelNode(
    node_id='multi_platform_collect',
    tasks=[collect_from_douyin, collect_from_xiaohongshu],
    join_mode='all'
)
```

### 2.4 子流程调用（Subprocess）

```python
class SubprocessNode:
    """子流程节点 - 复用已有流程模板"""
    
    def __init__(self, node_id, workflow_id, input_mapping=None, output_mapping=None):
        self.node_id = node_id
        self.workflow_id = workflow_id
        self.input_mapping = input_mapping or {}   # 主流程变量 → 子流程变量
        self.output_mapping = output_mapping or {}  # 子流程输出 → 主流程变量
    
    def prepare_input(self, context):
        """准备子流程输入"""
        sub_input = {}
        for main_key, sub_key in self.input_mapping.items():
            sub_input[sub_key] = context.get(main_key)
        return sub_input
    
    def map_output(self, sub_output, context):
        """映射子流程输出到主流程"""
        for sub_key, main_key in self.output_mapping.items():
            context[main_key] = sub_output.get(sub_key)
        return context

# 使用示例
lead_gen_subprocess = SubprocessNode(
    node_id='run_lead_gen',
    workflow_id='lead_generation_v2',
    input_mapping={
        'search_keywords': 'keywords',
        'target_platform': 'platform'
    },
    output_mapping={
        'collected_leads': 'leads',
        'collection_stats': 'stats'
    }
)
```

---

## 3. 流程模板设计

### 3.1 YAML 模板结构

```yaml
# workflow_template.yaml
workflow:
  id: lead_generation
  name: 获客流程模板
  version: "1.0"
  description: 搜索→筛选→评论→私信完整获客流程

# 全局配置
config:
  max_concurrent: 5
  timeout: 300
  retry_policy:
    max_retries: 3
    backoff: exponential

# 变量定义
variables:
  platform: "douyin"
  keywords: []
  min_score: 60
  max_comments_per_hour: 20

# 节点定义
nodes:
  - id: search
    type: action
    name: 搜索关键词
    config:
      action: search
      params:
        platform: "{{variables.platform}}"
        keyword: "{{loop.item}}"
    
  - id: filter
    type: action
    name: 筛选用户
    config:
      action: filter
      params:
        min_score: "{{variables.min_score}}"
        exclude_blocked: true
    
  - id: check_value
    type: conditional
    name: 判断用户价值
    condition: "{{item.score}} > 80"
    true_branch: vip_path
    false_branch: normal_path
    
  - id: vip_path
    type: subflow
    name: VIP获客路径
    workflow: vip_engagement
    
  - id: normal_path
    type: subflow
    name: 标准获客路径
    workflow: standard_engagement

# 边定义（依赖关系）
edges:
  - from: search
    to: filter
  - from: filter
    to: check_value
  - from: check_value
    to: vip_path
    type: conditional
  - from: check_value
    to: normal_path
    type: conditional
```

### 3.2 批量操作模板

```yaml
workflow:
  id: batch_operations
  name: 批量操作模板
  version: "1.0"

nodes:
  - id: load_targets
    type: action
    name: 加载目标列表
    
  - id: batch_loop
    type: loop
    name: 遍历目标
    iterator: "{{nodes.load_targets.result.targets}}"
    max_iterations: 100
    
  - id: execute_operation
    type: action
    name: 执行操作
    parent: batch_loop
    
  - id: rate_limit_check
    type: action
    name: 频率检查
    config:
      max_per_hour: 30
      random_delay: [1, 3]  # 随机延迟1-3秒

edges:
  - from: load_targets
    to: batch_loop
  - from: batch_loop
    to: execute_operation
  - from: execute_operation
    to: rate_limit_check
```

---

## 4. networkx 实践

### 4.1 基础 DAG 操作

```python
import networkx as nx

# 创建 DAG
G = nx.DiGraph()

# 添加节点（带属性）
G.add_node('search', type='action', name='搜索')
G.add_node('filter', type='action', name='筛选')
G.add_node('comment', type='action', name='评论')

# 添加边（依赖关系）
G.add_edge('search', 'filter')
G.add_edge('filter', 'comment')

# 拓扑排序
topo = list(nx.topological_sort(G))
print(f"执行顺序: {topo}")

# 检测环
if nx.is_directed_acyclic_graph(G):
    print("是有效的 DAG")
else:
    print("存在环！")

# 关键路径（按权重）
for node in G.nodes():
    G.nodes[node]['weight'] = 10  # 假设每个节点耗时10秒

longest_path = nx.dag_longest_path(G)
print(f"关键路径: {longest_path}")
print(f"最短完成时间: {nx.dag_longest_path_length(G)} 秒")
```

### 4.2 高级分析

```python
# 前驱和后继
predecessors = list(G.predecessors('comment'))  # ['filter']
successors = list(G.successors('search'))       # ['filter']

# 所有前驱（包括间接）
ancestors = nx.ancestors(G, 'comment')  # {'search', 'filter'}

# 所有后继（包括间接）
descendants = nx.descendants(G, 'search')  # {'filter', 'comment'}

# 层级分析
layers = {}
for node in nx.topological_sort(G):
    preds = list(G.predecessors(node))
    layers[node] = max(layers.get(p, 0) for p in preds) + 1 if preds else 0

# 并行度分析
from collections import Counter
layer_counts = Counter(layers.values())
max_parallel = max(layer_counts.values())
print(f"最大并行度: {max_parallel}")
```

---

## 5. Airflow DAG 设计理念

### 5.1 核心概念映射

| Airflow 概念 | RPA 映射 | 说明 |
|-------------|----------|------|
| DAG | Workflow | 一个完整的任务流程 |
| Task | Node | 单个执行单元 |
| Operator | NodeConfig | 执行器类型和配置 |
| TaskFlow | 函数调用 | 轻量级任务定义 |
| Trigger | Event | 外部事件触发 |
| XCom | Context | 节点间数据传递 |

### 5.2 设计原则

1. **幂等性**：同一任务多次执行结果一致
2. **可重试**：失败任务可安全重试
3. **可观测**：清晰的状态和日志
4. **模块化**：节点可复用、可组合
5. **声明式**：流程描述与执行分离

---

## 6. Prefect 工作流模式

### 6.1 关键模式

```python
# 1. 重试模式
@task(retries=3, retry_delay_seconds=30)
def resilient_task():
    pass

# 2. 缓存模式
@task(cache_key_fn=task_input_hash, cache_expiration=3600)
def expensive_computation():
    pass

# 3. 动态任务生成
@flow
def dynamic_flow(items):
    results = [process_item.submit(item) for item in items]
    return [r.result() for r in results]
```

---

## 7. 常见问题

### 7.1 循环依赖
**原因**：节点 A 依赖 B，B 又依赖 A
**解决**：DAG 检测 + 拓扑验证，构建时即时报错

### 7.2 死锁
**原因**：并行节点等待互相完成
**解决**：设置超时 + 死锁检测算法

### 7.3 级联失败
**原因**：上游失败导致下游全部失败
**解决**：隔离策略 + 降级方案 + 补偿任务

---

*更新日期：2026-06-18*
