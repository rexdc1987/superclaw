"""告警引擎 — 规则引擎 + 多通道推送 + 告警去重。

使用方式:
    engine = AlertEngine()
    engine.add_rule(AlertRule(
        name="成功率下降",
        condition="success_rate",
        threshold=0.8,
        operator="lt",
        channels=[feishu_channel],
    ))
    await engine.evaluate(metrics_collector)
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """告警级别。"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ComparisonOperator(Enum):
    """比较运算符。"""
    LT = "lt"       # <
    LE = "le"       # <=
    GT = "gt"       # >
    GE = "ge"       # >=
    EQ = "eq"       # ==


@dataclass
class AlertRule:
    """告警规则。"""
    name: str
    condition: str        # 指标名：success_rate, queue_depth, active_accounts 等
    threshold: float      # 阈值
    operator: str         # 比较运算符：lt, le, gt, ge, eq
    channels: list        # 告警通道列表
    severity: AlertSeverity = AlertSeverity.WARNING
    cooldown: float = 300.0  # 冷却时间（秒），避免重复告警
    message_template: str = ""  # 自定义消息模板

    def evaluate(self, current_value: float) -> bool:
        """评估当前值是否触发告警。"""
        ops = {
            "lt": lambda a, b: a < b,
            "le": lambda a, b: a <= b,
            "gt": lambda a, b: a > b,
            "ge": lambda a, b: a >= b,
            "eq": lambda a, b: abs(a - b) < 0.001,
        }
        op_func = ops.get(self.operator)
        if not op_func:
            logger.error("未知运算符: %s", self.operator)
            return False
        return op_func(current_value, self.threshold)


@dataclass
class Alert:
    """告警实例。"""
    rule_name: str
    severity: AlertSeverity
    message: str
    current_value: float
    threshold: float
    timestamp: float = field(default_factory=time.time)


class AlertEngine:
    """告警引擎 — 评估规则、推送告警、去重冷却。"""

    def __init__(self):
        self._rules: List[AlertRule] = []
        self._last_alert_time: Dict[str, float] = {}
        self._alert_history: List[Alert] = []

    def add_rule(self, rule: AlertRule) -> None:
        """添加告警规则。"""
        self._rules.append(rule)
        logger.info("告警规则已添加: %s (%s %s %.2f)",
                    rule.name, rule.condition, rule.operator, rule.threshold)

    def remove_rule(self, name: str) -> bool:
        """移除告警规则。"""
        for i, rule in enumerate(self._rules):
            if rule.name == name:
                self._rules.pop(i)
                return True
        return False

    def list_rules(self) -> List[AlertRule]:
        """列出所有规则。"""
        return list(self._rules)

    async def evaluate(self, metrics) -> List[Alert]:
        """评估所有规则并推送告警。

        Args:
            metrics: MetricsCollector 实例或 dict

        Returns:
            触发的告警列表
        """
        triggered = []

        for rule in self._rules:
            # 获取当前值
            current_value = self._get_metric_value(metrics, rule.condition)
            if current_value is None:
                continue

            # 评估规则
            if not rule.evaluate(current_value):
                continue

            # 检查冷却
            if self._in_cooldown(rule.name, rule.cooldown):
                continue

            # 生成告警
            alert = self._create_alert(rule, current_value)
            triggered.append(alert)
            self._last_alert_time[rule.name] = time.time()
            self._alert_history.append(alert)

            # 推送到所有通道
            await self._dispatch(alert, rule.channels)

        return triggered

    def _get_metric_value(self, metrics, condition: str) -> Optional[float]:
        """从 metrics 中提取指标值。"""
        if isinstance(metrics, dict):
            return metrics.get(condition)

        # MetricsCollector 实例
        getter = {
            "success_rate": lambda m: m.success_rate.value,
            "queue_depth": lambda m: m.queue_depth.value,
            "active_accounts": lambda m: m.active_accounts.value,
            "total_failure": lambda m: m._total_failure,
            "total_success": lambda m: m._total_success,
        }.get(condition)

        if getter:
            return getter(metrics)
        logger.warning("未知指标: %s", condition)
        return None

    def _in_cooldown(self, rule_name: str, cooldown: float) -> bool:
        """检查是否在冷却期内。"""
        last_time = self._last_alert_time.get(rule_name, 0)
        return (time.time() - last_time) < cooldown

    def _create_alert(self, rule: AlertRule, current_value: float) -> Alert:
        """创建告警实例。"""
        if rule.message_template:
            message = rule.message_template.format(
                name=rule.name,
                condition=rule.condition,
                current=current_value,
                threshold=rule.threshold,
            )
        else:
            message = (
                f"[{rule.severity.value.upper()}] {rule.name}\n"
                f"指标: {rule.condition}\n"
                f"当前值: {current_value}\n"
                f"阈值: {rule.threshold}"
            )
        return Alert(
            rule_name=rule.name,
            severity=rule.severity,
            message=message,
            current_value=current_value,
            threshold=rule.threshold,
        )

    async def _dispatch(self, alert: Alert, channels: list) -> None:
        """推送告警到所有通道。"""
        tasks = []
        for channel in channels:
            if hasattr(channel, "send"):
                tasks.append(channel.send(alert))
            else:
                logger.warning("通道缺少 send 方法: %s", type(channel).__name__)

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error("告警推送失败 (%s): %s",
                               type(channels[i]).__name__, result)

    def get_alert_history(self, limit: int = 50) -> List[Alert]:
        """获取告警历史。"""
        return self._alert_history[-limit:]

    def get_summary(self) -> dict:
        """获取引擎摘要。"""
        return {
            "rules": len(self._rules),
            "total_alerts": len(self._alert_history),
            "recent_alerts": [
                {
                    "rule": a.rule_name,
                    "severity": a.severity.value,
                    "value": a.current_value,
                    "threshold": a.threshold,
                    "time": a.timestamp,
                }
                for a in self._alert_history[-5:]
            ],
        }
