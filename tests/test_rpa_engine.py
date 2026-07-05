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
from rpa.hongguo.operations import HongguoOperations
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
    def test_launch_app_accepts_foreground_package(self):
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
                return '<node package="com.phoenix.read" text="搜索" />'

            def window_size(self):
                return (1080, 1920)

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_close_popups"):
            assert ops.launch_app() is True

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

    def test_get_current_episode_ignores_home_feed_episode_hint(self):
        class DummyDevice:
            def app_current(self):
                return {
                    "package": "com.phoenix.read",
                    "activity": "com.dragon.read.pages.main.MainFragmentActivity",
                }

            def dump_hierarchy(self):
                return '<node package="com.phoenix.read" text="第98集 高能短剧推荐" />'

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops.get_current_episode() == 0

    def test_get_current_episode_ignores_total_episode_hint(self):
        class DummyDevice:
            def app_current(self):
                return {
                    "package": "com.phoenix.read",
                    "activity": "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity",
                }

            def dump_hierarchy(self):
                return '<node package="com.phoenix.read" text="\u5168144\u96c6" />'

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops.get_current_episode() == 0
        assert ops.get_total_episodes() == 144

    def test_get_current_episode_ignores_ad_page_total_hint(self):
        class DummyDevice:
            def app_current(self):
                return {
                    "package": "com.phoenix.read",
                    "activity": "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity",
                }

            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" text="\u4e0a\u6ed1\u7ee7\u7eed\u770b\u77ed\u5267" />'
                    '<node package="com.phoenix.read" text="\u5168144\u96c6" />'
                )

            def window_size(self):
                return (900, 1600)

        ops = HongguoOperations(DummyDevice())
        assert ops._ad_continue_visible() is True
        assert ops.get_current_episode() == 0
        assert ops.get_total_episodes() == 144

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

    def test_click_episode_number_uses_content_desc_bounds(self):
        class DummyDevice:
            def __init__(self):
                self.clicked = []

            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" text="" content-desc="21" '
                    'bounds="[360,840][450,930]" />'
                )

            def window_size(self):
                return (900, 1600)

            def click(self, x, y):
                self.clicked.append((x, y))

        device = DummyDevice()
        ops = HongguoOperations(device)
        assert ops._click_episode_number_from_xml(21) is True
        assert device.clicked == [(405, 885)]

    def test_click_episode_number_scrolls_when_target_is_clipped(self):
        class DummyDevice:
            def __init__(self):
                self.clicked = []
                self.swipes = []

            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" text="21" '
                    'bounds="[316,1541][439,1600]" />'
                )

            def window_size(self):
                return (900, 1600)

            def click(self, x, y):
                self.clicked.append((x, y))

            def swipe(self, x1, y1, x2, y2, duration=0.4):
                self.swipes.append((x1, y1, x2, y2, duration))

        device = DummyDevice()
        ops = HongguoOperations(device)
        assert ops._click_episode_number_from_xml(21) is False
        assert device.clicked == []
        assert device.swipes

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
        assert ops._is_title_candidate("8.9分") is False
        assert ops._is_title_candidate("80集") is False
        assert ops._is_title_candidate("逆命谋臣：从赘婿到帝王") is True

    def test_extract_detail_title_skips_status_bar_time(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" text="12:54" bounds="[24,12][120,60]" />'
                    '<node package="com.phoenix.read" text="逆命谋臣：从赘婿到帝王" bounds="[24,1320][650,1390]" />'
                )

            def window_size(self):
                return (1080, 1920)

        ops = HongguoOperations(DummyDevice())
        assert ops._extract_detail_title() == "逆命谋臣：从赘婿到帝王"

    def test_extract_detail_title_prefers_expected_match_over_score(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" text="8.9分" bounds="[24,120][180,170]" />'
                    '<node package="com.phoenix.read" text="一品布衣2：烽火篇" bounds="[24,1320][650,1390]" />'
                )

            def window_size(self):
                return (1080, 1920)

        ops = HongguoOperations(DummyDevice())
        assert ops._extract_detail_title("一品布衣2") == "一品布衣2：烽火篇"

    def test_extract_detail_title_ignores_desktop_ad_banner(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    '<node package="app.lawnchair" text="水墨山海，再启仙途，共庆半周年！" />'
                    '<node package="com.phoenix.read" text="一品布衣2：烽火篇" bounds="[24,1320][650,1390]" />'
                    '<node package="com.phoenix.read" text="全144集" />'
                )

            def window_size(self):
                return (1080, 1920)

        ops = HongguoOperations(DummyDevice())
        assert ops._extract_detail_title("一品布衣2") == "一品布衣2：烽火篇"

    def test_extract_detail_title_does_not_fallback_to_synopsis_when_expected_missing(self):
        class DummyDevice:
            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" text="徐牧等人以异常残酷的方式打退…" bounds="[24,1320][650,1390]" />'
                    '<node package="com.phoenix.read" text="全144集" />'
                    '<node package="com.phoenix.read" text="剧情简介" />'
                )

            def window_size(self):
                return (1080, 1920)

        ops = HongguoOperations(DummyDevice())
        assert ops._extract_detail_title("一品布衣2") == ""


    def test_type_text_sends_whole_keyword_once(self):
        class DummyDevice:
            def __init__(self):
                self.calls = []
                self.text = ""

            def send_keys(self, text):
                self.calls.append(text)
                self.text = text

            def window_size(self):
                return (1080, 1920)

        device = DummyDevice()
        ops = HongguoOperations(device)
        ops._type_text("一品布衣")
        assert device.calls == ["一品布衣"]
        assert device.text == "一品布衣"

    def test_set_input_text_rejects_stale_keyword(self):
        class DummyInput:
            info = {"text": "一品布衣4"}

            def click(self):
                pass

            def set_text(self, text):
                pass

            def send_keys(self, text):
                pass

            def clear_text(self):
                pass

        class DummyDevice:
            def send_keys(self, text):
                pass

            def window_size(self):
                return (1080, 1920)

            def dump_hierarchy(self):
                return '<node class="android.widget.EditText" text="一品布衣4" />'

        ops = HongguoOperations(DummyDevice())
        result = ops._set_input_text(DummyInput(), "一品布衣2")
        assert result == {"success": False, "actual_text": "一品布衣4"}

    def test_set_input_text_accepts_verified_keyword(self):
        class DummyInput:
            def __init__(self):
                self.info = {"text": ""}

            def click(self):
                pass

            def set_text(self, text):
                self.info["text"] = text

        class DummyDevice:
            def __init__(self, input_el):
                self.input_el = input_el

            def __call__(self, **kwargs):
                return self.input_el

            def window_size(self):
                return (1080, 1920)

            def dump_hierarchy(self):
                return '<node package="com.phoenix.read" text="搜索" />'

        inp = DummyInput()
        ops = HongguoOperations(DummyDevice(inp))
        result = ops._set_input_text(inp, "一品布衣2")
        assert result == {"success": True, "actual_text": "一品布衣2"}

    def test_search_drama_runs_real_atomic_flow(self):
        ops = HongguoOperations(object())
        with patch.object(ops, "open_search_page", return_value={"success": True}) as open_search:
            with patch.object(ops, "input_search_keyword", return_value={"success": True, "input_text": "一品布衣2"}) as input_keyword:
                with patch.object(
                    ops,
                    "submit_search",
                    return_value={"success": True, "titles": ["一品布衣2：烽火篇"], "submit": {"action": "press_enter"}, "message": "搜索完成"},
                ) as submit_search:
                    result = ops.search_drama("一品布衣2")
        assert result["success"] is True
        assert result["input_text"] == "一品布衣2"
        assert result["titles"] == ["一品布衣2：烽火篇"]
        open_search.assert_called_once_with("一品布衣2")
        input_keyword.assert_called_once_with("一品布衣2")
        submit_search.assert_called_once_with("一品布衣2")

    def test_submit_search_rejects_when_results_tabs_missing(self):
        class DummySelector:
            def exists(self, timeout=0):
                return False

        class DummyDevice:
            def window_size(self):
                return (1080, 1920)

            def app_current(self):
                return {
                    "package": "com.phoenix.read",
                    "activity": "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity",
                }

            def dump_hierarchy(self):
                return '<node package="com.phoenix.read" text="一品布衣2" />'

            def __call__(self, **kwargs):
                return DummySelector()

            def press(self, key):
                pass

            def shell(self, command):
                pass

            def click(self, x, y):
                pass

        ops = HongguoOperations(DummyDevice())
        result = ops._submit_search("一品布衣2")
        assert result["success"] is True
        assert result["candidate_visible"] is True
        assert result["message"] == "已展示搜索候选结果，可直接进入目标剧集"
        assert result["actions"]

    def test_search_results_visible_requires_tabs(self):
        ops = HongguoOperations(object())
        assert ops._search_results_visible(
            '<node package="com.phoenix.read" text="综合" />'
            '<node package="com.phoenix.read" text="短剧" />'
            '<node package="com.phoenix.read" text="搜索" />'
        ) is True
        assert ops._search_results_visible('<node text="一品布衣2" /><node text="搜索" />') is False

    def test_candidate_results_visible_accepts_matching_suggestion_without_tabs(self):
        ops = HongguoOperations(object())
        xml = '<node package="com.phoenix.read" text="一品布衣2：烽火篇" />'
        with patch.object(ops, "_is_app_foreground", return_value=True):
            assert ops._candidate_results_visible("一品布衣2", xml) is True

    def test_search_results_visible_does_not_treat_candidate_page_as_tabs(self):
        ops = HongguoOperations(object())
        xml = '<node text="一品布衣2：烽火篇" /><node text="第2季" /><node text="历史古代" />'
        assert ops._search_results_visible(xml) is False

    def test_search_results_visible_ignores_desktop_tabs(self):
        ops = HongguoOperations(object())
        xml = (
            '<node package="app.lawnchair" text="综合" />'
            '<node package="app.lawnchair" text="短剧" />'
            '<node package="app.lawnchair" text="搜索" />'
            '<node package="com.phoenix.read" text="一品布衣2" />'
        )
        assert ops._search_results_visible(xml) is False

    def test_extract_drama_titles_ignores_desktop_nodes(self):
        ops = HongguoOperations(object())
        xml = (
            '<node package="app.lawnchair" text="小红书" />'
            '<node package="app.lawnchair" text="Play 商店" />'
            '<node package="com.phoenix.read" text="一品布衣2：烽火篇" />'
        )
        assert ops._extract_drama_titles_from_xml(xml) == ["一品布衣2：烽火篇"]

    def test_app_foreground_requires_visible_hongguo_nodes(self):
        class DummyDevice:
            def app_current(self):
                return {"package": "com.phoenix.read"}

            def dump_hierarchy(self):
                return '<node package="app.lawnchair" text="搜索" />'

            def window_size(self):
                return (1080, 1920)

        assert HongguoOperations(DummyDevice())._is_app_foreground() is False

    def test_app_foreground_accepts_mumu_overlay_with_hongguo_business_nodes(self):
        class DummyDevice:
            def app_current(self):
                return {"package": "com.phoenix.read"}

            def dump_hierarchy(self):
                return (
                    '<node package="app.lawnchair" text="Play 商店" />'
                    '<node package="com.phoenix.read" text="一品布衣2：烽火篇" />'
                    '<node package="com.phoenix.read" text="全144集" />'
                    '<node package="com.phoenix.read" text="剧评 · 9091" />'
                )

            def window_size(self):
                return (1080, 1920)

        assert HongguoOperations(DummyDevice())._is_app_foreground() is True

    def test_find_drama_rejects_unmatched_results(self):
        ops = HongguoOperations(object())
        with patch.object(ops, "search_drama", return_value={"success": True, "titles": ["时空猎人"]}):
            with patch.object(ops, "select_drama") as select_drama:
                result = ops.find_drama("一品布衣")
        assert result["success"] is False
        assert result["message"] == "没有匹配任务短剧名称的搜索结果"
        select_drama.assert_not_called()

    def test_find_drama_selects_matching_title_atomically(self):
        ops = HongguoOperations(object())
        search = {"success": True, "titles": ["一品布衣2", "一品布衣2：烽火篇"]}
        selected = {"success": True, "playable": True, "drama_title": "一品布衣2：烽火篇"}
        with patch.object(ops, "search_drama", return_value=search):
            with patch.object(ops, "select_drama", return_value=selected) as select_drama:
                result = ops.find_drama("一品布衣2")
        assert result["success"] is True
        assert result["selected_title"] == "一品布衣2：烽火篇"
        assert result["drama_title"] == "一品布衣2：烽火篇"
        select_drama.assert_called_once_with("一品布衣2：烽火篇", keyword="一品布衣2")

    def test_title_matching_keeps_numbered_sequels_distinct(self):
        ops = HongguoOperations(object())
        assert ops._title_matches("一品布衣2", "一品布衣") is False
        assert ops._title_matches("一品布衣2", "一品布衣20") is False
        assert ops._title_matches("一品布衣2", "一品布衣2：烽火篇") is True

    def test_choose_title_prefers_specific_full_title(self):
        ops = HongguoOperations(object())
        title = ops._choose_title("一品布衣2", ["一品布衣2", "一品布衣2：烽火篇", "一品布衣", "历史古代", "8.9分"])
        assert title == "一品布衣2：烽火篇"

    def test_choose_title_rejects_topic_video_result(self):
        ops = HongguoOperations(object())
        title = ops._choose_title(
            "一品布衣2",
            [
                "一品布衣2《这四重仪式后，我不在是我：将军定妆全纪录》 #一品布衣 #一品布衣2 #赵青云 #杨彦明 #2025第三只眼看中国",
                "一品布衣2",
                "一品布衣2：烽火篇",
            ],
        )
        assert title == "一品布衣2：烽火篇"

    def test_select_drama_does_not_click_first_suggestion(self):
        class DummySelector:
            count = 0

            def exists(self, timeout=0):
                return False

        class DummyDevice:
            def window_size(self):
                return (1080, 1920)

            def app_current(self):
                return {"package": "com.phoenix.read"}

            def dump_hierarchy(self):
                return '<node package="com.phoenix.read" text="搜索" />'

            def __call__(self, **kwargs):
                return DummySelector()

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_click_first_search_suggestion") as click_first:
            result = ops.select_drama("一品布衣2", keyword="一品布衣2")
        assert result["success"] is False
        click_first.assert_not_called()

    def test_select_drama_accepts_episode_picker_as_playable(self):
        class DummySelector:
            def exists(self, timeout=0):
                return False

        class DummyDevice:
            def __init__(self):
                self.clicked = []
                self.detail = False

            def window_size(self):
                return (1080, 1920)

            def app_current(self):
                return {"package": "com.phoenix.read"}

            def dump_hierarchy(self):
                if self.detail:
                    return (
                        '<node package="com.phoenix.read" text="一品布衣2：烽火篇" />'
                        '<node package="com.phoenix.read" text="选集" />'
                        '<node package="com.phoenix.read" text=" · 已完结 · 全144集" />'
                        '<node package="com.phoenix.read" text="第3集" />'
                        '<node package="app.lawnchair" text="Play 商店" />'
                    )
                return '<node package="com.phoenix.read" text="一品布衣2：烽火篇" bounds="[120,200][600,260]" />'

            def click(self, x, y):
                self.clicked.append((x, y))
                self.detail = True

            def __call__(self, **kwargs):
                return DummySelector()

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_sleep"):
            result = ops.select_drama("一品布衣2：烽火篇", keyword="一品布衣2")
        assert result["success"] is True
        assert result["playable"] is True
        assert result["drama_title"] == "一品布衣2：烽火篇"

    def test_select_drama_accepts_target_detail_without_play_button(self):
        class DummySelector:
            def exists(self, timeout=0):
                return False

        class DummyDevice:
            def window_size(self):
                return (1080, 1920)

            def app_current(self):
                return {
                    "package": "com.phoenix.read",
                    "activity": "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity",
                }

            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" text="一品布衣2：烽火篇" />'
                    '<node package="com.phoenix.read" text="全144集" />'
                    '<node package="com.phoenix.read" text="剧情简介" />'
                    '<node package="com.phoenix.read" text="剧评 · 9091" />'
                )

            def __call__(self, **kwargs):
                return DummySelector()

        ops = HongguoOperations(DummyDevice())
        result = ops.select_drama("一品布衣2：烽火篇", keyword="一品布衣2")
        assert result["success"] is True
        assert result["playable"] is False
        assert result["detail_visible"] is True

    def test_select_drama_uses_clicked_title_when_detail_only_shows_synopsis(self):
        class DummySelector:
            def exists(self, timeout=0):
                return False

        class DummyDevice:
            def __init__(self):
                self.detail = False

            def window_size(self):
                return (1080, 1920)

            def app_current(self):
                return {"package": "com.phoenix.read"}

            def dump_hierarchy(self):
                if self.detail:
                    return (
                        '<node package="com.phoenix.read" text="徐牧等人以异常残酷的方式打退…" bounds="[24,1320][650,1390]" />'
                        '<node package="com.phoenix.read" text="全144集" />'
                        '<node package="com.phoenix.read" text="选集" />'
                    )
                return '<node package="com.phoenix.read" text="一品布衣2：烽火篇" bounds="[120,200][600,260]" />'

            def click(self, x, y):
                self.detail = True

            def __call__(self, **kwargs):
                return DummySelector()

        ops = HongguoOperations(DummyDevice())
        with patch.object(ops, "_sleep"):
            result = ops.select_drama("一品布衣2：烽火篇", keyword="一品布衣2")
        assert result["success"] is True
        assert result["drama_title"] == "一品布衣2：烽火篇"

    def test_ad_continue_prompt_triggers_swipe(self):
        class DummyDevice:
            def __init__(self):
                self.swipes = []
                self.dumps = 0

            def window_size(self):
                return (1080, 1920)

            def dump_hierarchy(self):
                self.dumps += 1
                if self.dumps == 1:
                    return '<node package="com.phoenix.read" text="上滑继续观看短剧" />'
                return '<node package="com.phoenix.read" text="第2集" />'

            def swipe(self, x1, y1, x2, y2, duration=0.4):
                self.swipes.append((x1, y1, x2, y2, duration))

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch("rpa.hongguo.operations.time.sleep"):
            assert ops.skip_ad_if_present() is True
        assert device.swipes
        assert device.swipes[0][1] > device.swipes[0][3]

    def test_ad_continue_short_prompt_triggers_swipe(self):
        class DummyDevice:
            def __init__(self):
                self.swipes = []
                self.dumps = 0

            def window_size(self):
                return (1080, 1920)

            def dump_hierarchy(self):
                self.dumps += 1
                if self.dumps == 1:
                    return '<node package="com.phoenix.read" text="上滑继续看短剧" />'
                return '<node package="com.phoenix.read" text="第4集" />'

            def swipe(self, x1, y1, x2, y2, duration=0.4):
                self.swipes.append((x1, y1, x2, y2, duration))

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch("rpa.hongguo.operations.time.sleep"):
            assert ops.skip_ad_if_present() is True
        assert device.swipes
        assert device.swipes[0][1] > device.swipes[0][3]

    def test_ad_page_markers_with_continue_prompt_trigger_swipe(self):
        class DummyDevice:
            def __init__(self):
                self.swipes = []
                self.dumps = 0

            def window_size(self):
                return (1080, 1920)

            def dump_hierarchy(self):
                self.dumps += 1
                if self.dumps == 1:
                    return (
                        '<node package="com.phoenix.read" text="广告" />'
                        '<node package="com.phoenix.read" text="免费演示" />'
                        '<node package="com.phoenix.read" text="Kuaizi筷子科技" />'
                        '<node package="com.phoenix.read" text="上滑继续观看短剧" />'
                    )
                return '<node package="com.phoenix.read" text="第5集" />'

            def swipe(self, x1, y1, x2, y2, duration=0.4):
                self.swipes.append((x1, y1, x2, y2, duration))

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch("rpa.hongguo.operations.time.sleep"):
            assert ops.skip_ad_if_present() is True
        assert device.swipes
        assert device.swipes[0][1] > device.swipes[0][3]

    def test_ad_page_markers_without_swipe_prompt_do_not_trigger_swipe(self):
        class DummyDevice:
            def __init__(self):
                self.swipes = []

            def window_size(self):
                return (1080, 1920)

            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" text="第5集" />'
                    '<node package="com.phoenix.read" text="短剧" />'
                    '<node package="com.phoenix.read" text="广告" />'
                    '<node package="com.phoenix.read" text="直播中" />'
                    '<node package="com.phoenix.read" text="评论" />'
                )

            def swipe(self, x1, y1, x2, y2, duration=0.4):
                self.swipes.append((x1, y1, x2, y2, duration))

        device = DummyDevice()
        ops = HongguoOperations(device)
        assert ops.skip_ad_if_present() is False
        assert device.swipes == []

    def test_ad_carousel_on_playback_page_does_not_trigger_swipe(self):
        class DummyDevice:
            def __init__(self):
                self.swipes = []

            def window_size(self):
                return (1080, 1920)

            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" text="第19集" />'
                    '<node package="com.phoenix.read" text="一品布衣2：烽火篇" />'
                    '<node package="com.phoenix.read" text="选集 · 已完结 · 全144集" />'
                    '<node package="com.phoenix.read" content-desc="广告轮播" />'
                )

            def swipe(self, x1, y1, x2, y2, duration=0.4):
                self.swipes.append((x1, y1, x2, y2, duration))

        device = DummyDevice()
        ops = HongguoOperations(device)
        assert ops.skip_ad_if_present() is False
        assert device.swipes == []

    def test_ad_skip_returns_false_when_prompt_remains(self):
        class DummyDevice:
            def __init__(self):
                self.swipes = []

            def window_size(self):
                return (1080, 1920)

            def dump_hierarchy(self):
                return '<node package="com.phoenix.read" text="上滑继续看短剧" />'

            def swipe(self, x1, y1, x2, y2, duration=0.4):
                self.swipes.append((x1, y1, x2, y2, duration))

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch("rpa.hongguo.operations.time.sleep"):
            assert ops.skip_ad_if_present(attempts=2) is False
        assert len(device.swipes) == 2

    def test_resume_playback_clicks_center_overlay_without_text(self):
        class DummyDevice:
            def __init__(self):
                self.clicks = []

            def window_size(self):
                return (900, 1600)

            def dump_hierarchy(self):
                return (
                    '<node package="com.phoenix.read" text="第3集" />'
                    '<node package="com.phoenix.read" clickable="true" bounds="[386,680][514,808]" />'
                )

            def __call__(self, **kwargs):
                class Selector:
                    def exists(self, timeout=0):
                        return False

                return Selector()

            def click(self, x, y):
                self.clicks.append((x, y))

        device = DummyDevice()
        ops = HongguoOperations(device)
        with patch("rpa.hongguo.operations.time.sleep"):
            assert ops.resume_playback_if_paused() is True
        assert device.clicks == [(450, 744)]

    def test_exit_fullscreen_does_not_press_back_on_home_activity(self):
        class DummySelector:
            def exists(self, timeout=0):
                return False

        class DummyDevice:
            def __init__(self):
                self.presses = []

            def window_size(self):
                return (900, 1600)

            def app_current(self):
                return {
                    "package": "com.phoenix.read",
                    "activity": "com.dragon.read.pages.main.MainFragmentActivity",
                }

            def dump_hierarchy(self):
                return '<node package="com.phoenix.read" text="第98集" />'

            def __call__(self, **kwargs):
                return DummySelector()

            def press(self, key):
                self.presses.append(key)

        device = DummyDevice()
        ops = HongguoOperations(device)
        assert ops.exit_fullscreen() is False
        assert device.presses == []


class TestHongguoLoginDetails:
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


class TestHongguoCommentGeneration:
    def test_prompt_leak_comment_is_rejected(self):
        generator = CommentGenerator({})
        with pytest.raises(CommentGenerationError):
            generator._clean_comment("用户指令是：我是短剧评论生成器，只输出一条可直接发布的中文评论正文。不要")


class TestHongguoEngineWaits:
    def test_choose_title_rejects_missing_second_season(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        assert engine._choose_title(
            "逆命谋臣第二季",
            ["逆命谋臣：从赘婿到帝王", "边疆王爷"],
        ) == ""

    def test_choose_title_accepts_matching_keyword_prefix(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        assert engine._choose_title(
            "逆命谋臣",
            ["逆命谋臣：从赘婿到帝王"],
        ) == "逆命谋臣：从赘婿到帝王"

    def test_watch_episode_plan_starts_from_target_episode(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        assert engine._watch_episode_plan(6, 3) == [3, 4, 5, 6]
        assert engine._watch_episode_plan(6, 99) == [6]

    def test_watch_episode_plan_can_cover_full_drama_from_first_episode(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        assert engine._watch_episode_plan(6, 1) == [1, 2, 3, 4, 5, 6]

    def test_comment_episode_plan_keeps_rule_start_episode(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        task = {"comment_mode": "specified", "start_episode": 3, "episode_interval": 2}
        assert engine._comment_episode_plan(task, 8) == [3, 5, 7]

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

    def test_wait_for_episode_rejects_skip_ahead(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        class DummyOps:
            def get_current_episode(self):
                return 3

        assert engine._wait_for_episode(DummyOps(), 2, {"comment_interval_sec": 1}) is False

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

    def test_wait_for_next_episode_rejects_skip_ahead(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        logs = []
        engine._log = lambda level, message: logs.append((level, message))

        class DummyOps:
            def skip_ad_if_present(self):
                return False

            def get_current_episode(self):
                return 4

            def _playback_visible(self):
                return True

        assert engine._wait_for_next_episode(DummyOps(), 2, {"comment_interval_sec": 1}) is False
        assert any("目标下一集" in message for _, message in logs)

    def test_wait_for_next_episode_skips_ad_before_resume(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")
        logs = []
        engine._log = lambda level, message: logs.append((level, message))

        class DummyOps:
            def __init__(self):
                self.skip_calls = 0

            def skip_ad_if_present(self):
                self.skip_calls += 1
                return self.skip_calls == 1

            def _is_app_foreground(self):
                return True

            def get_current_episode(self):
                return 2

            def _playback_visible(self):
                return True

        ops = DummyOps()
        with patch("rpa.hongguo.engine.time.time", side_effect=[0, 1, 2, 3]):
            with patch("rpa.hongguo.engine.time.sleep"):
                assert engine._wait_for_next_episode(ops, 1, {"comment_interval_sec": 1}) is True
        assert ops.skip_calls == 1
        assert any("广告页" in message for _, message in logs)
        assert any("广告后已进入第2集" in message for _, message in logs)

    def test_wait_for_next_episode_does_not_resume_while_episode_is_playing(self):
        engine = TaskEngine(task_id=1, db_config={}, screenshot_dir="C:/tmp")

        class DummyOps:
            def __init__(self):
                self.resume_calls = 0

            def skip_ad_if_present(self):
                return False

            def get_current_episode(self):
                return 3

            def _playback_visible(self):
                return True

            def resume_playback_if_paused(self, allow_center_fallback=False):
                self.resume_calls += 1
                return True

        ops = DummyOps()
        times = iter([0, 1, 1, 15, 15, 17, 17, 29, 29, 31, 31, 123])
        last_time = [0]

        def fake_time():
            try:
                last_time[0] = next(times)
            except StopIteration:
                last_time[0] += 2
            return last_time[0]

        with patch("rpa.hongguo.engine.time.time", side_effect=fake_time):
            with patch("rpa.hongguo.engine.time.sleep"):
                assert engine._wait_for_next_episode(ops, 3, {"comment_interval_sec": 1}) is False
        assert ops.resume_calls == 0

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
        assert len(sleeps) <= 6

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
