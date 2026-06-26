# 诸葛亮 Phase 1 学习笔记 — 任务调度与队列系统

> 学习人：诸葛亮 | 日期：2026-06-20
> 任务来源：曹操派发 | 预计周期：3-5天

---

## 模块1：定时任务调度（APScheduler vs Celery Beat）

### 核心结论

APScheduler 适合单机场景，Celery Beat 适合分布式场景。SuperClaw 当前阶段推荐 APScheduler。

### APScheduler 要点

- **三种触发器**：CronTrigger（cron表达式）、IntervalTrigger（固定间隔）、DateTrigger（一次性）
- **CronTrigger 关键参数**：year/month/day/hour/minute/second/day_of_week/timezone/jitter
- **Jitter 机制**：随机延迟执行，防止多实例同时触发造成雪崩
- **JobStore**：支持 Memory、SQLAlchemy、MongoDB、Redis 持久化
- **事件监听**：可监听 EVENT_JOB_EXECUTED、EVENT_JOB_ERROR、EVENT_JOB_MISSED

### Celery Beat 要点

- **独立守护进程**：Beat 调度器 + Broker（Redis/RabbitMQ）+ Worker 三件套
- **必须单实例**：同一时间只能运行一个 Beat，否则重复触发
- **beat_schedule 配置**：通过 Python 字典或 Django 数据库动态配置
- **内置 crontab**：`celery.schedules.crontab(hour=7, minute=30, day_of_week=1)`

### 对比表

| 维度 | APScheduler | Celery Beat |
|------|-------------|-------------|
| 架构 | 进程内，轻量 | 独立守护进程 + 消息队列 |
| 依赖 | apscheduler 包 | celery + broker |
| 分布式 | ❌ 单进程 | ✅ 天然支持 |
| 持久化 | 内置 SQLAlchemy | 需 Django DB 或文件 |
| 适用场景 | 单机 MVP | 多机生产环境 |

### SuperClaw 建议

当前用 APScheduler + asyncio.Queue，后续多机部署时迁移 Celery。

---

## 模块2：任务队列（Celery + Redis）

### 核心结论

Celery 提供完整的企业级任务队列能力，但在单机场景下 Redis + asyncio 足够轻量高效。

### Celery 核心模型

```
Producer → Broker (Redis/RabbitMQ) → Consumer/Worker → Result Backend
```

关键配置：
- `task_acks_late=True`：任务完成后才确认，防 Worker 崩溃丢任务
- `worker_prefetch_multiplier=1`：每次只预取1个任务，适合长任务
- `task_track_started=True`：跟踪任务开始状态

### Redis 队列三种方案

1. **Celery + Redis Broker**：完整企业级功能，推荐生产环境
2. **自建 SimpleTaskQueue**：Redis Sorted Set 实现优先级队列，零外部依赖
3. **Redis Stream**：消费者组 + 消息确认 + 持久化，推荐介于前两者之间

### 任务状态机

```
PENDING → STARTED → SUCCESS
                  ↘ FAILURE
                  ↘ RETRY
                  ↘ REVOKED
```

可扩展自定义状态（SEARCHING/FILTERING/COMMENTING）通过 `self.update_state()`。

### SuperClaw 队列设计

- 按优先级分队列：critical(0) > high(10) > normal(50) > low(100)
- 任务类型分流：定时(APScheduler) / 采集(asyncio.Queue) / 互动(asyncio.Queue) / 导出(后台)

---

## 模块3：并发控制与限流

### 核心结论

多层限流（全局→平台→账号→操作）是 RPA 系统防风控的关键。令牌桶算法最适合社交平台场景。

### asyncio.Semaphore

```python
semaphore = asyncio.Semaphore(5)  # 最多5并发
async with semaphore:
    await do_work()
```

### 令牌桶 vs 漏桶

| 特性 | 令牌桶 | 漏桶 |
|------|--------|------|
| 允许突发 | ✅ 桶满时可突发 | ❌ 固定速率 |
| 适用场景 | API调用（容忍突发） | 数据流（严格匀速） |

### 多层限流架构

```
全局限流（100次/分钟）
  → 平台限流（抖音50次/分钟）
    → 账号+操作限流（评论20条/分钟/账号）
```

### 平台限流参考

| 平台 | 操作 | 建议频率 |
|------|------|----------|
| 抖音 | 评论 | ≤20条/分钟/账号 |
| 抖音 | 关注 | ≤50个/小时/账号 |
| 抖音 | 私信 | ≤20条/小时/账号 |

### 错误处理策略

- **网络超时**：重试3次，指数退避
- **验证码**：不重试，冷却账号30分钟
- **登录过期**：不重试，标记账号
- **被限流**：重试5次，长退避（60s起）

---

## 模块4：SuperClaw 调度系统设计

### 架构设计

```
Trigger Layer (APScheduler) → Queue Layer (asyncio.Queue) → Executor Layer (Worker Pool)
                                    ↓
                            Rate Limiter (令牌桶)
                                    ↓
                            State Manager (状态机)
                                    ↓
                            Retry Handler (指数退避)
```

### 任务状态机

```
DRAFT → QUEUED → RUNNING → COMPLETED
                   ↓    ↘
                PAUSED  FAILED → (retry) → QUEUED
                   ↓
                CANCELLED
```

合法转换规则：每个状态只能转换到指定目标状态，防止非法跳转。

### 指数退避公式

```python
delay = min(base_delay * (2 ** attempt) + jitter, max_delay)
```

jitter = 随机 0~10% 抖动，防止重试风暴。

### 产出文件

| 文件 | 说明 |
|------|------|
| `docs/scheduler_comparison.md` | APScheduler vs Celery Beat 对比 |
| `docs/task_queue_notes.md` | Celery + Redis 队列设计笔记 |
| `docs/rate_limiting_notes.md` | 并发控制与限流策略笔记 |
| `docs/scheduler_design.md` | 调度系统架构设计 |
| `src/rpa/scheduler.py` | 调度器原型代码（含状态机+限流+重试） |

### 技术选型总结

| 组件 | 选择 | 理由 |
|------|------|------|
| 调度器 | APScheduler | 轻量、已有代码基础 |
| 队列 | asyncio.Queue | 单机零依赖 |
| 并发控制 | asyncio.Semaphore | 原生支持 |
| 限流 | 自建 TokenBucket | 完全可控 |
| 持久化 | SQLAlchemy + SQLite | 已有基础设施 |

---

<!-- TASK_COMPLETE: phase1_scheduler -->
