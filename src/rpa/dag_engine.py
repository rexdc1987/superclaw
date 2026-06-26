"""
RPA DAG 流程引擎 - 第二阶段产出
基于 networkx 的有向无环图流程引擎，支持条件分支、循环、并行执行、子流程

用法示例：
    from rpa.dag_engine import DagEngine, Node, NodeType
    
    engine = DagEngine()
    
    # 添加节点
    engine.add_node(Node(id='search', type=NodeType.ACTION, name='搜索'))
    engine.add_node(Node(id='filter', type=NodeType.ACTION, name='筛选'))
    engine.add_node(Node(id='branch', type=NodeType.CONDITIONAL, name='判断'))
    
    # 添加边
    engine.add_edge('search', 'filter')
    engine.add_edge('filter', 'branch')
    
    # 执行
    result = engine.execute(context={'keywords': ['python', 'rpa']})
"""

import json
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from datetime import datetime
from pathlib import Path

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False

logger = logging.getLogger(__name__)


class NodeType(Enum):
    """节点类型"""
    ACTION = 'action'               # 普通动作
    CONDITIONAL = 'conditional'     # 条件分支
    LOOP = 'loop'                   # 循环节点
    PARALLEL = 'parallel'           # 并行执行
    SUBPROCESS = 'subprocess'       # 子流程
    START = 'start'                 # 起始节点
    END = 'end'                     # 结束节点


class NodeStatus(Enum):
    """节点执行状态"""
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'
    SKIPPED = 'skipped'


@dataclass
class Node:
    """流程节点"""
    id: str
    type: NodeType = NodeType.ACTION
    name: str = ''
    handler: Optional[Callable] = None          # 执行函数
    condition: Optional[Callable] = None        # 条件函数（条件分支用）
    config: Dict[str, Any] = field(default_factory=dict)
    
    # 条件分支
    true_branch: Optional[str] = None
    false_branch: Optional[str] = None
    
    # 循环
    iterator: Optional[Callable] = None
    loop_body: Optional[str] = None
    max_iterations: int = 100
    
    # 并行
    parallel_tasks: List[Callable] = field(default_factory=list)
    join_mode: str = 'all'  # all / any / majority
    
    # 子流程
    subworkflow_id: Optional[str] = None
    input_mapping: Dict[str, str] = field(default_factory=dict)
    output_mapping: Dict[str, str] = field(default_factory=dict)


@dataclass
class NodeResult:
    """节点执行结果"""
    node_id: str
    status: NodeStatus
    result: Any = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: Optional[float] = None


class DagEngine:
    """
    DAG 流程引擎
    
    功能：
    - 基于 networkx 构建 DAG
    - 拓扑排序确定执行顺序
    - 支持条件分支、循环、并行、子流程
    - 执行历史和状态追踪
    """
    
    def __init__(self):
        self.graph = nx.DiGraph()
        self.nodes: Dict[str, Node] = {}
        self.results: Dict[str, NodeResult] = {}
        self._execution_order: List[str] = []
        self._context: Dict[str, Any] = {}
    
    def add_node(self, node: Node):
        """添加节点"""
        self.nodes[node.id] = node
        self.graph.add_node(
            node.id,
            type=node.type.value,
            name=node.name
        )
        logger.debug(f"添加节点: {node.id} ({node.type.value})")
    
    def add_edge(self, from_id: str, to_id: str, **attrs):
        """添加边（依赖关系）"""
        if from_id not in self.nodes:
            raise ValueError(f"源节点不存在: {from_id}")
        if to_id not in self.nodes:
            raise ValueError(f"目标节点不存在: {to_id}")
        
        self.graph.add_edge(from_id, to_id, **attrs)
        logger.debug(f"添加边: {from_id} -> {to_id}")
    
    def validate(self) -> bool:
        """验证 DAG 有效性"""
        if not nx.is_directed_acyclic_graph(self.graph):
            cycles = list(nx.simple_cycles(self.graph))
            logger.error(f"检测到循环依赖: {cycles}")
            return False
        
        if len(self.nodes) == 0:
            logger.warning("DAG 为空")
            return False
        
        logger.info(f"DAG 验证通过: {len(self.nodes)} 节点, {self.graph.number_of_edges()} 条边")
        return True
    
    def get_execution_order(self) -> List[str]:
        """获取拓扑排序执行顺序"""
        return list(nx.topological_sort(self.graph))
    
    def get_critical_path(self) -> tuple:
        """关键路径分析"""
        # 假设每个节点权重为1（可扩展为实际耗时）
        for node_id in self.nodes:
            self.graph.nodes[node_id].setdefault('weight', 1)
        
        path = nx.dag_longest_path(self.graph)
        length = nx.dag_longest_path_length(self.graph)
        return path, length
    
    def get_parallel_groups(self) -> List[List[str]]:
        """获取可并行执行的节点组"""
        layers = {}
        for node in nx.topological_sort(self.graph):
            preds = list(self.graph.predecessors(node))
            if not preds:
                layers[node] = 0
            else:
                layers[node] = max(layers.get(p, 0) for p in preds) + 1
        
        # 按层级分组
        groups = {}
        for node, layer in layers.items():
            groups.setdefault(layer, []).append(node)
        
        return [groups[k] for k in sorted(groups.keys())]
    
    def execute(self, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        执行 DAG 流程
        
        Args:
            context: 执行上下文（共享变量）
        
        Returns:
            执行结果字典
        """
        if not self.validate():
            raise ValueError("DAG 验证失败，存在循环或为空")
        
        self._context = context or {}
        self.results = {}
        self._execution_order = self.get_execution_order()
        
        logger.info(f"开始执行 DAG, 共 {len(self._execution_order)} 个节点")
        
        for node_id in self._execution_order:
            node = self.nodes[node_id]
            
            # 检查前置条件
            if not self._check_predecessors(node_id):
                self.results[node_id] = NodeResult(
                    node_id=node_id,
                    status=NodeStatus.SKIPPED,
                    error="前置节点未完成"
                )
                continue
            
            # 执行节点
            result = self._execute_node(node)
            self.results[node_id] = result
            
            # 如果失败且没有跳过策略，停止执行
            if result.status == NodeStatus.FAILED:
                logger.error(f"节点 {node_id} 执行失败: {result.error}")
                # 标记后续节点为跳过
                self._skip_successors(node_id)
        
        return self._build_result()
    
    def _execute_node(self, node: Node) -> NodeResult:
        """执行单个节点"""
        result = NodeResult(
            node_id=node.id,
            status=NodeStatus.RUNNING,
            started_at=datetime.now().isoformat()
        )
        
        try:
            start_time = datetime.now()
            
            if node.type == NodeType.CONDITIONAL:
                node_result = self._execute_conditional(node)
            elif node.type == NodeType.LOOP:
                node_result = self._execute_loop(node)
            elif node.type == NodeType.PARALLEL:
                node_result = self._execute_parallel(node)
            elif node.type == NodeType.SUBPROCESS:
                node_result = self._execute_subprocess(node)
            elif node.type in (NodeType.START, NodeType.END):
                node_result = {'status': 'pass'}
            else:
                # ACTION 类型
                if node.handler:
                    node_result = node.handler(self._context, node.config)
                else:
                    node_result = {'status': 'no_handler'}
            
            end_time = datetime.now()
            result.result = node_result
            result.status = NodeStatus.COMPLETED
            result.duration_ms = (end_time - start_time).total_seconds() * 1000
            
            logger.info(f"节点 {node.id} 执行完成, 耗时 {result.duration_ms:.1f}ms")
            
        except Exception as e:
            result.status = NodeStatus.FAILED
            result.error = str(e)
            result.completed_at = datetime.now().isoformat()
            logger.error(f"节点 {node.id} 执行异常: {e}")
        
        result.completed_at = datetime.now().isoformat()
        return result
    
    def _execute_conditional(self, node: Node) -> Any:
        """执行条件分支"""
        if not node.condition:
            raise ValueError(f"条件节点 {node.id} 缺少 condition 函数")
        
        condition_result = node.condition(self._context)
        logger.info(f"条件节点 {node.id}: {condition_result}")
        
        # 通过上下文记录分支路径
        self._context[f'_branch_{node.id}'] = condition_result
        
        return {'condition': condition_result}
    
    def _execute_loop(self, node: Node) -> Any:
        """执行循环节点"""
        if not node.iterator:
            raise ValueError(f"循环节点 {node.id} 缺少 iterator 函数")
        
        items = node.iterator(self._context)
        items = items[:node.max_iterations]
        
        results = []
        for idx, item in enumerate(items):
            logger.info(f"循环 {node.id}: 第 {idx+1}/{len(items)} 次")
            self._context['loop_item'] = item
            self._context['loop_index'] = idx
            
            if node.handler:
                result = node.handler(self._context, node.config)
                results.append(result)
        
        return {'iterations': len(items), 'results': results}
    
    def _execute_parallel(self, node: Node) -> Any:
        """执行并行节点"""
        if not node.parallel_tasks:
            raise ValueError(f"并行节点 {node.id} 缺少 parallel_tasks")
        
        # 简化版：顺序模拟并行（实际可用 asyncio）
        results = []
        for task in node.parallel_tasks:
            try:
                result = task(self._context)
                results.append({'status': 'success', 'result': result})
            except Exception as e:
                results.append({'status': 'failed', 'error': str(e)})
        
        # 检查 join_mode
        successes = sum(1 for r in results if r['status'] == 'success')
        
        if node.join_mode == 'any' and successes > 0:
            pass
        elif node.join_mode == 'majority' and successes > len(results) / 2:
            pass
        elif node.join_mode == 'all' and successes == len(results):
            pass
        elif node.join_mode in ('any', 'majority') and successes == 0:
            raise RuntimeError("并行任务全部失败")
        
        return {'total': len(results), 'successes': successes, 'details': results}
    
    def _execute_subprocess(self, node: Node) -> Any:
        """执行子流程"""
        if not node.subworkflow_id:
            raise ValueError(f"子流程节点 {node.id} 缺少 subworkflow_id")
        
        # 准备子流程输入
        sub_input = {}
        for main_key, sub_key in node.input_mapping.items():
            sub_input[sub_key] = self._context.get(main_key)
        
        logger.info(f"子流程 {node.subworkflow_id}, 输入: {list(sub_input.keys())}")
        
        # 尝试加载并执行子流程
        sub_result = {'subworkflow': node.subworkflow_id, 'status': 'simulated'}
        try:
            from pathlib import Path
            sub_path = Path(node.subworkflow_id)
            if sub_path.exists() and sub_path.suffix == '.json':
                sub_engine = DagEngine.load(str(sub_path))
                sub_context = {**self._context, **sub_input}
                sub_result = sub_engine.execute(context=sub_context)
                sub_result['status'] = 'completed'
            else:
                logger.warning(f"子流程文件不存在: {node.subworkflow_id}")
        except Exception as e:
            logger.error(f"子流程执行失败: {e}")
            sub_result = {'subworkflow': node.subworkflow_id, 'status': 'failed', 'error': str(e)}
        
        # 映射输出
        for sub_key, main_key in node.output_mapping.items():
            self._context[main_key] = sub_result.get(sub_key)
        
        return sub_result
    
    def _check_predecessors(self, node_id: str) -> bool:
        """检查前置节点是否完成"""
        for pred in self.graph.predecessors(node_id):
            if pred in self.results:
                if self.results[pred].status == NodeStatus.FAILED:
                    return False
                if self.results[pred].status == NodeStatus.SKIPPED:
                    return False
            # 没有结果说明还没执行（拓扑排序保证顺序，不应出现）
        return True
    
    def _skip_successors(self, node_id: str):
        """跳过后续节点"""
        for successor in nx.descendants(self.graph, node_id):
            if successor not in self.results:
                self.results[successor] = NodeResult(
                    node_id=successor,
                    status=NodeStatus.SKIPPED,
                    error=f"上游节点 {node_id} 失败"
                )
    
    def _build_result(self) -> Dict[str, Any]:
        """构建执行结果"""
        completed = sum(1 for r in self.results.values() if r.status == NodeStatus.COMPLETED)
        failed = sum(1 for r in self.results.values() if r.status == NodeStatus.FAILED)
        skipped = sum(1 for r in self.results.values() if r.status == NodeStatus.SKIPPED)
        
        return {
            'total_nodes': len(self.nodes),
            'completed': completed,
            'failed': failed,
            'skipped': skipped,
            'success': failed == 0,
            'execution_order': self._execution_order,
            'node_results': {
                nid: {
                    'status': r.status.value,
                    'result': r.result,
                    'error': r.error,
                    'duration_ms': r.duration_ms
                }
                for nid, r in self.results.items()
            },
            'context': self._context
        }
    
    def to_json(self) -> str:
        """导出 DAG 为 JSON"""
        data = {
            'nodes': [],
            'edges': []
        }
        
        for node_id, node in self.nodes.items():
            data['nodes'].append({
                'id': node.id,
                'type': node.type.value,
                'name': node.name,
                'config': node.config,
                'true_branch': node.true_branch,
                'false_branch': node.false_branch,
                'max_iterations': node.max_iterations,
                'subworkflow_id': node.subworkflow_id,
                'input_mapping': node.input_mapping,
                'output_mapping': node.output_mapping
            })
        
        for from_id, to_id in self.graph.edges():
            data['edges'].append({'from': from_id, 'to': to_id})
        
        return json.dumps(data, indent=2, ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str, handlers: Dict[str, Callable] = None) -> 'DagEngine':
        """从 JSON 加载 DAG"""
        data = json.loads(json_str)
        engine = cls()
        handlers = handlers or {}
        
        for node_data in data['nodes']:
            node = Node(
                id=node_data['id'],
                type=NodeType(node_data['type']),
                name=node_data.get('name', ''),
                handler=handlers.get(node_data['id']),
                config=node_data.get('config', {}),
                true_branch=node_data.get('true_branch'),
                false_branch=node_data.get('false_branch'),
                max_iterations=node_data.get('max_iterations', 100),
                subworkflow_id=node_data.get('subworkflow_id'),
                input_mapping=node_data.get('input_mapping', {}),
                output_mapping=node_data.get('output_mapping', {})
            )
            engine.add_node(node)
        
        for edge in data['edges']:
            engine.add_edge(edge['from'], edge['to'])
        
        return engine
    
    def save(self, path: str):
        """保存 DAG 到文件"""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(self.to_json())
        logger.info(f"DAG 已保存: {path}")
    
    @classmethod
    def load(cls, path: str, handlers: Dict[str, Callable] = None) -> 'DagEngine':
        """从文件加载 DAG"""
        with open(path, 'r', encoding='utf-8') as f:
            return cls.from_json(f.read(), handlers)


# ============================================================
# DAGExecutor — 兼容 engine.py 的执行器
# 整合 ActionRegistry、ContextManager，支持重试/失败策略
# ============================================================

class DAGValidationError(Exception):
    """DAG 验证错误"""
    pass


class ActionExecutionError(Exception):
    """Action 执行错误"""
    pass


class DAGExecutor:
    """
    DAG 工作流执行器（兼容 engine.py）。

    基于 WorkflowDefinition/NodeDefinition 数据模型，
    整合 ActionRegistry 执行 Action，支持重试和失败策略。
    """

    def __init__(self, registry=None, max_workers: int = 4):
        self.registry = registry
        self.max_workers = max_workers
        self._running = False
        self._cancelled = False

    def validate(self, workflow) -> List[str]:
        """验证 Workflow DAG"""
        errors = workflow.validate_dag()
        if self.registry:
            for node in workflow.nodes:
                if not self.registry.has(node.action):
                    errors.append(f"节点 '{node.id}' 的 Action '{node.action}' 未注册")
        return errors

    def execute(self, workflow, context, on_node_complete=None, on_node_error=None):
        """执行 Workflow DAG"""
        from rpa.models import (
            NodeStatus, WorkflowRunRecord, WorkflowStatus,
        )

        errors = self.validate(workflow)
        if errors:
            raise DAGValidationError(f"DAG 验证失败: {'; '.join(errors)}")

        run_record = WorkflowRunRecord(
            workflow_id=workflow.id,
            status=WorkflowStatus.RUNNING,
            started_at=datetime.now(),
        )

        for key, value in workflow.variables.items():
            context.set(key, value)

        self._running = True
        self._cancelled = False

        try:
            parallel_groups = workflow.get_parallel_groups()
            for group in parallel_groups:
                if self._cancelled:
                    run_record.status = WorkflowStatus.CANCELLED
                    break
                self._execute_group(group, workflow, context, run_record, on_node_complete, on_node_error)
                failed_nodes = {
                    nid for nid, rec in run_record.node_records.items()
                    if rec.status in (NodeStatus.FAILED, NodeStatus.SKIPPED)
                }
                if failed_nodes and workflow.on_failure == "fail":
                    run_record.status = WorkflowStatus.FAILED
                    run_record.error = f"节点失败: {failed_nodes}"
                    break

            if run_record.status == WorkflowStatus.RUNNING:
                all_ok = all(
                    rec.status in (NodeStatus.SUCCESS, NodeStatus.SKIPPED)
                    for rec in run_record.node_records.values()
                )
                run_record.status = WorkflowStatus.COMPLETED if all_ok else WorkflowStatus.FAILED

        except Exception as e:
            run_record.status = WorkflowStatus.FAILED
            run_record.error = str(e)
            logger.error(f"Workflow 执行异常: {e}")
        finally:
            self._running = False
            run_record.completed_at = datetime.now()
            if run_record.started_at:
                run_record.duration_ms = (run_record.completed_at - run_record.started_at).total_seconds() * 1000

        return run_record

    def _execute_group(self, group, workflow, context, run_record, on_node_complete=None, on_node_error=None):
        """并行执行一组节点"""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        if len(group) == 1:
            self._execute_node(group[0], workflow, context, run_record, on_node_complete, on_node_error)
        else:
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(group))) as executor:
                futures = {
                    executor.submit(self._execute_node, nid, workflow, context, run_record, on_node_complete, on_node_error): nid
                    for nid in group
                }
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        logger.error(f"节点执行异常: {e}")

    def _execute_node(self, node_id, workflow, context, run_record, on_node_complete=None, on_node_error=None):
        """执行单个节点"""
        import time
        from rpa.models import NodeStatus

        node = workflow.get_node(node_id)
        if not node:
            logger.error(f"节点 {node_id} 不存在")
            return

        if not self._check_dependencies(node, run_record):
            record = run_record.create_node_record(node_id, node.action)
            record.status = NodeStatus.SKIPPED
            record.completed_at = datetime.now()
            record.error = "依赖节点未完成"
            return

        if node.condition:
            if not self._evaluate_condition(node, context, run_record):
                record = run_record.create_node_record(node_id, node.action)
                record.status = NodeStatus.SKIPPED
                record.completed_at = datetime.now()
                record.error = "条件不满足"
                return

        record = run_record.create_node_record(node_id, node.action)
        record.status = NodeStatus.RUNNING
        record.started_at = datetime.now()

        resolved_params = self._resolve_params(node.params, context)
        max_attempts = node.retry.max_attempts if node.retry else 1

        for attempt in range(1, max_attempts + 1):
            record.retry_count = attempt - 1
            try:
                result = self._run_action(node.action, resolved_params, context)
                if result.status.value == "success":
                    record.status = NodeStatus.SUCCESS
                    record.outputs = result.outputs
                    self._store_outputs(node, result.outputs, context)
                    record.completed_at = datetime.now()
                    record.duration_ms = (record.completed_at - record.started_at).total_seconds() * 1000
                    if on_node_complete:
                        on_node_complete(node_id, record)
                    return

                record.error = result.error
                if attempt < max_attempts and self._should_retry(node, result):
                    record.status = NodeStatus.RETRYING
                    delay = self._get_retry_delay(node.retry, attempt)
                    time.sleep(delay)
                    continue

                self._handle_failure(node, record, context, on_node_error)
                return

            except Exception as e:
                record.error = str(e)
                if attempt < max_attempts and self._should_retry_exception(node, e):
                    record.status = NodeStatus.RETRYING
                    delay = self._get_retry_delay(node.retry, attempt)
                    time.sleep(delay)
                    continue
                self._handle_failure(node, record, context, on_node_error)
                return

        record.status = NodeStatus.FAILED
        record.completed_at = datetime.now()
        if record.started_at:
            record.duration_ms = (record.completed_at - record.started_at).total_seconds() * 1000
        if on_node_error:
            on_node_error(node_id, Exception(record.error or "重试次数用尽"))

    def _run_action(self, action_name, params, context):
        """实例化并执行 Action"""
        from rpa.interfaces import ActionParams, ActionResult, ActionStatus

        if not self.registry:
            return ActionResult(status=ActionStatus.FAILED, error="无 Registry")
        action = self.registry.create(action_name)
        if not action:
            return ActionResult(status=ActionStatus.FAILED, error=f"Action '{action_name}' 未注册")
        action_params = ActionParams(**params)
        try:
            action.validate_params(action_params)
        except ValueError as e:
            return ActionResult(status=ActionStatus.FAILED, error=f"参数校验失败: {e}")
        try:
            result = action.execute(action_params, context)
        finally:
            action.cleanup()
        return result

    def _check_dependencies(self, node, run_record) -> bool:
        from rpa.models import NodeStatus
        for dep_id in node.depends_on:
            dep_record = run_record.get_node_record(dep_id)
            if not dep_record or dep_record.status != NodeStatus.SUCCESS:
                return False
        return True

    def _evaluate_condition(self, node, context, run_record) -> bool:
        if not node.condition:
            return True
        try:
            expression = context.resolve_template(node.condition.expression)
            sandbox = {}
            if hasattr(context, "get_all"):
                sandbox.update(context.get_all())
            safe_builtins = {"True": True, "False": False, "None": None, "len": len, "str": str, "int": int, "float": float, "bool": bool}
            result = eval(str(expression), {"__builtins__": safe_builtins}, sandbox)
            return bool(result)
        except Exception as e:
            logger.error(f"条件评估失败: {e}")
            return False

    def _resolve_params(self, params, context) -> Dict[str, Any]:
        resolved = {}
        for key, value in params.items():
            if isinstance(value, str):
                resolved[key] = context.resolve_template(value)
            elif isinstance(value, dict):
                resolved[key] = self._resolve_params(value, context)
            elif isinstance(value, list):
                resolved[key] = [context.resolve_template(v) if isinstance(v, str) else v for v in value]
            else:
                resolved[key] = value
        return resolved

    def _store_outputs(self, node, outputs, context):
        for var_name, json_path in node.outputs.items():
            value = outputs
            if json_path and json_path != "$":
                path = json_path.lstrip("$").lstrip(".")
                for part in path.split("."):
                    if isinstance(value, dict):
                        value = value.get(part)
                    else:
                        value = None
                        break
            context.set_node_outputs(node.id, {var_name: value})
            context.set(f"{node.id}.{var_name}", value)

    def _should_retry(self, node, result) -> bool:
        if not node.retry:
            return False
        if not node.retry.retry_on:
            return True
        return any(err_type in (result.error or "") for err_type in node.retry.retry_on)

    def _should_retry_exception(self, node, exc) -> bool:
        if not node.retry:
            return False
        if not node.retry.retry_on:
            return True
        return type(exc).__name__ in node.retry.retry_on

    def _get_retry_delay(self, retry, attempt) -> float:
        if not retry:
            return 0
        return retry.get_delay(attempt)

    def _handle_failure(self, node, record, context, on_node_error=None):
        from rpa.models import NodeStatus
        record.status = NodeStatus.FAILED
        record.completed_at = datetime.now()
        if record.started_at:
            record.duration_ms = (record.completed_at - record.started_at).total_seconds() * 1000
        if on_node_error:
            on_node_error(node.id, Exception(record.error or "执行失败"))
        logger.error(f"节点 {node.id} 失败: {record.error}")

    def cancel(self):
        self._cancelled = True

    @property
    def is_running(self) -> bool:
        return self._running


# ============ 使用示例 ============

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    # 定义处理函数
    def search_handler(context, config):
        keywords = context.get('keywords', [])
        print(f"搜索关键词: {keywords}")
        return {'found': len(keywords) * 10}
    
    def filter_handler(context, config):
        print("筛选用户...")
        return {'filtered': 5}
    
    def comment_handler(context, config):
        print("执行评论...")
        return {'commented': 3}
    
    def check_value(context):
        return context.get('score', 0) > 70
    
    # 构建 DAG
    engine = DagEngine()
    
    engine.add_node(Node(id='start', type=NodeType.START, name='开始'))
    engine.add_node(Node(id='search', type=NodeType.ACTION, name='搜索', handler=search_handler))
    engine.add_node(Node(id='filter', type=NodeType.ACTION, name='筛选', handler=filter_handler))
    engine.add_node(Node(id='branch', type=NodeType.CONDITIONAL, name='判断', condition=check_value, true_branch='vip', false_branch='normal'))
    engine.add_node(Node(id='vip', type=NodeType.ACTION, name='VIP路径', handler=comment_handler))
    engine.add_node(Node(id='normal', type=NodeType.ACTION, name='标准路径', handler=comment_handler))
    engine.add_node(Node(id='end', type=NodeType.END, name='结束'))
    
    engine.add_edge('start', 'search')
    engine.add_edge('search', 'filter')
    engine.add_edge('filter', 'branch')
    engine.add_edge('branch', 'vip')
    engine.add_edge('branch', 'normal')
    engine.add_edge('vip', 'end')
    engine.add_edge('normal', 'end')
    
    # 验证
    print("DAG 验证:", engine.validate())
    print("执行顺序:", engine.get_execution_order())
    
    # 执行
    result = engine.execute(context={'keywords': ['python', 'rpa', 'douyin'], 'score': 75})
    
    print(f"\n执行结果:")
    print(f"  成功: {result['completed']}/{result['total_nodes']}")
    print(f"  失败: {result['failed']}")
    
    # 导出
    print(f"\n导出 JSON:")
    print(engine.to_json())
