"""
SuperClaw RPA - Workflow 模块测试

测试 YAML Schema、Parser、Runner。
"""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rpa.workflow.parser import WorkflowParseError, WorkflowParser
from rpa.workflow.runner import WorkflowResult, WorkflowRunner
from rpa.workflow.schema import RetryConfig, StepStatus, WorkflowDefinition, WorkflowStep


# ============================================================
# 测试 YAML Schema
# ============================================================

class TestWorkflowSchema:
    """工作流 Schema 测试"""

    def test_workflow_definition(self):
        wf = WorkflowDefinition(
            name="test",
            steps=[
                WorkflowStep(id="s1", adapter="douyin", operation="search", params={"keyword": "test"}),
            ],
        )
        assert wf.name == "test"
        assert len(wf.steps) == 1

    def test_step_auto_id(self):
        step = WorkflowStep(adapter="douyin", operation="search")
        assert step.id == "douyin.search"

    def test_step_auto_id_action(self):
        step = WorkflowStep(action="log.info")
        assert step.id == "log.info"

    def test_validate_dag_success(self):
        wf = WorkflowDefinition(
            name="test",
            steps=[
                WorkflowStep(id="a", adapter="douyin", operation="search"),
                WorkflowStep(id="b", adapter="douyin", operation="comment", depends_on=["a"]),
            ],
        )
        errors = wf.validate_dag()
        assert errors == []

    def test_validate_dag_cycle(self):
        wf = WorkflowDefinition(
            name="test",
            steps=[
                WorkflowStep(id="a", adapter="douyin", operation="search", depends_on=["b"]),
                WorkflowStep(id="b", adapter="douyin", operation="comment", depends_on=["a"]),
            ],
        )
        errors = wf.validate_dag()
        assert any("循环" in e for e in errors)

    def test_validate_dag_duplicate_ids(self):
        wf = WorkflowDefinition(
            name="test",
            steps=[
                WorkflowStep(id="a", adapter="douyin", operation="search"),
                WorkflowStep(id="a", adapter="douyin", operation="comment"),
            ],
        )
        errors = wf.validate_dag()
        assert any("重复" in e for e in errors)

    def test_validate_dag_missing_adapter(self):
        wf = WorkflowDefinition(
            name="test",
            steps=[
                WorkflowStep(id="a", params={"keyword": "test"}),
            ],
        )
        errors = wf.validate_dag()
        assert any("必须指定" in e for e in errors)

    def test_validate_dag_adapter_without_operation(self):
        wf = WorkflowDefinition(
            name="test",
            steps=[
                WorkflowStep(id="a", adapter="douyin"),
            ],
        )
        errors = wf.validate_dag()
        assert any("缺少 operation" in e for e in errors)

    def test_validate_dag_invalid_dependency(self):
        wf = WorkflowDefinition(
            name="test",
            steps=[
                WorkflowStep(id="a", adapter="douyin", operation="search", depends_on=["nonexistent"]),
            ],
        )
        errors = wf.validate_dag()
        assert any("不存在" in e for e in errors)

    def test_topological_sort(self):
        wf = WorkflowDefinition(
            name="test",
            steps=[
                WorkflowStep(id="a", adapter="douyin", operation="search"),
                WorkflowStep(id="b", adapter="douyin", operation="comment", depends_on=["a"]),
                WorkflowStep(id="c", adapter="douyin", operation="like", depends_on=["a"]),
            ],
        )
        order = wf.topological_sort()
        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")

    def test_topological_sort_cycle_raises(self):
        wf = WorkflowDefinition(
            name="test",
            steps=[
                WorkflowStep(id="a", adapter="douyin", operation="search", depends_on=["b"]),
                WorkflowStep(id="b", adapter="douyin", operation="comment", depends_on=["a"]),
            ],
        )
        with pytest.raises(ValueError, match="循环"):
            wf.topological_sort()

    def test_parallel_groups(self):
        wf = WorkflowDefinition(
            name="test",
            steps=[
                WorkflowStep(id="a", adapter="douyin", operation="search"),
                WorkflowStep(id="b", adapter="douyin", operation="comment", depends_on=["a"]),
                WorkflowStep(id="c", adapter="douyin", operation="like", depends_on=["a"]),
            ],
        )
        groups = wf.get_parallel_groups()
        assert groups[0] == ["a"]
        assert set(groups[1]) == {"b", "c"}

    def test_retry_config(self):
        config = RetryConfig(max_attempts=5, delay_seconds=1.0, backoff_multiplier=3.0)
        assert config.max_attempts == 5
        assert config.backoff_multiplier == 3.0


# ============================================================
# 测试 Parser
# ============================================================

class TestWorkflowParser:
    """YAML 解析器测试"""

    def setup_method(self):
        self.parser = WorkflowParser()

    def test_parse_string(self):
        yaml_content = """
name: test_workflow
steps:
  - id: search
    adapter: douyin
    operation: search
    params:
      keyword: "AI"
      count: 10
  - id: comment
    adapter: douyin
    operation: comment
    params:
      content: "好内容！"
    depends_on: [search]
"""
        wf = self.parser.parse_string(yaml_content)
        assert wf.name == "test_workflow"
        assert len(wf.steps) == 2
        assert wf.steps[0].id == "search"
        assert wf.steps[1].depends_on == ["search"]

    def test_parse_with_variables(self):
        yaml_content = """
name: variable_test
variables:
  keyword: "Python"
  count: 5
steps:
  - adapter: douyin
    operation: search
    params:
      keyword: "{{keyword}}"
      count: "{{count}}"
"""
        wf = self.parser.parse_string(yaml_content)
        assert wf.variables["keyword"] == "Python"
        assert wf.variables["count"] == 5

    def test_parse_with_retry(self):
        yaml_content = """
name: retry_test
steps:
  - adapter: douyin
    operation: search
    params: {keyword: "test"}
    retry:
      max_attempts: 5
      delay_seconds: 2.0
"""
        wf = self.parser.parse_string(yaml_content)
        assert wf.steps[0].retry.max_attempts == 5
        assert wf.steps[0].retry.delay_seconds == 2.0

    def test_parse_with_condition(self):
        yaml_content = """
name: condition_test
steps:
  - adapter: douyin
    operation: comment
    params: {content: "好"}
    condition: "{{item.likes}} > 100"
"""
        wf = self.parser.parse_string(yaml_content)
        assert wf.steps[0].condition == "{{item.likes}} > 100"

    def test_parse_invalid_yaml(self):
        with pytest.raises(WorkflowParseError, match="YAML 解析失败"):
            self.parser.parse_string("{{{{invalid yaml")

    def test_parse_missing_name(self):
        with pytest.raises(WorkflowParseError, match="缺少 'name'"):
            self.parser.parse_string("steps: []")

    def test_parse_empty_steps(self):
        with pytest.raises(WorkflowParseError, match="没有定义任何步骤"):
            self.parser.parse_string("name: test\nsteps: []")

    def test_parse_file(self, tmp_path):
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("name: file_test\nsteps:\n  - adapter: douyin\n    operation: search\n    params: {keyword: hi}", encoding="utf-8")
        wf = self.parser.parse_file(str(yaml_file))
        assert wf.name == "file_test"

    def test_parse_file_not_found(self):
        with pytest.raises(WorkflowParseError, match="不存在"):
            self.parser.parse_file("nonexistent.yaml")

    def test_parse_file_wrong_extension(self, tmp_path):
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("hello")
        with pytest.raises(WorkflowParseError, match="不支持"):
            self.parser.parse_file(str(txt_file))

    def test_resolve_template(self):
        result = WorkflowParser.resolve_template("{{keyword}}", {"keyword": "AI"})
        assert result == "AI"

    def test_resolve_template_mixed(self):
        result = WorkflowParser.resolve_template("搜索: {{keyword}}", {"keyword": "AI"})
        assert result == "搜索: AI"

    def test_resolve_template_pure_reference(self):
        result = WorkflowParser.resolve_template("{{count}}", {"count": 42})
        assert result == 42
        assert isinstance(result, int)

    def test_resolve_step_params(self):
        params = {"keyword": "{{kw}}", "count": 10}
        resolved = WorkflowParser.resolve_step_params(params, {"kw": "Python"})
        assert resolved["keyword"] == "Python"
        assert resolved["count"] == 10


# ============================================================
# 测试 Runner (Mock)
# ============================================================

class TestWorkflowRunner:
    """工作流 Runner 测试"""

    def test_runner_init(self):
        runner = WorkflowRunner()
        assert runner.adapter_registry is not None
        assert runner.context is not None

    @pytest.mark.asyncio
    async def test_dry_run(self):
        runner = WorkflowRunner()
        yaml_content = """
name: dry_test
steps:
  - adapter: douyin
    operation: search
    params: {keyword: "test"}
"""
        result = await runner.run(yaml_content, dry_run=True)
        assert result.success
        assert result.dry_run is True
        assert result.total_steps == 0  # dry-run 不执行步骤

    @pytest.mark.asyncio
    async def test_run_invalid_workflow(self):
        runner = WorkflowRunner()
        result = await runner.run("nonexistent.yaml")
        assert result.status == "failed"
        assert "解析失败" in result.error

    @pytest.mark.asyncio
    async def test_run_workflow_summary(self):
        runner = WorkflowRunner()
        yaml_content = """
name: summary_test
steps:
  - adapter: douyin
    operation: search
    params: {keyword: "test"}
"""
        result = await runner.run(yaml_content, dry_run=True)
        summary = result.summary()
        assert summary["workflow"] == "summary_test"
        assert summary["dry_run"] is True

    @pytest.mark.asyncio
    async def test_run_with_variables(self):
        runner = WorkflowRunner()
        yaml_content = """
name: var_test
variables:
  default_kw: "default"
steps:
  - adapter: douyin
    operation: search
    params: {keyword: "{{default_kw}}"}
"""
        result = await runner.run(yaml_content, variables={"override": "value"}, dry_run=True)
        assert result.success

    def test_parse_variables(self):
        from rpa.cli.commands.run import _parse_variables
        result = _parse_variables(["keyword=AI", "count=10", 'name="hello"'])
        assert result["keyword"] == "AI"
        assert result["count"] == 10

    @pytest.mark.asyncio
    async def test_condition_eval(self):
        runner = WorkflowRunner()
        assert runner._evaluate_condition("True", {}) is True
        assert runner._evaluate_condition("False", {}) is False
        assert runner._evaluate_condition("{{x}} > 5", {"x": 10}) is True
        assert runner._evaluate_condition("{{x}} > 5", {"x": 3}) is False

    def test_step_result(self):
        from rpa.workflow.runner import StepResult
        record = StepResult(
            step_id="test",
            status=StepStatus.SUCCESS,
        )
        assert record.status == StepStatus.SUCCESS

    def test_workflow_result(self):
        result = WorkflowResult(workflow_name="test")
        assert result.success is False
        assert result.total_steps == 0


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
