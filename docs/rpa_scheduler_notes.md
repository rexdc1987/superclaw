# RPA 任务调度技术 - 学习笔记

> 作者：诸葛亮  
> 阶段：第一阶段 - 任务调度技术  
> 开始日期：2026-06-18

---

## 1. 定时任务技术

### 1.1 Python schedule 库

**核心概念**：轻量级进程内调度器，适合简单的定时任务场景。

**基础用法**：
```python
import schedule
import time

def job():
    print("执行任务...")

# 每10分钟执行
schedule.every(10).minutes.do(job)

# 每天10:30执行
schedule.every().day.at("10:30").do(job)

# 每周一执行
schedule.every().monday.do(job)

# 运行调度器
while True:
    schedule.run_pending()
    time.sleep(1)
```

**优点**：
- 极简API，学习成本低
- 无需外部依赖
- 支持链式调用

**缺点**：
- 单线程阻塞模型
- 不支持任务持久化
- 无法分布式部署
- 错误恢复能力弱

**适用场景**：
- 单机轻量任务
- 开发/测试环境
- 一次性脚本

---

### 1.2 APScheduler

**核心概念**：企业级任务调度框架，支持多种调度器和触发器。

**三大组件**：
1. **JobStore**：任务持久化（内存/SQLite/Redis/MongoDB）
2. **Executor**：任务执行器（线程池/进程池）
3. **Trigger**：调度触发器（interval/cron/date）

**基础用法**：
```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

scheduler = BackgroundScheduler()

# 每5分钟执行
scheduler.add_job(
    func=task_func,
    trigger=IntervalTrigger(minutes=5),
    id='task_001',
    name='定期任务',
    replace_existing=True
)

# Cron表达式：每天2:15执行
scheduler.add_job(
    func=daily_cleanup,
    trigger=CronTrigger(hour=2, minute=15),
    id='daily_cleanup'
)

# 一次性任务
scheduler.add_job(
    func=once_func,
    trigger='date',
    run_date='2026-06-19 10:00:00'
)

scheduler.start()
```

**高级特性**：
```python
# 任务依赖和错误处理
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

def error_listener(event):
    if event.exception:
        print(f"任务 {event.job_id} 执行失败: {event.exception}")

scheduler.add_listener(error_listener, EVENT_JOB_ERROR)

# 任务最大执行次数
scheduler.add_job(
    func=retry_task,
    trigger='interval',
    seconds=30,
    max_instances=3,
    misfire_grace_time=60  # 错过的任务在60秒内仍可执行
)
```

**持久化示例（SQLite）**：
```python
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

jobstores = {
    'default': SQLAlchemyJobStore(url='sqlite:///jobs.db')
}

scheduler = BackgroundScheduler(jobstores=jobstores)
```

**优点**：
- 功能丰富，企业级特性
- 支持多种调度器和JobStore
- 内置错误处理和任务管理
- 可扩展性强

**缺点**：
- 相对复杂，学习曲线陡
- 依赖较多

---

### 1.3 Cron 表达式详解

**格式**：`分 时 日 月 周`（5位）

| 字段 | 值范围 | 特殊字符 |
|------|--------|----------|
| 分钟 | 0-59 | * , - / |
| 小时 | 0-23 | * , - / |
| 日期 | 1-31 | * , - / ? L W |
| 月份 | 1-12 或 JAN-DEC | * , - / |
| 星期 | 0-6 或 SUN-SAT | * , - / ? L # |

**示例**：
```
*/5 * * * *       # 每5分钟
0 2 * * *         # 每天凌晨2点
0 9-18 * * 1-5    # 工作日9-18点每小时
0 0 1 * *         # 每月1号
0 12 ? * 2L       # 每月最后一个星期二中午
```

---

## 2. 任务队列技术

### 2.1 Redis 基础

**核心特性**：
- 内存数据库，极高性能
- 支持多种数据结构
- 原子操作保证线程安全
- 发布/订阅模式

**RPA相关操作**：
```python
import redis

r = redis.Redis(host='localhost', port=6379, db=0)

# 任务队列（List结构）
r.lpush('task_queue', task_json)  # 入队
r.brpop('task_queue', timeout=30)  # 阻塞出队

# 任务状态追踪（Hash结构）
r.hset('task:123', mapping={
    'status': 'running',
    'progress': 50,
    'started_at': '2026-06-18T10:00:00'
})

# 限流（Sorted Set + 滑动窗口）
def is_rate_limited(user_id, limit=100, window=60):
    key = f'rate:{user_id}'
    now = time.time()
    r.zremrangebyscore(key, 0, now - window)
    count = r.zcard(key)
    if count >= limit:
        return True
    r.zadd(key, {str(now): now})
    r.expire(key, window)
    return False
```

---

### 2.2 Celery 任务队列

**架构**：
```
Producer → Broker (Redis/RabbitMQ) → Worker → Result Backend
```

**基础配置**：
```python
# celery_config.py
from celery import Celery

app = Celery('rpa_tasks',
             broker='redis://localhost:6379/0',
             backend='redis://localhost:6379/1')

app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Shanghai',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 单任务超时5分钟
    task_soft_time_limit=250,
    worker_max_tasks_per_child=100,  # 防止内存泄漏
    worker_prefetch_multiplier=1  # 避免任务堆积
)
```

**任务定义**：
```python
# tasks.py
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError

@shared_task(bind=True, max_retries=3)
def execute_rpa_task(self, task_config):
    """执行RPA任务"""
    try:
        # 更新状态
        self.update_state(state='PROGRESS', meta={'current': 0, 'total': 100})
        
        # 执行逻辑
        result = do_rpa_work(task_config)
        
        return {'status': 'success', 'result': result}
    except Exception as exc:
        # 自动重试，指数退避
        self.retry(exc=exc, countdown=2 ** self.request.retries)
```

**任务调用**：
```python
# 同步执行（阻塞）
result = execute_rpa_task.apply(args=[config])

# 异步执行（非阻塞）
result = execute_rpa_task.delay(config)

# 定时执行
from celery.schedules import crontab
app.conf.beat_schedule = {
    'daily-collection': {
        'task': 'tasks.execute_rpa_task',
        'schedule': crontab(hour=2, minute=0),
        'args': (config,)
    }
}
```

**监控**：
```python
# Flower实时监控
pip install flower
celery -A app flower  # 访问 http://localhost:5555

# 代码内查询任务状态
from celery.result import AsyncResult
result = AsyncResult(task_id)
print(result.state)      # PENDING/STARTED/SUCCESS/FAILURE
print(result.info)       # 进度信息
```

---

### 2.3 队列模式设计

**优先级队列**：
```python
# Redis实现优先级队列
PRIORITY_HIGH = 'queue:high'
PRIORITY_NORMAL = 'queue:normal'
PRIORITY_LOW = 'queue:low'

def enqueue_task(task_data, priority='normal'):
    queue = f'queue:{priority}'
    r.lpush(queue, json.dumps(task_data))

def dequeue_task():
    # 使用BLPOP实现多队列优先级
    result = r.blpop(
        [PRIORITY_HIGH, PRIORITY_NORMAL, PRIORITY_LOW],
        timeout=30
    )
    if result:
        return json.loads(result[1])
    return None
```

**死信队列**：
```python
def execute_with_dlq(task_data):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return process_task(task_data)
        except Exception as e:
            if attempt == max_retries - 1:
                # 移入死信队列
                task_data['error'] = str(e)
                task_data['failed_at'] = datetime.now().isoformat()
                r.lpush('queue:dead_letter', json.dumps(task_data))
                logger.error(f"任务移入死信队列: {task_data}")
            else:
                time.sleep(2 ** attempt)
```

---

## 3. 并发控制技术

### 3.1 asyncio 异步编程

**核心概念**：单线程事件循环，适合I/O密集型任务。

**RPA场景适配**：
```python
import asyncio
from asyncio import Semaphore

class RPATaskRunner:
    def __init__(self, max_concurrent=5):
        self.semaphore = Semaphore(max_concurrent)
        self.results = []
    
    async def run_single_task(self, task_config):
        async with self.semaphore:
            try:
                # 模拟浏览器操作（I/O密集）
                result = await self._browser_operation(task_config)
                self.results.append(result)
                return result
            except Exception as e:
                logger.error(f"任务失败: {e}")
                return None
    
    async def _browser_operation(self, config):
        # 使用Playwright异步API
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.goto(config['url'])
            # ... 操作
            result = await page.content()
            await browser.close()
            return result
    
    async def run_batch(self, tasks):
        coroutines = [self.run_single_task(t) for t in tasks]
        return await asyncio.gather(*coroutines, return_exceptions=True)

# 使用
runner = RPATaskRunner(max_concurrent=3)
results = asyncio.run(runner.run_batch(task_list))
```

---

### 3.2 信号量与限流

**令牌桶算法**：
```python
import asyncio
import time

class TokenBucket:
    def __init__(self, rate, capacity):
        self.rate = rate          # 令牌生成速率（个/秒）
        self.capacity = capacity  # 桶容量
        self.tokens = capacity
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()
    
    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            # 补充令牌
            elapsed = now - self.last_refill
            self.tokens = min(
                self.capacity,
                self.tokens + elapsed * self.rate
            )
            self.last_refill = now
            
            if self.tokens >= 1:
                self.tokens -= 1
                return True
            return False
    
    async def wait_and_acquire(self, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if await self.acquire():
                return True
            await asyncio.sleep(0.1)
        return False

# 使用：每秒最多10个请求
bucket = TokenBucket(rate=10, capacity=10)

async def rate_limited_request(url):
    if await bucket.wait_and_acquire(timeout=30):
        return await make_request(url)
    else:
        raise TimeoutError("限流等待超时")
```

**并发池控制**：
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

class ConcurrentTaskManager:
    def __init__(self, max_workers=5):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
    
    def submit_tasks(self, tasks, callback=None):
        futures = {}
        for task in tasks:
            future = self.executor.submit(self._run_task, task)
            futures[future] = task
        
        results = []
        for future in as_completed(futures, timeout=300):
            task = futures[future]
            try:
                result = future.result()
                results.append({'task': task, 'result': result})
                if callback:
                    callback(task, result)
            except Exception as e:
                results.append({'task': task, 'error': str(e)})
        
        return results
    
    def _run_task(self, task):
        # 实际任务执行逻辑
        pass
```

---

### 3.3 实践：并发RPA任务执行器

**需求**：
- 支持批量关键词采集
- 控制并发避免触发风控
- 实时进度追踪
- 失败重试机制

**架构设计**：
```
┌─────────────────────────────────────────┐
│            TaskManager                  │
├─────────────────────────────────────────┤
│  ┌─────────┐  ┌─────────┐  ┌─────────┐│
│  │TaskQueue│  │Scheduler│  │ RateLimi ││
│  └────┬────┘  └────┬────┘  └────┬────┘│
│       │            │            │       │
│  ┌────▼────────────▼────────────▼────┐ │
│  │         ConcurrencyPool           │ │
│  │    ┌───┐ ┌───┐ ┌───┐ ┌───┐      │ │
│  │    │ T │ │ T │ │ T │ │ T │ ...  │ │
│  │    └───┘ └───┘ └───┘ └───┘      │ │
│  └───────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

---

## 4. 产出文件

### 4.1 调度器原型
路径：`src/rpa/scheduler.py`  
功能：集成APScheduler，支持定时/周期/一次性任务，带持久化和错误处理

### 4.2 队列管理器
路径：`src/rpa/task_queue.py`  
功能：基于Redis的任务队列，支持优先级、死信、重试机制

---

## 5. 技术选型建议

| 场景 | 推荐方案 | 原因 |
|------|----------|------|
| 简单单机任务 | schedule | 轻量，无依赖 |
| 企业级调度 | APScheduler | 功能完整，可扩展 |
| 分布式任务 | Celery | 分布式架构，监控完善 |
| I/O密集型 | asyncio | 高并发，资源占用低 |
| CPU密集型 | multiprocessing | 真并行，绕过GIL |

---

## 6. 常见问题与解决方案

### 任务重复执行
**原因**：调度器重启后重复触发
**解决**：使用持久化JobStore + misfire_grace_time

### 任务堆积
**原因**：Worker处理速度跟不上
**解决**：调整prefetch_multiplier，增加Worker数量

### 内存泄漏
**原因**：长时间运行累积
**解决**：worker_max_tasks_per_child限制Worker生命周期

### 风控触发
**原因**：请求频率过高
**解决**：实现令牌桶限流，添加随机延迟

---

*更新日期：2026-06-18*
