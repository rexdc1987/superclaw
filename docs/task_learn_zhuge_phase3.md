# ZhuGe Phase 3 - Monitoring + Alerting + Dashboard

> Dispatched by Cao Cao | Date: 2026-06-20
> Build monitoring, alerting and dashboard for SuperClaw
> Output: src/rpa/monitoring/ + docs/learning_zhuge_phase3.md

---

## Goals

1. Build metrics collection system
2. Build alert engine with multi-channel notification
3. Build simple web dashboard (FastAPI + Jinja2)

## Tasks

### Task 1: Metrics Collector
**Output**: src/rpa/monitoring/metrics.py

Collect and aggregate runtime metrics:
- Task execution count, success/fail rate, duration
- Per-platform stats (douyin, xiaohongshu, etc.)
- Per-account health score
- System metrics (CPU, memory, browser instances)
- Use simple in-memory store (dict + deque for time series)

### Task 2: Alert Engine
**Output**: src/rpa/monitoring/alert_engine.py + src/rpa/monitoring/channels.py

Alert system with rules and multi-channel notification:
- Alert rules: threshold-based (error_rate > 10%, latency > 5s)
- Alert channels: console log, file log (extendable for feishu/webhook later)
- Alert state machine: pending -> firing -> resolved
- Cooldown to prevent alert storms

### Task 3: Web Dashboard
**Output**: src/rpa/dashboard/app.py + src/rpa/dashboard/templates/

Simple FastAPI dashboard:
- GET / -- overview page (task stats, system health)
- GET /api/metrics -- JSON metrics endpoint
- GET /api/alerts -- active alerts
- Use Jinja2 templates with simple HTML (no frontend framework needed)

### Task 4: Learning Notes
**Output**: docs/learning_zhuge_phase3.md

Document metrics design, alert rules, dashboard architecture.

## Acceptance Criteria

1. Metrics collector tracks task execution stats correctly
2. Alert engine fires alerts when thresholds exceeded
3. Dashboard serves metrics via web UI and API
4. All modules have unit tests
5. Write TASK_COMPLETE phase3_monitoring at end of notes
