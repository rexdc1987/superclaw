"""
RPA 运行时监控指标采集器

支持：任务统计、平台维度、账号健康度、系统指标、时间序列。
无 prometheus_client 时自动降级为内存计数器。
"""

import logging
import time
import os
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry, generate_latest
    HAS_PROMETHEUS = True
except ImportError:
    HAS_PROMETHEUS = False
    logger.warning("prometheus_client 未安装，使用内存计数器")


class _StubMetric:
    """prometheus_client 不可用时的 stub。"""

    def __init__(self, name: str, value: float = 0):
        self.name = name
        self._value = value
        self._samples: list = []

    def inc(self, amount: float = 1):
        self._value += amount

    def dec(self, amount: float = 1):
        self._value -= amount

    def set(self, value: float):
        self._value = value

    def observe(self, value: float):
        self._samples.append(value)

    @property
    def value(self) -> float:
        return self._value

    def labels(self, **kwargs):
        """兼容 prometheus_client labels API"""
        return self


@dataclass
class TaskMetric:
    """单次任务指标记录。"""
    task_type: str
    success: bool
    duration: float
    timestamp: float
    platform: Optional[str] = None
    account_id: Optional[str] = None
    error_type: Optional[str] = None


@dataclass
class PlatformStats:
    """平台维度统计。"""
    platform: str
    total_tasks: int = 0
    success: int = 0
    failure: int = 0
    avg_duration: float = 0.0
    last_activity: float = 0.0

    @property
    def success_rate(self) -> float:
        total = self.success + self.failure
        return self.success / total if total > 0 else 0.0


class MetricsCollector:
    """RPA 运行时指标采集器。"""

    # 保留最近 N 条时间序列
    MAX_SERIES = 1000

    def __init__(self):
        if HAS_PROMETHEUS:
            self._registry = CollectorRegistry()
            self.task_success = Counter(
                "superclaw_task_success_total", "任务成功次数",
                ["task_type"], registry=self._registry,
            )
            self.task_failure = Counter(
                "superclaw_task_failure_total", "任务失败次数",
                ["task_type", "error_type"], registry=self._registry,
            )
            self.captcha_triggered = Counter(
                "superclaw_captcha_triggered_total", "验证码触发次数",
                registry=self._registry,
            )
            self.task_duration = Histogram(
                "superclaw_task_duration_seconds", "任务执行时长",
                ["task_type"],
                buckets=[0.5, 1, 2, 5, 10, 30, 60, 120, 300],
                registry=self._registry,
            )
            self.active_accounts = Gauge(
                "superclaw_active_accounts", "活跃账号数",
                registry=self._registry,
            )
            self.queue_depth = Gauge(
                "superclaw_queue_depth", "任务队列深度",
                registry=self._registry,
            )
            self.success_rate = Gauge(
                "superclaw_success_rate", "任务成功率",
                registry=self._registry,
            )
        else:
            self.task_success = _StubMetric("task_success")
            self.task_failure = _StubMetric("task_failure")
            self.captcha_triggered = _StubMetric("captcha_triggered")
            self.task_duration = _StubMetric("task_duration")
            self.active_accounts = _StubMetric("active_accounts")
            self.queue_depth = _StubMetric("queue_depth")
            self.success_rate = _StubMetric("success_rate")

        # 时间序列（deque 自动淘汰旧数据）
        self._recent_metrics: deque = deque(maxlen=self.MAX_SERIES)
        self._total_success = 0
        self._total_failure = 0

        # 平台维度统计
        self._platform_stats: Dict[str, PlatformStats] = {}

        # 账号健康度
        self._account_health: Dict[str, Dict[str, Any]] = {}

        # 系统指标
        self._system_metrics: Dict[str, Any] = {
            "start_time": time.time(),
            "browser_instances": 0,
            "cpu_percent": 0.0,
            "memory_mb": 0.0,
        }

    # ---- 任务指标 ----

    def record_task_success(self, task_type: str, duration: float,
                            platform: Optional[str] = None,
                            account_id: Optional[str] = None) -> None:
        if HAS_PROMETHEUS:
            self.task_success.labels(task_type=task_type).inc()
            self.task_duration.labels(task_type=task_type).observe(duration)
        else:
            self.task_success.inc()
            self.task_duration.observe(duration)

        self._total_success += 1
        self._update_success_rate()
        self._record_platform(task_type, True, duration, platform)
        self._recent_metrics.append(TaskMetric(
            task_type=task_type, success=True, duration=duration,
            timestamp=time.time(), platform=platform, account_id=account_id,
        ))

    def record_task_failure(self, task_type: str, duration: float,
                            error_type: str = "unknown",
                            platform: Optional[str] = None,
                            account_id: Optional[str] = None) -> None:
        if HAS_PROMETHEUS:
            self.task_failure.labels(task_type=task_type, error_type=error_type).inc()
            self.task_duration.labels(task_type=task_type).observe(duration)
        else:
            self.task_failure.inc()
            self.task_duration.observe(duration)

        self._total_failure += 1
        self._update_success_rate()
        self._record_platform(task_type, False, duration, platform)
        self._recent_metrics.append(TaskMetric(
            task_type=task_type, success=False, duration=duration,
            timestamp=time.time(), platform=platform, account_id=account_id,
            error_type=error_type,
        ))

    def record_captcha(self) -> None:
        self.captcha_triggered.inc()

    def set_active_accounts(self, count: int) -> None:
        self.active_accounts.set(count)

    def set_queue_depth(self, depth: int) -> None:
        self.queue_depth.set(depth)

    # ---- 平台维度 ----

    def _record_platform(self, task_type: str, success: bool, duration: float,
                         platform: Optional[str]) -> None:
        if not platform:
            return
        if platform not in self._platform_stats:
            self._platform_stats[platform] = PlatformStats(platform=platform)

        stats = self._platform_stats[platform]
        stats.total_tasks += 1
        if success:
            stats.success += 1
        else:
            stats.failure += 1
        # 滑动平均
        n = stats.total_tasks
        stats.avg_duration = stats.avg_duration * (n - 1) / n + duration / n
        stats.last_activity = time.time()

    def get_platform_stats(self) -> Dict[str, Dict[str, Any]]:
        return {
            name: {
                "platform": s.platform,
                "total": s.total_tasks,
                "success": s.success,
                "failure": s.failure,
                "success_rate": round(s.success_rate, 4),
                "avg_duration": round(s.avg_duration, 2),
            }
            for name, s in self._platform_stats.items()
        }

    # ---- 账号健康度 ----

    def update_account_health(self, account_id: str, health_score: float,
                              status: str = "active") -> None:
        self._account_health[account_id] = {
            "health_score": health_score,
            "status": status,
            "updated_at": time.time(),
        }

    def get_account_health(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._account_health)

    # ---- 系统指标 ----

    def update_system_metrics(self, **kwargs) -> None:
        self._system_metrics.update(kwargs)

    def _collect_system_metrics(self) -> Dict[str, Any]:
        """采集实时系统指标"""
        try:
            import psutil
            process = psutil.Process(os.getpid())
            self._system_metrics["cpu_percent"] = process.cpu_percent(interval=0)
            self._system_metrics["memory_mb"] = round(process.memory_info().rss / 1024 / 1024, 1)
        except ImportError:
            pass
        self._system_metrics["uptime_seconds"] = int(
            time.time() - self._system_metrics["start_time"]
        )
        return dict(self._system_metrics)

    # ---- 聚合 ----

    def _update_success_rate(self) -> None:
        total = self._total_success + self._total_failure
        if total > 0:
            rate = self._total_success / total
            self.success_rate.set(rate)

    def get_recent_metrics(self, limit: int = 100) -> List[TaskMetric]:
        return list(self._recent_metrics)[-limit:]

    def get_summary(self) -> Dict[str, Any]:
        total = self._total_success + self._total_failure
        return {
            "total_tasks": total,
            "success": self._total_success,
            "failure": self._total_failure,
            "success_rate": round(self._total_success / total, 4) if total > 0 else None,
            "active_accounts": self.active_accounts.value,
            "queue_depth": self.queue_depth.value,
            "platforms": self.get_platform_stats(),
            "system": self._collect_system_metrics(),
        }

    def export(self) -> str:
        if HAS_PROMETHEUS:
            return generate_latest(self._registry).decode("utf-8")
        return (
            "# HELP superclaw metrics (stub mode)\n"
            "superclaw_task_success_total {}\n"
            "superclaw_task_failure_total {}\n"
            "superclaw_success_rate {}\n"
        ).format(self._total_success, self._total_failure, self.success_rate.value)
