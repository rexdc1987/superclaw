"""
告警通道模块

提供统一的告警推送通道抽象，支持飞书 Webhook 和通用 HTTP Webhook。
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


class AlertSeverity(Enum):
    """告警严重级别。"""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class AlertMessage:
    """告警消息体。

    Attributes:
        title: 告警标题
        description: 详细描述
        severity: 严重级别
        rule_name: 触发的规则名称
        metric_value: 当前指标值
        threshold: 阈值
        timestamp: 触发时间
        extra: 附加信息
    """
    title: str
    description: str
    severity: AlertSeverity
    rule_name: str
    metric_value: float = 0.0
    threshold: float = 0.0
    timestamp: Optional[datetime] = None
    extra: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()

    def to_text(self) -> str:
        """生成纯文本格式的告警消息。"""
        severity_icon = {
            AlertSeverity.INFO: "[INFO]",
            AlertSeverity.WARNING: "[WARN]",
            AlertSeverity.CRITICAL: "[CRIT]",
        }
        icon = severity_icon.get(self.severity, "[????]")
        return (
            f"{icon} {self.title}\n"
            f"Rule: {self.rule_name}\n"
            f"Description: {self.description}\n"
            f"Value: {self.metric_value}  Threshold: {self.threshold}\n"
            f"Time: {self.timestamp.isoformat() if self.timestamp else 'N/A'}"
        )


class AlertChannel(abc.ABC):
    """告警通道抽象基类。

    所有告警推送通道（飞书、Webhook、邮件等）都应继承此类并实现 send 方法。
    """

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @abc.abstractmethod
    async def send(self, message: AlertMessage) -> bool:
        """发送告警消息。

        Args:
            message: 告警消息体

        Returns:
            True 表示发送成功，False 表示失败。
        """
        ...

    async def send_batch(self, messages: List[AlertMessage]) -> Dict[str, bool]:
        """批量发送告警（默认逐条发送，子类可覆盖优化）。"""
        results: Dict[str, bool] = {}
        for msg in messages:
            key = f"{msg.rule_name}_{msg.timestamp.isoformat() if msg.timestamp else 'unknown'}"
            results[key] = await self.send(msg)
        return results


__all__ = [
    "AlertChannel",
    "AlertMessage",
    "AlertSeverity",
]

# Available channels:
# - FeishuChannel (feishu_channel.py)
# - WebhookChannel (webhook_channel.py)
# - EmailChannel (email_channel.py)
