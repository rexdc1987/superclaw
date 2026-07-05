# 模块2：任务队列设计 — Celery + Redis

> 学习人：诸葛亮 | 日期：2026-06-20

---

## 1. Celery 核心架构

### Producer → Broker → Consumer 模型

```
Producer (生产者)
    ↓ 发送任务消息
Broker (消息代理：Redis / RabbitMQ)
    ↓ 分发任务
Consumer / Worker (消费者/工作进程)
    ↓ 执行任务
Result Backend (结果存储：Redis / DB)
```

- **Producer**：调用 `task.delay()` 或 `task.apply_async()` 的代码
- **Broker**：消息中间件，暂存待执行的任务。Redis 是最常用的选择（轻量、高性能）。
- **Consumer/Worker**：执行任务的进程，从 Broker 消费消息
- **Result Backend**：存储任务执行结果（可选）

### Celery 基础用法

```python
from celery import Celery

# 创建 Celery 实例
app = Celery(
    'superclaw',
    broker='redis://localhost:6379/0',
    backend='redis://localhost:6379/1'
)

# 配置
app.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    timezone='Asia/Shanghai',
    enable_utc=True,
    task_track_started=True,     # 跟踪任务开始状态
    task_acks_late=True,         # 任务完成后才确认（防worker崩溃丢任务）
    worker_prefetch_multiplier=1, # 每次只预取1个任务（长任务适用）
)

# 定义任务
@app.task(bind=True, max_retries=3)
def search_videos(self, keyword, platform='douyin'):
    try:
        # 执行搜索逻辑
        results = do_search(keyword, platform)
        return {'status': 'success', 'count': len(results)}
    except Exception as exc:
        # 指数退避重试
        self.retry(exc=exc, countdown=2 ** self.request.retries * 60)

# 调用任务
search_videos.delay('python', 'douyin')
```

---

## 2. Redis 作为消息队列

### 为什么选 Redis

| 特性 | 说明 |
|------|------|
| 高性能 | 内存操作，单机 10万+ QPS |
| 数据结构丰富 | List（简单队列）、Stream（持久化队列）、Pub/Sub |
| 持久化 | RDB + AOF，重启后数据可恢复 |
| 轻量 | 单二进制文件，运维简单 |
| Celery 原生支持 | `broker='redis://...'` 即可 |

### Redis 队列方案对比

#### 方案 A：Celery + Redis Broker（推荐）

```python
app = Celery('superclaw', broker='redis://localhost:6379/0')
```

优点：完整的企业级功能（重试、状态追踪、结果存储）
缺点：Celery 依赖较重

#### 方案 B：自建 Redis 队列（轻量替代）

```python
import redis
import json
import uuid

class SimpleTaskQueue:
    def __init__(self, redis_url='redis://localhost:6379/0'):
        self.redis = redis.from_url(redis_url)
        self.queue_name = 'superclaw:tasks'
    
    def enqueue(self, task_name, args=None, kwargs=None, priority=0):
        task_id = str(uuid.uuid4())
        task_data = {
            'id': task_id,
            'task': task_name,
            'args': args or [],
            'kwargs': kwargs or {},
            'priority': priority,
            'status': 'pending',
            'created_at': time.time()
        }
        # 使用 Sorted Set 实现优先级队列
        self.redis.zadd(self.queue_name, {json.dumps(task_data): priority})
        return task_id
    
    def dequeue(self):
        # 取出优先级最高的任务
        result = self.redis.zpopmin(self.queue_name)
        if result:
            task_data = json.loads(result[0][0])
            return task_data
        return None
    
    def get_status(self, task_id):
        return self.redis.hget(f'superclaw:task:{task_id}', 'status')
```

优点：零外部依赖（只需 redis-py），完全可控
缺点：需要自己实现重试、状态管理、Worker 等

#### 方案 C：Redis Stream（推荐用于生产）

```python
# 生产者
redis.xadd('superclaw:tasks', {
    'task': 'search_videos',
    'args': json.dumps(['python', 'douyin']),
    'task_id': str(uuid.uuid4())
})

# 消费者（消费者组，支持多 Worker）
redis.xreadgroup('worker-group', 'worker-1', {'superclaw:tasks': '>'}, count=1)
```

优点：持久化、消费者组、消息确认、支持多 Worker
缺点：API 比 List 复杂

---

## 3. 任务状态管理

### Celery 任务状态机

```
PENDING → STARTED → SUCCESS
                  ↘ FAILURE
                  ↘ REVOKED (手动撤销)
                  ↘ RETRY (自动重试，回到PENDING)
```

状态说明：
- **PENDING**：任务刚创建，等待执行
- **STARTED**：Worker 已开始执行（需设置 `task_track_started=True`）
- **SUCCESS**：执行成功
- **FAILURE**：执行失败
- **RETRY**：正在重试
- **REVOKED**：被手动撤销

### 自定义状态追踪

对于 RPA 任务，Celery 默认状态不够细。可以在任务中主动更新状态：

```python
@app.task(bind=True)
def run_rpa_task(self, task_id):
    # 更新进度
    self.update_state(state='SEARCHING', meta={'progress': 0.1})
    results = search_videos(keyword)
    
    self.update_state(state='FILTERING', meta={'progress': 0.5})
    filtered = filter_results(results)
    
    self.update_state(state='COMMENTING', meta={'progress': 0.7})
    commented = post_comments(filtered)
    
    return {'status': 'done', 'commented': len(commented)}
```

### 任务元数据（request 对象）

```python
@app.task(bind=True)
def my_task(self):
    # self.request 包含任务执行上下文
    self.request.id          # 任务唯一ID
    self.request.retries     # 当前重试次数
    self.request.max_retries # 最大重试次数
    self.request.delivery_info # 投递信息
```

---

## 4. SuperClaw 任务队列设计建议

### 任务分类

| 任务类型 | 特点 | 建议方案 |
|----------|------|----------|
| 定时触发 | 周期性、轻量 | APScheduler（进程内） |
| 数据采集 | 耗时、I/O 密集 | 异步队列 + Worker |
| 评论/互动 | 耗时、有频率限制 | 异步队列 + 限流器 |
| 数据导出 | 耗时、低优先级 | 后台队列 |
| 监控告警 | 轻量、周期性 | APScheduler |

### 队列优先级设计

```python
# Redis 队列优先级（Sorted Set）
QUEUES = {
    'critical': 0,    # 紧急：验证码处理、账号异常
    'high': 10,       # 高优：评论发布、私信发送
    'normal': 50,     # 正常：数据采集、搜索
    'low': 100,       # 低优：数据导出、报表生成
}
```

### 推荐方案

考虑到 SuperClaw 当前是单机 MVP 阶段，建议：

1. **调度层**：APScheduler（已有 scheduler.py）
2. **队列层**：简单的 Redis 队列（自建 SimpleTaskQueue）或直接用 asyncio.Queue
3. **执行层**：asyncio.Semaphore 控制并发
4. **后续扩展**：当需要多机部署时，迁移到 Celery + Redis

---

<!-- MODULE_COMPLETE: task_queue -->
