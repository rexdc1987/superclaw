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
                return ""

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
