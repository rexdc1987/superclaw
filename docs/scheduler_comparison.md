# 模块1：定时任务调度方案对比 — APScheduler vs Celery Beat

> 学习人：诸葛亮 | 日期：2026-06-20

---

## 1. APScheduler 概述

APScheduler（Advanced Python Scheduler）是一个轻量级的 Python 进程内任务调度库。

### 核心概念

- **JobStore**：任务持久化存储。支持 Memory（内存）、SQLAlchemy（SQLite/PostgreSQL）、MongoDB、Redis。
- **Executor**：任务执行器。默认 ThreadPoolExecutor，可替换为 ProcessPoolExecutor 或 asyncio 的协程执行器。
- **Trigger**：触发器，决定任务何时执行。
  - `CronTrigger`：类 UNIX cron 表达式，支持 year/month/day/hour/minute/second/day_of_week，还支持 `jitter`（随机延迟）防雪崩。
  - `IntervalTrigger`：固定间隔触发（seconds/minutes/hours/days）。
  - `DateTrigger`：一次性定时触发（指定 datetime）。
- **Event Listener**：事件监听，可监听任务执行成功/失败/错过等事件。

### CronTrigger 关键参数

```python
CronTrigger(
    year=2026, month=6, day=20,
    hour=2, minute=0,
    day_of_week='mon',      # mon=周一
    timezone='Asia/Shanghai',
    jitter=30               # 最多延迟30秒执行，防多实例同时触发
)
```

还支持 `from_crontab('0 2 * * 1')` 标准 cron 表达式写法。

### 已有代码对应

我们的 `src/rpa/scheduler.py` 已经基于 APScheduler 实现了：
- 三种触发器（cron/interval/date）✅
- SQLAlchemy 持久化 ✅
- 事件监听（执行/错误/错过）✅
- 任务历史追踪 ✅
- 全局单例模式 ✅

---

## 2. Celery Beat 概述

Celery Beat 是 Celery 框架自带的定时任务调度器。它是一个独立的守护进程，负责按计划将任务发送到消息队列（Broker），由 Worker 执行。

### 核心架构

```
Celery Beat (调度器)
    ↓ 按计划发送任务
Broker (Redis/RabbitMQ)
    ↓ 分发
Worker Node 1, 2, 3... (消费并执行)
```

### 关键特性

- **集中式调度**：Beat 是单点调度器，必须保证同一时间只有一个 Beat 运行（否则会重复触发）。
- **beat_schedule 配置**：通过 Python 字典或 Django 数据库配置周期任务。
- **crontab 支持**：`celery.schedules.crontab(hour=7, minute=30, day_of_week=1)`。
- **时区支持**：通过 `timezone` 配置项，默认 UTC。
- **动态调度**：django-celery-beat 支持通过 Django Admin 动态增删改周期任务。

### 配置示例

```python
from celery import Celery
from celery.schedules import crontab

app = Celery('superclaw')

@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    # 每10秒执行一次
    sender.add_periodic_task(10.0, search_task.s('douyin'))
    # 每周一早上7:30
    sender.add_periodic_task(
        crontab(hour=7, minute=30, day_of_week=1),
        report_task.s()
    )
```

---

## 3. 对比分析

| 维度 | APScheduler | Celery Beat |
|------|-------------|-------------|
| **定位** | 进程内调度库 | 分布式任务队列的调度组件 |
| **架构** | 单进程，内嵌在应用中 | 独立守护进程 + 消息队列 + Worker |
| **依赖** | 轻量（apscheduler 包） | 重（celery + broker 如 Redis/RabbitMQ） |
| **持久化** | 内置 SQLAlchemy/MongoDB/Redis JobStore | 需要 Django DB 或文件（celerybeat-schedule） |
| **分布式** | ❌ 不支持（单进程） | ✅ 天然支持（多 Worker 消费） |
| **任务执行** | 同进程内直接调用函数 | 通过消息队列分发到 Worker |
| **并发模型** | ThreadPoolExecutor / ProcessPoolExecutor | Worker 进程池（prefork / eventlet / gevent） |
| **任务状态** | 内存中追踪，可选 DB 持久化 | 完整的状态管理（PENDING/STARTED/SUCCESS/FAILURE） |
| **结果存储** | 需自行实现 | 内置 result_backend（DB/Redis/S3） |
| **监控** | 事件监听（有限） | Flower（Web UI 实时监控） |
| **适用场景** | 轻量定时任务、单机应用 | 分布式任务队列、需要水平扩展 |
| **学习曲线** | 低 | 中高 |

---

## 4. SuperClaw 场景分析

### 我们的需求

1. **定时触发任务**：每天凌晨2点执行数据清理，每30分钟监控账号状态
2. **异步执行 RPA 操作**：搜索视频、采集评论、发布评论（耗时操作）
3. **多账号并发**：同时操作多个账号，需要并发控制
4. **频率限制**：每个平台有 API 调用频率限制
5. **失败重试**：网络异常、验证码等导致的失败需要自动重试
6. **状态追踪**：任务执行状态、进度、结果需要持久化

### 我的建议

**当前阶段（单机 MVP）：使用 APScheduler + 队列**

理由：
- SuperClaw 目前是单机部署，不需要分布式调度
- APScheduler 轻量、零外部依赖（除 SQLAlchemy），适合 MVP
- 已有 `scheduler.py` 基于 APScheduler，代码可复用
- 可以用 Redis 做简单的任务队列（不依赖 Celery），满足异步执行需求

**后续阶段（多机扩展）：引入 Celery**

理由：
- 当需要多机部署、水平扩展时，Celery 的分布式能力是必要的
- Celery 的任务状态管理、结果存储、Flower 监控都是生产级方案
- 但会增加运维复杂度（需要维护 Redis/RabbitMQ Broker）

### 混合方案（推荐）

```
调度层：APScheduler（进程内定时触发）
    ↓
队列层：Redis Queue / asyncio.Queue（异步任务分发）
    ↓
执行层：Worker Pool（并发执行 RPA 操作）
```

这样既保持了轻量，又为后续迁移到 Celery 预留了接口。

---

## 5. 代码验证：APScheduler CronTrigger 示例

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

scheduler = BackgroundScheduler()

# 每天凌晨2点执行清理
scheduler.add_job(
    cleanup_task,
    CronTrigger(hour=2, minute=0, timezone='Asia/Shanghai'),
    id='daily_cleanup'
)

# 每30分钟监控
scheduler.add_job(
    monitor_task,
    IntervalTrigger(minutes=30),
    id='monitor'
)

# 每周一早上7:30生成报告（带jitter防雪崩）
scheduler.add_job(
    report_task,
    CronTrigger(hour=7, minute=30, day_of_week='mon', jitter=30),
    id='weekly_report'
)

scheduler.start()
```

---

<!-- MODULE_COMPLETE: scheduler_comparison -->
