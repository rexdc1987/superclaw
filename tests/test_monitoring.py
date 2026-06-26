"""
监控 + 告警 + Dashboard 单元测试
"""

import asyncio
import time
import pytest
from rpa.monitoring.metrics import MetricsCollector, PlatformStats
from rpa.monitoring.alert_engine import AlertEngine, AlertRule, AlertSeverity
from rpa.monitoring.channels import AlertMessage
from rpa.monitoring.simple_channels import ConsoleChannel, FileChannel


# ============================================================
# MetricsCollector 测试
# ============================================================

class TestMetricsCollector:

    def test_record_success(self):
        c = MetricsCollector()
        c.record_task_success("search", 1.5, platform="douyin")
        assert c._total_success == 1
        assert c._total_failure == 0
        assert c.success_rate.value == 1.0

    def test_record_failure(self):
        c = MetricsCollector()
        c.record_task_failure("comment", 3.0, error_type="timeout")
        assert c._total_failure == 1
        assert c.success_rate.value == 0.0

    def test_success_rate_calculation(self):
        c = MetricsCollector()
        c.record_task_success("task_a", 1.0)
        c.record_task_success("task_a", 1.0)
        c.record_task_failure("task_a", 1.0)
        assert c._total_success == 2
        assert c._total_failure == 1
        assert abs(c.success_rate.value - 2 / 3) < 0.01

    def test_platform_stats(self):
        c = MetricsCollector()
        c.record_task_success("search", 1.0, platform="douyin")
        c.record_task_success("search", 2.0, platform="douyin")
        c.record_task_failure("search", 3.0, platform="weibo")
        stats = c.get_platform_stats()
        assert "douyin" in stats
        assert stats["douyin"]["success"] == 2
        assert "weibo" in stats
        assert stats["weibo"]["failure"] == 1

    def test_account_health(self):
        c = MetricsCollector()
        c.update_account_health("acc_001", 95.0, "active")
        c.update_account_health("acc_002", 45.0, "cooldown")
        health = c.get_account_health()
        assert health["acc_001"]["health_score"] == 95.0
        assert health["acc_002"]["status"] == "cooldown"

    def test_system_metrics(self):
        c = MetricsCollector()
        c.update_system_metrics(browser_instances=3)
        summary = c.get_summary()
        assert summary["system"]["browser_instances"] == 3
        assert "uptime_seconds" in summary["system"]

    def test_recent_metrics_limit(self):
        c = MetricsCollector()
        for i in range(150):
            c.record_task_success("task", 0.1)
        recent = c.get_recent_metrics(limit=50)
        assert len(recent) == 50

    def test_summary_structure(self):
        c = MetricsCollector()
        s = c.get_summary()
        assert all(k in s for k in ["total_tasks", "success", "failure", "platforms", "system"])

    def test_export(self):
        c = MetricsCollector()
        c.record_task_success("task", 1.0)
        assert isinstance(c.export(), str)


# ============================================================
# AlertEngine 测试
# ============================================================

class _MockChannel:
    def __init__(self):
        self.sent = []
    async def send(self, alert):
        self.sent.append(alert)
        return True


class TestAlertEngine:

    def test_add_remove_rule(self):
        engine = AlertEngine()
        ch = _MockChannel()
        engine.add_rule(AlertRule(name="r1", condition="x", threshold=1, operator="gt", channels=[ch]))
        assert len(engine.list_rules()) == 1
        engine.remove_rule("r1")
        assert len(engine.list_rules()) == 0

    def test_rule_evaluate(self):
        rule = AlertRule(name="r", condition="x", threshold=0.8, operator="lt", channels=[])
        assert rule.evaluate(0.5) is True
        assert rule.evaluate(0.9) is False

    def test_rule_operators(self):
        base = dict(name="x", condition="y", threshold=10.0, channels=[])
        assert AlertRule(operator="gt", **base).evaluate(15.0) is True
        assert AlertRule(operator="ge", **base).evaluate(10.0) is True
        assert AlertRule(operator="le", **base).evaluate(10.0) is True
        assert AlertRule(operator="eq", **base).evaluate(10.0) is True
        assert AlertRule(operator="lt", **base).evaluate(5.0) is True

    @pytest.mark.asyncio
    async def test_evaluate_triggers(self):
        engine = AlertEngine()
        ch = _MockChannel()
        engine.add_rule(AlertRule(name="high_fail", condition="total_failure", threshold=5, operator="gt", channels=[ch]))
        alerts = await engine.evaluate({"total_failure": 10})
        assert len(alerts) == 1
        assert len(ch.sent) == 1

    @pytest.mark.asyncio
    async def test_cooldown(self):
        engine = AlertEngine()
        ch = _MockChannel()
        engine.add_rule(AlertRule(name="cd", condition="x", threshold=0, operator="gt", channels=[ch], cooldown=600))
        await engine.evaluate({"x": 1})
        alerts2 = await engine.evaluate({"x": 2})
        assert len(alerts2) == 0

    @pytest.mark.asyncio
    async def test_no_trigger(self):
        engine = AlertEngine()
        engine.add_rule(AlertRule(name="ok", condition="success_rate", threshold=0.5, operator="lt", channels=[]))
        alerts = await engine.evaluate({"success_rate": 0.95})
        assert len(alerts) == 0

    def test_alert_history(self):
        engine = AlertEngine()
        engine.add_rule(AlertRule(name="h", condition="x", threshold=0, operator="gt", channels=[_MockChannel()]))
        loop = asyncio.new_event_loop()
        loop.run_until_complete(engine.evaluate({"x": 1}))
        loop.close()
        assert len(engine.get_alert_history()) >= 1


# ============================================================
# Channels 测试
# ============================================================

class TestChannels:

    @pytest.mark.asyncio
    async def test_console_channel(self):
        ch = ConsoleChannel()
        msg = AlertMessage(title="test", description="desc", severity=AlertSeverity.WARNING, rule_name="r")
        assert await ch.send(msg) is True

    @pytest.mark.asyncio
    async def test_file_channel(self, tmp_path):
        ch = FileChannel(log_path=str(tmp_path / "alerts.log"))
        msg = AlertMessage(title="ft", description="d", severity=AlertSeverity.CRITICAL, rule_name="r1", metric_value=99, threshold=50)
        assert await ch.send(msg) is True
        import json
        with open(tmp_path / "alerts.log") as f:
            record = json.loads(f.readline())
        assert record["rule"] == "r1"
        assert record["severity"] == "critical"


# ============================================================
# Dashboard API 测试
# ============================================================

class TestDashboard:

    def test_health(self):
        from fastapi.testclient import TestClient
        from rpa.dashboard.app import app
        client = TestClient(app)
        assert client.get("/api/health").json()["status"] == "ok"

    def test_metrics_api(self):
        from fastapi.testclient import TestClient
        from rpa.dashboard.app import app, init_dashboard
        from rpa.monitoring.metrics import MetricsCollector
        c = MetricsCollector()
        c.record_task_success("test", 1.0)
        init_dashboard(collector=c)
        data = TestClient(app).get("/api/metrics").json()
        assert data["total_tasks"] == 1

    def test_overview_page(self):
        from fastapi.testclient import TestClient
        from rpa.dashboard.app import app, init_dashboard
        from rpa.monitoring.metrics import MetricsCollector
        init_dashboard(collector=MetricsCollector())
        resp = TestClient(app).get("/")
        assert resp.status_code == 200
        assert "SuperClaw" in resp.text

    def test_platforms_api(self):
        from fastapi.testclient import TestClient
        from rpa.dashboard.app import app, init_dashboard
        from rpa.monitoring.metrics import MetricsCollector
        c = MetricsCollector()
        c.record_task_success("s", 1.0, platform="douyin")
        init_dashboard(collector=c)
        data = TestClient(app).get("/api/platforms").json()
        assert "douyin" in data
