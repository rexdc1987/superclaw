"""
SuperClaw RPA - Workflow Runner

执行 YAML 定义的工作流。
"""

from __future__ import annotations

import asyncio
import logging

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from rpa.adapters.base import AdapterResult, AdapterStatus, BaseAdapter
from rpa.adapters.registry import AdapterRegistry, get_adapter_registry
from rpa.context import ContextManager
from rpa.workflow.parser import WorkflowParser
from rpa.workflow.schema import StepStatus, WorkflowDefinition, WorkflowStep

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    """步骤执行结果"""
    step_id: str
    status: StepStatus
    result: Optional[AdapterResult] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: float = 0.0
    iteration_index: Optional[int] = None  # 循环中的索引


@dataclass
class WorkflowResult:
    """工作流执行结果"""
    workflow_name: str
    status: str = "pending"  # pending/running/completed/failed
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: float = 0.0
    step_results: List[StepResult] = field(default_factory=list)
    error: Optional[str] = None
    dry_run: bool = False

    @property
    def success(self) -> bool:
        return self.status == "completed"

    @property
    def total_steps(self) -> int:
        return len(self.step_results)

    @property
    def successful_steps(self) -> int:
        return sum(1 for r in self.step_results if r.status == StepStatus.SUCCESS)

    @property
    def failed_steps(self) -> int:
        return sum(1 for r in self.step_results if r.status == StepStatus.FAILED)

    def summary(self) -> Dict[str, Any]:
        """生成摘要"""
        return {
            "workflow": self.workflow_name,
            "status": self.status,
            "total_steps": self.total_steps,
            "successful": self.successful_steps,
            "failed": self.failed_steps,
            "duration_ms": round(self.duration_ms, 1),
            "dry_run": self.dry_run,
        }


class WorkflowRunner:
    """
    工作流执行器。

    功能:
    - 从 YAML 加载并执行工作流
    - 集成适配器注册中心
    - 支持 dry-run 模式
    - 支持进度回调
    - 支持变量和上下文

    使用示例:
        runner = WorkflowRunner()
        result = await runner.run("workflow.yaml", variables={"keyword": "AI"})
        print(result.summary())
    """

    def __init__(
        self,
        adapter_registry: Optional[AdapterRegistry] = None,
        on_step_complete: Optional[Callable] = None,
        on_step_error: Optional[Callable] = None,
    ):
        self.adapter_registry = adapter_registry or get_adapter_registry()
        self.parser = WorkflowParser()
        self.context = ContextManager()
        self._adapters: Dict[str, BaseAdapter] = {}
        self._on_step_complete = on_step_complete
        self._on_step_error = on_step_error

    async def run(
        self,
        workflow_source: str,
        variables: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
        timeout_seconds: Optional[float] = None,
    ) -> WorkflowResult:
        """
        执行工作流。

        Args:
            workflow_source: YAML 文件路径或 YAML 字符串
            variables: 运行时变量（覆盖 workflow 定义中的变量）
            dry_run: 仅验证不执行
            timeout_seconds: 全局超时

        Returns:
            WorkflowResult
        """
        # 1. 解析工作流
        source_path = workflow_source
        try:
            if workflow_source.endswith((".yaml", ".yml")):
                workflow = self.parser.parse_file(workflow_source)
            else:
                workflow = self.parser.parse_string(workflow_source)
                source_path = "<yaml_string>"
        except Exception as e:
            return WorkflowResult(
                workflow_name="parse_error",
                status="failed",
                error=f"解析失败: {e}",
            )

        result = WorkflowResult(
            workflow_name=workflow.name,
            started_at=datetime.now(),
        )

        # 2. Dry-run 模式
        if dry_run:
            result.dry_run = True
            result.status = "completed"
            result.completed_at = datetime.now()
            result.duration_ms = 0
            logger.info(f"[DRY RUN] 工作流 '{workflow.name}' 验证通过 ({len(workflow.steps)} 步骤)")
            return result

        # 3. 合并变量
        all_variables = {**workflow.variables}
        if variables:
            all_variables.update(variables)
        all_variables["workflow"] = workflow.model_dump()

        # 加载到上下文
        for key, value in all_variables.items():
            self.context.set(key, value)

        # 4. 执行步骤
        result.status = "running"
        logger.info(f"开始执行工作流: {workflow.name}")

        try:
            parallel_groups = workflow.get_parallel_groups()

            for group in parallel_groups:
                if timeout_seconds:
                    elapsed = (datetime.now() - result.started_at).total_seconds()
                    if elapsed >= timeout_seconds:
                        result.status = "failed"
                        result.error = "工作流超时"
                        break

                # 并行执行组内步骤
                if len(group) == 1:
                    step_result = await self._execute_step(
                        group[0], workflow, all_variables
                    )
                    result.step_results.append(step_result)
                else:
                    tasks = [
                        self._execute_step(sid, workflow, all_variables)
                        for sid in group
                    ]
                    group_results = await asyncio.gather(*tasks, return_exceptions=True)
                    for r in group_results:
                        if isinstance(r, Exception):
                            result.step_results.append(StepResult(
                                step_id="unknown",
                                status=StepStatus.FAILED,
                                error=str(r),
                            ))
                        else:
                            result.step_results.append(r)

                # 检查失败
                if any(r.status == StepStatus.FAILED for r in result.step_results[-len(group):]):
                    step = workflow.get_step(group[0])
                    if step and step.on_failure == "fail":
                        result.status = "failed"
                        result.error = f"步骤失败: {group[0]}"
                        break

            # 设置最终状态
            if result.status == "running":
                result.status = "completed"

        except Exception as e:
            result.status = "failed"
            result.error = str(e)
            logger.error(f"工作流执行异常: {e}")

        finally:
            result.completed_at = datetime.now()
            result.duration_ms = (result.completed_at - result.started_at).total_seconds() * 1000
            await self._cleanup_adapters()

        logger.info(
            f"工作流完成: {result.workflow_name} -> {result.status} "
            f"({result.successful_steps}/{result.total_steps} 成功)"
        )
        return result

    async def _execute_step(
        self,
        step_id: str,
        workflow: WorkflowDefinition,
        variables: Dict[str, Any],
    ) -> StepResult:
        """执行单个步骤"""
        step = workflow.get_step(step_id)
        if not step:
            return StepResult(
                step_id=step_id,
                status=StepStatus.FAILED,
                error=f"步骤 '{step_id}' 不存在",
            )

        record = StepResult(
            step_id=step_id,
            status=StepStatus.RUNNING,
            started_at=datetime.now(),
        )

        # 检查条件
        if step.condition:
            if not self._evaluate_condition(step.condition, variables):
                record.status = StepStatus.SKIPPED
                record.completed_at = datetime.now()
                record.error = "条件不满足"
                logger.info(f"步骤 {step_id} 跳过: 条件不满足")
                return record

        # 解析参数
        resolved_params = WorkflowParser.resolve_step_params(step.params, variables)

        # 处理循环
        if step.loop_over:
            return await self._execute_loop(step, resolved_params, variables, workflow)

        # 执行操作
        try:
            if step.adapter:
                result = await self._execute_adapter_operation(
                    step.adapter, step.operation, resolved_params
                )
            elif step.action:
                result = await self._execute_action(step.action, resolved_params)
            else:
                result = AdapterResult(
                    status=AdapterStatus.FAILED,
                    error="未指定操作",
                )

            record.result = result
            record.status = StepStatus.SUCCESS if result.success else StepStatus.FAILED
            record.error = result.error

            # 写入上下文
            if result.success and result.data:
                self.context.set(step_id, result.data)
                for key, value in result.data.items():
                    self.context.set(f"{step_id}.{key}", value)

        except Exception as e:
            record.status = StepStatus.FAILED
            record.error = str(e)
            logger.error(f"步骤 {step_id} 异常: {e}")

        finally:
            record.completed_at = datetime.now()
            record.duration_ms = (record.completed_at - record.started_at).total_seconds() * 1000

            if self._on_step_complete:
                self._on_step_complete(step_id, record)
            if record.status == StepStatus.FAILED and self._on_step_error:
                self._on_step_error(step_id, Exception(record.error or "执行失败"))

        return record

    async def _execute_loop(
        self,
        step: WorkflowStep,
        params: Dict[str, Any],
        variables: Dict[str, Any],
        workflow: WorkflowDefinition,
    ) -> StepResult:
        """执行循环步骤"""
        loop_data = variables.get(step.loop_over.lstrip("{{").rstrip("}}"))
        if not isinstance(loop_data, list):
            loop_data = [loop_data]

        all_results = []
        for i, item in enumerate(loop_data):
            # 将循环变量注入上下文
            loop_vars = {**variables, step.loop_var: item, f"{step.loop_var}_index": i}

            try:
                if step.adapter:
                    result = await self._execute_adapter_operation(
                        step.adapter, step.operation, params
                    )
                elif step.action:
                    result = await self._execute_action(step.action, params)
                else:
                    result = AdapterResult(status=AdapterStatus.FAILED, error="未指定操作")

                all_results.append(StepResult(
                    step_id=f"{step.id}[{i}]",
                    status=StepStatus.SUCCESS if result.success else StepStatus.FAILED,
                    result=result,
                    iteration_index=i,
                ))
            except Exception as e:
                all_results.append(StepResult(
                    step_id=f"{step.id}[{i}]",
                    status=StepStatus.FAILED,
                    error=str(e),
                    iteration_index=i,
                ))

        # 汇总结果
        success_count = sum(1 for r in all_results if r.status == StepStatus.SUCCESS)
        return StepResult(
            step_id=step.id,
            status=StepStatus.SUCCESS if success_count == len(all_results) else StepStatus.FAILED,
            result=AdapterResult(
                status=AdapterStatus.SUCCESS if success_count == len(all_results) else AdapterStatus.FAILED,
                data={"iterations": len(all_results), "success": success_count},
            ),
            error=None if success_count == len(all_results) else f"{len(all_results) - success_count} 次迭代失败",
        )

    async def _execute_adapter_operation(
        self,
        platform: str,
        operation: str,
        params: Dict[str, Any],
    ) -> AdapterResult:
        """执行适配器操作"""
        adapter = self._get_adapter(platform)
        if not adapter:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error=f"未注册的适配器: {platform}",
            )

        # 映射操作方法
        method_map = {
            "login": "login",
            "search": "search_content",
            "search_content": "search_content",
            "comment": "post_comment",
            "post_comment": "post_comment",
            "like": "like_content",
            "like_content": "like_content",
            "follow": "follow_user",
            "follow_user": "follow_user",
            "collect": "collect_note",
            "get_comments": "get_comments",
            "get_user_info": "get_user_info",
        }

        method_name = method_map.get(operation)
        if not method_name:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error=f"不支持的操作: {operation}",
            )

        method = getattr(adapter, method_name, None)
        if not method:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error=f"适配器 {platform} 不支持操作: {operation}",
            )

        try:
            return await method(**params)
        except Exception as e:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error=str(e),
            )

    async def _execute_action(
        self,
        action_name: str,
        params: Dict[str, Any],
    ) -> AdapterResult:
        """执行 DAG Action（兼容模式）"""
        from rpa.actions import get_registry
        from rpa.interfaces import ActionParams

        registry = get_registry()
        action = registry.create(action_name)
        if not action:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error=f"未注册的 Action: {action_name}",
            )

        try:
            action_params = ActionParams(**params)
            result = action.execute(action_params, self.context)
            return AdapterResult(
                status=AdapterStatus.SUCCESS if result.status.value == "success" else AdapterStatus.FAILED,
                data=result.outputs,
                error=result.error,
            )
        except Exception as e:
            return AdapterResult(status=AdapterStatus.FAILED, error=str(e))
        finally:
            action.cleanup()

    def _get_adapter(self, platform: str) -> Optional[BaseAdapter]:
        """获取或创建适配器实例"""
        if platform not in self._adapters:
            adapter = self.adapter_registry.create(platform)
            if adapter:
                self._adapters[platform] = adapter
        return self._adapters.get(platform)

    def _evaluate_condition(self, condition: str, variables: Dict[str, Any]) -> bool:
        """评估条件表达式"""
        try:
            import re
            def _replace_var(m):
                var_name = (m.group(1) or m.group(2)).strip()
                val = variables.get(var_name, self.context.get(var_name))
                if isinstance(val, str):
                    return repr(val)
                elif val is None:
                    return "None"
                else:
                    return str(val)
            expression = re.sub(r"\{\{(.+?)\}\}|\$\{(.+?)\}", _replace_var, condition)

            safe_builtins = {
                "True": True, "False": False, "None": None,
                "len": len, "str": str, "int": int, "float": float, "bool": bool,
            }
            result = eval(expression, {"__builtins__": safe_builtins}, {})
            return bool(result)
        except Exception as e:
            logger.warning(f"条件评估失败: {condition} -> {e}")
            return False

    async def _cleanup_adapters(self):
        """清理所有适配器"""
        for adapter in self._adapters.values():
            try:
                await adapter.teardown()
            except Exception:
                pass
        self._adapters.clear()


# TASK_COMPLETE: phase4_workflow
