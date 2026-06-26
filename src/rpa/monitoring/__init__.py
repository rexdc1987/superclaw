"""
SuperClaw 监控与告警系统

提供指标采集、告警引擎、多通道推送等能力。

Usage:
    from rpa.monitoring import MetricsCollector, AlertEngine

    # 初始化指标采集
    collector = MetricsCollector()
    collector.record_task_success()
    collector.record_task_duration(12.5)

    # 初始化告警引擎
    engine = AlertEngine()
    engine.register_default_rules()
    await engine.evaluate(collector)
"""

from rpa.monitoring.metrics import MetricsCollector
from rpa.monitoring.alert_engine import AlertEngine, AlertRule

__all__ = ["MetricsCollector", "AlertEngine", "AlertRule"]
