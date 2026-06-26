"""
RPA 流程编排器 - 第二阶段产出
加载 YAML 模板，构建 DAG，统一调度执行

用法示例：
    from rpa.orchestrator import WorkflowOrchestrator
    
    orchestrator = WorkflowOrchestrator()
    
    # 从 YAML 加载流程
    orchestrator.load_workflow('src/rpa/templates/lead_gen.yaml')
    
    # 执行流程
    result = orchestrator.run('lead_generation', context={
        'keywords': ['python', 'rpa'],
        'platform': 'douyin'
    })
    
    # 查看执行状态
    status = orchestrator.get_status('lead_generation')
"""

import yaml
import json
import logging
import time
from pathlib import Path
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass

from rpa.dag_engine import DagEngine, Node, NodeType

logger = logging.getLogger(__name__)


@dataclass
class WorkflowRun:
    """流程执行实例"""
    workflow_id: str
    run_id: str
    status: str  # pending / running / completed / failed
    context: Dict[str, Any]
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class WorkflowOrchestrator:
    """
    流程编排器
    
    功能：
    - 从 YAML/JSON 加载流程模板
    - 构建并验证 DAG
    - 管理流程执行生命周期
    - 支持并发执行多个流程实例
    """
    
    def __init__(self):
        self.workflows: Dict[str, Dict] = {}          # 流程定义
        self.engines: Dict[str, DagEngine] = {}       # DAG 引擎
        self.handlers: Dict[str, Callable] = {}       # 处理函数注册
        self.runs: Dict[str, WorkflowRun] = {}        # 执行实例
        self._run_counter = 0
    
    def register_handler(self, name: str, handler: Callable):
        """注册处理函数"""
        self.handlers[name] = handler
        logger.debug(f"注册处理函数: {name}")
    
    def register_handlers(self, handlers: Dict[str, Callable]):
        """批量注册处理函数"""
        self.handlers.update(handlers)
    
    def load_workflow(self, path: str) -> str:
        """
        从 YAML 文件加载流程
        
        Args:
            path: YAML 文件路径
        
        Returns:
            workflow_id
        """
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        return self._load_workflow_data(data)
    
    def load_workflow_json(self, json_str: str) -> str:
        """从 JSON 字符串加载流程"""
        data = json.loads(json_str)
        return self._load_workflow_data(data)
    
    def _load_workflow_data(self, data: Dict) -> str:
        """加载流程数据"""
        workflow = data.get('workflow', {})
        workflow_id = workflow.get('id')
        
        if not workflow_id:
            raise ValueError("流程定义缺少 id")
        
        # 存储流程定义
        self.workflows[workflow_id] = data
        
        # 构建 DAG
        engine = self._build_engine(data)
        self.engines[workflow_id] = engine
        
        logger.info(f"加载流程: {workflow_id} ({workflow.get('name', '')})")
        return workflow_id
    
    def _build_engine(self, data: Dict) -> DagEngine:
        """从流程定义构建 DAG 引擎"""
        engine = DagEngine()
        
        nodes_data = data.get('nodes', [])
        edges_data = data.get('edges', [])
        variables = data.get('variables', {})
        config = data.get('config', {})
        
        # 构建节点
        for node_def in nodes_data:
            node = self._create_node(node_def, variables, config)
            engine.add_node(node)
        
        # 构建边
        for edge_def in edges_data:
            from_id = edge_def.get('from')
            to_id = edge_def.get('to')
            attrs = {k: v for k, v in edge_def.items() if k not in ('from', 'to')}
            engine.add_edge(from_id, to_id, **attrs)
        
        return engine
    
    def _create_node(self, node_def: Dict, variables: Dict, config: Dict) -> Node:
        """从定义创建节点"""
        node_type_str = node_def.get('type', 'action')
        try:
            node_type = NodeType(node_type_str)
        except ValueError:
            node_type = NodeType.ACTION
        
        node = Node(
            id=node_def['id'],
            type=node_type,
            name=node_def.get('name', ''),
            config=node_def.get('config', {}),
            true_branch=node_def.get('true_branch'),
            false_branch=node_def.get('false_branch'),
            max_iterations=node_def.get('max_iterations', 100),
            subworkflow_id=node_def.get('subworkflow'),
            input_mapping=node_def.get('input_mapping', {}),
            output_mapping=node_def.get('output_mapping', {})
        )
        
        # 绑定处理函数
        handler_name = node_def.get('handler')
        if handler_name and handler_name in self.handlers:
            node.handler = self.handlers[handler_name]
        elif handler_name:
            logger.warning(f"处理函数未注册: {handler_name} (节点 {node.id})")
        
        # 绑定条件函数
        condition_expr = node_def.get('condition')
        if condition_expr:
            node.condition = self._compile_condition(condition_expr)
        
        # 绑定迭代器
        iterator_ref = node_def.get('iterator')
        if iterator_ref:
            node.iterator = self._compile_iterator(iterator_ref)
        
        return node
    
    def _compile_condition(self, expr: str) -> Callable:
        """编译条件表达式"""
        def condition_func(context):
            try:
                # 安全的表达式求值
                item = context.get('item', {})
                return eval(expr, {"__builtins__": {}}, {
                    'item': item,
                    'context': context,
                    'variables': context.get('variables', {})
                })
            except Exception as e:
                logger.error(f"条件求值失败: {expr} - {e}")
                return False
        return condition_func
    
    def _compile_iterator(self, ref: str) -> Callable:
        """编译迭代器引用"""
        def iterator_func(context):
            try:
                # 支持 "variables.keywords" 格式
                parts = ref.split('.')
                value = context
                for part in parts:
                    if isinstance(value, dict):
                        value = value.get(part, [])
                    else:
                        return []
                return value if isinstance(value, list) else []
            except Exception as e:
                logger.error(f"迭代器解析失败: {ref} - {e}")
                return []
        return iterator_func
    
    def run(self, workflow_id: str, context: Dict[str, Any] = None) -> str:
        """
        执行流程
        
        Args:
            workflow_id: 流程ID
            context: 执行上下文
        
        Returns:
            run_id
        """
        if workflow_id not in self.engines:
            raise ValueError(f"流程不存在: {workflow_id}")
        
        # 创建执行实例
        self._run_counter += 1
        run_id = f"run_{int(time.time())}_{self._run_counter}"
        
        workflow_data = self.workflows[workflow_id]
        variables = workflow_data.get('variables', {})
        
        # 合并上下文
        full_context = {
            'variables': {**variables, **(context or {})},
            **(context or {})
        }
        
        run = WorkflowRun(
            workflow_id=workflow_id,
            run_id=run_id,
            status='running',
            context=full_context,
            started_at=datetime.now().isoformat()
        )
        self.runs[run_id] = run
        
        logger.info(f"开始执行流程: {workflow_id} (run={run_id})")
        
        try:
            # 创建新的引擎实例执行
            engine = self.engines[workflow_id]
            result = engine.execute(full_context)
            
            run.status = 'completed' if result.get('success') else 'failed'
            run.result = result
            run.completed_at = datetime.now().isoformat()
            
            logger.info(f"流程执行完成: {workflow_id} - {run.status}")
            
        except Exception as e:
            run.status = 'failed'
            run.error = str(e)
            run.completed_at = datetime.now().isoformat()
            logger.error(f"流程执行异常: {workflow_id} - {e}")
        
        return run_id
    
    def get_status(self, run_id: str) -> Optional[Dict[str, Any]]:
        """获取执行状态"""
        run = self.runs.get(run_id)
        if not run:
            return None
        
        return {
            'run_id': run.run_id,
            'workflow_id': run.workflow_id,
            'status': run.status,
            'started_at': run.started_at,
            'completed_at': run.completed_at,
            'error': run.error,
            'result_summary': {
                'completed': run.result.get('completed', 0),
                'failed': run.result.get('failed', 0),
                'total': run.result.get('total_nodes', 0)
            } if run.result else None
        }
    
    def list_workflows(self) -> List[Dict[str, str]]:
        """列出所有已加载的流程"""
        return [
            {
                'id': wf_id,
                'name': data.get('workflow', {}).get('name', ''),
                'version': data.get('workflow', {}).get('version', ''),
                'nodes': len(data.get('nodes', []))
            }
            for wf_id, data in self.workflows.items()
        ]
    
    def list_runs(self, workflow_id: str = None) -> List[Dict]:
        """列出执行实例"""
        runs = self.runs.values()
        if workflow_id:
            runs = [r for r in runs if r.workflow_id == workflow_id]
        
        return [
            {
                'run_id': r.run_id,
                'workflow_id': r.workflow_id,
                'status': r.status,
                'started_at': r.started_at,
                'completed_at': r.completed_at
            }
            for r in runs
        ]
    
    def export_workflow(self, workflow_id: str, path: str):
        """导出流程为 YAML"""
        if workflow_id not in self.workflows:
            raise ValueError(f"流程不存在: {workflow_id}")
        
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(
                self.workflows[workflow_id],
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False
            )
        
        logger.info(f"流程已导出: {path}")
    
    def get_dag_visualization(self, workflow_id: str) -> str:
        """获取 DAG 可视化（文本格式）"""
        if workflow_id not in self.engines:
            raise ValueError(f"流程不存在: {workflow_id}")
        
        engine = self.engines[workflow_id]
        lines = ["=== DAG 结构 ==="]
        
        for layer_idx, group in enumerate(engine.get_parallel_groups()):
            nodes_str = ', '.join(
                f"{nid} ({engine.nodes[nid].type.value})"
                for nid in group
            )
            lines.append(f"Layer {layer_idx}: [{nodes_str}]")
        
        lines.append("\n=== 依赖关系 ===")
        for from_id, to_id in engine.graph.edges():
            lines.append(f"  {from_id} -> {to_id}")
        
        return '\n'.join(lines)


# ============================================================
# 内置处理函数
# ============================================================

def default_search_handler(context: Dict, config: Dict) -> Any:
    """默认搜索处理函数 — 通过适配器执行"""
    keyword = config.get('keyword', '')
    platform = config.get('platform', '')
    count = config.get('count', 10)
    logger.info(f"搜索: platform={platform}, keyword={keyword}")
    try:
        from rpa.adapters.registry import get_adapter_registry
        import asyncio
        registry = get_adapter_registry()
        adapter = registry.create(platform)
        if adapter:
            async def _do_search():
                await adapter.setup()
                try:
                    result = await adapter.search_content(keyword, count=count)
                    return result.data if result.success else {'found': 0, 'error': result.error}
                finally:
                    await adapter.teardown()
            return asyncio.run(_do_search())
        logger.warning(f"未注册的适配器: {platform}")
        return {'found': 0, 'keyword': keyword}
    except Exception as e:
        logger.error(f"搜索失败: {e}")
        return {'found': 0, 'keyword': keyword, 'error': str(e)}

def default_filter_handler(context: Dict, config: Dict) -> Any:
    """默认筛选处理函数（占位）"""
    min_score = config.get('min_score', 0)
    logger.info(f"筛选: min_score={min_score}")
    return {'filtered': 0}

def default_comment_handler(context: Dict, config: Dict) -> Any:
    """默认评论处理函数（占位）"""
    logger.info("执行评论")
    return {'commented': 0}

def default_export_handler(context: Dict, config: Dict) -> Any:
    """默认导出处理函数（占位）"""
    path = config.get('path', 'data/exports/')
    logger.info(f"导出到: {path}")
    return {'exported': 0}


# 默认处理函数注册表
DEFAULT_HANDLERS = {
    'handlers.search_keyword': default_search_handler,
    'handlers.filter_users': default_filter_handler,
    'handlers.standard_engagement': default_comment_handler,
    'handlers.post_comment': default_comment_handler,
    'handlers.send_dm': default_comment_handler,
    'handlers.follow_user': default_comment_handler,
    'handlers.collect_results': default_export_handler,
    'handlers.export_leads': default_export_handler,
}


# ============ 使用示例 ============

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    # 创建编排器
    orchestrator = WorkflowOrchestrator()
    
    # 注册默认处理函数
    orchestrator.register_handlers(DEFAULT_HANDLERS)
    
    # 加载流程模板
    template_path = Path(__file__).parent / 'templates' / 'lead_gen.yaml'
    if template_path.exists():
        wf_id = orchestrator.load_workflow(str(template_path))
        print(f"加载流程: {wf_id}")
        
        # 查看流程列表
        print("\n已加载流程:")
        for wf in orchestrator.list_workflows():
            print(f"  - {wf['id']}: {wf['name']} ({wf['nodes']} 节点)")
        
        # 执行流程
        run_id = orchestrator.run(wf_id, context={
            'keywords': ['python', 'rpa', 'automation'],
            'platform': 'douyin'
        })
        print(f"\n执行ID: {run_id}")
        
        # 查看状态
        status = orchestrator.get_status(run_id)
        print(f"状态: {json.dumps(status, indent=2, ensure_ascii=False)}")
        
        # DAG 可视化
        print(f"\n{orchestrator.get_dag_visualization(wf_id)}")
    else:
        print(f"模板文件不存在: {template_path}")
