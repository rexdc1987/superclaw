"""
SuperClaw RPA 引擎 - 单元测试

覆盖：
- ActionRegistry 注册/发现/实例化
- ContextManager 变量读写/模板解析
- DAGExecutor 验证/拓扑排序/执行
- WorkflowEngine 完整流程
- 内置 Actions
"""

import json
import os
import sys
import time
import pytest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

# 添加 src 到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rpa.actions import ActionRegistry, get_registry, init_registry
from rpa.actions.builtin import (
    ConditionAction,
    DelayAction,
    GetVarAction,
    HttpGetAction,
    LogAction,
    SetVarAction,
    TransformAction,
    register_builtin_actions,
)
from rpa.context import ContextManager
from rpa.dag_engine import DAGExecutor, DAGValidationError
from rpa.engine import WorkflowEngine
from rpa.hongguo.engine import TaskEngine
from rpa.hongguo.comment_gen import CommentGenerationError, CommentGenerator
from rpa.hongguo import device as hongguo_device
from rpa.hongguo.operations import HongguoOperations
from rpa.dashboard.routes_hongguo import (
    TaskUpdate,
    delete_task,
    _latest_screenshot_file,
    _serialize_task,
    latest_screenshot,
    list_logs,
    list_records,
    list_tasks,
    update_task,
)
from services.ai_config_service import public_ai_settings
from rpa.interfaces import (
    ActionParams,
    ActionResult,
    ActionStatus,
    BaseAction,
)
from rpa.models import (
    FailureStrategy,
    NodeDefinition,
    NodeStatus,
    RetryConfig,
    WorkflowDefinition,
    WorkflowRunRecord,
    WorkflowStatus,
    create_sample_workflow,
)


# ============================================================
# 测试 ActionRegistry
# ============================================================

class TestActionRegistry:
    """Action 注册中心测试"""

    def setup_method(self):
        self.registry = ActionRegistry()

    def test_register_and_get(self):
        """注册后能通过 name 查找"""
        self.registry.register(LogAction)
        assert self.registry.has("log")
        assert self.registry.get("log") is LogAction

    def test_register_with_override_name(self):
        """用覆盖名称注册"""
        self.registry.register(LogAction, name="my_log")
        assert self.registry.has("my_log")
        assert self.registry.get("my_log") is LogAction

    def test_create_instance(self):
        """创建 Action 实例"""
        self.registry.register(LogAction)
        action = self.registry.create("log")
        assert action is not None
        assert isinstance(action, LogAction)
        assert action.name == "log"

    def test_create_nonexistent(self):
        """创建不存在的 Action 返回 None"""
        assert self.registry.create("nonexistent") is None

    def test_unregister(self):
        """注销 Action"""
        self.registry.register(LogAction)
        assert self.registry.unregister("log") is True
        assert self.registry.has("log") is False
        assert self.registry.unregister("nonexistent") is False

    def test_list_actions(self):
        """列出所有 Action"""
        self.registry.register(LogAction)
        self.registry.register(DelayAction)
        actions = self.registry.list_actions()
        assert len(actions) == 2
        names = [a["name"] for a in actions]
        assert "log" in names
        assert "delay" in names

    def test_register_no_name_raises(self):
        """没有 name 属性的类注册时抛异常"""
        class BadAction(BaseAction):
            def execute(self, params, context):
                pass

        with pytest.raises(ValueError, match="未定义 name"):
            self.registry.register(BadAction)

    def test_register_override_warning(self):
        """重复注册覆盖时发出警告"""
        self.registry.register(LogAction)
        self.registry.register(LogAction)  # 覆盖，不报错


# ============================================================
# 测试 ContextManager
# ============================================================

class TestContextManager:
    """上下文管理器测试"""

    def setup_method(self):
        self.ctx = ContextManager()

    def test_set_and_get(self):
        """设置和获取变量"""
        self.ctx.set("name", "test")
        assert self.ctx.get("name") == "test"

    def test_get_default(self):
        """获取不存在的变量返回默认值"""
        assert self.ctx.get("nonexistent", "default") == "default"

    def test_node_outputs(self):
        """节点输出读写"""
        self.ctx.set_node_outputs("fetch_user", {"email": "test@example.com"})
        outputs = self.ctx.get_node_outputs("fetch_user")
        assert outputs["email"] == "test@example.com"

    def test_resolve_template_variable(self):
        """解析模板变量 {{var}}"""
        self.ctx.set("name", "Alice")
        result = self.ctx.resolve_template("Hello {{name}}!")
        assert result == "Hello Alice!"

    def test_resolve_template_dollar(self):
        """解析模板变量 ${var}"""
        self.ctx.set("count", 42)
        result = self.ctx.resolve_template("Count: ${count}")
        assert result == "Count: 42"

    def test_resolve_template_node_output(self):
        """解析节点输出引用"""
        self.ctx.set_node_outputs("step_1", {"data": "hello"})
        result = self.ctx.resolve_template("{{step_1.data}}")
        assert result == "hello"

    def test_resolve_template_pure_reference(self):
        """纯模板引用保留原始类型"""
        self.ctx.set("count", 42)
        result = self.ctx.resolve_template("{{count}}")
        assert result == 42
        assert isinstance(result, int)

    def test_resolve_template_env(self):
        """解析环境变量引用"""
        os.environ["TEST_RPA_VAR"] = "env_value"
        try:
            result = self.ctx.resolve_template("{{env.TEST_RPA_VAR}}")
            assert result == "env_value"
        finally:
            del os.environ["TEST_RPA_VAR"]

    def test_get_all(self):
        """获取所有变量快照"""
        self.ctx.set("a", 1)
        self.ctx.set("b", 2)
        self.ctx.set_node_outputs("node1", {"out": 3})
        all_vars = self.ctx.get_all()
        assert all_vars["a"] == 1
        assert all_vars["b"] == 2
        assert all_vars["node1.out"] == 3

    def test_clear(self):
        """清空所有变量"""
        self.ctx.set("x", 1)
        self.ctx.clear()
        assert self.ctx.get("x") is None


# ============================================================
# 测试内置 Actions
# ============================================================

class TestBuiltinActions:
    """内置 Action 测试"""

    def setup_method(self):
        self.ctx = ContextManager()

    def test_log_action(self):
        """日志 Action"""
        action = LogAction()
        params = ActionParams(message="Hello", level="info")
        result = action.execute(params, self.ctx)
        assert result.status == ActionStatus.SUCCESS
        assert result.outputs["logged"] is True

    def test_delay_action(self):
        """延时 Action"""
        action = DelayAction()
        params = ActionParams(seconds=0.1)
        result = action.execute(params, self.ctx)
        assert result.status == ActionStatus.SUCCESS
        assert result.outputs["waited_seconds"] == 0.1

    def test_delay_action_validation(self):
        """延时 Action 参数校验"""
        action = DelayAction()
        params = ActionParams(seconds=-1)
        with pytest.raises(ValueError, match="非负数"):
            action.validate_params(params)

    def test_set_var_action(self):
        """设置变量 Action"""
        action = SetVarAction()
        params = ActionParams(name="my_var", value="test_value")
        result = action.execute(params, self.ctx)
        assert result.status == ActionStatus.SUCCESS
        assert self.ctx.get("my_var") == "test_value"

    def test_set_var_action_empty_name(self):
        """空变量名校验"""
        action = SetVarAction()
        params = ActionParams(name="", value="test")
        result = action.execute(params, self.ctx)
        assert result.status == ActionStatus.FAILED

    def test_get_var_action(self):
        """获取变量 Action"""
        self.ctx.set("existing", "value")
        action = GetVarAction()
        params = ActionParams(name="existing")
        result = action.execute(params, self.ctx)
        assert result.status == ActionStatus.SUCCESS
        assert result.outputs["value"] == "value"

    def test_get_var_action_with_default(self):
        """获取不存在的变量返回默认值"""
        action = GetVarAction()
        params = ActionParams(name="missing", default="fallback")
        result = action.execute(params, self.ctx)
        assert result.outputs["value"] == "fallback"

    def test_condition_action_true(self):
        """条件判断 - 为真"""
        self.ctx.set("role", "admin")
        action = ConditionAction()
        params = ActionParams(expression="{{role}} == 'admin'", true_value="yes", false_value="no")
        result = action.execute(params, self.ctx)
        assert result.status == ActionStatus.SUCCESS
        assert result.outputs["result"] is True
        assert result.outputs["value"] == "yes"

    def test_condition_action_false(self):
        """条件判断 - 为假"""
        self.ctx.set("role", "user")
        action = ConditionAction()
        params = ActionParams(expression="{{role}} == 'admin'")
        result = action.execute(params, self.ctx)
        assert result.status == ActionStatus.SUCCESS
        assert result.outputs["result"] is False

    def test_transform_json_parse(self):
        """JSON 解析"""
        action = TransformAction()
        params = ActionParams(operation="json_parse", input='{"key": "value"}')
        result = action.execute(params, self.ctx)
        assert result.status == ActionStatus.SUCCESS
        assert result.outputs["result"]["key"] == "value"

    def test_transform_json_dumps(self):
        """JSON 序列化"""
        action = TransformAction()
        params = ActionParams(operation="json_dumps", input={"key": "value"})
        result = action.execute(params, self.ctx)
        assert result.status == ActionStatus.SUCCESS
        assert '"key"' in result.outputs["result"]

    def test_transform_extract(self):
        """JSONPath 提取"""
        action = TransformAction()
        data = {"user": {"name": "Alice", "age": 30}}
        params = ActionParams(operation="extract", input=data, path="$.user.name")
        result = action.execute(params, self.ctx)
        assert result.outputs["result"] == "Alice"


# ============================================================
# 测试 DAGExecutor
# ============================================================

class TestDAGExecutor:
    """DAG 执行器测试"""

    def setup_method(self):
        self.registry = ActionRegistry()
        self.registry.register(LogAction)
        self.registry.register(SetVarAction)
        self.registry.register(GetVarAction)
        self.registry.register(ConditionAction)
        self.registry.register(DelayAction)
        self.registry.register(TransformAction)
        self.executor = DAGExecutor(registry=self.registry)

    def test_validate_success(self):
        """验证通过"""
        workflow = WorkflowDefinition(
            id="test",
            name="Test",
            nodes=[
                NodeDefinition(id="a", action="log", params={"message": "hi"}),
            ],
        )
        errors = self.executor.validate(workflow)
        assert errors == []

    def test_validate_unregistered_action(self):
        """验证未注册的 Action"""
        workflow = WorkflowDefinition(
            id="test",
            name="Test",
            nodes=[
                NodeDefinition(id="a", action="nonexistent", params={}),
            ],
        )
        errors = self.executor.validate(workflow)
        assert len(errors) > 0
        assert "nonexistent" in errors[0]

    def test_validate_duplicate_ids(self):
        """验证重复节点 ID"""
        workflow = WorkflowDefinition(
            id="test",
            name="Test",
            nodes=[
                NodeDefinition(id="a", action="log", params={"message": "1"}),
                NodeDefinition(id="a", action="log", params={"message": "2"}),
            ],
        )
        errors = workflow.validate_dag()
        assert any("重复" in e for e in errors)

    def test_validate_cycle(self):
        """验证循环依赖"""
        workflow = WorkflowDefinition(
            id="test",
            name="Test",
            nodes=[
                NodeDefinition(id="a", action="log", params={"message": "1"}, depends_on=["b"]),
                NodeDefinition(id="b", action="log", params={"message": "2"}, depends_on=["a"]),
            ],
        )
        errors = workflow.validate_dag()
        assert any("循环" in e for e in errors)

    def test_topological_sort(self):
        """拓扑排序"""
        workflow = WorkflowDefinition(
            id="test",
            name="Test",
            nodes=[
                NodeDefinition(id="a", action="log", params={"message": "1"}),
                NodeDefinition(id="b", action="log", params={"message": "2"}, depends_on=["a"]),
                NodeDefinition(id="c", action="log", params={"message": "3"}, depends_on=["a"]),
                NodeDefinition(id="d", action="log", params={"message": "4"}, depends_on=["b", "c"]),
            ],
        )
        order = workflow.topological_sort()
        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")
        assert order.index("b") < order.index("d")
        assert order.index("c") < order.index("d")

    def test_parallel_groups(self):
        """并行分组"""
        workflow = WorkflowDefinition(
            id="test",
            name="Test",
            nodes=[
                NodeDefinition(id="a", action="log", params={"message": "1"}),
                NodeDefinition(id="b", action="log", params={"message": "2"}, depends_on=["a"]),
                NodeDefinition(id="c", action="log", params={"message": "3"}, depends_on=["a"]),
            ],
        )
        groups = workflow.get_parallel_groups()
        assert groups == [["a"], ["b", "c"]]

    def test_execute_simple_workflow(self):
        """执行简单线性工作流"""
        workflow = WorkflowDefinition(
            id="test",
            name="Test",
            nodes=[
                NodeDefinition(id="s1", action="set_var", params={"name": "x", "value": 10}),
                NodeDefinition(id="s2", action="set_var", params={"name": "y", "value": 20}, depends_on=["s1"]),
            ],
        )
        context = ContextManager()
        record = self.executor.execute(workflow, context)
        assert record.status == WorkflowStatus.COMPLETED
        assert record.node_records["s1"].status == NodeStatus.SUCCESS
        assert record.node_records["s2"].status == NodeStatus.SUCCESS

    def test_execute_with_failure_skip(self):
        """失败节点被跳过"""
        # 注册一个会失败的 Action
        class FailAction(BaseAction):
            name = "fail"
            def execute(self, params, context):
                return ActionResult(status=ActionStatus.FAILED, error="boom")

        self.registry.register(FailAction)

        workflow = WorkflowDefinition(
            id="test",
            name="Test",
            nodes=[
                NodeDefinition(id="s1", action="fail", params={}, on_failure=FailureStrategy.SKIP),
                NodeDefinition(id="s2", action="set_var", params={"name": "ok", "value": True}),
            ],
        )
        context = ContextManager()
        record = self.executor.execute(workflow, context)
        assert record.node_records["s1"].status == NodeStatus.FAILED
        # s2 不依赖 s1，应该仍然执行
        assert record.node_records["s2"].status == NodeStatus.SUCCESS

    def test_cancel(self):
        """取消执行"""
        assert self.executor.is_running is False
        self.executor.cancel()  # 不应该报错


# ============================================================
# 测试 WorkflowEngine
# ============================================================

class TestWorkflowEngine:
    """Workflow 引擎集成测试"""

    def setup_method(self):
        self.registry = ActionRegistry()
        self.registry.register(LogAction)
        self.registry.register(SetVarAction)
        self.registry.register(TransformAction)
        self.engine = WorkflowEngine(registry=self.registry, auto_init=False)

    def test_load_and_list(self):
        """加载和列出 Workflow"""
        wf_def = {
            "id": "wf1",
            "name": "Test",
            "nodes": [{"id": "s1", "action": "log", "params": {"message": "hi"}}],
        }
        wf_id = self.engine.load_workflow(wf_def)
        assert wf_id == "wf1"
        
        workflows = self.engine.list_workflows()
        assert len(workflows) == 1
        assert workflows[0]["id"] == "wf1"

    def test_load_invalid_workflow(self):
        """加载无效 Workflow 抛异常"""
        wf_def = {
            "id": "wf_bad",
            "name": "Bad",
            "nodes": [{"id": "s1", "action": "nonexistent", "params": {}}],
        }
        with pytest.raises(DAGValidationError):
            self.engine.load_workflow(wf_def)

    def test_execute_workflow(self):
        """执行 Workflow 并查询状态"""
        wf_def = {
            "id": "wf_exec",
            "name": "Exec Test",
            "nodes": [
                {"id": "s1", "action": "set_var", "params": {"name": "x", "value": 42}},
                {"id": "s2", "action": "log", "params": {"message": "done"}, "depends_on": ["s1"]},
            ],
        }
        self.engine.load_workflow(wf_def)
        run_id = self.engine.execute("wf_exec")
        
        status = self.engine.get_status(run_id)
        assert status["status"] == "completed"
        assert status["node_count"] == 2

    def test_execute_with_inputs(self):
        """带输入参数执行"""
        wf_def = {
            "id": "wf_input",
            "name": "Input Test",
            "nodes": [
                {"id": "s1", "action": "set_var", "params": {"name": "result", "value": "{{input.value}}"}},
            ],
        }
        self.engine.load_workflow(wf_def)
        run_id = self.engine.execute("wf_input", inputs={"value": "hello"})
        
        record = self.engine.get_run_record(run_id)
        assert record.status == WorkflowStatus.COMPLETED

    def test_callback_events(self):
        """事件回调"""
        completed_nodes = []
        
        self.engine.on_node_complete(lambda nid, rec: completed_nodes.append(nid))
        
        wf_def = {
            "id": "wf_cb",
            "name": "Callback Test",
            "nodes": [
                {"id": "s1", "action": "log", "params": {"message": "test"}},
            ],
        }
        self.engine.load_workflow(wf_def)
        self.engine.execute("wf_cb")
        
        assert "s1" in completed_nodes

    def test_list_runs(self):
        """列出运行记录"""
        wf_def = {
            "id": "wf_runs",
            "name": "Runs Test",
            "nodes": [{"id": "s1", "action": "log", "params": {"message": "hi"}}],
        }
        self.engine.load_workflow(wf_def)
        self.engine.execute("wf_runs")
        self.engine.execute("wf_runs")
        
        runs = self.engine.list_runs(workflow_id="wf_runs")
        assert len(runs) == 2

    def test_remove_workflow(self):
        """移除 Workflow"""
        wf_def = {
            "id": "wf_rm",
            "name": "Remove Test",
            "nodes": [{"id": "s1", "action": "log", "params": {"message": "hi"}}],
        }
        self.engine.load_workflow(wf_def)
        assert self.engine.remove_workflow("wf_rm") is True
        assert self.engine.get_workflow("wf_rm") is None

    def test_sample_workflow(self):
        """示例 Workflow 结构测试"""
        wf = create_sample_workflow()
        assert wf.id == "sample_workflow"
        assert len(wf.nodes) == 3
        errors = wf.validate_dag()
        assert errors == []
        order = wf.topological_sort()
        assert order == ["step_1", "step_2", "step_3"]


# ============================================================
# 测试 RetryConfig
# ============================================================

class TestRetryConfig:
    """重试配置测试"""

    def test_default_values(self):
        """默认值"""
        config = RetryConfig()
        assert config.max_attempts == 3
        assert config.delay_seconds == 5.0
        assert config.backoff_multiplier == 2.0

    def test_delay_calculation(self):
        """指数退避计算"""
        config = RetryConfig(delay_seconds=1.0, backoff_multiplier=2.0)
        assert config.get_delay(1) == 1.0
        assert config.get_delay(2) == 2.0
        assert config.get_delay(3) == 4.0


class TestHongguoPlaybackHeuristics:
    def test_launch_app_accepts_ready_foreground_package(self):
        class DummyDevice:
            def __init__(self):
                self.started = 0
                self.stopped = 0

            def app_stop(self, package):
                self.stopped += 1

            def app_start(self, package):
                self.started += 1

            def shell(self, command):
                return ""

            def app_current(self):
                return {"package": "com.phoenix.read"}

            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" resource-id="com.phoenix.read:id/hds" clickable="true" bounds="[24,1][876,73]" />'
                    '<node package="com.phoenix.read" text="首页" bounds="[71,1529][135,1572]" />'
                    '<node package="com.phoenix.read" text="剧场" bounds="[245,1529][309,1572]" />'
                    '<node package="com.phoenix.read" text="我的" bounds="[765,1529][829,1572]" />'
                )

            def window_size(self):
                return (1080, 1920)

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_close_popups"):
            assert ops.launch_app() is True

    def test_wait_app_ready_ignores_launcher_search_without_hongguo_nodes(self):
        class DummyDevice:
            def __init__(self):
                self.calls = 0

            def app_current(self):
                return {"package": "com.phoenix.read"}

            def dump_hierarchy(self):
                self.calls += 1
                return (
                    '<node package="app.lawnchair" text="搜索" />'
                    '<node package="app.lawnchair" text="红果免费短剧" />'
                    '<node package="app.lawnchair" text="Play 商店" />'
                )

            def window_size(self):
                return (900, 1600)

            def shell(self, command):
                return ""

        ops = HongguoOperations(DummyDevice())
        with patch("rpa.hongguo.operations.time.sleep"):
            assert ops._wait_app_ready(timeout=0.01) is False

    def test_launch_app_retries_when_not_ready(self):
        class DummyDevice:
            def __init__(self):
                self.started = 0
                self.stopped = 0

            def app_stop(self, package):
                self.stopped += 1

            def app_start(self, package):
                self.started += 1

            def shell(self, command):
                return ""

            def app_current(self):
                return {"package": "other.app"}

            def dump_hierarchy(self):
                return ""

            def window_size(self):
                return (1080, 1920)

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_wait_app_ready", return_value=False):
            with patch.object(ops, "_close_popups"):
                with patch("rpa.hongguo.operations.time.sleep"):
                    assert ops.launch_app() is False

    def test_launch_app_rejects_blank_foreground_without_ready_marker(self):
        class DummyDevice:
            def __init__(self):
                self.started = 0
                self.stopped = 0

            def app_stop(self, package):
                self.stopped += 1

            def app_start(self, package):
                self.started += 1

            def shell(self, command):
                return ""

            def app_current(self):
                return {"package": "com.phoenix.read"}

            def dump_hierarchy(self):
                return ""

            def window_size(self):
                return (1080, 1920)

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_wait_app_ready", return_value=False) as wait_ready:
            with patch.object(ops, "_close_popups") as close_popups:
                with patch("rpa.hongguo.operations.time.sleep"):
                    assert ops.launch_app() is False

        assert wait_ready.call_count == 3
        close_popups.assert_not_called()

    def test_launch_app_accepts_foreground_splash_with_nonblank_ui(self):
        class DummyDevice:
            def __init__(self):
                self.started = 0
                self.stopped = 0

            def app_stop(self, package):
                self.stopped += 1

            def app_start(self, package):
                self.started += 1

            def shell(self, command):
                return ""

            def app_current(self):
                return {
                    "package": "com.phoenix.read",
                    "activity": "com.dragon.read.pages.splash.SplashActivity",
                }

            def dump_hierarchy(self):
                return '<hierarchy>' + ('<node text="" bounds="[0,0][900,1600]" />' * 80) + "</hierarchy>"

            def window_size(self):
                return (900, 1600)

            def __call__(self, **kwargs):
                selector = MagicMock()
                selector.exists.return_value = False
                return selector

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_wait_app_ready", return_value=False) as wait_ready:
            with patch("rpa.hongguo.operations.time.sleep"):
                assert ops.launch_app() is True

        assert wait_ready.call_count == 2
        assert ops.d.started == 1

    def test_launch_app_accepts_foreground_splash_even_when_xml_is_empty_after_start(self):
        class DummyDevice:
            def __init__(self):
                self.started = 0
                self.stopped = 0

            def app_stop(self, package):
                self.stopped += 1

            def app_start(self, package):
                self.started += 1

            def shell(self, command):
                return ""

            def app_current(self):
                return {
                    "package": "com.phoenix.read",
                    "activity": "com.dragon.read.pages.splash.SplashActivity",
                }

            def dump_hierarchy(self):
                return ""

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_wait_app_ready", return_value=False):
            with patch("rpa.hongguo.operations.time.sleep"):
                assert ops.launch_app() is True

        assert ops.d.started == 1

    def test_launch_app_accepts_foreground_short_series_activity(self):
        class DummyDevice:
            def __init__(self):
                self.started = 0
                self.stopped = 0

            def app_stop(self, package):
                self.stopped += 1

            def app_start(self, package):
                self.started += 1

            def shell(self, command):
                return ""

            def app_current(self):
                return {
                    "package": "com.phoenix.read",
                    "activity": "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity",
                }

            def dump_hierarchy(self):
                return 'text="第12集" text="选集" text="倍速"'

            def window_size(self):
                return (1080, 1920)

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_close_popups"):
            with patch("rpa.hongguo.operations.time.sleep"):
                assert ops.launch_app() is True

        assert ops.d.stopped == 0
        assert ops.d.started == 0

    def test_close_popups_dismisses_douyin_association_with_back(self):
        class DummySelector:
            def exists(self, timeout=0):
                return False

        class DummyDevice:
            def __init__(self):
                self.pressed = []

            def dump_hierarchy(self):
                return 'text="关联抖音账号" text="授权后可同步信息"'

            def window_size(self):
                return (1080, 1920)

            def __call__(self, **kwargs):
                return DummySelector()

            def press(self, key):
                self.pressed.append(key)

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch("rpa.hongguo.operations.time.sleep"):
            ops._close_popups()

        assert "back" in device.pressed

    def test_blocking_popup_visible_detects_promo_card(self):
        ops = HongguoOperations(MagicMock(window_size=MagicMock(return_value=(1080, 1920))))
        xml = (
            '<node text="聚宝仙盆之杂灵根才是真BOSS" bounds="[120,360][960,520]" />'
            '<node text="爆剧续作来袭 凡身踏破天骄会" bounds="[180,740][900,820]" />'
            '<node text="点击观看" bounds="[330,1080][750,1180]" />'
        )

        assert ops._blocking_popup_visible(xml) is True

    def test_close_popups_dismisses_promo_card_without_clicking_watch_cta(self):
        class DummySelector:
            def exists(self, timeout=0):
                return False

        class DummyDevice:
            def __init__(self):
                self.clicks = []
                self.pressed = []
                self.closed = False

            def dump_hierarchy(self):
                if self.closed:
                    return 'text="剧场" text="搜索"'
                return (
                    '<node text="聚宝仙盆之杂灵根才是真BOSS" bounds="[120,360][960,520]" />'
                    '<node text="点击观看" bounds="[330,1080][750,1180]" />'
                )

            def window_size(self):
                return (1080, 1920)

            def __call__(self, **kwargs):
                return DummySelector()

            def click(self, x, y):
                self.clicks.append((x, y))
                self.closed = True

            def press(self, key):
                self.pressed.append(key)

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch("rpa.hongguo.operations.time.sleep"):
            ops._close_popups()

        assert device.clicks
        assert device.clicks[0] != (540, 1130)
        assert "back" not in device.pressed

    def test_get_current_episode_prefers_playing_context(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return 'text="第3集" text="第12集" text="正在播放第3集"'

            def window_size(self):
                return (1080, 1920)

        ops = HongguoOperations(DummyDevice())
        assert ops.get_current_episode() == 3

    def test_get_total_episodes_uses_max_hint(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return 'text="更新至12集" text="第1集" text="第12集"'

            def window_size(self):
                return (1080, 1920)

        ops = HongguoOperations(DummyDevice())
        assert ops.get_total_episodes() == 12

    def test_get_current_episode_uses_playback_header(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    'resource-id="com.phoenix.read:id/cdi" '
                    'text="\u7b2c1\u96c6" package="com.phoenix.read" bounds="[88,48][636,136]"'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops.get_current_episode() == 1

    def test_get_current_episode_ignores_total_episode_hint(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return 'text="观看完整短剧·全105集" text="第105集" text="选集"'

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops.get_current_episode() == 0
        assert ops.get_total_episodes() == 105

    def test_reserved_drama_page_is_not_playback_or_episode(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    'resource-id="com.phoenix.read:id/cdi" '
                    'text="@17K剧场" text="第5季" '
                    'text="一品布衣5:入蜀篇 · 预计8月上线" text="立即预约"'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._playback_visible() is False
        assert ops.get_current_episode() == 0
        assert ops.get_total_episodes() == 0
        assert ops._current_playing_title() == ""

    def test_feed_ad_is_not_playback_and_can_be_skipped(self):
        class DummyDevice:
            def __init__(self):
                self.swipes = []
                self.ad_visible = True

            def dump_hierarchy(self):
                if not self.ad_visible:
                    return 'text="第8集" text="选集" text="评论"'
                return (
                    'text="广告" text="查看详情" text="点击进入直播间" '
                    'text="灵妖劫" text="上滑继续观看短剧"'
                )

            def window_size(self):
                return (900, 1600)

            def swipe(self, x1, y1, x2, y2, duration=0.4):
                self.swipes.append((x1, y1, x2, y2, duration))
                self.ad_visible = False

            def press(self, key):
                pass

        device = DummyDevice()
        ops = HongguoOperations(device)
        assert ops._playback_visible() is False
        assert ops.skip_feed_ad_if_visible() is True
        assert device.swipes
        assert device.swipes[0][1] > device.swipes[0][3]

    def test_feed_ad_detects_swipe_up_continue_variant(self):
        class DummyDevice:
            def __init__(self):
                self.swipes = []
                self.ad_visible = True

            def dump_hierarchy(self):
                if not self.ad_visible:
                    return 'text="第9集" text="选集" text="评论"'
                return 'text="向上滑动可以继续观看" text="精彩应用" text="查看详情"'

            def window_size(self):
                return (900, 1600)

            def swipe(self, x1, y1, x2, y2, duration=0.4):
                self.swipes.append((x1, y1, x2, y2, duration))
                self.ad_visible = False

            def press(self, key):
                pass

        device = DummyDevice()
        ops = HongguoOperations(device)
        assert ops._playback_visible() is False
        assert ops.skip_feed_ad_if_visible() is True
        assert device.swipes

    def test_search_drama_skips_feed_ad_before_opening_search(self):
        class DummySelector:
            def __init__(self, exists=False):
                self._exists = exists
                self.info = {"bounds": {"left": 24, "top": 1, "right": 876, "bottom": 73}}

            def exists(self, timeout=0):
                return self._exists

            def click(self):
                pass

        class DummyDevice:
            def __init__(self):
                self.ad_visible = True
                self.swipes = []

            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity"}

            def dump_hierarchy(self):
                if self.ad_visible:
                    return '<node package="com.phoenix.read" text="上滑继续观看短剧" /><node package="com.phoenix.read" text="广告" /><node package="com.phoenix.read" text="极速下载" /><node package="com.phoenix.read" text="重生武大郎" />'
                return '<node package="com.phoenix.read" text="首页" /><node package="com.phoenix.read" text="剧场" /><node package="com.phoenix.read" text="我的" /><node package="com.phoenix.read" text="搜索" />'

            def window_size(self):
                return (900, 1600)

            def swipe(self, x1, y1, x2, y2, duration=0.4):
                self.swipes.append((x1, y1, x2, y2, duration))
                self.ad_visible = False

            def press(self, key):
                pass

            def __call__(self, **kwargs):
                return DummySelector(False)

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch.object(ops, "_close_popups"), patch.object(ops, "_open_search", return_value=True):
            with patch.object(ops, "_submit_search", return_value={"success": True, "titles": ["一品布衣"]}) as submit:
                with patch("rpa.hongguo.operations.time.sleep"), patch.object(ops, "_sleep"):
                    result = ops.search_drama("一品布衣")

        assert result["success"] is True
        assert device.swipes
        submit.assert_called_once()

    def test_search_drama_backs_out_of_follow_fans_page_before_search(self):
        class DummySelector:
            def __init__(self, exists=False):
                self._exists = exists
                self.info = {"bounds": {"left": 24, "top": 1, "right": 876, "bottom": 73}}

            def exists(self, timeout=0):
                return self._exists

            def click(self):
                pass

        class DummyDevice:
            def __init__(self):
                self.back_count = 0
                self.search_opened = False
                self.commands = []

            def app_current(self):
                activity = (
                    "com.dragon.read.component.biz.impl.SearchActivity"
                    if self.search_opened
                    else "com.dragon.read.pages.bullet.AnnieXActivity"
                )
                return {"package": "com.phoenix.read", "activity": activity}

            def dump_hierarchy(self):
                if self.search_opened:
                    return (
                        '<node package="com.phoenix.read" class="android.widget.EditText" text="" />'
                        '<node package="com.phoenix.read" text="搜索" />'
                    )
                if self.back_count == 0:
                    return (
                        '<node package="com.phoenix.read" text="用户名2667338" />'
                        '<node package="com.phoenix.read" text="关注" />'
                        '<node package="com.phoenix.read" text="粉丝" />'
                        '<node package="com.phoenix.read" text="暂无关注的用户" />'
                    )
                return (
                    '<node package="com.phoenix.read" resource-id="com.phoenix.read:id/hds" clickable="true" bounds="[24,1][876,73]" />'
                    '<node package="com.phoenix.read" text="首页" />'
                    '<node package="com.phoenix.read" text="剧场" />'
                    '<node package="com.phoenix.read" text="我的" />'
                )

            def window_size(self):
                return (900, 1600)

            def press(self, key):
                if key == "back":
                    self.back_count += 1

            def shell(self, command):
                self.commands.append(command)
                if command == "input -d 0 tap 450 37":
                    self.search_opened = True
                return ""

            def __call__(self, **kwargs):
                return DummySelector(kwargs.get("resourceId") == "com.phoenix.read:id/hds")

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch.object(ops, "_close_popups"), patch.object(ops, "_submit_search", return_value={"success": True, "titles": ["一品布衣"]}):
            with patch.object(ops, "_move_app_stack_to_default_display", return_value=False), patch("rpa.hongguo.operations.time.sleep"):
                result = ops.search_drama("一品布衣")

        assert result["success"] is True
        assert device.back_count == 1
        assert "input -d 0 tap 450 37" in device.commands
        assert not any("dragon8662://search" in command for command in device.commands)

    def test_actor_quote_is_not_playing_title(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return 'text="主演说：" text="观看完整短剧" text="第1集"'

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._current_playing_title() == ""

    def test_select_drama_rejects_reserved_page(self):
        class DummySelector:
            count = 0

            def exists(self, timeout=0):
                return False

        class DummyDevice:
            def __call__(self, **kwargs):
                return DummySelector()

            def dump_hierarchy(self):
                return 'text="一品布衣5:入蜀篇 · 预计8月上线" text="立即预约"'

            def window_size(self):
                return (900, 1600)

            def click(self, x, y):
                pass

            def app_current(self):
                return {"activity": "SearchActivity"}

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_current_playing_title", return_value=""):
            with patch.object(ops, "_extract_detail_title", return_value="一品布衣5:入蜀篇"):
                result = ops.select_drama("一品布衣")

        assert result["success"] is False
        assert result["playable"] is False
        assert "不匹配" in result["message"]

    def test_normalize_playback_speed_label(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return ""

            def window_size(self):
                return (1080, 1920)

        ops = HongguoOperations(DummyDevice())
        assert ops._normalize_speed_label("1.5") == "1.5x"
        assert ops._normalize_speed_label("2.0x") == "2.0x"
        assert ops._normalize_speed_label("bad") is None

    def test_current_speed_match_uses_selected_state(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return 'text="倍速" text="1.5x" selected="true"'

            def window_size(self):
                return (1080, 1920)

        ops = HongguoOperations(DummyDevice())
        assert ops._current_speed_matches("1.5x") is True

    def test_episode_range_label_uses_30_episode_pages(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return ""

            def window_size(self):
                return (1080, 1920)

        ops = HongguoOperations(DummyDevice())
        assert ops._episode_range_label(1) == "1-30"
        assert ops._episode_range_label(30) == "1-30"
        assert ops._episode_range_label(31) == "31-60"
        assert ops._episode_range_label(60) == "31-60"

    def test_click_episode_number_scrolls_when_next_episode_below_visible_grid(self):
        class DummySelector:
            count = 0

            def exists(self, timeout=0):
                return False

        class DummyDevice:
            def __init__(self):
                self.swipes = []
                self.clicks = []

            def dump_hierarchy(self):
                nodes = []
                width = 900
                cell_w = 124
                cell_h = 118
                start_x = 32
                start_y = 1084
                gap_x = 18
                gap_y = 16
                for index in range(18):
                    number = index + 1
                    col = index % 6
                    row = index // 6
                    left = start_x + col * (cell_w + gap_x)
                    top = start_y + row * (cell_h + gap_y)
                    nodes.append(
                        f'<node text="{number}" bounds="[{left},{top}][{left + cell_w},{top + cell_h}]" />'
                    )
                return "".join(nodes)

            def window_size(self):
                return (900, 1600)

            def __call__(self, **kwargs):
                return DummySelector()

            def swipe(self, x1, y1, x2, y2, duration=0.4):
                self.swipes.append((x1, y1, x2, y2, duration))

            def click(self, x, y):
                self.clicks.append((x, y))

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch.object(ops, "get_current_episode", return_value=18):
            with patch.object(ops, "_click_episode_range_tab", return_value=True):
                with patch("rpa.hongguo.operations.time.sleep"):
                    assert ops._click_episode_number(19) is False
        assert device.clicks == []
        assert device.swipes
        assert device.swipes[0][1] > device.swipes[0][3]

    def test_open_comment_panel_falls_back_to_comment_bubble_coordinates(self):
        class DummySelector:
            def exists(self, timeout=0):
                return False

        class DummyDevice:
            def __init__(self):
                self.clicked = []
                self.xml = 'text="第18集" text="全屏观看"'

            def dump_hierarchy(self):
                if self.clicked:
                    return 'text="有趣评论" text="说点什么"'
                return self.xml

            def window_size(self):
                return (900, 1600)

            def __call__(self, **kwargs):
                return DummySelector()

            def click(self, x, y):
                self.clicked.append((x, y))

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch("rpa.hongguo.operations.time.sleep"):
            assert ops._open_comment_panel(0) is True
        assert device.clicked == [(846, 1072)]

    def test_title_candidate_rejects_status_bar_time(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return ""

            def window_size(self):
                return (1080, 1920)

        ops = HongguoOperations(DummyDevice())
        assert ops._is_title_candidate("12:54") is False
        assert ops._is_title_candidate("逆命谋臣：从赘婿到帝王") is True

    def test_extract_detail_title_skips_status_bar_time(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return 'text="12:54" bounds="[24,12][120,60]" text="逆命谋臣：从赘婿到帝王" bounds="[24,1320][650,1390]"'

            def window_size(self):
                return (1080, 1920)

        ops = HongguoOperations(DummyDevice())
        assert ops._extract_detail_title() == "逆命谋臣：从赘婿到帝王"

    def test_loose_title_match_rejects_wrong_drama_after_click(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return ""

            def window_size(self):
                return (1080, 1920)

        ops = HongguoOperations(DummyDevice())
        assert ops._loose_title_match("罪妻开荒第二季", "现代人陈砚穿越成即将嫁入将军府") is False
        assert ops._loose_title_match("罪妻开荒第二季", "发配边关，罪妻开荒养出战神") is True

    def test_select_drama_trusts_clicked_title_when_detail_extracts_description(self):
        title = "\u53d1\u914d\u8fb9\u5173\uff0c\u7f6a\u59bb\u5f00\u8352\u517b\u51fa\u6218\u795e\u7b2c\u4e94\u5b63"

        class DummySelector:
            def exists(self, timeout=0):
                return False

        class DummyDevice:
            def dump_hierarchy(self):
                return '<node text="\u5927\u9756\u8fde\u65f1\u4e24\u5e74\uff0c\u7cae\u8352\u56db\u8d77\uff0c\u6218\u706b\u2026" bounds="[24,300][860,360]" />'

            def window_size(self):
                return (900, 1600)

            def __call__(self, **kwargs):
                return DummySelector()

            def app_current(self):
                return {"activity": "DetailActivity"}

            def click(self, x, y):
                pass

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_current_playing_title", return_value=""):
            with patch.object(ops, "_click_matching_title_card", return_value=title):
                with patch.object(ops, "_search_results_visible", return_value=False):
                    with patch("rpa.hongguo.operations.time.sleep"), patch.object(ops, "_sleep"):
                        result = ops.select_drama(title)
        assert result["success"] is True
        assert result["drama_title"] == title

    def test_find_matching_title_node_skips_reserved_cards(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    '<node text="\u4e00\u54c1\u5e03\u88635:\u5165\u8700\u7bc7" bounds="[460,780][850,840]" />'
                    '<node text="265.8\u4e07\u4eba\u9884\u7ea6" bounds="[460,850][850,900]" />'
                    '<node text="\u7acb\u5373\u9884\u7ea6" bounds="[500,920][820,980]" />'
                    '<node text="\u4e00\u54c1\u5e03\u8863" bounds="[48,900][420,960]" />'
                    '<node text="\u6536\u85cf\u699c No.15" bounds="[48,980][280,1040]" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        match = ops._find_matching_title_node("\u4e00\u54c1\u5e03\u8863")
        assert match is not None
        assert match[0] == "\u4e00\u54c1\u5e03\u8863"

    def test_click_matching_title_card_uses_default_display_tap(self):
        class DummyDevice:
            def __init__(self):
                self.commands = []

            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" class="android.widget.EditText" text="\u4e00\u54c1\u5e03\u8863" bounds="[88,64][772,136]" />'
                    '<node package="com.phoenix.read" text="\u641c\u7d22" bounds="[804,79][868,122]" />'
                    '<node package="com.phoenix.read" text="\u7efc\u5408" bounds="[36,180][92,220]" />'
                    '<node package="com.phoenix.read" text="\u6f2b\u5267" bounds="[144,180][200,220]" />'
                    '<node package="com.phoenix.read" clickable="true" bounds="[24,249][443,958]" />'
                    '<node package="com.phoenix.read" text="4032\u4e07\u70ed\u5ea6" bounds="[48,790][220,835]" />'
                    '<node package="com.phoenix.read" text="\u4e00\u54c1\u5e03\u8863" bounds="[48,858][204,902]" />'
                )

            def window_size(self):
                return (900, 1600)

            def shell(self, command):
                self.commands.append(command)
                return ""

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch("rpa.hongguo.operations.time.sleep"):
            assert ops._click_matching_title_card("\u4e00\u54c1\u5e03\u8863") == "\u4e00\u54c1\u5e03\u8863"

        assert "input -d 0 tap 233 549" in device.commands

    def test_find_matching_title_node_prefers_playable_card_when_reserved_card_is_nearby(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    '<node class="android.widget.EditText" text="\u4e00\u54c1\u5e03\u8863" bounds="[88,66][772,136]" />'
                    '<node text="\u4e00\u54c1\u5e03\u8863" bounds="[168,500][430,552]" />'
                    '<node text="\u5386\u53f2\u53e4\u4ee3" bounds="[168,560][340,604]" />'
                    '<node text="4294\u4e07\u70ed\u5ea6" bounds="[168,612][380,656]" />'
                    '<node text="\u4e00\u54c1\u5e03\u88635:\u5165\u8700\u7bc7" bounds="[168,720][620,772]" />'
                    '<node text="268.7\u4e07\u4eba\u9884\u7ea6" bounds="[168,780][470,824]" />'
                    '<node text="\u7acb\u5373\u9884\u7ea6" bounds="[650,780][850,840]" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        match = ops._find_matching_title_node("\u4e00\u54c1\u5e03\u8863")
        assert match is not None
        assert match[0] == "\u4e00\u54c1\u5e03\u8863"

    def test_playback_visible_ignores_related_reserved_card(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    '<node text="\u7b2c12\u96c6" package="com.phoenix.read" bounds="[88,48][636,136]" '
                    'resource-id="com.phoenix.read:id/cdi" />'
                    '<node text="\u9009\u96c6" package="com.phoenix.read" bounds="[760,1200][860,1260]" />'
                    '<node text="\u89c2\u770b\u5b8c\u6574\u77ed\u5267\u00b7\u5168105\u96c6" package="com.phoenix.read" bounds="[60,1320][520,1370]" />'
                    '<node text="\u4e00\u54c1\u5e03\u88635:\u5165\u8700\u7bc7 \u00b7 \u9884\u8ba18\u6708\u4e0a\u7ebf" bounds="[80,1420][620,1480]" />'
                    '<node text="\u7acb\u5373\u9884\u7ea6" bounds="[650,1420][850,1480]" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._playback_visible() is True
        assert ops.get_current_episode() == 12
        assert ops.get_total_episodes() == 105

    def test_select_drama_returns_specific_unplayable_reason(self):
        class DummySelector:
            def exists(self, timeout=0):
                return False

        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    '<node text="\u4e00\u54c1\u5e03\u88635:\u5165\u8700\u7bc7" bounds="[460,780][850,840]" />'
                    '<node text="\u7acb\u5373\u9884\u7ea6" bounds="[500,920][820,980]" />'
                )

            def window_size(self):
                return (900, 1600)

            def __call__(self, **kwargs):
                return DummySelector()

            def app_current(self):
                return {"activity": "DetailActivity"}

            def click(self, x, y):
                pass

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_current_playing_title", return_value=""):
            with patch.object(ops, "_click_matching_title_card", return_value="\u4e00\u54c1\u5e03\u88635:\u5165\u8700\u7bc7"):
                with patch.object(ops, "_search_results_visible", return_value=False):
                    with patch("rpa.hongguo.operations.time.sleep"), patch.object(ops, "_sleep"):
                        result = ops.select_drama("\u4e00\u54c1\u5e03\u8863")
        assert result["success"] is False
        assert result["playable"] is False
        assert "\u4e0d\u5339\u914d" in result["message"]

    def test_select_drama_accepts_playable_page_with_related_reserved_card(self):
        title = "\u4e00\u54c1\u5e03\u8863"

        class DummySelector:
            def exists(self, timeout=0):
                return False

        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    '<node text="\u4e00\u54c1\u5e03\u8863" package="com.phoenix.read" bounds="[64,300][360,360]" />'
                    '<node text="\u7acb\u5373\u89c2\u770b" package="com.phoenix.read" bounds="[64,900][360,980]" />'
                    '<node text="\u5168105\u96c6" package="com.phoenix.read" bounds="[64,1000][220,1050]" />'
                    '<node text="\u4e00\u54c1\u5e03\u88635:\u5165\u8700\u7bc7 \u00b7 \u9884\u8ba18\u6708\u4e0a\u7ebf" bounds="[80,1220][620,1280]" />'
                    '<node text="\u7acb\u5373\u9884\u7ea6" bounds="[650,1220][850,1280]" />'
                )

            def window_size(self):
                return (900, 1600)

            def __call__(self, **kwargs):
                return DummySelector()

            def app_current(self):
                return {"activity": "DetailActivity"}

            def click(self, x, y):
                pass

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_current_playing_title", return_value=""):
            with patch.object(ops, "_click_matching_title_card", return_value=title):
                with patch.object(ops, "_extract_detail_title", return_value=title):
                    with patch.object(ops, "_search_results_visible", return_value=False):
                        with patch("rpa.hongguo.operations.time.sleep"), patch.object(ops, "_sleep"):
                            result = ops.select_drama(title)
        assert result["success"] is True
        assert result["playable"] is True

    def test_select_drama_accepts_playback_page_without_play_button_text(self):
        title = "\u4e00\u54c1\u5e03\u8863"

        class DummySelector:
            def exists(self, timeout=0):
                return False

        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    '<node text="\u7b2c1\u96c6" bounds="[80,80][220,140]" />'
                    '<node resource-id="com.phoenix.read:id/cdi" content-desc="\u8bc4\u8bba" bounds="[810,1040][890,1120]" />'
                    '<node text="\u9009\u96c6\u00b7\u5df2\u5b8c\u7ed3\u00b7\u5168105\u96c6" bounds="[64,1480][760,1560]" />'
                    f'<node text="{title}" bounds="[48,1320][300,1380]" />'
                )

            def window_size(self):
                return (900, 1600)

            def __call__(self, **kwargs):
                return DummySelector()

            def app_current(self):
                return {"activity": "DetailActivity"}

            def click(self, x, y):
                pass

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_current_playing_title", return_value=""):
            with patch.object(ops, "_click_matching_title_card", return_value=title):
                with patch.object(ops, "_search_results_visible", return_value=False):
                    with patch("rpa.hongguo.operations.time.sleep"), patch.object(ops, "_sleep"):
                        result = ops.select_drama(title)
        assert result["success"] is True
        assert result["playable"] is True

    def test_extract_detail_title_skips_description_snippet(self):
        title = "\u53d1\u914d\u8fb9\u5173\uff0c\u7f6a\u59bb\u5f00\u8352\u517b\u51fa\u6218\u795e\u7b2c\u4e94\u5b63"

        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    '<node text="\u5927\u9756\u8fde\u65f1\u4e24\u5e74\uff0c\u7cae\u8352\u56db\u8d77\uff0c\u6218\u706b\u2026" bounds="[24,300][860,360]" />'
                    f'<node text="{title}" bounds="[24,420][860,480]" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._extract_detail_title() == title

    def test_set_input_text_prefers_control_set_text_once(self):
        class DummyInput:
            def __init__(self):
                self.text = ""
                self.calls = []

            def set_text(self, value):
                self.text = value

            def get_text(self):
                return self.text
                self.calls.append(value)
                return True

            def click(self):
                pass

            @property
            def info(self):
                return {"text": self.text}

        class DummyDevice:
            def __init__(self):
                self.sent = []

            def dump_hierarchy(self):
                return ""

            def window_size(self):
                return (1080, 1920)

            def send_keys(self, text):
                self.sent.append(text)

            def shell(self, command):
                raise AssertionError("ADB fallback should not be used")

        inp = DummyInput()
        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch("rpa.hongguo.operations.time.sleep"):
            result = ops._set_input_text(inp, "罪妻开荒第二季", verify=True)
        assert result["success"] is True
        assert inp.calls == ["", "罪妻开荒第二季"]
        assert device.sent == []

    def test_set_input_text_uses_adb_fallback_after_empty_readback(self):
        class DummyInput:
            def __init__(self):
                self.text = ""

            def click(self):
                pass

            def set_text(self, value):
                return True

            @property
            def info(self):
                return {"text": self.text}

        class DummyDevice:
            def __init__(self, inp):
                self.inp = inp
                self.sent = []
                self.shells = []

            def dump_hierarchy(self):
                return ""

            def window_size(self):
                return (1080, 1920)

            def send_keys(self, text):
                self.sent.append(text)
                return False

            def shell(self, command):
                self.shells.append(command)
                self.inp.text = "一品布衣"
                return ""

        inp = DummyInput()
        device = DummyDevice(inp)
        ops = HongguoOperations(device)
        with patch("rpa.hongguo.operations.time.sleep"):
            result = ops._set_input_text(inp, "一品布衣", verify=True)
        assert result["success"] is True
        assert result["method"] == "ADB输入"
        assert device.shells

    def test_search_drama_stops_when_input_readback_mismatches(self):
        class DummyInput:
            def __init__(self):
                self.text = ""

            def click(self):
                pass

            def set_text(self, value):
                self.text = "季" if value else ""
                return True

            @property
            def info(self):
                return {"text": self.text}

            def exists(self, timeout=0):
                return True

        class DummySelector:
            def __init__(self, exists=False):
                self._exists = exists

            def exists(self, timeout=0):
                return self._exists

        class DummyDevice:
            def __init__(self):
                self.input = DummyInput()
                self.sent = []

            def dump_hierarchy(self):
                return f'<node class="android.widget.EditText" text="{self.input.text}" focused="true" />'

            def window_size(self):
                return (1080, 1920)

            def __call__(self, **kwargs):
                if kwargs.get("className") == "android.widget.EditText":
                    return self.input
                return DummySelector(False)

            def send_keys(self, text):
                self.sent.append(text)
                self.input.text = "季"

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_close_popups"), patch.object(ops, "_current_playing_title", return_value=""):
            with patch.object(ops, "_return_to_search_home", return_value=True):
                with patch.object(ops, "_open_theater"), patch.object(ops, "_open_search", return_value=True):
                    with patch("rpa.hongguo.operations.time.sleep"), patch.object(ops, "_sleep"):
                        result = ops.search_drama("罪妻开荒第二季")
        assert result["success"] is False
        assert result["input_text"] == "季"
        assert "搜索框输入校验失败" in result["message"]

    def test_search_drama_returns_to_home_after_account_profile_before_opening_search(self):
        class DummyDevice:
            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "com.dragon.read.pages.main.MainFragmentActivity"}

            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" text="用户名2667338" />'
                    '<node package="com.phoenix.read" text="红果号: 209734115491" />'
                    '<node package="com.phoenix.read" text="编辑资料" />'
                )

            def window_size(self):
                return (900, 1600)

            def __call__(self, **kwargs):
                return MagicMock(exists=MagicMock(return_value=False))

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_current_playing_title", return_value=""):
            with patch.object(ops, "_return_to_search_home", return_value=True) as recover:
                with patch.object(ops, "_open_search", return_value=True) as open_search:
                    with patch.object(ops, "_submit_search", return_value={"success": True, "titles": ["一品布衣"]}):
                        result = ops.search_drama("一品布衣")

        assert result["success"] is True
        recover.assert_called_once()
        open_search.assert_called()

    def test_search_drama_does_not_click_launcher_search_when_app_not_foreground(self):
        class DummySelector:
            def __init__(self, exists=False, device=None):
                self._exists = exists
                self.device = device

            def exists(self, timeout=0):
                return self._exists

            def click(self):
                if self.device:
                    self.device.clicked_search = True

        class DummyDevice:
            def __init__(self):
                self.clicked_search = False
                self.started = 0

            def app_current(self):
                return {"package": "com.android.launcher", "activity": "Launcher"}

            def app_start(self, package):
                self.started += 1

            def shell(self, command):
                return ""

            def dump_hierarchy(self):
                return '<node text="搜索" bounds="[505,505][610,610]" />'

            def window_size(self):
                return (900, 1600)

            def __call__(self, **kwargs):
                if kwargs.get("textContains") == "搜索":
                    return DummySelector(True, self)
                return DummySelector(False, self)

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch.object(ops, "_wait_app_ready", return_value=False):
            with patch.object(ops, "take_screenshot", return_value="search_start_app_not_ready.png"):
                result = ops.search_drama("一品布衣", screenshot_dir="C:/tmp")

        assert result["success"] is False
        assert "红果未在前台" in result["message"]
        assert result["screenshot_path"] == "search_start_app_not_ready.png"
        assert device.clicked_search is False

    def test_search_drama_rejects_launcher_ui_even_when_package_reports_hongguo(self):
        class DummySelector:
            def __init__(self, exists=False, device=None):
                self._exists = exists
                self.device = device

            def exists(self, timeout=0):
                return self._exists

            def click(self):
                if self.device:
                    self.device.clicked_search = True

        class DummyDevice:
            def __init__(self):
                self.clicked_search = False
                self.started = 0

            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "com.dragon.read.pages.main.MainFragmentActivity"}

            def app_start(self, package):
                self.started += 1

            def app_stop(self, package):
                pass

            def shell(self, command):
                return ""

            def dump_hierarchy(self):
                return (
                    '<node package="app.lawnchair" resource-id="app.lawnchair:id/launcher" />'
                    '<node text="应用宝" bounds="[720,500][820,610]" />'
                    '<node text="Play 商店" bounds="[290,680][395,790]" />'
                    '<node text="微信" bounds="[720,1020][820,1130]" />'
                    '<node text="抖音" bounds="[80,1020][180,1130]" />'
                    '<node text="红果免费短剧" bounds="[75,1200][200,1310]" />'
                    '<node text="搜索" bounds="[505,505][610,610]" />'
                )

            def window_size(self):
                return (900, 1600)

            def __call__(self, **kwargs):
                if kwargs.get("textContains") == "搜索":
                    return DummySelector(True, self)
                return DummySelector(False, self)

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch.object(ops, "_wait_app_ready", return_value=False):
            with patch.object(ops, "take_screenshot", return_value="search_start_app_not_ready.png"):
                result = ops.search_drama("一品布衣", screenshot_dir="C:/tmp")

        assert result["success"] is False
        assert "红果未在前台" in result["message"]
        assert device.clicked_search is False
        assert ops._known_not_foreground() is True

    def test_known_not_foreground_rejects_launcher_with_only_stale_hongguo_nodes(self):
        class DummyDevice:
            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "com.dragon.read.pages.main.MainFragmentActivity"}

            def dump_hierarchy(self):
                return (
                    '<node package="app.lawnchair" text="搜索" bounds="[505,505][610,610]" />'
                    '<node package="app.lawnchair" text="红果免费短剧" bounds="[80,1200][220,1320]" />'
                    '<node package="com.phoenix.read" text="" resource-id="com.phoenix.read:id/root" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._known_not_foreground() is True

    def test_known_not_foreground_rejects_hongguo_on_non_default_display(self):
        class DummyDevice:
            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "com.dragon.read.pages.main.MainFragmentActivity"}

            def dump_hierarchy(self):
                return (
                    '<node package="app.lawnchair" text="Play 商店" />'
                    '<node package="app.lawnchair" text="微信" />'
                    '<node package="app.lawnchair" text="红果免费短剧" />'
                    '<node package="com.phoenix.read" text="首页" />'
                    '<node package="com.phoenix.read" text="剧场" />'
                    '<node package="com.phoenix.read" text="我的" />'
                )

            def shell(self, command, timeout=10):
                return (
                    "RootTask id=246 bounds=[0,0][900,1600] displayId=35 userId=0\n"
                    "  taskId=246: com.phoenix.read/com.dragon.read.pages.splash.SplashActivity "
                    "visible=true topActivity=ComponentInfo{com.phoenix.read/com.dragon.read.pages.main.MainFragmentActivity}\n"
                    "RootTask id=1 bounds=[0,0][900,1600] displayId=0 userId=0\n"
                    "  taskId=2: app.lawnchair/app.lawnchair.LawnchairLauncher visible=true\n"
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._app_root_stack_on_non_default_display() == "246"
        assert ops._known_not_foreground() is True

    def test_known_not_foreground_allows_hongguo_on_default_display_with_launcher_leak(self):
        class DummyDevice:
            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "com.dragon.read.pages.main.MainFragmentActivity"}

            def dump_hierarchy(self):
                return (
                    '<node package="app.lawnchair" text="Play 商店" />'
                    '<node package="app.lawnchair" text="微信" />'
                    '<node package="app.lawnchair" text="红果免费短剧" />'
                    '<node package="com.phoenix.read" text="首页" />'
                    '<node package="com.phoenix.read" text="剧场" />'
                    '<node package="com.phoenix.read" text="我的" />'
                )

            def shell(self, command, timeout=10):
                return (
                    "RootTask id=246 bounds=[0,0][900,1600] displayId=0 userId=0\n"
                    "  taskId=246: com.phoenix.read/com.dragon.read.pages.splash.SplashActivity "
                    "visible=true topActivity=ComponentInfo{com.phoenix.read/com.dragon.read.pages.main.MainFragmentActivity}\n"
                    "RootTask id=1 bounds=[0,0][900,1600] displayId=0 userId=0\n"
                    "  taskId=2: app.lawnchair/app.lawnchair.LawnchairLauncher visible=false\n"
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._app_root_stack_on_non_default_display() == ""
        assert ops._known_not_foreground() is False

    def test_known_not_foreground_allows_anniex_internal_follow_page(self):
        class DummyDevice:
            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "com.dragon.read.pages.bullet.AnnieXActivity"}

            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" text="用户名2667338" />'
                    '<node package="com.phoenix.read" text="关注" />'
                    '<node package="com.phoenix.read" text="粉丝" />'
                    '<node package="com.phoenix.read" text="暂无关注的用户" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._known_not_foreground() is False

    def test_known_not_foreground_accepts_profile_when_background_displays_leak_into_xml(self):
        class DummyDevice:
            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "com.dragon.read.pages.main.MainFragmentActivity"}

            def dump_hierarchy(self):
                return (
                    '<node package="com.mx.browser" text="搜索或输入网址" display-id="35" />'
                    '<node package="app.lawnchair" text="游戏中心" display-id="0" />'
                    '<node package="app.lawnchair" text="红果免费短剧" display-id="0" />'
                    '<node package="com.phoenix.read" text="用户名2667338" display-id="36" />'
                    '<node package="com.phoenix.read" text="红果号: 209734115491" display-id="36" />'
                    '<node package="com.phoenix.read" text="编辑资料" display-id="36" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._known_not_foreground() is False

    def test_known_not_foreground_accepts_hongguo_feed_before_launcher_leak(self):
        class DummyDevice:
            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "com.dragon.read.pages.main.MainFragmentActivity"}

            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" text="偷听我心声后，美女总裁绷不住了" />'
                    '<node package="com.phoenix.read" text="第1集 | 李景龙意外重生" />'
                    '<node package="com.phoenix.read" text="观看完整短剧 全61集" />'
                    '<node package="com.phoenix.read" text="首页" />'
                    '<node package="com.phoenix.read" text="剧场" />'
                    '<node package="com.phoenix.read" text="我的" />'
                    '<node package="app.lawnchair" text="应用宝" />'
                    '<node package="app.lawnchair" text="游戏中心" />'
                    '<node package="app.lawnchair" text="Play 商店" />'
                    '<node package="app.lawnchair" text="抖音" />'
                    '<node package="app.lawnchair" text="红果免费短剧" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._launcher_content_dominates() is False
        assert ops._known_not_foreground() is False
        with patch.object(ops, "_close_popups"):
            assert ops.launch_app() is True

    def test_known_not_foreground_accepts_active_hongguo_feed_after_launcher_leak(self):
        class DummyDevice:
            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "com.dragon.read.pages.main.MainFragmentActivity"}

            def dump_hierarchy(self):
                return (
                    '<node package="app.lawnchair" resource-id="app.lawnchair:id/launcher" text="" />'
                    '<node package="app.lawnchair" text="时空猎人·觉醒" />'
                    '<node package="app.lawnchair" text="热血江湖：归来" />'
                    '<node package="app.lawnchair" text="三国志将星闪耀" />'
                    '<node package="app.lawnchair" text="鹅鸭杀" />'
                    '<node package="app.lawnchair" text="红果免费短剧" />'
                    '<node package="com.phoenix.read" text="爆剧" />'
                    '<node package="com.phoenix.read" text="嫌我赚得多？我走后，全镇灵果果农哭了" />'
                    '<node package="com.phoenix.read" text="玄幻" />'
                    '<node package="com.phoenix.read" text="逆袭" />'
                    '<node package="com.phoenix.read" text="古代" />'
                    '<node package="com.phoenix.read" text="第1集 | 全镇果农来求我" />'
                    '<node package="com.phoenix.read" text="观看完整短剧 全30集" />'
                    '<node package="com.phoenix.read" text="首页" />'
                    '<node package="com.phoenix.read" text="剧场" />'
                    '<node package="com.phoenix.read" text="商城" />'
                    '<node package="com.phoenix.read" text="赚钱" />'
                    '<node package="com.phoenix.read" text="我的" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._launcher_visible() is True
        assert ops._launcher_content_dominates() is True
        assert ops._hongguo_active_feed_surface_visible() is True
        assert ops._xml_definitely_not_hongguo() is False
        assert ops._known_not_foreground() is False
        with patch.object(ops, "_close_popups"):
            assert ops.launch_app() is True

    def test_known_not_foreground_accepts_active_playback_after_launcher_leak(self):
        class DummyDevice:
            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity"}

            def dump_hierarchy(self):
                return (
                    '<node package="app.lawnchair" resource-id="app.lawnchair:id/launcher" text="" />'
                    '<node package="app.lawnchair" text="时空猎人·觉醒" />'
                    '<node package="app.lawnchair" text="ATX" />'
                    '<node package="app.lawnchair" text="傲游浏览器" />'
                    '<node package="app.lawnchair" text="搜索" />'
                    '<node package="app.lawnchair" text="应用宝" />'
                    '<node package="app.lawnchair" text="游戏中心" />'
                    '<node package="app.lawnchair" text="Play 商店" />'
                    '<node package="app.lawnchair" text="红果免费短剧" />'
                    '<node package="com.phoenix.read" text="嫌我赚得多？我走后，全镇灵果果农哭了" />'
                    '<node package="com.phoenix.read" text="热评：" />'
                    '<node package="com.phoenix.read" text="展开" />'
                    '<node package="com.phoenix.read" text="作者声明：内容由AI生成" />'
                    '<node package="com.phoenix.read" text="选集" />'
                    '<node package="com.phoenix.read" text="· 已完结 · 全30集" />'
                    '<node package="com.phoenix.read" text="第3集" />'
                    '<node package="com.phoenix.read" text="倍速" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._launcher_visible() is True
        assert ops._launcher_content_dominates() is True
        assert ops._hongguo_active_playback_surface_visible() is True
        assert ops._xml_definitely_not_hongguo() is False
        assert ops._known_not_foreground() is False
        with patch.object(ops, "_close_popups"):
            assert ops.launch_app() is True

    def test_known_not_foreground_prioritizes_launcher_over_stale_hongguo_markers(self):
        class DummyDevice:
            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity"}

            def dump_hierarchy(self):
                return (
                    '<node package="app.lawnchair" resource-id="app.lawnchair:id/launcher" text="" />'
                    '<node package="app.lawnchair" text="搜索" bounds="[505,505][610,610]" />'
                    '<node package="app.lawnchair" text="红果免费短剧" bounds="[80,1200][220,1320]" />'
                    '<node package="com.phoenix.read" text="搜索" bounds="[760,60][840,140]" />'
                    '<node package="com.phoenix.read" text="第12集" bounds="[88,48][636,136]" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._launcher_visible() is True
        assert ops._xml_definitely_not_hongguo() is True
        assert ops._known_not_foreground() is True

    def test_known_not_foreground_accepts_focused_hongguo_with_launcher_background(self):
        class DummyDevice:
            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity"}

            def dump_hierarchy(self):
                return (
                    '<node package="app.lawnchair" resource-id="app.lawnchair:id/launcher" text="" />'
                    '<node package="com.phoenix.read" text="全屏观看" bounds="[422,1054][518,1087]" />'
                    '<node package="com.phoenix.read" text="选集" bounds="[64,1525][120,1563]" />'
                    '<node package="com.phoenix.read" text="第2集" bounds="[88,0][636,88]" />'
                )

            def window_size(self):
                return (900, 1600)

            def shell(self, command):
                return (
                    "mFocusedApp=ActivityRecord{ef2b5d6 u0 app.lawnchair/.LawnchairLauncher t2}\n"
                    "mCurrentFocus=Window{f099b92 u0 "
                    "com.phoenix.read/com.dragon.read.component.shortvideo.impl.ShortSeriesActivity}"
                )

        ops = HongguoOperations(DummyDevice())
        assert ops._launcher_visible() is True
        assert ops._xml_definitely_not_hongguo() is False
        assert ops._known_not_foreground() is False

    def test_known_not_foreground_rejects_launcher_games_even_when_focus_reports_hongguo(self):
        class DummyDevice:
            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "com.dragon.read.pages.main.MainFragmentActivity"}

            def dump_hierarchy(self):
                return (
                    '<node package="app.lawnchair" resource-id="app.lawnchair:id/launcher" text="" />'
                    '<node package="app.lawnchair" text="热血江湖：归来" bounds="[480,300][560,350]" />'
                    '<node package="app.lawnchair" text="时空猎人·觉醒" bounds="[500,360][620,410]" />'
                    '<node package="app.lawnchair" text="三国志将星闪耀" bounds="[500,420][660,470]" />'
                    '<node package="app.lawnchair" text="鹅鸭杀" bounds="[500,480][620,530]" />'
                    '<node package="app.lawnchair" text="应用宝" bounds="[720,500][820,610]" />'
                    '<node package="app.lawnchair" text="搜索" bounds="[505,505][610,610]" />'
                    '<node package="com.phoenix.read" text="搜索" bounds="[760,60][840,140]" />'
                    '<node package="com.phoenix.read" text="第7集" bounds="[88,0][636,88]" />'
                    '<node package="com.phoenix.read" text="选集" bounds="[64,1525][120,1563]" />'
                )

            def window_size(self):
                return (900, 1600)

            def shell(self, command):
                return (
                    "mCurrentFocus=Window{f099b92 u0 "
                    "com.phoenix.read/com.dragon.read.pages.main.MainFragmentActivity}"
                )

        ops = HongguoOperations(DummyDevice())
        assert ops._launcher_visible() is True
        assert ops._hongguo_surface_visible() is True
        assert ops._launcher_content_dominates() is True
        assert ops._hongguo_strong_surface_visible() is True
        assert ops._xml_definitely_not_hongguo() is True
        assert ops._known_not_foreground() is True

    def test_known_not_foreground_rejects_mumu_launcher_recommendations_with_stale_hongguo_activity(self):
        class DummyDevice:
            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity"}

            def dump_hierarchy(self):
                return (
                    '<node package="app.lawnchair" resource-id="app.lawnchair:id/launcher" text="" />'
                    '<node package="app.lawnchair" text="每日新发现" bounds="[500,200][760,260]" />'
                    '<node package="app.lawnchair" text="热血江湖：归来" bounds="[70,350][420,450]" />'
                    '<node package="app.lawnchair" text="时空猎人·觉醒" bounds="[500,260][600,320]" />'
                    '<node package="app.lawnchair" text="三国志将星闪耀" bounds="[600,260][700,320]" />'
                    '<node package="app.lawnchair" text="鹅鸭杀" bounds="[680,260][760,320]" />'
                    '<node package="app.lawnchair" text="搜索" bounds="[505,505][610,610]" />'
                    '<node package="app.lawnchair" text="应用宝" bounds="[720,500][820,610]" />'
                    '<node package="app.lawnchair" text="红果免费短剧" bounds="[80,1200][220,1320]" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._launcher_visible() is True
        assert ops._xml_definitely_not_hongguo() is True
        assert ops._known_not_foreground() is True

    def test_known_not_foreground_accepts_active_playback_when_focus_unknown(self):
        class DummyDevice:
            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity"}

            def dump_hierarchy(self):
                return (
                    '<node package="app.lawnchair" resource-id="app.lawnchair:id/launcher" text="" />'
                    '<node package="com.phoenix.read" text="全屏观看" bounds="[422,1054][518,1087]" />'
                    '<node package="com.phoenix.read" text="选集" bounds="[64,1525][120,1563]" />'
                    '<node package="com.phoenix.read" text="第2集" bounds="[88,0][636,88]" />'
                )

            def window_size(self):
                return (900, 1600)

            def shell(self, command):
                raise RuntimeError("dumpsys unavailable")

        ops = HongguoOperations(DummyDevice())
        assert ops._launcher_visible() is True
        assert ops._xml_definitely_not_hongguo() is False
        assert ops._known_not_foreground() is False

    def test_open_search_does_not_click_launcher_search_when_hongguo_overlay_is_visible(self):
        class DummySelector:
            def __init__(self, exists=False, device=None):
                self._exists = exists
                self.device = device

            def exists(self, timeout=0):
                return self._exists

            def click(self):
                if self.device:
                    self.device.clicked_launcher_search = True

        class DummyDevice:
            def __init__(self):
                self.clicked_launcher_search = False
                self.coordinate_clicks = []

            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "com.dragon.read.pages.main.MainFragmentActivity"}

            def dump_hierarchy(self):
                return (
                    '<node package="app.lawnchair" text="搜索" bounds="[505,505][610,610]" />'
                    '<node package="com.phoenix.read" text="首页" bounds="[80,1500][160,1580]" />'
                    '<node package="com.phoenix.read" text="剧场" bounds="[250,1500][330,1580]" />'
                    '<node package="com.phoenix.read" text="我的" bounds="[730,1500][820,1580]" />'
                )

            def window_size(self):
                return (900, 1600)

            def __call__(self, **kwargs):
                if kwargs.get("resourceId") == "com.phoenix.read:id/hds":
                    return DummySelector(False, self)
                if kwargs.get("textContains") == "搜索" or kwargs.get("descriptionContains") == "搜索":
                    return DummySelector(True, self)
                return DummySelector(False, self)

            def click(self, x, y):
                self.coordinate_clicks.append((x, y))

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch.object(ops, "_close_popups"):
            assert ops._open_search() is False
        assert device.clicked_launcher_search is False
        assert device.coordinate_clicks == []

    def test_open_search_does_not_use_search_deeplink_when_feed_has_no_search_button(self):
        class DummySelector:
            def exists(self, timeout=0):
                return False

        class DummyDevice:
            def __init__(self):
                self.commands = []
                self.search_opened = False

            def app_current(self):
                activity = (
                    "com.dragon.read.component.biz.impl.SearchActivity"
                    if self.search_opened
                    else "com.dragon.read.pages.main.MainFragmentActivity"
                )
                return {"package": "com.phoenix.read", "activity": activity}

            def dump_hierarchy(self):
                if self.search_opened:
                    return (
                        '<node package="com.phoenix.read" class="android.widget.EditText" text="" />'
                        '<node package="com.phoenix.read" text="搜索" />'
                    )
                return (
                    '<node package="com.phoenix.read" text="首页" bounds="[71,1529][135,1572]" />'
                    '<node package="com.phoenix.read" text="剧场" bounds="[245,1529][309,1572]" />'
                    '<node package="com.phoenix.read" text="我的" bounds="[765,1529][829,1572]" />'
                    '<node package="com.phoenix.read" text="观看完整短剧 全8集" />'
                )

            def window_size(self):
                return (900, 1600)

            def shell(self, command):
                self.commands.append(command)
                if "dragon8662://search" in command:
                    self.search_opened = True
                return ""

            def click(self, x, y):
                return None

            def __call__(self, **kwargs):
                return DummySelector()

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch.object(ops, "_close_popups"), patch("rpa.hongguo.operations.time.sleep"):
            assert ops._open_search() is False

        assert not any("dragon8662://search" in command for command in device.commands)

    def test_open_search_returns_false_after_ui_entry_fails_without_deeplink(self):
        class DummyDevice:
            def __init__(self):
                self.commands = []
                self.search_opened = False

            def app_current(self):
                activity = (
                    "com.dragon.read.component.biz.impl.SearchActivity"
                    if self.search_opened
                    else "com.dragon.read.pages.main.MainFragmentActivity"
                )
                return {"package": "com.phoenix.read", "activity": activity}

            def dump_hierarchy(self):
                return '<node package="com.phoenix.read" text="首页" />'

            def window_size(self):
                return (900, 1600)

            def shell(self, command):
                self.commands.append(command)
                if "dragon8662://search" in command:
                    self.search_opened = True
                return ""

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch.object(ops, "_close_popups") as close_popups, patch("rpa.hongguo.operations.time.sleep"):
            assert ops._open_search() is False

        assert not any("dragon8662://search" in command for command in device.commands)
        assert close_popups.call_count >= 1

    def test_open_search_taps_search_entry_on_default_display(self):
        class DummySelector:
            def __init__(self, exists=False):
                self._exists = exists
                self.info = {"bounds": {"left": 24, "top": 1, "right": 876, "bottom": 73}}

            def exists(self, timeout=0):
                return self._exists

        class DummyDevice:
            def __init__(self):
                self.commands = []
                self.opened = False

            def app_current(self):
                activity = (
                    "com.dragon.read.component.biz.impl.SearchActivity"
                    if self.opened
                    else "com.dragon.read.pages.main.MainFragmentActivity"
                )
                return {"package": "com.phoenix.read", "activity": activity}

            def dump_hierarchy(self):
                if self.opened:
                    return (
                        '<node package="com.phoenix.read" class="android.widget.EditText" text="" />'
                        '<node package="com.phoenix.read" text="搜索" bounds="[804,79][868,122]" />'
                    )
                return (
                    '<node package="com.phoenix.read" resource-id="com.phoenix.read:id/hds" clickable="true" bounds="[24,1][876,73]" />'
                    '<node package="com.phoenix.read" text="首页" bounds="[71,1529][135,1572]" />'
                    '<node package="com.phoenix.read" text="剧场" bounds="[245,1529][309,1572]" />'
                    '<node package="com.phoenix.read" text="我的" bounds="[765,1529][829,1572]" />'
                )

            def window_size(self):
                return (900, 1600)

            def shell(self, command):
                self.commands.append(command)
                if command == "input -d 0 tap 450 37":
                    self.opened = True
                return ""

            def __call__(self, **kwargs):
                return DummySelector(kwargs.get("resourceId") == "com.phoenix.read:id/hds")

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch.object(ops, "_close_popups"), patch("rpa.hongguo.operations.time.sleep"):
            assert ops._open_search() is True

        assert "input -d 0 tap 450 37" in device.commands

    def test_extract_drama_titles_skips_search_input_text(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    '<node class="android.widget.EditText" text="罪妻开荒第二季" bounds="[88,66][772,136]" />'
                    '<node text="综合" bounds="[36,180][92,220]" />'
                    '<node text="发配边关，罪妻开荒养出战神第二季" bounds="[50,856][430,924]" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._extract_drama_titles() == ["发配边关，罪妻开荒养出战神第二季"]

    def test_extract_drama_titles_ignores_launcher_leak_when_hongguo_nodes_exist(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    '<node package="com.mx.browser" text="Photo by Danny Rienecker on Unsplash" bounds="[0,0][300,40]" />'
                    '<node package="com.mx.browser" text="百度" bounds="[20,180][80,220]" />'
                    '<node package="app.lawnchair" text="京东" bounds="[20,240][80,280]" />'
                    '<node package="com.phoenix.read" class="android.widget.EditText" text="一品布衣" bounds="[88,64][772,136]" />'
                    '<node package="com.phoenix.read" text="一品布衣3：朝堂篇" bounds="[160,181][434,224]" />'
                    '<node package="com.phoenix.read" text="第3季" bounds="[160,232][221,260]" />'
                    '<node package="com.phoenix.read" text="历史古代" bounds="[240,232][330,260]" />'
                    '<node package="com.phoenix.read" text="4151万热度" bounds="[360,232][485,260]" />'
                    '<node package="com.phoenix.read" text="一品布衣2：烽火篇" bounds="[80,494][320,536]" />'
                    '<node package="com.phoenix.read" text="一品布衣1" bounds="[80,682][220,724]" />'
                    '<node package="com.phoenix.read" text="一品布衣" bounds="[80,776][208,818]" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        titles = ops._extract_drama_titles()
        assert "Photo by Danny Rienecker on Unsplash" not in titles
        assert "百度" not in titles
        assert "京东" not in titles
        assert titles == ["一品布衣2：烽火篇", "一品布衣1", "一品布衣"]

    def test_find_matching_title_node_uses_result_card_not_search_box(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    '<node class="android.widget.EditText" text="罪妻开荒第二季" bounds="[88,66][772,136]" />'
                    '<node text="发配边关，罪妻开荒养出战神第二季" bounds="[50,856][430,924]" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._find_matching_title_node("罪妻开荒第二季") == (
            "发配边关，罪妻开荒养出战神第二季",
            50,
            856,
            430,
            924,
        )

    def test_search_results_visible_detects_result_list_without_tabs(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" class="android.widget.EditText" text="一品布衣" bounds="[88,64][772,136]" />'
                    '<node package="com.phoenix.read" text="搜索" bounds="[790,70][860,130]" />'
                    '<node package="com.phoenix.read" text="一品布衣3：朝堂篇" bounds="[160,181][434,224]" />'
                    '<node package="com.phoenix.read" text="第3季" bounds="[160,232][221,260]" />'
                    '<node package="com.phoenix.read" text="4187万热度" bounds="[357,232][481,260]" />'
                    '<node package="com.phoenix.read" text="一品布衣" bounds="[80,864][208,907]" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._search_results_visible() is True
        assert ops._is_reserved_or_unplayable_context(ops._xml()) is False
        assert ops._current_playing_title() == ""
        assert ops._search_submitted_results_visible() is False
        assert ops._search_suggestion_page_visible() is True

    def test_search_submitted_results_visible_requires_result_tabs(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" class="android.widget.EditText" text="一品布衣" bounds="[88,64][772,136]" />'
                    '<node package="com.phoenix.read" text="搜索" bounds="[790,70][860,130]" />'
                    '<node package="com.phoenix.read" text="综合" bounds="[20,150][80,195]" />'
                    '<node package="com.phoenix.read" text="漫剧" bounds="[100,150][160,195]" />'
                    '<node package="com.phoenix.read" text="一品布衣" bounds="[36,842][164,885]" />'
                    '<node package="com.phoenix.read" text="4032万热度" bounds="[36,780][190,825]" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._search_submitted_results_visible() is True
        assert ops._search_suggestion_page_visible() is False

    def test_submit_search_query_clicks_top_right_search_until_submitted_results(self):
        class DummyDevice:
            def __init__(self):
                self.clicks = []
                self.submitted = False

            def dump_hierarchy(self):
                if self.submitted:
                    return (
                        '<node package="com.phoenix.read" class="android.widget.EditText" text="一品布衣" bounds="[88,64][772,136]" />'
                        '<node package="com.phoenix.read" text="搜索" bounds="[804,70][870,126]" />'
                        '<node package="com.phoenix.read" text="综合" bounds="[20,150][80,195]" />'
                        '<node package="com.phoenix.read" text="漫剧" bounds="[100,150][160,195]" />'
                        '<node package="com.phoenix.read" text="一品布衣" bounds="[36,842][164,885]" />'
                        '<node package="com.phoenix.read" text="4032万热度" bounds="[36,780][190,825]" />'
                    )
                return (
                    '<node package="com.phoenix.read" class="android.widget.EditText" text="一品布衣" bounds="[88,64][772,136]" />'
                    '<node package="com.phoenix.read" text="搜索" bounds="[804,70][870,126]" />'
                    '<node package="com.phoenix.read" text="一品布衣4：割据篇" bounds="[160,181][434,224]" />'
                    '<node package="com.phoenix.read" text="第4季" bounds="[160,232][221,260]" />'
                    '<node package="com.phoenix.read" text="4216万热度" bounds="[357,232][481,260]" />'
                    '<node package="com.phoenix.read" text="一品布衣1" bounds="[80,682][226,725]" />'
                    '<node package="com.phoenix.read" text="一品布衣" bounds="[80,773][208,816]" />'
                )

            def window_size(self):
                return (900, 1600)

            def click(self, x, y):
                self.clicks.append((x, y))
                if x > 780 and y < 150:
                    self.submitted = True

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch("rpa.hongguo.operations.time.sleep"):
            assert ops._submit_search_query() is True

        assert device.clicks == [(837, 98)]

    def test_submit_search_returns_failure_when_still_on_suggestion_page(self):
        class DummyElement:
            def __init__(self, exists=True):
                self._exists = exists

            def exists(self, timeout=0):
                return self._exists

            def click(self):
                pass

            @property
            def info(self):
                return {"text": "一品布衣"}

        class DummyInput:
            def __init__(self):
                self.text = ""

            def clear_text(self):
                self.text = ""

            def set_text(self, value):
                self.text = value

        class DummyDevice:
            def __init__(self):
                self.input = DummyInput()
                self.clicks = []

            def __call__(self, **kwargs):
                if kwargs.get("className") == "android.widget.EditText":
                    return DummyElement(True)
                return DummyElement(False)

            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" class="android.widget.EditText" text="一品布衣" bounds="[88,64][772,136]" />'
                    '<node package="com.phoenix.read" text="搜索" bounds="[804,70][870,126]" />'
                    '<node package="com.phoenix.read" text="一品布衣4：割据篇" bounds="[160,181][434,224]" />'
                    '<node package="com.phoenix.read" text="第4季" bounds="[160,232][221,260]" />'
                    '<node package="com.phoenix.read" text="4216万热度" bounds="[357,232][481,260]" />'
                    '<node package="com.phoenix.read" text="一品布衣1" bounds="[80,682][226,725]" />'
                    '<node package="com.phoenix.read" text="一品布衣" bounds="[80,773][208,816]" />'
                )

            def window_size(self):
                return (900, 1600)

            def click(self, x, y):
                self.clicks.append((x, y))

            def press(self, key):
                pass

            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "com.dragon.read.biz.impl.SearchActivity"}

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_set_search_input_text", return_value={"success": True, "actual_text": "一品布衣", "method": "set_text"}):
            with patch.object(ops, "_submit_search_query", return_value=False):
                with patch("rpa.hongguo.operations.time.sleep"):
                    result = ops._submit_search("一品布衣")

        assert result["success"] is False
        assert "点击搜索按钮后" in result["message"]
        assert result["titles"] == []

    def test_submit_search_query_force_taps_submit_when_still_suggestion_page(self):
        class DummyDevice:
            def __init__(self):
                self.commands = []
                self.click_count = 0

            def dump_hierarchy(self):
                if self.click_count >= 1:
                    return (
                        '<node package="com.phoenix.read" class="android.widget.EditText" text="一品布衣" bounds="[88,64][772,136]" />'
                        '<node package="com.phoenix.read" text="搜索" bounds="[804,79][868,122]" />'
                        '<node package="com.phoenix.read" text="综合" bounds="[20,150][80,195]" />'
                        '<node package="com.phoenix.read" text="漫剧" bounds="[100,150][160,195]" />'
                        '<node package="com.phoenix.read" text="一品布衣" bounds="[36,842][164,885]" />'
                    )
                return (
                    '<node package="com.phoenix.read" class="android.widget.EditText" text="一品布衣" bounds="[88,64][772,136]" />'
                    '<node package="com.phoenix.read" text="搜索" bounds="[804,79][868,122]" />'
                    '<node package="com.phoenix.read" text="一品布衣3：朝堂篇" bounds="[160,181][434,224]" />'
                    '<node package="com.phoenix.read" text="第3季" bounds="[160,232][221,260]" />'
                    '<node package="com.phoenix.read" text="一品布衣" bounds="[80,864][208,907]" />'
                )

            def window_size(self):
                return (900, 1600)

            def shell(self, command):
                self.commands.append(command)
                if command == "input -d 0 tap 836 100":
                    self.click_count += 1
                return ""

            def press(self, key):
                pass

            def __call__(self, **kwargs):
                selector = MagicMock()
                selector.exists.return_value = False
                return selector

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch("rpa.hongguo.operations.time.sleep"), patch.object(ops, "_sleep"):
            assert ops._submit_search_query(attempts=0) is True

        assert "input -d 0 tap 836 100" in device.commands

    def test_submit_search_uses_control_input_before_adb_fallback(self):
        class DummyElement:
            def __init__(self):
                self.value = ""
                self.set_text_values = []

            def exists(self, timeout=0):
                return True

            def click(self):
                pass

            def set_text(self, value):
                self.set_text_values.append(value)
                self.value = value

            @property
            def info(self):
                return {"text": self.value}

        class DummyDevice:
            def __init__(self):
                self.input = DummyElement()
                self.commands = []

            def __call__(self, **kwargs):
                return self.input

            def dump_hierarchy(self):
                return (
                    f'<node package="com.phoenix.read" class="android.widget.EditText" text="{self.input.value}" bounds="[88,64][772,136]" />'
                    '<node package="com.phoenix.read" text="搜索" bounds="[804,70][870,126]" />'
                )

            def window_size(self):
                return (900, 1600)

            def shell(self, command, timeout=None):
                self.commands.append(command)
                if str(command).startswith("input text "):
                    self.input.value = str(command).replace("input text ", "", 1)
                return True

            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "com.dragon.read.biz.impl.SearchActivity"}

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch.object(ops, "_submit_search_query", return_value=True):
            with patch.object(ops, "_extract_drama_titles", return_value=["一品布衣"]):
                with patch("rpa.hongguo.operations.time.sleep"):
                    result = ops._submit_search("一品布衣")

        assert result["success"] is True
        assert result["input_method"] == "控件写入"
        assert device.commands == []
        assert device.input.set_text_values == ["", "一品布衣"]

    def test_click_exact_search_suggestion_prefers_plain_keyword(self):
        class DummyDevice:
            def __init__(self):
                self.clicks = []

            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" class="android.widget.EditText" text="一品布衣" bounds="[88,64][772,136]" />'
                    '<node package="com.phoenix.read" text="搜索" bounds="[790,70][860,130]" />'
                    '<node package="com.phoenix.read" class="android.view.ViewGroup" clickable="true" bounds="[0,153][900,291]" />'
                    '<node package="com.phoenix.read" text="一品布衣3：朝堂篇" bounds="[160,181][434,224]" />'
                    '<node package="com.phoenix.read" class="android.view.ViewGroup" clickable="true" bounds="[0,658][900,749]" />'
                    '<node package="com.phoenix.read" text="一品布衣1" bounds="[80,682][226,725]" />'
                    '<node package="com.phoenix.read" class="android.view.ViewGroup" clickable="true" bounds="[0,749][900,840]" />'
                    '<node package="com.phoenix.read" text="一品布衣" bounds="[80,773][208,816]" />'
                )

            def window_size(self):
                return (900, 1600)

            def click(self, x, y):
                self.clicks.append((x, y))

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch("rpa.hongguo.operations.time.sleep"):
            assert ops._click_exact_search_suggestion("一品布衣") is True

        assert device.clicks == [(144, 794)]

    def test_extract_drama_titles_prefers_playable_cards_over_suggestions(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" class="android.widget.EditText" text="一品布衣" bounds="[88,64][772,136]" />'
                    '<node package="com.phoenix.read" text="搜索" bounds="[790,70][860,130]" />'
                    '<node package="com.phoenix.read" text="一品布衣3：朝堂篇" bounds="[160,181][434,224]" />'
                    '<node package="com.phoenix.read" text="第3季" bounds="[160,232][221,260]" />'
                    '<node package="com.phoenix.read" text="4151万热度" bounds="[357,232][481,260]" />'
                    '<node package="com.phoenix.read" text="一品布衣2：烽火篇" bounds="[160,319][434,362]" />'
                    '<node package="com.phoenix.read" text="第2季" bounds="[160,370][221,398]" />'
                    '<node package="com.phoenix.read" text="4091万热度" bounds="[357,370][481,398]" />'
                    '<node package="com.phoenix.read" text="一品布衣1" bounds="[80,682][226,725]" />'
                    '<node package="com.phoenix.read" text="一品布衣" bounds="[80,773][208,816]" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._extract_drama_titles() == ["一品布衣3：朝堂篇", "一品布衣2：烽火篇"]

    def test_click_matching_title_card_skips_numbered_result_for_base_title(self):
        class DummyDevice:
            def __init__(self):
                self.clicks = []

            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" class="android.widget.EditText" text="一品布衣" bounds="[88,64][772,136]" />'
                    '<node package="com.phoenix.read" text="搜索" bounds="[790,70][860,130]" />'
                    '<node package="com.phoenix.read" text="一品布衣3：朝堂篇" bounds="[160,181][434,224]" />'
                    '<node package="com.phoenix.read" text="第3季" bounds="[160,232][221,260]" />'
                    '<node package="com.phoenix.read" text="4187万热度" bounds="[357,232][481,260]" />'
                    '<node package="com.phoenix.read" text="一品布衣" bounds="[80,864][208,907]" />'
                )

            def window_size(self):
                return (900, 1600)

            def click(self, x, y):
                self.clicks.append((x, y))

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch("rpa.hongguo.operations.time.sleep"):
            assert ops._click_matching_title_card("一品布衣") == ""

        assert device.clicks == []

    def test_click_matching_title_card_clicks_search_card_container(self):
        class DummyDevice:
            def __init__(self):
                self.clicks = []

            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" class="android.widget.EditText" text="一品布衣" bounds="[88,64][772,136]" />'
                    '<node package="com.phoenix.read" text="综合" bounds="[20,150][80,195]" />'
                    '<node package="com.phoenix.read" class="android.view.ViewGroup" clickable="true" bounds="[16,210][452,900]" />'
                    '<node package="com.phoenix.read" text="4032万热度" bounds="[36,780][190,825]" />'
                    '<node package="com.phoenix.read" text="一品布衣" bounds="[36,842][164,885]" />'
                    '<node package="com.phoenix.read" class="android.view.ViewGroup" clickable="true" bounds="[474,210][884,900]" />'
                    '<node package="com.phoenix.read" text="一品布衣5:入蜀篇" bounds="[500,760][780,805]" />'
                )

            def window_size(self):
                return (900, 1600)

            def click(self, x, y):
                self.clicks.append((x, y))

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch("rpa.hongguo.operations.time.sleep"):
            assert ops._click_matching_title_card("一品布衣") == "一品布衣"

        assert device.clicks == [(234, 522)]

    def test_click_matching_title_card_falls_back_to_left_poster_area(self):
        class DummyDevice:
            def __init__(self):
                self.clicks = []

            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" class="android.widget.EditText" text="一品布衣" bounds="[88,64][772,136]" />'
                    '<node package="com.phoenix.read" text="综合" bounds="[20,150][80,195]" />'
                    '<node package="com.phoenix.read" text="4032万热度" bounds="[36,780][190,825]" />'
                    '<node package="com.phoenix.read" text="一品布衣" bounds="[36,842][164,885]" />'
                )

            def window_size(self):
                return (900, 1600)

            def click(self, x, y):
                self.clicks.append((x, y))

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch("rpa.hongguo.operations.time.sleep"):
            assert ops._click_matching_title_card("一品布衣") == "一品布衣"

        assert device.clicks == [(225, 554)]

    def test_select_drama_researches_exact_suggestion_when_no_playable_card_exists(self):
        class DummySelector:
            def __init__(self, exists=False):
                self._exists = exists
                self.text = ""

            def exists(self, timeout=0):
                return self._exists

            def click(self):
                pass

            def set_text(self, value):
                self.text = value

            def get_text(self):
                return self.text

        class DummyDevice:
            def __init__(self):
                self.clicks = []
                self.input = DummySelector(True)
                self.search_clicks = 0

            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" class="android.widget.EditText" text="一品布衣" bounds="[88,64][772,136]" />'
                    '<node package="com.phoenix.read" text="搜索" bounds="[790,70][860,130]" />'
                    '<node package="com.phoenix.read" text="一品布衣3：朝堂篇" bounds="[160,181][434,224]" />'
                    '<node package="com.phoenix.read" text="第3季" bounds="[160,232][221,260]" />'
                    '<node package="com.phoenix.read" text="4187万热度" bounds="[357,232][481,260]" />'
                    '<node package="com.phoenix.read" text="一品布衣1" bounds="[80,682][220,724]" />'
                    '<node package="com.phoenix.read" text="一品布衣" bounds="[80,864][208,907]" />'
                )

            def window_size(self):
                return (900, 1600)

            def click(self, x, y):
                self.clicks.append((x, y))

            def __call__(self, **kwargs):
                if kwargs.get("className") == "android.widget.EditText":
                    return self.input
                if kwargs.get("text") == "搜索":
                    selector = DummySelector(True)
                    selector.click = lambda: setattr(self, "search_clicks", self.search_clicks + 1)
                    return selector
                return DummySelector()

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch("rpa.hongguo.operations.time.sleep"), patch.object(ops, "_sleep"):
            result = ops.select_drama("一品布衣")

        assert result["success"] is True
        assert result["playable"] is False
        assert result["drama_title"] == "一品布衣"
        assert "仍停留在搜索结果页" in result["message"]
        assert device.input.text == "一品布衣"
        assert device.search_clicks == 1
        assert device.clicks == [(144, 885)]

    def test_retry_search_from_clicked_result_clicks_playable_card(self):
        class DummySelector:
            def __init__(self, exists=False, on_click=None):
                self._exists = exists
                self.text = ""
                self.on_click = on_click

            def exists(self, timeout=0):
                return self._exists

            def click(self):
                if self.on_click:
                    self.on_click()

            def set_text(self, value):
                self.text = value

            def get_text(self):
                return self.text

        class DummyDevice:
            def __init__(self):
                self.clicks = []
                self.input = DummySelector(True)
                self.phase = "suggestions"

            def dump_hierarchy(self):
                if self.phase == "results":
                    return (
                        '<node package="com.phoenix.read" class="android.widget.EditText" text="一品布衣1" bounds="[88,64][772,136]" />'
                        '<node package="com.phoenix.read" text="搜索" bounds="[790,70][860,130]" />'
                        '<node package="com.phoenix.read" text="一品布衣1" bounds="[160,181][320,224]" />'
                        '<node package="com.phoenix.read" text="历史古代" bounds="[241,232][337,260]" />'
                        '<node package="com.phoenix.read" text="4091万热度" bounds="[357,232][481,260]" />'
                    )
                return (
                    '<node package="com.phoenix.read" class="android.widget.EditText" text="一品布衣" bounds="[88,64][772,136]" />'
                    '<node package="com.phoenix.read" text="搜索" bounds="[790,70][860,130]" />'
                    '<node package="com.phoenix.read" text="一品布衣1" bounds="[80,682][226,725]" />'
                )

            def window_size(self):
                return (900, 1600)

            def click(self, x, y):
                self.clicks.append((x, y))

            def __call__(self, **kwargs):
                if kwargs.get("className") == "android.widget.EditText":
                    return self.input
                if kwargs.get("text") == "搜索":
                    return DummySelector(True, on_click=lambda: setattr(self, "phase", "results"))
                return DummySelector()

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch("rpa.hongguo.operations.time.sleep"), patch.object(ops, "_sleep"):
            assert ops._retry_search_from_clicked_result("一品布衣1", "一品布衣") == "一品布衣1"

        assert device.input.text == "一品布衣1"
        assert device.clicks == [(225, 224)]

    def test_current_playing_title_reads_feed_title_with_chevron(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    '<node text="冒姓琅琊2 &gt;" bounds="[40,1360][280,1408]" />'
                    '<node text="第2季" bounds="[180,1420][260,1460]" />'
                    '<node text="观看完整短剧 · 全61集" bounds="[60,1640][520,1690]" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._current_playing_title() == "冒姓琅琊2"

    def test_current_playing_title_ignores_episode_caption_text(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    '<node text="第1集 | 牧哥儿，要老婆不？开金口就送来…" bounds="[40,1360][720,1408]" />'
                    '<node text="热评：这段太上头了" bounds="[40,1480][720,1530]" />'
                    '<node text="选集 · 已完结 · 全105集" bounds="[60,1640][520,1690]" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._current_playing_title() == ""

    def test_current_playing_title_ignores_shell_completion_text(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    '<node text="· 已完结 · 全119集" bounds="[50,1360][420,1410]" />'
                    '<node text="观看完整短剧·全119集" bounds="[52,1500][540,1560]" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._current_playing_title() == ""

    def test_current_playing_title_reads_title_from_contextual_card(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    '<node text="若如此" bounds="[72,1030][180,1080]" />'
                    '<node text="聚宝仙盆之杂灵根才是真BOSS" bounds="[50,1120][520,1180]" />'
                    '<node text="第1季" bounds="[60,1230][150,1270]" />'
                    '<node text="观看完整漫剧·全99集" bounds="[52,1500][540,1560]" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._current_playing_title() == "聚宝仙盆之杂灵根才是真BOSS"

    def test_current_playing_title_ignores_channel_account_name(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    '<node text="@蜗牛短剧" bounds="[48,1120][280,1180]" />'
                    '<node text="第9集" bounds="[60,1230][150,1270]" />'
                    '<node text="观看完整短剧·全105集" bounds="[52,1500][540,1560]" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._current_playing_title() == ""


class TestHongguoLoginDetails:
    def test_connect_uses_configured_device_without_fallback(self):
        calls = []

        class DummyU2:
            def connect(self, addr):
                calls.append(addr)
                if addr == "offline-device":
                    raise RuntimeError("offline")
                return MagicMock(info={})

        with patch.object(hongguo_device, "_load_u2", return_value=DummyU2()):
            with patch.object(hongguo_device, "discover_addrs", return_value=["online-device"]):
                with pytest.raises(RuntimeError, match="offline"):
                    hongguo_device.connect("offline-device")

        assert calls == ["offline-device"]

    def test_get_device_info_returns_emulator_context(self):
        class DummyDevice:
            serial = "127.0.0.1:5555"
            info = {"sdkInt": 29, "productName": "ASUS_AI2401_A"}
            device_info = {"brand": "ROG", "model": "ASUS_AI2401_A", "version": "14"}

            def window_size(self):
                return (900, 1600)

            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "SplashActivity"}

        info = HongguoOperations(DummyDevice()).get_device_info()
        assert info["serial"] == "127.0.0.1:5555"
        assert info["emulator"] == "雷电模拟器"
        assert info["model"] == "ASUS_AI2401_A"
        assert info["resolution"] == "900x1600"
        assert info["current_package"] == "com.phoenix.read"

    def test_get_device_info_marks_mumu_emulator_serial(self):
        class DummyDevice:
            serial = "emulator-5554"
            info = {"productName": "ASUS_AI2401_A"}
            device_info = {"brand": "ROG", "model": "ASUS_AI2401_A"}

            def window_size(self):
                return (1080, 1920)

            def app_current(self):
                return {}

        info = HongguoOperations(DummyDevice()).get_device_info()
        assert info["emulator"] == "MuMu 模拟器"

    def test_get_device_info_marks_network_phone(self):
        class DummyDevice:
            serial = "192.168.3.134:5555"
            info = {"productName": "shennong"}
            device_info = {"brand": "Xiaomi", "model": "23116PN5BC"}

            def window_size(self):
                return (900, 1600)

            def app_current(self):
                return {}

        info = HongguoOperations(DummyDevice()).get_device_info()
        assert info["emulator"] == "真机/网络 ADB"

    def test_get_account_info_extracts_profile_fields(self):
        class DummyDevice:
            def window_size(self):
                return (1080, 1920)

            def dump_hierarchy(self):
                return (
                    'text="我的钱包" text="姜维测试号" '
                    'text="红果号: HG123456" text="编辑资料"'
                )

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_open_profile_tab", return_value=True):
            account = ops.get_account_info()
        assert account["logged_in"] is True
        assert account["nickname"] == "姜维测试号"
        assert account["hongguo_id"] == "HG123456"

    def test_get_account_info_returns_to_search_home_after_reading_profile(self):
        class DummyDevice:
            def window_size(self):
                return (1080, 1920)

            def dump_hierarchy(self):
                return (
                    'text="我的钱包" text="姜维测试号" '
                    'text="红果号: HG123456" text="编辑资料"'
                )

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_open_profile_tab", return_value=True):
            with patch.object(ops, "_return_to_search_home", return_value=True) as recover:
                account = ops.get_account_info()

        assert account["logged_in"] is True
        recover.assert_called_once()

    def test_get_account_info_prefers_profile_name_near_hongguo_id_over_launcher_ad(self):
        class DummyDevice:
            def window_size(self):
                return (900, 1600)

            def dump_hierarchy(self):
                return (
                    'text="仙逆：战天道" text="游戏中心" text="每日新发现" '
                    'text="avatar image" text="用户名2667338" '
                    'text="红果号: 209734115491" text="关注" text="编辑资料"'
                )

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_open_profile_tab", return_value=True):
            account = ops.get_account_info()
        assert account["logged_in"] is True
        assert account["nickname"] == "用户名2667338"
        assert account["hongguo_id"] == "209734115491"

    def test_get_account_info_returns_from_follow_fans_page(self):
        class DummyDevice:
            def __init__(self):
                self.back_count = 0

            def window_size(self):
                return (900, 1600)

            def dump_hierarchy(self):
                if self.back_count == 0:
                    return (
                        '<node package="com.phoenix.read" text="用户名2667338" />'
                        '<node package="com.phoenix.read" text="关注" />'
                        '<node package="com.phoenix.read" text="粉丝" />'
                        '<node package="com.phoenix.read" text="暂无关注的用户" />'
                    )
                return (
                    '<node package="com.phoenix.read" text="用户名2667338" />'
                    '<node package="com.phoenix.read" text="红果号: 209734115491" />'
                    '<node package="com.phoenix.read" text="编辑资料" />'
                )

            def press(self, key):
                if key == "back":
                    self.back_count += 1

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch.object(ops, "_open_profile_tab", return_value=True):
            with patch.object(ops, "_return_to_search_home", return_value=True):
                account = ops.get_account_info()

        assert device.back_count == 1
        assert account["logged_in"] is True
        assert account["nickname"] == "用户名2667338"
        assert account["hongguo_id"] == "209734115491"

    def test_open_profile_tab_returns_from_follow_fans_page_before_tapping_tab(self):
        class DummyDevice:
            def __init__(self):
                self.back_count = 0
                self.coordinate_clicks = []

            def window_size(self):
                return (900, 1600)

            def dump_hierarchy(self):
                if self.back_count == 0:
                    return (
                        '<node package="com.phoenix.read" text="用户名2667338" />'
                        '<node package="com.phoenix.read" text="关注" />'
                        '<node package="com.phoenix.read" text="粉丝" />'
                        '<node package="com.phoenix.read" text="暂无关注的用户" />'
                    )
                return (
                    '<node package="com.phoenix.read" text="用户名2667338" />'
                    '<node package="com.phoenix.read" text="红果号: 209734115491" />'
                    '<node package="com.phoenix.read" text="编辑资料" />'
                )

            def press(self, key):
                if key == "back":
                    self.back_count += 1

            def click(self, x, y):
                self.coordinate_clicks.append((x, y))

            def __call__(self, **kwargs):
                return MagicMock(exists=MagicMock(return_value=False))

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch.object(ops, "_close_popups"), patch("rpa.hongguo.operations.time.sleep"):
            assert ops._open_profile_tab() is True

        assert device.back_count == 1
        assert device.coordinate_clicks == []

    def test_check_login_playback_page_is_not_logged_in(self):
        class DummyDevice:
            def window_size(self):
                return (1080, 1920)

            def dump_hierarchy(self):
                return 'text="\u7b2c1\u96c6" text="\u8bc4\u8bba" text="\u9009\u96c6"'

            def __call__(self, **kwargs):
                return MagicMock(exists=MagicMock(return_value=False))

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_close_popups"):
            result = ops.check_login()
        assert result["logged_in"] is False
        assert result["status"] == "playback_only"

    def test_check_login_uses_current_xml_login_prompt_without_navigation(self):
        class DummyDevice:
            def __init__(self):
                self.clicked = False

            def window_size(self):
                return (1080, 1920)

            def dump_hierarchy(self):
                return 'text="\u7acb\u5373\u767b\u5f55" text="\u624b\u673a\u53f7\u767b\u5f55"'

            def __call__(self, **kwargs):
                return MagicMock(exists=MagicMock(return_value=False))

            def click(self, x, y):
                self.clicked = True

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch.object(ops, "_close_popups"):
            result = ops.check_login()
        assert result["logged_in"] is False
        assert result["status"] == "not_logged_in"
        assert device.clicked is False

    def test_check_login_ignores_launcher_login_ad_text(self):
        class DummySelector:
            def exists(self, timeout=0):
                return False

        class DummyDevice:
            def window_size(self):
                return (900, 1600)

            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "com.dragon.read.component.biz.impl.SearchActivity"}

            def dump_hierarchy(self):
                return (
                    '<node package="app.lawnchair" text="仙逆正版授权手游，登录领千抽！" />'
                    '<node package="com.phoenix.read" text="一品布衣" />'
                    '<node package="com.phoenix.read" text="搜索" />'
                )

            def __call__(self, **kwargs):
                return DummySelector()

            def click(self, x, y):
                pass

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_close_popups"):
            result = ops.check_login()
        assert result["logged_in"] is False
        assert result["status"] == "unknown"

    def test_check_login_can_skip_popup_closing_after_app_ready(self):
        class DummyDevice:
            def window_size(self):
                return (1080, 1920)

            def dump_hierarchy(self):
                return 'text="\u7acb\u5373\u767b\u5f55" text="\u624b\u673a\u53f7\u767b\u5f55"'

            def __call__(self, **kwargs):
                return MagicMock(exists=MagicMock(return_value=False))

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_close_popups") as close_popups:
            result = ops.check_login(close_popups=False)
        assert result["status"] == "not_logged_in"
        close_popups.assert_not_called()

    def test_check_login_uses_current_xml_account_marker_without_navigation(self):
        class DummyDevice:
            def __init__(self):
                self.clicked = False

            def window_size(self):
                return (1080, 1920)

            def dump_hierarchy(self):
                return 'text="\u7ea2\u679c\u53f7: HG123456" text="\u7f16\u8f91\u8d44\u6599"'

            def __call__(self, **kwargs):
                return MagicMock(exists=MagicMock(return_value=False))

            def click(self, x, y):
                self.clicked = True

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch.object(ops, "_close_popups"):
            result = ops.check_login()
        assert result["logged_in"] is True
        assert result["status"] == "logged_in"
        assert device.clicked is False

    def test_check_login_returns_from_follow_fans_page_before_reading_status(self):
        class DummyDevice:
            def __init__(self):
                self.back_count = 0
                self.clicked = False

            def window_size(self):
                return (900, 1600)

            def dump_hierarchy(self):
                if self.back_count == 0:
                    return (
                        '<node package="com.phoenix.read" text="用户名2667338" />'
                        '<node package="com.phoenix.read" text="关注" />'
                        '<node package="com.phoenix.read" text="粉丝" />'
                        '<node package="com.phoenix.read" text="暂无关注的用户" />'
                    )
                return (
                    '<node package="com.phoenix.read" text="用户名2667338" />'
                    '<node package="com.phoenix.read" text="红果号: 209734115491" />'
                    '<node package="com.phoenix.read" text="编辑资料" />'
                )

            def press(self, key):
                if key == "back":
                    self.back_count += 1

            def __call__(self, **kwargs):
                return MagicMock(exists=MagicMock(return_value=False))

            def click(self, x, y):
                self.clicked = True

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch.object(ops, "_close_popups"):
            result = ops.check_login()

        assert result["logged_in"] is True
        assert result["status"] == "logged_in"
        assert device.back_count == 1
        assert device.clicked is False

    def test_get_account_info_rejects_promo_text_as_account(self):
        class DummyDevice:
            def window_size(self):
                return (1080, 1920)

            def dump_hierarchy(self):
                return (
                    'text="\u514d\u8d39\u77ed\u5267 \u5c3d\u5728\u7ea2\u679c(get)" '
                    'text="\u4e3b\u6f14\u8bf4\uff1a\u5c55\u5f00" text="\u7acb\u5373\u767b\u5f55" '
                    'text="\u624b\u673a\u53f7\u767b\u5f55"'
                )

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_open_profile_tab", return_value=True):
            account = ops.get_account_info()
        assert account["logged_in"] is False
        assert account["nickname"] == ""
        assert account["hongguo_id"] == ""

    def test_get_account_info_does_not_treat_generic_profile_actions_as_login(self):
        class DummyDevice:
            def window_size(self):
                return (1080, 1920)

            def dump_hierarchy(self):
                return (
                    'text="\u6211\u7684\u94b1\u5305" text="\u89c2\u770b\u5386\u53f2" '
                    'text="\u6536\u85cf" text="\u63d0\u73b0"'
                )

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_open_profile_tab", return_value=True):
            account = ops.get_account_info()
        assert account["logged_in"] is False
        assert account["nickname"] == ""
        assert account["hongguo_id"] == ""

    def test_get_account_info_clears_nickname_when_login_not_confirmed(self):
        class DummyDevice:
            def window_size(self):
                return (900, 1600)

            def dump_hierarchy(self):
                return 'text="一品布衣" text="第9集" text="选集" text="评论"'

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_open_profile_tab", return_value=True):
            with patch.object(ops, "_profile_visible", return_value=True):
                account = ops.get_account_info()
        assert account["logged_in"] is False
        assert account["nickname"] == ""
        assert account["hongguo_id"] == ""

    def test_get_account_info_does_not_read_launcher_recommendation_as_account(self):
        class DummyDevice:
            def window_size(self):
                return (900, 1600)

            def dump_hierarchy(self):
                return (
                    'text="仙逆：战天道" text="应用宝" text="Play 商店" '
                    'text="微信" text="抖音" text="红果免费短剧"'
                )

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_open_profile_tab", return_value=False):
            account = ops.get_account_info()
        assert account["logged_in"] is False
        assert account["nickname"] == ""
        assert account["hongguo_id"] == ""
        assert "未进入红果我的页面" in account["message"]

    def test_check_login_rejects_profile_actions_without_account_markers(self):
        class DummyDevice:
            def window_size(self):
                return (1080, 1920)

            def dump_hierarchy(self):
                return (
                    'text="\u6211\u7684\u94b1\u5305" text="\u89c2\u770b\u5386\u53f2" '
                    'text="\u6536\u85cf" text="\u63d0\u73b0"'
                )

            def __call__(self, **kwargs):
                return MagicMock(exists=MagicMock(return_value=False))

            def click(self, x, y):
                return None

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_close_popups"):
            result = ops.check_login()
        assert result["logged_in"] is False
        assert result["status"] == "unknown"

    def test_ensure_app_ready_does_not_restart_foreground_app(self):
        class DummyDevice:
            def __init__(self):
                self.started = False
                self.stopped = False

            def window_size(self):
                return (1080, 1920)

            def app_current(self):
                return {"package": "com.phoenix.read"}

            def dump_hierarchy(self):
                return 'text="首页" text="剧场" text="我的"'

            def app_start(self, package):
                self.started = True

            def app_stop(self, package):
                self.stopped = True

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch.object(ops, "_close_popups"):
            assert ops.ensure_app_ready() is True
        assert device.started is False
        assert device.stopped is False

    def test_ensure_app_ready_launches_from_launcher_icon_when_start_leaves_app_on_virtual_display(self):
        class DummyDevice:
            def __init__(self):
                self.stops = 0
                self.icon_clicked = False

            def window_size(self):
                return (900, 1600)

            def app_current(self):
                if self.icon_clicked:
                    return {"package": "com.phoenix.read", "activity": "com.dragon.read.pages.main.MainFragmentActivity"}
                return {"package": "app.lawnchair", "activity": ".LawnchairLauncher"}

            def dump_hierarchy(self):
                if self.icon_clicked:
                    return 'package="com.phoenix.read" text="首页" text="剧场" text="我的"'
                return (
                    '<node package="app.lawnchair" resource-id="app.lawnchair:id/launcher" text="" />'
                    '<node package="app.lawnchair" text="搜索" bounds="[450,499][665,672]" />'
                    '<node package="app.lawnchair" text="应用宝" bounds="[665,499][880,672]" />'
                    '<node package="app.lawnchair" text="Play 商店" bounds="[235,672][450,845]" />'
                    '<node package="app.lawnchair" text="微信" bounds="[665,1018][880,1191]" />'
                    '<node package="app.lawnchair" text="红果免费短剧" bounds="[20,1191][235,1364]" />'
                )

            def app_start(self, package):
                return None

            def app_stop(self, package):
                self.stops += 1

            def shell(self, command):
                return ""

            def click(self, x, y):
                self.icon_clicked = True

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch.object(ops, "_wait_app_ready", side_effect=[False, True]):
            with patch.object(ops, "_foreground_app_active", return_value=False):
                with patch.object(ops, "_close_popups"), patch("rpa.hongguo.operations.time.sleep"):
                    assert ops.ensure_app_ready(restart=True) is True

        assert device.stops == 2
        assert device.icon_clicked is True

    def test_app_root_stack_detects_hongguo_on_non_default_display(self):
        class DummyDevice:
            def window_size(self):
                return (900, 1600)

            def shell(self, command):
                if command == "am stack list":
                    return (
                        "RootTask id=199 bounds=[0,0][900,1600] displayId=19 userId=0\n"
                        "  taskId=199: com.phoenix.read/com.dragon.read.pages.splash.SplashActivity "
                        "bounds=[0,0][900,1600] userId=0 visible=true "
                        "topActivity=ComponentInfo{com.phoenix.read/com.dragon.read.component.shortvideo.impl.ShortSeriesActivity}\n"
                        "RootTask id=1 bounds=[0,0][900,1600] displayId=0 userId=0\n"
                        "  taskId=2: app.lawnchair/app.lawnchair.LawnchairLauncher bounds=[0,0][900,1600]\n"
                    )
                return ""

        ops = HongguoOperations(DummyDevice())
        assert ops._app_root_stack_on_non_default_display() == "199"

    def test_ensure_app_ready_moves_hongguo_stack_back_to_default_display(self):
        class DummyDevice:
            def __init__(self):
                self.commands = []
                self.moved = False

            def window_size(self):
                return (900, 1600)

            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity"}

            def dump_hierarchy(self):
                if self.moved:
                    return 'package="com.phoenix.read" text="全屏观看" text="选集"'
                return (
                    '<node package="app.lawnchair" resource-id="app.lawnchair:id/launcher" text="" />'
                    '<node package="app.lawnchair" text="搜索" bounds="[450,499][665,672]" />'
                    '<node package="app.lawnchair" text="应用宝" bounds="[665,499][880,672]" />'
                    '<node package="app.lawnchair" text="Play 商店" bounds="[235,672][450,845]" />'
                    '<node package="app.lawnchair" text="微信" bounds="[665,1018][880,1191]" />'
                    '<node package="app.lawnchair" text="红果免费短剧" bounds="[20,1191][235,1364]" />'
                    '<node package="com.phoenix.read" text="全屏观看" bounds="[422,1054][518,1087]" />'
                )

            def shell(self, command):
                self.commands.append(command)
                if command == "am stack list":
                    return (
                        "RootTask id=199 bounds=[0,0][900,1600] displayId=19 userId=0\n"
                        "  taskId=199: com.phoenix.read/com.dragon.read.pages.splash.SplashActivity\n"
                    )
                if command == "am display move-stack 199 0":
                    self.moved = True
                return ""

            def app_start(self, package):
                return None

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch.object(ops, "_wait_app_ready", return_value=True):
            with patch.object(ops, "_close_popups"), patch("rpa.hongguo.operations.time.sleep"):
                assert ops.ensure_app_ready() is True

        assert "am display move-stack 199 0" in device.commands

    def test_move_app_stack_rejects_stale_launcher_xml_after_move(self):
        class DummyDevice:
            def __init__(self):
                self.commands = []

            def window_size(self):
                return (900, 1600)

            def app_current(self):
                return {"package": "com.phoenix.read", "activity": "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity"}

            def dump_hierarchy(self):
                return (
                    '<node package="app.lawnchair" text="搜索" />'
                    '<node package="app.lawnchair" text="应用宝" />'
                    '<node package="app.lawnchair" text="微信" />'
                )

            def shell(self, command):
                self.commands.append(command)
                if command == "am stack list":
                    return (
                        "RootTask id=199 bounds=[0,0][900,1600] displayId=19 userId=0\n"
                        "  taskId=199: com.phoenix.read/com.dragon.read.component.shortvideo.impl.ShortSeriesActivity\n"
                    )
                return ""

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch("rpa.hongguo.operations.time.sleep"):
            assert ops._move_app_stack_to_default_display() is False

        assert "am display move-stack 199 0" in device.commands

    def test_open_search_moves_hongguo_stack_to_default_display_first(self):
        class DummySelector:
            def exists(self, timeout=0):
                return False

        class DummyDevice:
            def __init__(self):
                self.commands = []
                self.clicks = []
                self.moved = False
                self.search_opened = False

            def window_size(self):
                return (900, 1600)

            def app_current(self):
                activity = (
                    "com.dragon.read.component.biz.impl.SearchActivity"
                    if self.search_opened
                    else "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity"
                )
                return {"package": "com.phoenix.read", "activity": activity}

            def dump_hierarchy(self):
                if self.moved:
                    return (
                        '<node package="com.phoenix.read" text="搜索" bounds="[720,52][820,120]" />'
                        '<node package="com.phoenix.read" text="全屏观看" bounds="[422,1054][518,1087]" />'
                    )
                return (
                    '<node package="app.lawnchair" text="搜索" />'
                    '<node package="app.lawnchair" text="应用宝" />'
                    '<node package="app.lawnchair" text="微信" />'
                    '<node package="com.phoenix.read" text="全屏观看" />'
                )

            def shell(self, command):
                self.commands.append(command)
                if command == "am stack list":
                    return (
                        "RootTask id=199 bounds=[0,0][900,1600] displayId=19 userId=0\n"
                        "  taskId=199: com.phoenix.read/com.dragon.read.component.shortvideo.impl.ShortSeriesActivity\n"
                    )
                if command == "am display move-stack 199 0":
                    self.moved = True
                if "dragon8662://search" in command:
                    self.search_opened = True
                return ""

            def click(self, x, y):
                self.clicks.append((x, y))

            def __call__(self, **kwargs):
                return DummySelector()

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch.object(ops, "_close_popups"), patch("rpa.hongguo.operations.time.sleep"):
            assert ops._open_search() is True

        assert "am display move-stack 199 0" in device.commands
        assert not any("dragon8662://search" in command for command in device.commands)
        assert device.clicks == [(770, 86)]

    def test_ensure_app_ready_starts_when_not_foreground(self):
        class DummyDevice:
            def __init__(self):
                self.started = False

            def window_size(self):
                return (1080, 1920)

            def app_current(self):
                return {"package": "android"}

            def app_start(self, package):
                self.started = True

            def shell(self, command):
                self.started = True

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch.object(ops, "_wait_app_ready", return_value=True):
            with patch.object(ops, "_close_popups"):
                assert ops.ensure_app_ready() is True
        assert device.started is True

    def test_extract_account_nickname_filters_promo_copy(self):
        ops = HongguoOperations(MagicMock(window_size=MagicMock(return_value=(1080, 1920))))
        nickname = ops._extract_account_nickname(
            [
                "\u514d\u8d39\u77ed\u5267 \u5c3d\u5728\u7ea2\u679c(get)",
                "\u4e3b\u6f14\u8bf4\uff1a\u8fd9\u5267\u592a\u4e0a\u5934",
                "\u5c55\u5f00",
            ]
        )
        assert nickname == ""

    def test_extract_hongguo_id_rejects_promo_get_suffix(self):
        ops = HongguoOperations(MagicMock(window_size=MagicMock(return_value=(1080, 1920))))
        hongguo_id = ops._extract_hongguo_id(
            ["\u514d\u8d39\u77ed\u5267 \u5c3d\u5728\u7ea2\u679c(get)"],
            'text="\u514d\u8d39\u77ed\u5267 \u5c3d\u5728\u7ea2\u679c(get)"',
        )
        assert hongguo_id == ""

    def test_verify_comment_does_not_rewind_after_episode_jump(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    'resource-id="com.phoenix.read:id/cdi" '
                    'text="第2集" package="com.phoenix.read" bounds="[88,48][636,136]"'
                )

            def window_size(self):
                return (900, 1600)

            def __call__(self, **kwargs):
                return MagicMock(exists=MagicMock(return_value=False))

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "ensure_playback_page") as ensure:
            result = ops.verify_comment("越看越过瘾", 1, "")
        assert result["verified"] is False
        assert "跳过回退验证" in result["message"]
        ensure.assert_not_called()


class TestHongguoCommentGeneration:
    def test_prompt_leak_comment_is_rejected(self):
        generator = CommentGenerator({})
        with pytest.raises(CommentGenerationError):
            generator._clean_comment("用户指令是：我是短剧评论生成器，只输出一条可直接发布的中文评论正文。不要")

    def test_prompt_leak_variants_are_rejected(self):
        generator = CommentGenerator({})
        leaks = [
            "嗯，用户想要一条针对短剧《一品布衣》的自然短评！",
            "输出一条直接发布到红果短剧评论区的中文短评。",
            "生成一条中文短评，不要带任何说明。",
        ]
        for leak in leaks:
            with pytest.raises(CommentGenerationError):
                generator._clean_comment(leak)

    def test_current_season_request_comment_is_rejected(self):
        generator = CommentGenerator({})
        with pytest.raises(CommentGenerationError):
            generator._clean_comment(
                "第二季赶紧安排上，边关开荒带娃这段简直太上头了",
                title="发配边关，罪妻开荒养出战神第二季",
            )

    def test_prompt_rule_fragment_comment_is_rejected(self):
        generator = CommentGenerator({})
        with pytest.raises(CommentGenerationError):
            generator._clean_comment("-口语化、接地气、有情绪，但不过度夸张。-优先12")

    def test_template_falls_back_when_requesting_current_season(self):
        generator = CommentGenerator({})
        with patch("rpa.hongguo.comment_gen.random.choice", side_effect=lambda items: items[0]):
            comment = generator.pick_template(
                ["第二季赶紧安排上，边关开荒带娃这段简直太上头了"],
                "发配边关，罪妻开荒养出战神第二季",
        )
        assert "第二季赶紧" not in comment
        assert "第二季" not in comment
        assert "第三季" in comment

    def test_ai_falls_back_when_requesting_current_season(self):
        generator = CommentGenerator({"enabled": True, "api_key": "x"})
        with patch.object(generator, "_generate_remote_comment", side_effect=CommentGenerationError("bad season")):
            with patch("rpa.hongguo.comment_gen.random.choice", side_effect=lambda items: items[0]):
                comment, usage = generator.generate_ai_comment_with_usage("发配边关，罪妻开荒养出战神第二季")
        assert usage == {}
        assert "第二季赶紧" not in comment

    def test_local_comment_can_request_next_season(self):
        generator = CommentGenerator({})
        with patch("rpa.hongguo.comment_gen.random.choice", side_effect=lambda items: items[0]):
            comment = generator._generate_local_comment("发配边关，罪妻开荒养出战神第二季")
        assert "第三季" in comment
        assert "第二季赶紧" not in comment

    def test_clean_comment_trims_at_natural_boundary(self):
        generator = CommentGenerator({})
        comment = generator._clean_comment(
            "这一季的罪妻太飒了！在边关白手起家，硬生生把荒地种成粮仓，养出的战神简直太燃了",
            title="罪妻开荒第六季",
        )
        assert comment == "这一季的罪妻太飒了！在边关白手起家，硬生生把荒地种成粮仓！"
        assert len(comment) <= 36
        assert not comment.endswith("简直")

    def test_remote_comment_payload_includes_persona_and_grounded_style(self):
        generator = CommentGenerator(
            {
                "enabled": True,
                "api_key": "test-key",
                "base_url": "https://example.test/v1",
                "model": "mimo-v2.5",
                "max_tokens": 512,
                "comment_style": "funny",
                "default_persona": "爱轻吐槽的真实观众",
                "comment_persona": {"persona": "宝妈号，评论生活化", "style": "plot"},
                "account_info": {"nickname": "小姜"},
            }
        )
        captured = {}

        class DummyResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(
                    {
                        "choices": [{"message": {"content": "这反转可以，下一集得接着看"}}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
                    }
                ).encode("utf-8")

        def fake_urlopen(req, timeout=0):
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            return DummyResponse()

        with patch("rpa.hongguo.comment_gen.request.urlopen", side_effect=fake_urlopen):
            comment, usage = generator._generate_remote_comment("测试短剧第二季")

        user_prompt = captured["payload"]["messages"][1]["content"]
        system_prompt = captured["payload"]["messages"][0]["content"]
        assert comment == "这反转可以，下一集得接着看"
        assert usage["model"] == "mimo-v2.5"
        assert captured["payload"]["max_tokens"] == 120
        assert "宝妈号，评论生活化" in user_prompt
        assert "小姜" in user_prompt
        assert "嗑剧情" in user_prompt
        assert "接地气" in system_prompt

    def test_public_ai_settings_exposes_comment_persona_fields(self):
        settings = public_ai_settings(
            {
                "comment_style": "plot",
                "default_persona": "剧情党",
                "account_personas": [{"nickname": "A", "persona": "爱追反转"}],
            }
        )
        assert settings["comment_style"] == "plot"
        assert settings["default_persona"] == "剧情党"
        assert settings["account_personas"][0]["nickname"] == "A"

    def test_click_visible_episode_node_handles_visible_bottom_row(self):
        class DummyDevice:
            def __init__(self):
                self.clicked = []
                self.swiped = []

            def window_size(self):
                return (900, 1600)

            def dump_hierarchy(self):
                nodes = []
                width = 124
                height = 124
                start_x = 32
                start_y = 1084
                gap_x = 18
                gap_y = 17
                for number in range(1, 19):
                    idx = number - 1
                    row = idx // 6
                    col = idx % 6
                    left = start_x + col * (width + gap_x)
                    top = start_y + row * (height + gap_y)
                    nodes.append(
                        f'<node text="{number}" bounds="[{left},{top}][{left + width},{top + height}]" />'
                    )
                return "".join(nodes)

            def click(self, x, y):
                self.clicked.append((x, y))

            def swipe(self, sx, sy, ex, ey, duration=0.3):
                self.swiped.append((sx, sy, ex, ey, duration))

            def __call__(self, **kwargs):
                return MagicMock(exists=MagicMock(return_value=False))

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch("rpa.hongguo.operations.time.sleep"):
            assert ops._click_visible_episode_node(13) is True
        assert device.clicked == [(94, 1428)]

    def test_open_episode_panel_clicks_bottom_selection_bar_fallback(self):
        class DummySelector:
            def exists(self, timeout=0):
                return False

        class DummyDevice:
            def __init__(self):
                self.clicks = []
                self.panel_open = False

            def window_size(self):
                return (900, 1600)

            def dump_hierarchy(self):
                if self.panel_open:
                    return (
                        '<node package="com.phoenix.read" text="1-30" bounds="[48,930][160,990]" />'
                        '<node package="com.phoenix.read" text="1" bounds="[32,1084][156,1208]" />'
                        '<node package="com.phoenix.read" text="2" bounds="[174,1084][298,1208]" />'
                        '<node package="com.phoenix.read" text="3" bounds="[316,1084][440,1208]" />'
                    )
                return (
                    '<node package="com.phoenix.read" text="第13集" bounds="[88,48][220,120]" />'
                    '<node package="com.phoenix.read" text="选集 · 已完结 · 全105集" bounds="[32,1504][781,1584]" />'
                )

            def click(self, x, y):
                self.clicks.append((x, y))
                if y >= 1504:
                    self.panel_open = True

            def shell(self, command):
                self.clicks.append(command)
                if "tap" in command:
                    self.panel_open = True
                return ""

            def __call__(self, **kwargs):
                return DummySelector()

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch.object(ops, "_sleep"):
            assert ops._open_episode_panel() is True

        assert device.panel_open is True


class TestHongguoEngineWaits:
    def test_choose_title_accepts_missing_season_when_main_title_matches(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        assert engine._choose_title(
            "逆命谋臣第二季",
            ["逆命谋臣：从赘婿到帝王", "边疆王爷"],
        ) == "逆命谋臣：从赘婿到帝王"

    def test_choose_title_accepts_core_phrase_match(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        assert engine._choose_title(
            "罪妻开荒第二季",
            ["逆命谋臣：从赘婿到帝王", "发配边关，罪妻开荒养出战神"],
        ) == "发配边关，罪妻开荒养出战神"

    def test_choose_title_rejects_unrelated_title_with_season_keyword(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        assert engine._choose_title(
            "逆命谋臣第二季",
            ["边疆王爷", "热播榜 No.11"],
        ) == ""

    def test_choose_title_accepts_matching_keyword_prefix(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        assert engine._choose_title(
            "逆命谋臣",
            ["逆命谋臣：从赘婿到帝王"],
        ) == "逆命谋臣：从赘婿到帝王"

    def test_choose_title_rejects_later_seasons_for_base_title(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        assert (
            engine._choose_title(
                "一品布衣",
                ["一品布衣3：朝堂篇", "一品布衣2：烽火篇", "一品布衣4：割据篇"],
            )
            == ""
        )

    def test_choose_title_accepts_first_season_for_base_title(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        assert engine._choose_title("一品布衣", ["一品布衣1"]) == "一品布衣1"

    def test_choose_title_rejects_later_seasons_for_first_season_title(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        assert engine._choose_title("一品布衣1", ["一品布衣3：朝堂篇", "一品布衣2：烽火篇"]) == ""

    def test_resume_playback_check_runs_once(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        engine._resume_playback_check = True

        class DummyOps:
            def __init__(self):
                self.calls = 0

            def resume_playback_if_paused(self, allow_center_fallback=False):
                self.calls += 1
                return True

        ops = DummyOps()
        engine._resume_playback_if_needed(ops)
        engine._resume_playback_if_needed(ops)
        assert ops.calls == 1

    def test_pause_attempts_to_pause_player_when_ops_available(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        ops = MagicMock()
        ops.pause_playback_if_playing.return_value = True
        engine._ops = ops
        with patch.object(engine, "_update_task") as update:
            with patch.object(engine, "_log"):
                assert engine.pause() is True
        ops.pause_playback_if_playing.assert_called_once()
        update.assert_called_once_with(status="paused")

    def test_resume_sets_playback_check_only_when_ops_available(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        engine._ops = None
        with patch.object(engine, "_update_task"):
            with patch.object(engine, "_log"):
                assert engine.resume() is True
        assert engine._resume_playback_check is False

        engine._ops = MagicMock()
        with patch.object(engine, "_update_task"):
            with patch.object(engine, "_log"):
                assert engine.resume() is True
        assert engine._resume_playback_check is True

    def test_resume_playback_requires_strict_pause_marker(self):
        from rpa.hongguo.operations import HongguoOperations

        class DummyDevice:
            serial = "dummy"

            def __init__(self):
                self.clicks = []

            def window_size(self):
                return (900, 1600)

            def dump_hierarchy(self):
                return '<node text="播放" content-desc="播放" />'

            def click(self, x, y):
                self.clicks.append((x, y))

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_playback_visible", return_value=True):
            assert ops.resume_playback_if_paused(allow_center_fallback=True) is False

        assert ops.d.clicks == []

    def test_pause_playback_uses_center_fallback_when_pause_button_missing(self):
        from rpa.hongguo.operations import HongguoOperations

        class EmptySelector:
            def exists(self, timeout=0):
                return False

        class DummyDevice:
            serial = "dummy"

            def __init__(self):
                self.clicks = []
                self.dumps = 0

            def window_size(self):
                return (900, 1600)

            def dump_hierarchy(self):
                self.dumps += 1
                if self.clicks:
                    return '<node text="继续播放" />'
                return '<node text="暂停" />'

            def click(self, x, y):
                self.clicks.append((x, y))

            def __call__(self, **kwargs):
                return EmptySelector()

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_playback_visible", return_value=True):
            assert ops.pause_playback_if_playing() is True

        assert ops.d.clicks[-1] == (450, 704)

    def test_confirm_login_rejects_playback_only_without_account(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        ops = MagicMock()
        ops.check_login.return_value = {
            "logged_in": False,
            "status": "playback_only",
            "message": "红果播放页可用，未确认账号登录",
        }
        ops.get_account_info.return_value = {
            "logged_in": False,
            "nickname": "",
            "hongguo_id": "",
            "message": "红果未登录",
        }

        result = engine._confirm_login(ops)

        assert result["logged_in"] is False
        assert result["status"] == "playback_only"
        assert result["account"]["logged_in"] is False

    def test_login_wait_policy_allows_playback_only_to_continue(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        assert engine._login_requires_wait({"logged_in": False, "status": "playback_only"}) is False
        assert engine._login_requires_wait({"logged_in": False, "status": "unknown"}) is False
        assert engine._login_requires_wait({"logged_in": False, "status": "not_logged_in"}) is True
        assert engine._login_requires_wait({"logged_in": True, "status": "logged_in"}) is False

    def test_confirm_login_accepts_account_from_profile_after_playback_only(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        ops = MagicMock()
        ops.check_login.return_value = {
            "logged_in": False,
            "status": "playback_only",
            "message": "红果播放页可用，未确认账号登录",
        }
        ops.get_account_info.return_value = {
            "logged_in": True,
            "nickname": "姜维测试号",
            "hongguo_id": "HG123456",
            "message": "已识别红果账号",
        }

        result = engine._confirm_login(ops)

        assert result["logged_in"] is True
        assert result["status"] == "logged_in"
        assert result["account"]["hongguo_id"] == "HG123456"

    def test_confirm_login_downgrades_marker_login_when_account_is_not_logged_in(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        ops = MagicMock()
        ops.check_login.return_value = {
            "logged_in": True,
            "status": "logged_in",
            "message": "已登录",
        }
        ops.get_account_info.return_value = {
            "logged_in": False,
            "nickname": "",
            "hongguo_id": "",
            "message": "红果未登录",
        }

        result = engine._confirm_login(ops)

        assert result["logged_in"] is False
        assert result["status"] == "not_logged_in"
        assert result["message"] == "红果未登录"
        assert result["account"]["logged_in"] is False

    def test_wait_for_episode_rejects_skip_ahead(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        class DummyOps:
            def get_current_episode(self):
                return 3

        assert engine._wait_for_episode(DummyOps(), 2, {"comment_interval_sec": 1}) is False

    def test_wait_for_episode_rejects_matching_episode_on_off_target_drama(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        class DummyOps:
            def get_current_episode(self):
                return 12

            def _current_playing_title(self):
                return "聚宝仙盆之杂灵根才是真BOSS第三季"

            def _loose_title_match(self, expected, actual):
                return expected == actual

        assert engine._wait_for_episode(
            DummyOps(),
            12,
            {"drama_name": "一品布衣", "comment_interval_sec": 1},
        ) is False

    def test_wait_for_first_episode_requires_explicit_episode_match(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        class DummyOps:
            def get_current_episode(self):
                return 0

            def _playback_visible(self):
                return True

        with patch("rpa.hongguo.engine.time.time", side_effect=[0, 1, 93]):
            with patch("rpa.hongguo.engine.time.sleep"):
                assert engine._wait_for_episode(DummyOps(), 1, {"comment_interval_sec": 1}) is False

    def test_wait_for_next_episode_rejects_backtrack(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        class DummyOps:
            def get_current_episode(self):
                return 1

        assert engine._wait_for_next_episode(DummyOps(), 2, {"comment_interval_sec": 1}) is False

    def test_wait_for_next_episode_skips_feed_ad_before_confirming_target(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        class DummyOps:
            def __init__(self):
                self.calls = 0

            def skip_feed_ad_if_visible(self):
                self.calls += 1
                return self.calls == 1

            def get_current_episode(self):
                return 8

            def _current_playing_title(self):
                return "一品布衣"

            def _loose_title_match(self, expected, actual):
                return expected == actual

        ops = DummyOps()
        logs = []
        with patch.object(engine, "_log", side_effect=lambda level, message: logs.append((level, message))):
            assert engine._wait_for_next_episode(ops, 7, {"drama_name": "一品布衣", "comment_interval_sec": 1}) is True

        assert ("warn", "检测到追剧广告，已尝试上滑继续观看短剧") in logs
        assert ops.calls == 2

    def test_wait_for_next_episode_restarts_app_when_surface_drops_to_launcher(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        class DummyOps:
            def __init__(self):
                self.foreground_checks = 0
                self.restarts = 0

            def _known_not_foreground(self):
                self.foreground_checks += 1
                return self.foreground_checks == 1

            def ensure_app_ready(self, restart=False, timeout=12):
                self.restarts += 1
                return restart is True

            def skip_feed_ad_if_visible(self):
                return False

            def get_current_episode(self):
                return 9

            def _current_playing_title(self):
                return "一品布衣"

            def _loose_title_match(self, expected, actual):
                return expected == actual

        ops = DummyOps()
        logs = []
        with patch.object(engine, "_log", side_effect=lambda level, message: logs.append((level, message))):
            with patch("rpa.hongguo.engine.time.time", side_effect=[0, 1, 2]):
                with patch("rpa.hongguo.engine.time.sleep"):
                    assert engine._wait_for_next_episode(
                        ops,
                        8,
                        {"drama_name": "一品布衣", "comment_interval_sec": 1},
                    ) is True

        assert ops.restarts == 1
        assert ("warn", "检测到红果已离开播放页，已重新拉起红果") in logs

    def test_large_jump_crossing_multiple_comment_targets_is_untrusted(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        assert engine._large_jump_crosses_comment_plan(26, 105, {12, 27, 42, 57, 72, 87, 102}) is True
        assert engine._large_jump_crosses_comment_plan(26, 28, {12, 27, 42, 57, 72, 87, 102}) is False

    def test_wait_for_next_episode_does_not_force_target_by_default_when_stuck(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        class DummyOps:
            def __init__(self):
                self.played = []

            def get_current_episode(self):
                return 6

            def _playback_visible(self):
                return True

            def resume_playback_if_paused(self, allow_center_fallback=False):
                return False

            def play_episode(self, episode):
                self.played.append(episode)
                return True

        ops = DummyOps()
        times = [0, 1, 2, 50, 50, 70, 70, 91, 91, 92]
        with patch("rpa.hongguo.engine.time.time", side_effect=times):
            with patch("rpa.hongguo.engine.time.sleep"):
                assert engine._wait_for_next_episode(ops, 6, {"comment_interval_sec": 1}) is False
        assert ops.played == []

    def test_wait_for_next_episode_attempts_target_episode_when_stuck_and_enabled(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        class DummyOps:
            def __init__(self):
                self.played = []

            def get_current_episode(self):
                return 6

            def _playback_visible(self):
                return True

            def resume_playback_if_paused(self, allow_center_fallback=False):
                assert allow_center_fallback is False
                return True

            def play_episode(self, episode):
                self.played.append(episode)
                return True

        ops = DummyOps()
        times = [0, 1, 2, 50, 50, 70, 70, 71]
        with patch("rpa.hongguo.engine.time.time", side_effect=times):
            with patch("rpa.hongguo.engine.time.sleep"):
                with patch.object(engine, "_wait_for_episode", return_value=True) as wait:
                    assert engine._wait_for_next_episode(
                        ops,
                        6,
                        {"comment_interval_sec": 1, "force_next_on_stuck": True},
                    ) is True
        assert ops.played == [7]
        wait.assert_called_once()

    def test_wait_for_next_episode_does_not_force_switch_too_early(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        class DummyOps:
            def __init__(self):
                self.played = []

            def get_current_episode(self):
                return 6

            def _playback_visible(self):
                return True

            def resume_playback_if_paused(self, allow_center_fallback=False):
                return False

            def play_episode(self, episode):
                self.played.append(episode)
                return True

        ops = DummyOps()
        times = [0, 1, 2, 10, 20, 30, 40, 50, 60, 66, 91]
        with patch("rpa.hongguo.engine.time.time", side_effect=times):
            with patch("rpa.hongguo.engine.time.sleep"):
                with patch.object(engine, "_wait_for_episode", return_value=False):
                    assert engine._wait_for_next_episode(ops, 6, {"comment_interval_sec": 1}) is False
        assert ops.played == []

    def test_wait_for_next_episode_rejects_off_target_drama(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        class DummyOps:
            def _current_playing_title(self):
                return "冒姓琅琊2"

            def _loose_title_match(self, expected, actual):
                return expected == actual

            def get_current_episode(self):
                return 13

            def resume_playback_if_paused(self, allow_center_fallback=False):
                return False

        assert engine._wait_for_next_episode(
            DummyOps(),
            13,
            {"drama_name": "一品布衣", "comment_interval_sec": 1},
        ) is False

    def test_recover_episode_position_researches_target_when_off_target(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        class DummyOps:
            def __init__(self):
                self.searches = []
                self.selected = []
                self.played = []

            def _current_playing_title(self):
                return "冒姓琅琊2" if not self.played else "一品布衣"

            def _loose_title_match(self, expected, actual):
                return expected == actual

            def get_current_episode(self):
                return 14 if self.played else 0

            def search_drama(self, keyword, force_reset=False):
                self.searches.append((keyword, force_reset))
                return {"success": True, "titles": ["一品布衣"]}

            def select_drama(self, title):
                self.selected.append(title)
                return {"success": True, "playable": True, "drama_title": title}

            def play_episode(self, episode):
                self.played.append(episode)
                return True

        ops = DummyOps()
        with patch.object(engine, "_wait_for_episode", return_value=True):
            assert engine._recover_episode_position(ops, 14, {"drama_name": "一品布衣"}) is True

        assert ops.searches == [("一品布衣", True)]
        assert ops.selected == ["一品布衣"]
        assert ops.played == [14]

    def test_choose_title_prefers_exact_match_over_later_seasons(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        titles = [
            "一品布衣4：割据篇",
            "第4季",
            "一品布衣5:入蜀篇",
            "第5季",
            "一品布衣2：烽火篇",
            "一品布衣1",
            "一品布衣",
        ]

        assert engine._choose_title("一品布衣", titles) == "一品布衣"

    def test_choose_title_accepts_first_season_suffix_as_base_title(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        titles = [
            "一品布衣3：朝堂篇",
            "第3季",
            "一品布衣4：割据篇",
            "第4季",
            "一品布衣5:入蜀篇",
            "第5季",
            "一品布衣2：烽火篇",
            "一品布衣第五季",
            "一品布衣1",
        ]

        assert engine._choose_title("一品布衣", titles) == "一品布衣1"

    def test_choose_title_ignores_zero_width_characters(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        assert engine._choose_title("一品布衣", ["一品\u200b布衣"]) == "一品\u200b布衣"

    def test_choose_title_does_not_treat_number_suffix_as_main_title(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        titles = [
            "一品布衣2：烽火篇",
            "第2季",
            "历史古代",
            "一品布衣4：割据篇",
            "第4季",
        ]

        assert engine._choose_title("一品布衣", titles) == ""

    def test_loose_title_match_rejects_numbered_later_season_for_base_title(self):
        ops = HongguoOperations(MagicMock(window_size=MagicMock(return_value=(900, 1600))))

        assert ops._loose_title_match("一品布衣", "一品布衣2：烽火篇") is False
        assert ops._loose_title_match("一品布衣", "一品布衣1") is True
        assert ops._loose_title_match("一品布衣", "一品布衣第一季") is True
        assert ops._loose_title_match("一品布衣", "一品\u200b布衣") is True
        assert ops._loose_title_match("一品布衣", "一品布衣") is True

    def test_recover_episode_position_researches_target_after_plain_recovery_failure(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        class DummyOps:
            def __init__(self):
                self.searches = []
                self.selected = []
                self.played = []
                self.ensure_calls = 0

            def _current_playing_title(self):
                return "一品布衣" if self.played else ""

            def _loose_title_match(self, expected, actual):
                return expected == actual

            def get_current_episode(self):
                return 18 if self.played else 0

            def ensure_playback_page(self, episode):
                self.ensure_calls += 1
                return False

            def search_drama(self, keyword, force_reset=False):
                self.searches.append((keyword, force_reset))
                return {"success": True, "titles": ["一品布衣"]}

            def select_drama(self, title):
                self.selected.append(title)
                return {"success": True, "playable": True, "drama_title": title}

            def play_episode(self, episode):
                self.played.append(episode)
                return True

        ops = DummyOps()
        with patch.object(engine, "_wait_for_episode", return_value=True):
            assert engine._recover_episode_position(ops, 18, {"drama_name": "一品布衣"}) is True

        assert ops.ensure_calls == 2
        assert ops.searches == [("一品布衣", True)]
        assert ops.selected == ["一品布衣"]
        assert ops.played == [18]

    def test_recover_episode_position_rejects_off_target_after_research(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        class DummyOps:
            def __init__(self):
                self.searches = []
                self.selected = []
                self.played = []

            def _current_playing_title(self):
                return "万妖图录传第四季"

            def _loose_title_match(self, expected, actual):
                return expected == actual

            def get_current_episode(self):
                return 7

            def search_drama(self, keyword, force_reset=False):
                self.searches.append((keyword, force_reset))
                return {"success": True, "titles": ["一品布衣"]}

            def select_drama(self, title):
                self.selected.append(title)
                return {"success": True, "playable": True, "drama_title": title}

            def play_episode(self, episode):
                self.played.append(episode)
                return True

            def ensure_playback_page(self, episode):
                return False

        ops = DummyOps()
        with patch.object(engine, "_wait_for_episode", return_value=True):
            assert engine._recover_episode_position(ops, 7, {"drama_name": "一品布衣"}) is False

        assert ops.searches
        assert ops.played

    def test_recover_episode_position_restarts_app_when_launcher_is_visible(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        class DummyOps:
            def __init__(self):
                self.foreground_checks = 0
                self.restarts = 0
                self.ensure_calls = 0

            def _known_not_foreground(self):
                self.foreground_checks += 1
                return self.foreground_checks == 1

            def ensure_app_ready(self, restart=False, timeout=12):
                self.restarts += 1
                return restart is True

            def _current_playing_title(self):
                return "一品布衣"

            def _loose_title_match(self, expected, actual):
                return expected == actual

            def ensure_playback_page(self, episode):
                self.ensure_calls += 1
                return True

            def get_current_episode(self):
                return 14

        ops = DummyOps()
        logs = []
        with patch.object(engine, "_log", side_effect=lambda level, message: logs.append((level, message))):
            with patch.object(engine, "_wait_for_episode", return_value=True):
                with patch("rpa.hongguo.engine.time.sleep"):
                    assert engine._recover_episode_position(ops, 14, {"drama_name": "一品布衣"}) is True

        assert ops.restarts == 1
        assert ops.ensure_calls == 1
        assert ("warn", "检测到红果已离开播放页，已重新拉起红果") in logs

    def test_comment_episode_plan_keeps_interval_targets_each_run(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        plan = engine._comment_episode_plan(
            {
                "comment_mode": "specified",
                "start_episode": 1,
                "episode_interval": 10,
            },
            52,
        )
        assert plan == [1, 11, 21, 31, 41, 51]

    def test_pending_comment_plan_skips_already_successful_episodes(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        task = {
            "comment_mode": "specified",
            "start_episode": 12,
            "episode_interval": 12,
        }
        with patch.object(engine, "_completed_comment_episodes", return_value={12, 24, 99}):
            pending, skipped = engine._pending_comment_plan(task, 48)

        assert sorted(pending) == [36, 48]
        assert skipped == [12, 24]

    def test_pending_comment_plan_allows_all_episodes_to_be_skipped(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        task = {
            "comment_mode": "specified",
            "start_episode": 12,
            "episode_interval": 12,
        }
        with patch.object(engine, "_completed_comment_episodes", return_value={12, 24, 36}):
            pending, skipped = engine._pending_comment_plan(task, 36)

        assert pending == set()
        assert skipped == [12, 24, 36]

    def test_resolve_comment_persona_matches_hongguo_id(self):
        engine = TaskEngine(
            task_id=1,
            db_config={},
            screenshot_dir="C:/tmp",
            ai_config={
                "comment_style": "grounded",
                "default_persona": "默认观众",
                "account_personas": [
                    {"hongguo_id": "10086", "nickname": "甲", "persona": "爱吐槽的账号", "style": "funny"}
                ],
            },
        )
        persona = engine._resolve_comment_persona({"hongguo_id": "10086", "nickname": "乙"})
        assert persona["matched"] is True
        assert persona["persona"] == "爱吐槽的账号"
        assert persona["style"] == "funny"

    def test_current_ai_config_includes_account_persona(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp", ai_config={"model": "mimo-v2.5"})
        engine._account_info = {"nickname": "小姜"}
        engine._comment_persona = {"persona": "剧情党", "style": "plot", "matched": True}
        cfg = engine._current_ai_config()
        assert cfg["account_info"]["nickname"] == "小姜"
        assert cfg["comment_persona"]["persona"] == "剧情党"

    def test_comment_for_episode_uses_prewarmed_cache(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        lock = __import__("threading").Lock()
        cache = {11: ("cached comment", "ai", {"total_tokens": 1})}
        with patch("rpa.hongguo.engine.CommentGenerator") as generator:
            result = engine._comment_for_episode(cache, lock, 11, "短剧", {"content_source": "ai"})
        assert result == ("cached comment", "ai", {"total_tokens": 1})
        generator.assert_not_called()

    def test_comment_for_episode_populates_cache_on_miss(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        lock = __import__("threading").Lock()
        cache = {}
        generated = ("new comment", "template", {})
        with patch("rpa.hongguo.engine.CommentGenerator") as generator:
            generator.return_value.pick_template.return_value = generated[0]
            result = engine._comment_for_episode(
                cache,
                lock,
                21,
                "短剧",
                {"content_source": "template", "templates_json": "[\"new comment\"]"},
            )
        assert result == generated
        generator.return_value.generate_with_usage.assert_not_called()
        assert cache[21] == generated

    def test_comment_for_episode_uses_local_fallback_on_cache_miss_without_templates(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        lock = __import__("threading").Lock()
        cache = {}
        with patch("rpa.hongguo.engine.CommentGenerator") as generator:
            generator.return_value._generate_local_comment.return_value = "local comment"
            result = engine._comment_for_episode(cache, lock, 1, "短剧第二季", {"content_source": "ai", "templates_json": "[]"})
        assert result == ("local comment", "local", {})
        generator.return_value.generate_with_usage.assert_not_called()
        generator.return_value.generate_ai_comment_with_usage.assert_not_called()
        assert cache[1] == result

    def test_dedupe_comment_replaces_duplicate_with_local_comment(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        used = {"重复评论"}
        with patch("rpa.hongguo.engine.CommentGenerator") as generator:
            generator.return_value._generate_local_comment.side_effect = ["重复评论", "新的自然评论"]
            content, source = engine._dedupe_comment("重复评论", "ai", used, "短剧")
        assert content == "新的自然评论"
        assert source == "local"
        assert "新的自然评论" in used

    def test_dedupe_comment_replaces_similar_comment(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        used = {engine._normalize_comment_key("第七季赶紧安排上，这一季真的太上头了")}
        with patch("rpa.hongguo.engine.CommentGenerator") as generator:
            generator.return_value._generate_local_comment.return_value = "女主这段反击看得很爽"
            content, source = engine._dedupe_comment("第七季赶紧安排上这一季真的太上头了", "ai", used, "短剧")
        assert content == "女主这段反击看得很爽"
        assert source == "local"

    def test_safe_comment_content_falls_back_on_prompt_leak(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        with patch("rpa.hongguo.engine.CommentGenerator") as generator:
            generator.return_value._clean_comment.side_effect = CommentGenerationError("leak")
            generator.return_value._generate_local_comment.return_value = "这集节奏不错"
            content, source = engine._safe_comment_content("输出一条中文短评", "ai", "一品布衣")

        assert content == "这集节奏不错"
        assert source == "local"

    def test_used_comment_keys_loads_successful_history(self):
        engine = TaskEngine(task_id=7, db_config={}, screenshot_dir="C:/tmp")

        class DummyCursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql, params=None):
                self.sql = sql
                self.params = params

            def fetchall(self):
                return [
                    {"comment_text": "第七季赶紧安排上，这一季真的太上头了"},
                    {"comment_text": ""},
                    {"comment_text": None},
                ]

        class DummyConnection:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def cursor(self):
                return DummyCursor()

        with patch.object(engine, "_load_task", return_value={"started_at": None}):
            with patch.object(engine, "_connection", return_value=DummyConnection()):
                keys = engine._used_comment_keys()

        assert engine._normalize_comment_key("第七季赶紧安排上，这一季真的太上头了") in keys
        assert "" not in keys

    def test_completed_comment_episodes_filters_current_rule_generation(self):
        engine = TaskEngine(task_id=7, db_config={}, screenshot_dir="C:/tmp")
        rule_updated = datetime(2026, 6, 27, 10, 0, 0)
        captured = {}

        class DummyCursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql, params=None):
                captured["sql"] = sql
                captured["params"] = params

            def fetchall(self):
                return [{"episode_number": 12}, {"episode_number": 24}]

        class DummyConnection:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def cursor(self):
                return DummyCursor()

        with patch.object(engine, "_load_task", return_value={"updated_at": rule_updated}):
            with patch.object(engine, "_connection", return_value=DummyConnection()):
                episodes = engine._completed_comment_episodes()

        assert episodes == {12, 24}
        assert "created_at >= %s" in captured["sql"]
        assert captured["params"] == [7, rule_updated]

    def test_completed_comment_episodes_prefers_rule_updated_at(self):
        engine = TaskEngine(task_id=7, db_config={}, screenshot_dir="C:/tmp")
        rule_updated = datetime(2026, 6, 27, 10, 0, 0)
        status_updated = datetime(2026, 6, 27, 12, 0, 0)
        captured = {}

        class DummyCursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql, params=None):
                captured["params"] = params

            def fetchall(self):
                return [{"episode_number": 12}]

        class DummyConnection:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def cursor(self):
                return DummyCursor()

        with patch.object(
            engine,
            "_load_task",
            return_value={"rule_updated_at": rule_updated, "updated_at": status_updated},
        ):
            with patch.object(engine, "_connection", return_value=DummyConnection()):
                episodes = engine._completed_comment_episodes()

        assert episodes == {12}
        assert captured["params"] == [7, rule_updated]

    def test_used_comment_keys_filters_current_rule_generation(self):
        engine = TaskEngine(task_id=7, db_config={}, screenshot_dir="C:/tmp")
        rule_updated = datetime(2026, 6, 27, 10, 0, 0)
        captured = {}

        class DummyCursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql, params=None):
                captured["sql"] = sql
                captured["params"] = params

            def fetchall(self):
                return [{"comment_text": "这一集越看越上头"}]

        class DummyConnection:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def cursor(self):
                return DummyCursor()

        with patch.object(engine, "_load_task", return_value={"updated_at": rule_updated}):
            with patch.object(engine, "_connection", return_value=DummyConnection()):
                keys = engine._used_comment_keys()

        assert engine._normalize_comment_key("这一集越看越上头") in keys
        assert "created_at >= %s" in captured["sql"]
        assert captured["params"] == [7, rule_updated]

    def test_completed_comment_episodes_uses_rule_update_time_not_restart_time(self):
        engine = TaskEngine(task_id=7, db_config={}, screenshot_dir="C:/tmp")
        rule_updated = datetime(2026, 6, 27, 10, 0, 0)
        restarted = datetime(2026, 6, 27, 12, 0, 0)
        captured = {}

        class DummyCursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql, params=None):
                captured["sql"] = sql
                captured["params"] = params

            def fetchall(self):
                return [{"episode_number": 12}]

        class DummyConnection:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def cursor(self):
                return DummyCursor()

        with patch.object(engine, "_load_task", return_value={"started_at": restarted, "updated_at": rule_updated}):
            with patch.object(engine, "_connection", return_value=DummyConnection()):
                episodes = engine._completed_comment_episodes()

        assert episodes == {12}
        assert captured["params"] == [7, rule_updated]

    def test_save_record_does_not_mark_sent_without_sent_screenshot(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        captured = {}

        class DummyCursor:
            def execute(self, sql, values):
                captured["values"] = values

        class DummyConnection:
            def __init__(self):
                self.cursor_obj = DummyCursor()

            def cursor(self):
                return self

            def __enter__(self):
                return self.cursor_obj

            def __exit__(self, exc_type, exc, tb):
                return False

            def commit(self):
                pass

            def rollback(self):
                pass

            def close(self):
                pass

        with patch.object(engine, "_connection") as connection:
            connection.return_value.__enter__.return_value = DummyConnection()
            engine._save_record(11, "待发评论", "ai", "failed", screenshot_input="missed.png")
        values = captured["values"]
        assert values[5] is None
        assert values[6] is None

    def test_save_record_marks_sent_when_sent_screenshot_exists(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        captured = {}

        class DummyCursor:
            def execute(self, sql, values):
                captured["values"] = values

        class DummyConnection:
            def __init__(self):
                self.cursor_obj = DummyCursor()

            def cursor(self):
                return self

            def __enter__(self):
                return self.cursor_obj

            def __exit__(self, exc_type, exc, tb):
                return False

            def commit(self):
                pass

            def rollback(self):
                pass

            def close(self):
                pass

        with patch.object(engine, "_connection") as connection:
            connection.return_value.__enter__.return_value = DummyConnection()
            engine._save_record(21, "已发评论", "ai", "success", screenshot_sent="sent.png")
        values = captured["values"]
        assert values[5] is not None
        assert values[6] is not None

    def test_finish_task_sets_duration_seconds(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        started = datetime(2026, 6, 27, 10, 0, 0)
        updates = {}
        logs = []
        with patch.object(engine, "_load_task", return_value={"started_at": started}):
            with patch.object(engine, "_update_task", side_effect=lambda **kwargs: updates.update(kwargs)):
                with patch.object(engine, "_log", side_effect=lambda level, message: logs.append((level, message))):
                    with patch("rpa.hongguo.engine.datetime") as dt:
                        dt.now.return_value = started + timedelta(seconds=125)
                        engine._finish_task("completed")
        assert updates["status"] == "completed"
        assert updates["duration_seconds"] == 125
        assert ("info", "执行总时长: 2分5秒，状态: 已完成") in logs

    def test_format_duration_handles_hours_minutes_seconds(self):
        assert TaskEngine._format_duration(None) == "-"
        assert TaskEngine._format_duration(8) == "8秒"
        assert TaskEngine._format_duration(125) == "2分5秒"
        assert TaskEngine._format_duration(3661) == "1小时1分1秒"

    def test_start_task_initialization_clears_stale_progress_fields(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        updates = {}

        def capture_update(**kwargs):
            if kwargs.get("status") == "running":
                updates.update(kwargs)

        with patch.object(engine, "_update_task", side_effect=capture_update):
            with patch.object(engine, "_log"):
                with patch("rpa.hongguo.engine.check_connection", return_value=False):
                    engine._run()

        assert updates["status"] == "running"
        assert updates["completed_at"] is None
        assert updates["duration_seconds"] is None
        assert updates["current_episode"] == 0
        assert updates["total_episodes"] == 0
        assert updates["comments_sent"] == 0
        assert updates["comments_verified"] == 0
        assert updates["execution_plan_json"] is None

    def test_engine_progress_update_does_not_touch_rule_updated_at(self):
        engine = TaskEngine(task_id=7, db_config={}, screenshot_dir="C:/tmp")
        captured = {}

        class DummyCursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql, params=None):
                captured["sql"] = sql
                captured["params"] = params

        class DummyConnection:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def cursor(self):
                return DummyCursor()

        with patch.object(engine, "_connection", return_value=DummyConnection()):
            engine._update_task(current_episode=12)

        assert "current_episode=%s" in captured["sql"]
        assert "updated_at" not in captured["sql"]
        assert captured["params"] == [12, 7]

    def test_offline_device_failure_uses_finish_task(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp", device_addr="127.0.0.1:7555")
        finishes = {}

        with patch.object(engine, "_update_task"):
            with patch.object(engine, "_finish_task", side_effect=lambda **kwargs: finishes.update(kwargs)):
                with patch.object(engine, "_log"):
                    with patch("rpa.hongguo.engine.check_connection", return_value=False):
                        engine._run()

        assert finishes["status"] == "failed"
        assert finishes["error_message"] == "device 127.0.0.1:7555 not online"

    def test_engine_force_restarts_hongguo_at_task_start(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        ops = MagicMock()
        ops.launch_app.return_value = True
        ops.take_screenshot.return_value = "shot.png"
        ops.check_login.return_value = {"logged_in": True, "status": "logged_in", "message": "已登录"}
        ops.get_account_info.return_value = {"logged_in": True, "nickname": "小姜", "hongguo_id": "HG123"}
        ops.search_drama.side_effect = RuntimeError("stop after launch")

        with patch.object(engine, "_update_task"):
            with patch.object(engine, "_finish_task"):
                with patch.object(engine, "_log"):
                    with patch.object(engine, "_load_task", return_value={"id": 1, "drama_name": "一品布衣"}):
                        with patch("rpa.hongguo.engine.check_connection", return_value=True):
                            with patch("rpa.hongguo.engine.connect", return_value=MagicMock(serial="device")):
                                with patch("rpa.hongguo.engine.HongguoOperations", return_value=ops):
                                    engine._run()

        ops.launch_app.assert_called_once_with(force_restart=True)

    def test_dashboard_task_response_falls_back_created_at_and_duration(self):
        started = datetime(2026, 6, 27, 10, 0, 0)
        completed = started + timedelta(seconds=90)

        response = _serialize_task(
            {
                "id": 7,
                "drama_name": "测试短剧",
                "status": "completed",
                "templates_json": "[]",
                "playback_speed": "2.0x",
                "execution_plan_json": "{}",
                "started_at": started,
                "completed_at": completed,
                "duration_seconds": None,
                "created_at": None,
                "updated_at": started,
            }
        )
        assert response["created_at"] == started
        assert response["duration_seconds"] == 90

    def test_dashboard_task_list_orders_by_recent_activity(self):
        captured = {}

        class DummyCursor:
            def execute(self, sql, params):
                captured["sql"] = sql
                captured["params"] = params

            def fetchall(self):
                return []

        class DummyConnection:
            def cursor(self):
                return self

            def __enter__(self):
                return DummyCursor()

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("rpa.dashboard.routes_hongguo._connection") as connection:
            connection.return_value.__enter__.return_value = DummyConnection()
            import asyncio

            asyncio.run(list_tasks(status=None, limit=50, offset=0))
        assert "COALESCE(started_at, updated_at, created_at, completed_at) DESC" in captured["sql"]
        assert "ORDER BY id DESC" not in captured["sql"]

    def test_list_records_filters_to_current_run_by_default(self):
        started = datetime(2026, 6, 27, 10, 0, 0)
        captured = {}

        class DummyCursor:
            def execute(self, sql, params):
                captured["sql"] = sql
                captured["params"] = params

            def fetchone(self):
                return {
                    "id": 12,
                    "drama_name": "一品布衣",
                    "status": "running",
                    "started_at": started,
                    "templates_json": "[]",
                    "playback_speed": "2.0x",
                    "execution_plan_json": None,
                }

            def fetchall(self):
                return []

        class DummyConnection:
            def cursor(self):
                return self

            def __enter__(self):
                return DummyCursor()

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("rpa.dashboard.routes_hongguo._connection") as connection:
            connection.return_value.__enter__.return_value = DummyConnection()
            import asyncio

            asyncio.run(list_records(12, status=None, limit=50, offset=0))

        assert "created_at >= %s" in captured["sql"]
        assert started in captured["params"]

    def test_list_records_can_include_historical_records(self):
        started = datetime(2026, 6, 27, 10, 0, 0)
        captured = {}

        class DummyCursor:
            def execute(self, sql, params):
                captured["sql"] = sql
                captured["params"] = params

            def fetchone(self):
                return {
                    "id": 12,
                    "drama_name": "一品布衣",
                    "status": "running",
                    "started_at": started,
                    "templates_json": "[]",
                    "playback_speed": "2.0x",
                    "execution_plan_json": None,
                }

            def fetchall(self):
                return []

        class DummyConnection:
            def cursor(self):
                return self

            def __enter__(self):
                return DummyCursor()

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("rpa.dashboard.routes_hongguo._connection") as connection:
            connection.return_value.__enter__.return_value = DummyConnection()
            import asyncio

            asyncio.run(list_records(12, status=None, current_run_only=False, limit=50, offset=0))

        assert "created_at >= %s" not in captured["sql"]
        assert started not in captured["params"]

    def test_list_logs_filters_to_current_run_by_default(self):
        started = datetime(2026, 6, 27, 10, 0, 0)
        captured = {}

        class DummyCursor:
            def execute(self, sql, params):
                captured["sql"] = sql
                captured["params"] = params

            def fetchone(self):
                return {
                    "id": 12,
                    "drama_name": "一品布衣",
                    "status": "running",
                    "started_at": started,
                    "templates_json": "[]",
                    "playback_speed": "2.0x",
                    "execution_plan_json": None,
                }

            def fetchall(self):
                return []

        class DummyConnection:
            def cursor(self):
                return self

            def __enter__(self):
                return DummyCursor()

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("rpa.dashboard.routes_hongguo._connection") as connection:
            connection.return_value.__enter__.return_value = DummyConnection()
            import asyncio

            asyncio.run(list_logs(12, level=None, limit=50, offset=0))

        assert "created_at >= %s" in captured["sql"]
        assert started in captured["params"]

    def test_list_logs_can_include_historical_logs(self):
        started = datetime(2026, 6, 27, 10, 0, 0)
        captured = {}

        class DummyCursor:
            def execute(self, sql, params):
                captured["sql"] = sql
                captured["params"] = params

            def fetchone(self):
                return {
                    "id": 12,
                    "drama_name": "一品布衣",
                    "status": "running",
                    "started_at": started,
                    "templates_json": "[]",
                    "playback_speed": "2.0x",
                    "execution_plan_json": None,
                }

            def fetchall(self):
                return []

        class DummyConnection:
            def cursor(self):
                return self

            def __enter__(self):
                return DummyCursor()

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("rpa.dashboard.routes_hongguo._connection") as connection:
            connection.return_value.__enter__.return_value = DummyConnection()
            import asyncio

            asyncio.run(list_logs(12, level=None, current_run_only=False, limit=50, offset=0))

        assert "created_at >= %s" not in captured["sql"]
        assert started not in captured["params"]

    def test_latest_screenshot_file_filters_by_current_run_timestamp(self, tmp_path):
        shot_dir = tmp_path / "12"
        shot_dir.mkdir()
        old_file = shot_dir / "old.png"
        new_file = shot_dir / "new.png"
        old_file.write_text("old", encoding="utf-8")
        new_file.write_text("new", encoding="utf-8")
        import os

        old_ts = datetime(2026, 6, 27, 9, 0, 0).timestamp()
        new_ts = datetime(2026, 6, 27, 11, 0, 0).timestamp()
        os.utime(old_file, (old_ts, old_ts))
        os.utime(new_file, (new_ts, new_ts))

        with patch("rpa.dashboard.routes_hongguo._task_screenshot_dir", return_value=shot_dir):
            result = _latest_screenshot_file(12, since=datetime(2026, 6, 27, 10, 0, 0))

        assert result.endswith("new.png")

    def test_latest_screenshot_returns_none_when_only_old_screenshot_exists(self, tmp_path):
        shot_dir = tmp_path / "12"
        shot_dir.mkdir()
        old_file = shot_dir / "old.png"
        old_file.write_text("old", encoding="utf-8")
        import os

        old_ts = datetime(2026, 6, 27, 9, 0, 0).timestamp()
        os.utime(old_file, (old_ts, old_ts))
        captured = {}
        started = datetime(2026, 6, 27, 10, 0, 0)

        class DummyCursor:
            def __init__(self):
                self.fetchone_calls = 0

            def execute(self, sql, params):
                captured["sql"] = sql
                captured["params"] = params

            def fetchone(self):
                self.fetchone_calls += 1
                if self.fetchone_calls == 1:
                    return {
                        "id": 12,
                        "drama_name": "一品布衣",
                        "status": "running",
                        "started_at": started,
                        "templates_json": "[]",
                        "playback_speed": "2.0x",
                        "execution_plan_json": None,
                    }
                return None

        class DummyConnection:
            def cursor(self):
                return self

            def __enter__(self):
                return DummyCursor()

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("rpa.dashboard.routes_hongguo._task_screenshot_dir", return_value=shot_dir):
            with patch("rpa.dashboard.routes_hongguo._connection") as connection:
                connection.return_value.__enter__.return_value = DummyConnection()
                import asyncio

                result = asyncio.run(latest_screenshot(12, current_run_only=True))

        assert result["screenshot_path"] is None
        assert "created_at >= %s" in captured["sql"]
        assert started in captured["params"]

    def test_update_task_resets_stale_run_state_when_rule_changes(self):
        captured = {}

        class DummyCursor:
            def execute(self, sql, params=None):
                captured.setdefault("calls", []).append((sql, params))

            def fetchone(self):
                return {
                    "id": 12,
                    "drama_name": "一品布衣",
                    "status": "completed",
                    "started_at": datetime(2026, 6, 27, 10, 0, 0),
                    "completed_at": datetime(2026, 6, 27, 11, 0, 0),
                    "duration_seconds": 3600,
                    "current_episode": 99,
                    "total_episodes": 100,
                    "comments_sent": 8,
                    "comments_verified": 8,
                    "error_message": "old error",
                    "templates_json": "[]",
                    "playback_speed": "2.0x",
                    "execution_plan_json": "{}",
                }

        class DummyConnection:
            def cursor(self):
                return self

            def __enter__(self):
                return DummyCursor()

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("rpa.dashboard.routes_hongguo._connection") as connection:
            connection.return_value.__enter__.return_value = DummyConnection()
            import asyncio

            result = asyncio.run(update_task(12, TaskUpdate(start_episode=12, episode_interval=13)))

        update_sql, update_params = next(
            call for call in captured["calls"] if "UPDATE hongguo_comment_tasks" in call[0]
        )
        assert result["updated"] is True
        assert "execution_plan_json=%s" in update_sql
        assert "status=%s" in update_sql
        assert "started_at=%s" in update_sql
        assert "completed_at=%s" in update_sql
        assert "duration_seconds=%s" in update_sql
        assert "current_episode=%s" in update_sql
        assert "comments_sent=%s" in update_sql
        assert "comments_verified=%s" in update_sql
        assert "rule_updated_at=%s" in update_sql
        assert "pending" in update_params
        assert None in update_params
        assert update_params.count(0) >= 4

    def test_update_task_noop_does_not_reset_run_state(self):
        captured = {"calls": []}
        started = datetime(2026, 6, 27, 10, 0, 0)

        class DummyCursor:
            def execute(self, sql, params=None):
                captured["calls"].append((sql, params))

            def fetchone(self):
                return {
                    "id": 12,
                    "drama_name": "一品布衣",
                    "comment_mode": "specified",
                    "content_source": "ai",
                    "playback_speed": "2.0x",
                    "start_episode": 12,
                    "episode_interval": 13,
                    "comment_interval_sec": 30,
                    "random_comment_count": 5,
                    "random_min_interval": 10,
                    "random_max_interval": 30,
                    "status": "paused",
                    "started_at": started,
                    "completed_at": None,
                    "duration_seconds": None,
                    "current_episode": 3,
                    "total_episodes": 105,
                    "comments_sent": 0,
                    "comments_verified": 0,
                    "templates_json": "[]",
                    "execution_plan_json": "{}",
                }

        class DummyConnection:
            def cursor(self):
                return self

            def __enter__(self):
                return DummyCursor()

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("rpa.dashboard.routes_hongguo._connection") as connection:
            connection.return_value.__enter__.return_value = DummyConnection()
            import asyncio

            result = asyncio.run(
                update_task(
                    12,
                    TaskUpdate(
                        drama_name="一品布衣",
                        comment_mode="specified",
                        content_source="ai",
                        playback_speed="2.0x",
                        start_episode=12,
                        episode_interval=13,
                        comment_interval_sec=30,
                        random_comment_count=5,
                        random_min_interval=10,
                        random_max_interval=30,
                        templates=[],
                    ),
                )
            )

        assert result["status"] == "paused"
        assert result["updated"] is False
        assert result["current_episode"] == 3
        assert not any("UPDATE hongguo_comment_tasks" in sql for sql, _ in captured["calls"])
        assert not any("INSERT INTO hongguo_execution_logs" in sql for sql, _ in captured["calls"])

    def test_update_task_status_only_does_not_reset_run_state(self):
        captured = {}

        class DummyCursor:
            def execute(self, sql, params=None):
                captured.setdefault("calls", []).append((sql, params))

            def fetchone(self):
                return {
                    "id": 12,
                    "drama_name": "一品布衣",
                    "status": "paused",
                    "started_at": datetime(2026, 6, 27, 10, 0, 0),
                    "completed_at": None,
                    "duration_seconds": None,
                    "current_episode": 9,
                    "total_episodes": 100,
                    "comments_sent": 1,
                    "comments_verified": 1,
                    "templates_json": "[]",
                    "playback_speed": "2.0x",
                    "execution_plan_json": "{}",
                }

        class DummyConnection:
            def cursor(self):
                return self

            def __enter__(self):
                return DummyCursor()

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("rpa.dashboard.routes_hongguo._connection") as connection:
            connection.return_value.__enter__.return_value = DummyConnection()
            import asyncio

            asyncio.run(update_task(12, TaskUpdate(status="running")))

        update_sql, _ = next(
            call for call in captured["calls"] if "UPDATE hongguo_comment_tasks" in call[0]
        )
        assert "status=%s" in update_sql
        assert "execution_plan_json=%s" not in update_sql
        assert "current_episode=%s" not in update_sql
        assert "comments_sent=%s" not in update_sql
        assert "rule_updated_at=%s" not in update_sql

    def test_update_task_rejects_rule_change_while_active(self):
        from fastapi import HTTPException

        class DummyCursor:
            def execute(self, sql, params=None):
                pass

            def fetchone(self):
                return {
                    "id": 12,
                    "drama_name": "一品布衣",
                    "status": "running",
                    "templates_json": "[]",
                    "playback_speed": "2.0x",
                    "execution_plan_json": "{}",
                }

        class DummyConnection:
            def cursor(self):
                return self

            def __enter__(self):
                return DummyCursor()

            def __exit__(self, exc_type, exc, tb):
                return False

        manager = MagicMock()
        manager.is_running.return_value = True
        with patch("rpa.dashboard.routes_hongguo._connection") as connection:
            connection.return_value.__enter__.return_value = DummyConnection()
            with patch("rpa.dashboard.routes_hongguo._engine_manager", return_value=manager):
                import asyncio

                with pytest.raises(HTTPException) as exc:
                    asyncio.run(update_task(12, TaskUpdate(start_episode=3)))

        assert exc.value.status_code == 409
        assert "停止" in exc.value.detail
        assert manager.is_running.call_count >= 1
        manager.is_running.assert_any_call(12)

    def test_update_task_allows_rule_change_when_runtime_is_gone(self):
        captured = {}

        class DummyCursor:
            def execute(self, sql, params=None):
                captured.setdefault("calls", []).append((sql, params))

            def fetchone(self):
                return {
                    "id": 12,
                    "drama_name": "一品布衣",
                    "status": "paused",
                    "started_at": datetime(2026, 6, 27, 10, 0, 0),
                    "completed_at": None,
                    "duration_seconds": None,
                    "current_episode": 9,
                    "total_episodes": 100,
                    "comments_sent": 1,
                    "comments_verified": 1,
                    "templates_json": "[]",
                    "playback_speed": "2.0x",
                    "execution_plan_json": "{}",
                }

        class DummyConnection:
            def cursor(self):
                return self

            def __enter__(self):
                return DummyCursor()

            def __exit__(self, exc_type, exc, tb):
                return False

        manager = MagicMock()
        manager.is_running.return_value = False
        with patch("rpa.dashboard.routes_hongguo._connection") as connection:
            connection.return_value.__enter__.return_value = DummyConnection()
            with patch("rpa.dashboard.routes_hongguo._engine_manager", return_value=manager):
                import asyncio

                asyncio.run(update_task(12, TaskUpdate(start_episode=3)))

        update_sql, update_params = next(
            call for call in captured["calls"] if "UPDATE hongguo_comment_tasks" in call[0]
        )
        assert "execution_plan_json=%s" in update_sql
        assert "status=%s" in update_sql
        assert "pending" in update_params
        assert manager.is_running.call_count >= 1
        manager.is_running.assert_any_call(12)

    def test_serialize_task_includes_engine_running_flag(self):
        from rpa.dashboard import routes_hongguo

        manager = MagicMock()
        manager.is_running.return_value = False
        with patch.object(routes_hongguo, "_engine_manager", return_value=manager):
            row = routes_hongguo._serialize_task(
                {
                    "id": 12,
                    "drama_name": "一品布衣",
                    "status": "paused",
                    "templates_json": "[]",
                    "playback_speed": "2.0x",
                    "execution_plan_json": None,
                }
            )

        assert row["engine_running"] is False
        manager.is_running.assert_called_once_with(12)

    def test_stop_task_without_runtime_sets_completed_time_and_duration(self):
        from rpa.dashboard import routes_hongguo

        captured = {"calls": []}
        started = datetime(2026, 6, 27, 10, 0, 0)
        stopped = datetime(2026, 6, 27, 10, 2, 5)

        class DummyCursor:
            def __init__(self):
                self.fetchone_calls = 0

            def execute(self, sql, params=None):
                captured["calls"].append((sql, params))

            def fetchone(self):
                self.fetchone_calls += 1
                return {
                    "id": 12,
                    "drama_name": "一品布衣",
                    "status": "paused",
                    "started_at": started,
                    "completed_at": None,
                    "duration_seconds": None,
                    "templates_json": "[]",
                    "playback_speed": "2.0x",
                    "execution_plan_json": None,
                }

        class DummyConnection:
            def cursor(self):
                return self

            def __enter__(self):
                return DummyCursor()

            def __exit__(self, exc_type, exc, tb):
                return False

        manager = MagicMock()
        manager.stop_task.return_value = False
        manager.is_running.return_value = False
        with patch("rpa.dashboard.routes_hongguo._connection") as connection:
            connection.return_value.__enter__.return_value = DummyConnection()
            with patch("rpa.dashboard.routes_hongguo._engine_manager", return_value=manager):
                with patch("rpa.dashboard.routes_hongguo.datetime") as dt:
                    dt.now.return_value = stopped
                    import asyncio

                    asyncio.run(routes_hongguo.stop_task(12))

        update_sql, update_params = next(
            call for call in captured["calls"] if "UPDATE hongguo_comment_tasks" in call[0]
        )
        assert "completed_at=%s" in update_sql
        assert "duration_seconds=%s" in update_sql
        assert update_params[0] == "stopped"
        assert update_params[1] == stopped
        assert update_params[2] == 125
        assert any("INSERT INTO hongguo_execution_logs" in sql for sql, _ in captured["calls"])

    def test_delete_task_rejects_active_task(self):
        from fastapi import HTTPException

        captured = {"executed": []}

        class DummyCursor:
            def execute(self, sql, params=None):
                captured["executed"].append(sql)

            def fetchone(self):
                return {
                    "id": 12,
                    "drama_name": "一品布衣",
                    "status": "paused",
                    "templates_json": "[]",
                    "playback_speed": "2.0x",
                    "execution_plan_json": None,
                }

        class DummyConnection:
            def cursor(self):
                return self

            def __enter__(self):
                return DummyCursor()

            def __exit__(self, exc_type, exc, tb):
                return False

        manager = MagicMock()
        manager.is_running.return_value = True
        with patch("rpa.dashboard.routes_hongguo._connection") as connection:
            connection.return_value.__enter__.return_value = DummyConnection()
            with patch("rpa.dashboard.routes_hongguo._engine_manager", return_value=manager):
                import asyncio

                with pytest.raises(HTTPException) as exc:
                    asyncio.run(delete_task(12))

        assert exc.value.status_code == 409
        assert "停止" in exc.value.detail
        assert not any("DELETE FROM hongguo_comment_tasks" in sql for sql in captured["executed"])
        manager.is_running.assert_called_once_with(12)

    def test_delete_task_allows_inactive_task(self):
        captured = {"executed": []}

        class DummyCursor:
            def execute(self, sql, params=None):
                captured["executed"].append(sql)

            def fetchone(self):
                return {
                    "id": 12,
                    "drama_name": "一品布衣",
                    "status": "stopped",
                    "templates_json": "[]",
                    "playback_speed": "2.0x",
                    "execution_plan_json": None,
                }

        class DummyConnection:
            def cursor(self):
                return self

            def __enter__(self):
                return DummyCursor()

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("rpa.dashboard.routes_hongguo._connection") as connection:
            connection.return_value.__enter__.return_value = DummyConnection()
            import asyncio

            result = asyncio.run(delete_task(12))

        assert result == {"success": True, "id": 12}
        assert any("DELETE FROM hongguo_execution_logs" in sql for sql in captured["executed"])
        assert any("DELETE FROM hongguo_comment_records" in sql for sql in captured["executed"])
        assert any("DELETE FROM hongguo_comment_tasks" in sql for sql in captured["executed"])

    def test_dashboard_check_login_downgrades_when_account_is_not_logged_in(self):
        from rpa.dashboard import routes_hongguo

        device = MagicMock()
        ops = MagicMock()
        ops.get_device_info.return_value = {"serial": "127.0.0.1:5555"}
        ops.ensure_app_ready.return_value = True
        ops.check_login.return_value = {
            "logged_in": True,
            "status": "logged_in",
            "message": "已登录",
        }
        ops.get_account_info.return_value = {
            "logged_in": False,
            "nickname": "",
            "hongguo_id": "",
            "message": "红果未登录",
        }

        with patch.object(routes_hongguo, "connect", return_value=device):
            with patch.object(routes_hongguo, "HongguoOperations", return_value=ops):
                result = routes_hongguo.check_login()

        assert result["success"] is True
        assert result["logged_in"] is False
        assert result["status"] == "not_logged_in"
        assert result["account"]["logged_in"] is False
        ops.launch_app.assert_not_called()

    def test_dashboard_check_login_skips_account_probe_when_not_logged_in(self):
        from rpa.dashboard import routes_hongguo

        device = MagicMock()
        ops = MagicMock()
        ops.get_device_info.return_value = {"serial": "127.0.0.1:5555"}
        ops.ensure_app_ready.return_value = True
        ops.check_login.return_value = {
            "logged_in": False,
            "status": "not_logged_in",
            "message": "未登录",
        }

        with patch.object(routes_hongguo, "connect", return_value=device):
            with patch.object(routes_hongguo, "HongguoOperations", return_value=ops):
                result = routes_hongguo.check_login()

        assert result["logged_in"] is False
        assert result["status"] == "not_logged_in"
        assert result["account"]["logged_in"] is False
        ops.get_account_info.assert_not_called()
        assert ops.get_device_info.call_count == 1
        ops.check_login.assert_called_once_with(close_popups=False)

    def test_dashboard_check_login_rejects_promo_account_text(self):
        from rpa.dashboard import routes_hongguo

        device = MagicMock()
        ops = MagicMock()
        ops.get_device_info.return_value = {"serial": "127.0.0.1:5555"}
        ops.ensure_app_ready.return_value = True
        ops.check_login.return_value = {
            "logged_in": False,
            "status": "unknown",
            "message": "无法确认登录状态",
        }
        ops.get_account_info.return_value = {
            "logged_in": True,
            "nickname": "免费短剧 尽在红果(get)",
            "hongguo_id": "get",
            "message": "已识别红果账号",
        }

        with patch.object(routes_hongguo, "connect", return_value=device):
            with patch.object(routes_hongguo, "HongguoOperations", return_value=ops):
                result = routes_hongguo.check_login()

        assert result["logged_in"] is False
        assert result["status"] != "logged_in"
        assert result["account"]["logged_in"] is False
        assert result["account"]["nickname"] == ""
        assert result["account"]["hongguo_id"] == ""

    def test_dashboard_check_login_stops_when_app_ready_fails_even_if_package_is_stale(self):
        from rpa.dashboard import routes_hongguo

        device = MagicMock()
        ops = MagicMock()
        ops.ensure_app_ready.return_value = False
        ops.get_device_info.return_value = {
            "serial": "192.168.3.134:5555",
            "current_package": "com.phoenix.read",
            "current_activity": "com.dragon.read.pages.main.MainFragmentActivity",
        }

        with patch.object(routes_hongguo, "connect", return_value=device):
            with patch.object(routes_hongguo, "HongguoOperations", return_value=ops):
                result = routes_hongguo.check_login()

        assert result["logged_in"] is False
        assert result["status"] == "app_launch_failed"
        ops.check_login.assert_not_called()
        ops.get_account_info.assert_not_called()

    def test_current_device_returns_configured_device_without_discovery(self):
        from rpa.dashboard import routes_hongguo

        device = MagicMock()
        ops = MagicMock()
        ops.get_device_info.return_value = {
            "serial": "192.168.3.134:5555",
            "emulator": "真机/网络 ADB",
            "model": "23116PN5BC",
        }

        with patch.object(routes_hongguo, "_hongguo_device_addr", return_value="192.168.3.134:5555"):
            with patch.object(routes_hongguo, "connect_exact", return_value=device) as connect_exact:
                with patch.object(routes_hongguo, "discover_addrs") as discover:
                    with patch.object(routes_hongguo, "HongguoOperations", return_value=ops):
                        result = routes_hongguo.current_device()

        assert result["success"] is True
        assert result["configured_device_online"] is True
        assert result["device"]["addr"] == "192.168.3.134:5555"
        assert result["device"]["device"]["emulator"] == "真机/网络 ADB"
        connect_exact.assert_called_once_with("192.168.3.134:5555")
        discover.assert_not_called()

    def test_current_device_returns_offline_for_configured_device_failure(self):
        from rpa.dashboard import routes_hongguo

        with patch.object(routes_hongguo, "_hongguo_device_addr", return_value="127.0.0.1:7555"):
            with patch.object(routes_hongguo, "connect_exact", side_effect=RuntimeError("offline")):
                result = routes_hongguo.current_device()

        assert result["success"] is True
        assert result["configured_device_online"] is False
        assert result["device"]["addr"] == "127.0.0.1:7555"
        assert result["device"]["online"] is False
        assert "offline" in result["device"]["message"]

    def test_start_task_validates_transition_before_updating_running_state(self):
        from fastapi import HTTPException
        from rpa.dashboard import routes_hongguo

        captured = {"executed": []}

        class DummyCursor:
            def execute(self, sql, params=None):
                captured["executed"].append(sql)

            def fetchone(self):
                return {
                    "id": 12,
                    "drama_name": "一品布衣",
                    "status": "running",
                    "templates_json": "[]",
                    "playback_speed": "2.0x",
                    "execution_plan_json": None,
                }

        class DummyConnection:
            def cursor(self):
                return self

            def __enter__(self):
                return DummyCursor()

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch.object(routes_hongguo, "_connection") as connection:
            connection.return_value.__enter__.return_value = DummyConnection()
            import asyncio

            with pytest.raises(HTTPException):
                asyncio.run(routes_hongguo.start_task(12))

        update_calls = [sql for sql in captured["executed"] if "UPDATE hongguo_comment_tasks" in sql]
        assert update_calls == []

    def test_start_task_does_not_overwrite_engine_status_after_thread_start(self):
        from rpa.dashboard import routes_hongguo

        captured = {"executed": []}

        class DummyCursor:
            def execute(self, sql, params=None):
                captured["executed"].append(sql)

            def fetchone(self):
                return {
                    "id": 12,
                    "drama_name": "一品布衣",
                    "status": "pending",
                    "templates_json": "[]",
                    "playback_speed": "2.0x",
                    "execution_plan_json": None,
                }

        class DummyConnection:
            def cursor(self):
                return self

            def __enter__(self):
                return DummyCursor()

            def __exit__(self, exc_type, exc, tb):
                return False

        manager = MagicMock()
        manager.start_task.return_value = True
        with patch.object(routes_hongguo, "_connection") as connection:
            connection.return_value.__enter__.return_value = DummyConnection()
            with patch.object(routes_hongguo, "_engine_manager", return_value=manager):
                import asyncio

                result = asyncio.run(routes_hongguo.start_task(12))

        assert result["id"] == 12
        manager.start_task.assert_called_once_with(12)
        update_calls = [sql for sql in captured["executed"] if "UPDATE hongguo_comment_tasks" in sql]
        assert update_calls == []

    def test_safe_comment_window_caps_delay_for_fast_playback(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        class DummyOps:
            def __init__(self):
                self.calls = 0

            def get_current_episode(self):
                self.calls += 1
                return 5

            def ensure_playback_page(self, episode):
                return episode == 5

        sleeps = []
        with patch("rpa.hongguo.engine.random.randint", return_value=60):
            with patch("rpa.hongguo.engine.time.time", side_effect=[0, 1, 2, 3, 4, 5, 6, 7, 8]):
                with patch("rpa.hongguo.engine.time.sleep", side_effect=lambda seconds: sleeps.append(seconds)):
                    assert engine._wait_safe_comment_window(
                        DummyOps(),
                        5,
                        {"comment_mode": "random", "random_min_interval": 20, "random_max_interval": 60, "playback_speed": "2.0x"},
                    ) is True
        assert sum(sleeps) <= 2

    def test_safe_comment_window_rejects_episode_jump(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        class DummyOps:
            def get_current_episode(self):
                return 6

            def ensure_playback_page(self, episode):
                return False

        with patch("rpa.hongguo.engine.random.randint", return_value=20):
            assert engine._wait_safe_comment_window(
                DummyOps(),
                5,
                {"comment_mode": "random", "random_min_interval": 20, "random_max_interval": 60, "playback_speed": "2.0x"},
            ) is False

    def test_sleep_until_ignores_expired_deadline(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        with patch("rpa.hongguo.engine.time.time", return_value=10):
            with patch("rpa.hongguo.engine.time.sleep") as sleep:
                engine._sleep_until(9)
        sleep.assert_not_called()


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])


# TASK_COMPLETE: phase2_rpa_engine


# TASK_COMPLETE: phase1_rpa_design
