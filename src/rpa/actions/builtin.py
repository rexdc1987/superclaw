"""
SuperClaw RPA 引擎 - 内置 Actions

提供开箱即用的基础 Action：
- log: 日志输出
- delay: 等待/延时
- condition: 条件判断
- set_var / get_var: 变量操作
- http_get / http_post: HTTP 请求
- transform: 数据转换
"""

from __future__ import annotations

import json

import time
from typing import Any, Dict

from rpa.actions import get_registry
from rpa.interfaces import (
    ActionParams,
    ActionResult,
    ActionStatus,
    BaseAction,
)


# ============================================================
# 日志 Action
# ============================================================

class LogAction(BaseAction):
    """输出日志信息"""
    name = "log"
    description = "输出日志信息"
    category = "util"

    def execute(self, params: ActionParams, context: Any) -> ActionResult:
        level = params.get("level", "info").upper()
        message = params.get("message", "")
        message = context.resolve_template(str(message))

        log_func = getattr(self.logger, level.lower(), self.logger.info)
        log_func(message)

        return ActionResult(
            status=ActionStatus.SUCCESS,
            outputs={"logged": True, "message": message},
        )


# ============================================================
# 等待 Action
# ============================================================

class DelayAction(BaseAction):
    """等待指定时间"""
    name = "delay"
    description = "等待指定秒数"
    category = "util"

    def validate_params(self, params: ActionParams) -> bool:
        seconds = params.get("seconds", 0)
        if not isinstance(seconds, (int, float)) or seconds < 0:
            raise ValueError(f"seconds 必须是非负数，当前值: {seconds}")
        return True

    def execute(self, params: ActionParams, context: Any) -> ActionResult:
        seconds = float(params.get("seconds", 1))
        self.logger.info(f"等待 {seconds} 秒...")
        time.sleep(seconds)
        return ActionResult(
            status=ActionStatus.SUCCESS,
            outputs={"waited_seconds": seconds},
        )


# ============================================================
# 条件判断 Action
# ============================================================

class ConditionAction(BaseAction):
    """
    条件判断，根据表达式结果决定走哪个分支。
    
    params:
        expression: Python 表达式字符串
        true_value: 条件为真时的输出值（可选）
        false_value: 条件为假时的输出值（可选）
    """
    name = "condition"
    description = "条件判断"
    category = "control"

    def execute(self, params: ActionParams, context: Any) -> ActionResult:
        expression = params.get("expression", "True")
        
        # 先用正则将 {{var}} 引用替换为 Python 字面量（保留类型）
        import re
        def _replace_var(m):
            var_name = (m.group(1) or m.group(2)).strip()
            val = context.get(var_name)
            if isinstance(val, str):
                return repr(val)
            elif val is None:
                return "None"
            else:
                return str(val)
        expression = re.sub(r"\{\{(.+?)\}\}|\$\{(.+?)\}", _replace_var, str(expression))

        # 安全评估表达式
        try:
            result = self._safe_eval(expression, context)
        except Exception as e:
            self.logger.error(f"条件表达式执行失败: {expression} -> {e}")
            return ActionResult(
                status=ActionStatus.FAILED,
                error=f"表达式执行失败: {e}",
            )

        true_val = params.get("true_value", result)
        false_val = params.get("false_value", not result)

        output_value = true_val if result else false_val

        self.logger.info(f"条件判断: {expression} = {result}")

        return ActionResult(
            status=ActionStatus.SUCCESS,
            outputs={
                "result": bool(result),
                "value": output_value,
            },
        )

    def _safe_eval(self, expression: str, context: Any) -> bool:
        """安全评估表达式（仅允许简单比较和逻辑运算）"""
        # 构建可用变量的沙箱
        sandbox: Dict[str, Any] = {}
        
        # 从 context 加载变量
        if hasattr(context, "get_all"):
            all_vars = context.get_all()
            sandbox.update(all_vars)
        
        # 仅允许安全的内置函数
        safe_builtins = {
            "True": True,
            "False": False,
            "None": None,
            "len": len,
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
        }
        
        try:
            result = eval(expression, {"__builtins__": safe_builtins}, sandbox)
            return bool(result)
        except Exception:
            # 尝试作为简单布尔值解析
            if expression.lower() in ("true", "yes", "1"):
                return True
            if expression.lower() in ("false", "no", "0", ""):
                return False
            raise


# ============================================================
# 变量操作 Action
# ============================================================

class SetVarAction(BaseAction):
    """设置变量"""
    name = "set_var"
    description = "设置上下文变量"
    category = "util"

    def execute(self, params: ActionParams, context: Any) -> ActionResult:
        var_name = params.get("name", "")
        var_value = params.get("value")
        
        if not var_name:
            return ActionResult(
                status=ActionStatus.FAILED,
                error="变量名不能为空",
            )
        
        context.set(str(var_name), var_value)
        self.logger.info(f"设置变量: {var_name} = {var_value}")
        
        return ActionResult(
            status=ActionStatus.SUCCESS,
            outputs={"name": var_name, "value": var_value},
        )


class GetVarAction(BaseAction):
    """获取变量"""
    name = "get_var"
    description = "获取上下文变量"
    category = "util"

    def execute(self, params: ActionParams, context: Any) -> ActionResult:
        var_name = params.get("name", "")
        default = params.get("default")
        
        value = context.get(str(var_name), default)
        self.logger.info(f"获取变量: {var_name} = {value}")
        
        return ActionResult(
            status=ActionStatus.SUCCESS,
            outputs={"name": var_name, "value": value},
        )


# ============================================================
# HTTP Actions
# ============================================================

class HttpGetAction(BaseAction):
    """
    HTTP GET 请求。
    
    params:
        url: 请求 URL
        headers: 请求头（可选）
        timeout: 超时秒数（可选，默认 30）
    """
    name = "http.get"
    description = "HTTP GET 请求"
    category = "http"

    def execute(self, params: ActionParams, context: Any) -> ActionResult:
        url = str(context.resolve_template(str(params.get("url", ""))))
        headers = params.get("headers", {})
        timeout = int(params.get("timeout", 30))
        
        if not url:
            return ActionResult(
                status=ActionStatus.FAILED,
                error="URL 不能为空",
            )

        try:
            import httpx
            response = httpx.get(url, headers=headers, timeout=timeout)
            
            # 尝试解析 JSON
            try:
                body = response.json()
            except Exception:
                body = response.text
            
            return ActionResult(
                status=ActionStatus.SUCCESS,
                outputs={
                    "status_code": response.status_code,
                    "body": body,
                    "headers": dict(response.headers),
                },
            )
        except ImportError:
            # 降级到 urllib
            import urllib.request
            import urllib.error
            
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    body = resp.read().decode("utf-8")
                    try:
                        body = json.loads(body)
                    except Exception:
                        pass
                    
                    return ActionResult(
                        status=ActionStatus.SUCCESS,
                        outputs={
                            "status_code": resp.status,
                            "body": body,
                            "headers": dict(resp.headers),
                        },
                    )
            except urllib.error.URLError as e:
                return ActionResult(
                    status=ActionStatus.FAILED,
                    error=f"HTTP 请求失败: {e}",
                )


class HttpPostAction(BaseAction):
    """
    HTTP POST 请求。
    
    params:
        url: 请求 URL
        data: 请求体（dict 或 str）
        headers: 请求头（可选）
        timeout: 超时秒数（可选，默认 30）
    """
    name = "http.post"
    description = "HTTP POST 请求"
    category = "http"

    def execute(self, params: ActionParams, context: Any) -> ActionResult:
        url = str(context.resolve_template(str(params.get("url", ""))))
        data = params.get("data", {})
        headers = params.get("headers", {"Content-Type": "application/json"})
        timeout = int(params.get("timeout", 30))
        
        if not url:
            return ActionResult(
                status=ActionStatus.FAILED,
                error="URL 不能为空",
            )

        # 如果 data 是 dict，序列化为 JSON
        if isinstance(data, dict):
            json_data = json.dumps(data, ensure_ascii=False).encode("utf-8")
        else:
            json_data = str(data).encode("utf-8")

        try:
            import httpx
            response = httpx.post(url, content=json_data, headers=headers, timeout=timeout)
            
            try:
                body = response.json()
            except Exception:
                body = response.text
            
            return ActionResult(
                status=ActionStatus.SUCCESS,
                outputs={
                    "status_code": response.status_code,
                    "body": body,
                    "headers": dict(response.headers),
                },
            )
        except ImportError:
            import urllib.request
            import urllib.error
            
            req = urllib.request.Request(url, data=json_data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    body = resp.read().decode("utf-8")
                    try:
                        body = json.loads(body)
                    except Exception:
                        pass
                    
                    return ActionResult(
                        status=ActionStatus.SUCCESS,
                        outputs={
                            "status_code": resp.status,
                            "body": body,
                            "headers": dict(resp.headers),
                        },
                    )
            except urllib.error.URLError as e:
                return ActionResult(
                    status=ActionStatus.FAILED,
                    error=f"HTTP 请求失败: {e}",
                )


# ============================================================
# 数据转换 Action
# ============================================================

class TransformAction(BaseAction):
    """
    数据转换。
    
    支持操作：
    - json_parse: 解析 JSON 字符串
    - json_dumps: 序列化为 JSON
    - extract: 使用 JSONPath 提取字段
    - template: 模板渲染
    """
    name = "transform"
    description = "数据转换（JSON 解析/序列化/提取）"
    category = "data"

    def execute(self, params: ActionParams, context: Any) -> ActionResult:
        operation = params.get("operation", "json_parse")
        input_data = params.get("input")
        
        if input_data is not None and isinstance(input_data, str):
            input_data = context.resolve_template(input_data)
        
        try:
            if operation == "json_parse":
                result = json.loads(str(input_data)) if input_data else None
            elif operation == "json_dumps":
                result = json.dumps(input_data, ensure_ascii=False, indent=2)
            elif operation == "extract":
                path = params.get("path", "")
                result = self._extract_path(input_data, path)
            elif operation == "template":
                template = params.get("template", "")
                result = context.resolve_template(str(template))
            else:
                return ActionResult(
                    status=ActionStatus.FAILED,
                    error=f"不支持的操作: {operation}",
                )
            
            return ActionResult(
                status=ActionStatus.SUCCESS,
                outputs={"result": result},
            )
        except Exception as e:
            return ActionResult(
                status=ActionStatus.FAILED,
                error=f"转换失败: {e}",
            )

    def _extract_path(self, data: Any, path: str) -> Any:
        """简单的 JSONPath 提取（支持 $.key.subkey 格式）"""
        if not path or not data:
            return data
        
        # 移除开头的 $
        path = path.lstrip("$").lstrip(".")
        
        current = data
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                current = current[int(part)]
            else:
                return None
        
        return current


# ============================================================
# 注册所有内置 Actions
# ============================================================

_BUILTIN_ACTIONS = [
    LogAction,
    DelayAction,
    ConditionAction,
    SetVarAction,
    GetVarAction,
    HttpGetAction,
    HttpPostAction,
    TransformAction,
]


def register_builtin_actions() -> int:
    """注册所有内置 Action"""
    registry = get_registry()
    count = 0
    for action_class in _BUILTIN_ACTIONS:
        if not registry.has(action_class.name):
            registry.register(action_class)
            count += 1
    logger.info(f"注册了 {count} 个内置 Action")
    return count
