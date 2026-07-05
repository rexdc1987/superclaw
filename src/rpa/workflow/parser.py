"""
SuperClaw RPA - Workflow YAML 解析器

将 YAML 文件解析为 WorkflowDefinition 对象。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, Union

import yaml

from rpa.workflow.schema import RetryConfig, WorkflowDefinition, WorkflowStep

logger = logging.getLogger(__name__)

# 模板变量匹配: {{var}} 或 ${var}
_TEMPLATE_PATTERN = re.compile(r"\{\{(.+?)\}\}|\$\{(.+?)\}")


class WorkflowParseError(Exception):
    """工作流解析错误"""
    pass


class WorkflowParser:
    """
    YAML 工作流解析器。

    支持:
    - 从文件加载 YAML
    - 从字符串加载 YAML
    - 模板变量替换
    - DAG 验证

    使用示例:
        parser = WorkflowParser()
        workflow = parser.parse_file("workflow.yaml")
        # 或
        workflow = parser.parse_string(yaml_content)
    """

    def parse_file(self, file_path: Union[str, Path]) -> WorkflowDefinition:
        """
        从 YAML 文件解析工作流。

        Args:
            file_path: YAML 文件路径

        Returns:
            WorkflowDefinition

        Raises:
            WorkflowParseError: 解析失败
        """
        path = Path(file_path)
        if not path.exists():
            raise WorkflowParseError(f"文件不存在: {path}")

        if not path.suffix in (".yaml", ".yml"):
            raise WorkflowParseError(f"不支持的文件格式: {path.suffix}")

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise WorkflowParseError(f"YAML 解析失败: {e}")
        except Exception as e:
            raise WorkflowParseError(f"读取文件失败: {e}")

        return self.parse_dict(data, source=str(path))

    def parse_string(self, content: str) -> WorkflowDefinition:
        """
        从 YAML 字符串解析工作流。

        Args:
            content: YAML 内容字符串

        Returns:
            WorkflowDefinition
        """
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise WorkflowParseError(f"YAML 解析失败: {e}")

        return self.parse_dict(data)

    def parse_dict(self, data: Dict[str, Any], source: str = "<string>") -> WorkflowDefinition:
        """
        从字典解析工作流。

        Args:
            data: 已解析的字典数据
            source: 来源标识（用于错误信息）

        Returns:
            WorkflowDefinition
        """
        if not isinstance(data, dict):
            raise WorkflowParseError(f"工作流定义必须是字典，当前类型: {type(data)}")

        # 提取工作流级字段
        name = data.get("name", "")
        if not name:
            raise WorkflowParseError("工作流缺少 'name' 字段")

        # 提取变量
        variables = data.get("variables", {})

        # 解析步骤
        raw_steps = data.get("steps", [])
        if not raw_steps:
            raise WorkflowParseError("工作流没有定义任何步骤")

        steps = []
        for i, raw_step in enumerate(raw_steps):
            try:
                step = self._parse_step(raw_step, index=i)
                steps.append(step)
            except Exception as e:
                raise WorkflowParseError(f"步骤 {i} 解析失败: {e}")

        # 构建 WorkflowDefinition
        workflow = WorkflowDefinition(
            name=name,
            description=data.get("description"),
            version=data.get("version", "1.0.0"),
            author=data.get("author"),
            tags=data.get("tags", []),
            steps=steps,
            variables=variables,
            on_failure=data.get("on_failure", "fail"),
            max_retries=data.get("max_retries", 3),
            timeout_seconds=data.get("timeout_seconds"),
        )

        # 验证 DAG
        errors = workflow.validate_dag()
        if errors:
            raise WorkflowParseError(f"工作流验证失败:\n" + "\n".join(f"  - {e}" for e in errors))

        logger.info(f"工作流解析成功: {name} ({len(steps)} 个步骤)")
        return workflow

    def _parse_step(self, raw: Dict[str, Any], index: int) -> WorkflowStep:
        """解析单个步骤"""
        if not isinstance(raw, dict):
            raise ValueError(f"步骤必须是字典，当前类型: {type(raw)}")

        # 解析重试配置
        retry = None
        retry_raw = raw.get("retry")
        if retry_raw:
            if isinstance(retry_raw, dict):
                retry = RetryConfig(**retry_raw)
            elif isinstance(retry_raw, int):
                retry = RetryConfig(max_attempts=retry_raw)

        return WorkflowStep(
            id=raw.get("id"),
            name=raw.get("name"),
            adapter=raw.get("adapter"),
            operation=raw.get("operation"),
            action=raw.get("action"),
            params=raw.get("params", {}),
            depends_on=raw.get("depends_on", []),
            condition=raw.get("condition"),
            on_failure=raw.get("on_failure", "fail"),
            retry=retry,
            timeout_seconds=raw.get("timeout_seconds"),
            loop_over=raw.get("loop_over"),
            loop_var=raw.get("loop_var"),
        )

    @staticmethod
    def resolve_template(template: str, variables: Dict[str, Any]) -> Any:
        """
        解析模板变量。

        Args:
            template: 模板字符串，如 "{{keyword}}" 或 "${count}"
            variables: 变量字典

        Returns:
            解析后的值（如果整个字符串就是模板引用，返回原始类型）
        """
        if not isinstance(template, str):
            return template

        # 纯模板引用
        match = _TEMPLATE_PATTERN.fullmatch(template)
        if match:
            var_name = (match.group(1) or match.group(2)).strip()
            return variables.get(var_name, template)

        # 混合模板
        def replacer(m):
            var_name = (m.group(1) or m.group(2)).strip()
            value = variables.get(var_name, "")
            return str(value) if value is not None else ""

        return _TEMPLATE_PATTERN.sub(replacer, template)

    @staticmethod
    def resolve_step_params(
        params: Dict[str, Any],
        variables: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        解析步骤参数中的模板变量。

        Args:
            params: 原始参数
            variables: 变量字典

        Returns:
            解析后的参数
        """
        resolved = {}
        for key, value in params.items():
            if isinstance(value, str):
                resolved[key] = WorkflowParser.resolve_template(value, variables)
            elif isinstance(value, dict):
                resolved[key] = WorkflowParser.resolve_step_params(value, variables)
            elif isinstance(value, list):
                resolved[key] = [
                    WorkflowParser.resolve_template(v, variables) if isinstance(v, str) else v
                    for v in value
                ]
            else:
                resolved[key] = value
        return resolved


# TASK_COMPLETE: phase4_workflow
