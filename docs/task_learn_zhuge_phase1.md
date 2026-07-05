# 诸葛亮 Phase 1 学习任务 — 任务调度与队列系统

> 派发人：曹操 | 日期：2026-06-20
> 预计周期：3-5天 | 产出位置：docs/learning_zhuge_phase1.md

---

## 学习目标

1. 理解定时任务调度方案（APScheduler、Celery Beat）
2. 掌握任务队列设计（Celery + Redis）
3. 学习并发控制和限流策略
4. 设计 SuperClaw 的任务调度系统

## 学习内容

### 模块1：定时任务调度（第1天）
- 研究 APScheduler 的 CronTrigger、IntervalTrigger
- 研究 Celery Beat 的调度机制
- 对比两者优劣
- **产出**：`docs/scheduler_comparison.md`

### 模块2：任务队列（第2天）
- 学习 Celery 基础：Producer → Broker → Consumer
- 研究 Redis 作为消息队列的用法
- 理解任务状态管理
- **产出**：`docs/task_queue_notes.md`

### 模块3：并发控制与限流（第3天）
- 研究 asyncio.Semaphore 并发控制
- 研究令牌桶/漏桶限流算法
- 研究平台 API 的限流策略
- **产出**：`docs/rate_limiting_notes.md`

### 模块4：SuperClaw 调度系统设计（第4-5天）
- 设计任务调度器架构
- 设计任务状态机
- 设计失败重试策略（指数退避）
- 编写调度器原型代码
- **产出**：`docs/scheduler_design.md` + `src/rpa/scheduler.py`

## 学习要求

1. 用实际代码验证每个概念
2. 考虑 SuperClaw 的实际场景：多账号、多平台、频率限制
3. 画任务状态机图（ASCII 或 Mermaid）
4. 对技术选型给出明确建议
5. 完成后在笔记末尾写 <!-- TASK_COMPLETE: phase1_scheduler -->
