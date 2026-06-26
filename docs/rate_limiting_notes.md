# 模块3：并发控制与限流策略

> 学习人：诸葛亮 | 日期：2026-06-20

---

## 1. asyncio.Semaphore 并发控制

### 基本原理

Semaphore（信号量）是一个计数器，控制同时访问共享资源的并发数。

```python
import asyncio

# 最多允许5个并发任务
semaphore = asyncio.Semaphore(5)

async def limited_task(task_id):
    async with semaphore:
        print(f"Task {task_id} 开始执行")
        await asyncio.sleep(2)  # 模拟耗时操作
        print(f"Task {task_id} 执行完成")

async def main():
    # 同时启动20个任务，但只有5个能同时执行
    tasks = [limited_task(i) for i in range(20)]
    await asyncio.gather(*tasks)

asyncio.run(main())
```

### 在 RPA 场景中的应用

```python
# 控制浏览器并发数（每个浏览器占用大量内存）
browser_semaphore = asyncio.Semaphore(3)

# 控制每个账号的并发操作
account_semaphore = asyncio.Semaphore(1)  # 单账号串行

async def search_with_limit(account, keyword):
    async with account_semaphore:
        # 同一账号的操作串行执行
        browser = await get_browser(account)
        results = await browser.search(keyword)
        return results

# 多账号并行，但每个账号串行
async def multi_account_search(accounts, keyword):
    tasks = [search_with_limit(acc, keyword) for acc in accounts]
    return await asyncio.gather(*tasks)
```

### 并发模式对比

| 模式 | 实现 | 适用场景 |
|------|------|----------|
| **无限制并发** | `asyncio.gather(*tasks)` | 轻量 I/O 操作 |
| **Semaphore 限流** | `asyncio.Semaphore(n)` | 控制并发上限 |
| **队列 + Worker** | `asyncio.Queue` + Worker 协程 | 复杂任务编排 |
| **进程池** | `ProcessPoolExecutor(n)` | CPU 密集型任务 |

---

## 2. 令牌桶算法（Token Bucket）

### 原理

令牌桶是最常用的限流算法之一：

- 桶以固定速率填充令牌（如每秒 1 个）
- 桶有最大容量（如 10 个令牌）
- 每次请求消耗 1 个令牌
- 桶空时请求被拒绝（或等待）

```
时间 →
桶容量: 10, 填充速率: 2个/秒

t=0: 桶=10, 请求1个 → 桶=9, 允许
t=1: 桶=9+2=10(上限10), 请求3个 → 桶=7, 允许
t=2: 桶=7+2=9, 请求10个 → 桶=0, 只允许9个, 拒绝1个
```

### Python 实现

```python
import time
import asyncio
from dataclasses import dataclass

@dataclass
class TokenBucket:
    """令牌桶限流器"""
    capacity: int          # 桶容量
    refill_rate: float     # 每秒填充的令牌数
    tokens: float = 0      # 当前令牌数
    last_refill: float = 0
    
    def __post_init__(self):
        self.tokens = self.capacity
        self.last_refill = time.monotonic()
    
    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(
            self.capacity,
            self.tokens + elapsed * self.refill_rate
        )
        self.last_refill = now
    
    def acquire(self) -> bool:
        """尝试获取令牌"""
        self._refill()
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False
    
    async def wait(self):
        """等待直到获取令牌"""
        while not self.acquire():
            # 计算需要等待的时间
            wait_time = (1 - self.tokens) / self.refill_rate
            await asyncio.sleep(min(wait_time, 0.1))
```

### 使用示例

```python
# 抖音评论：每分钟最多20条
douyin_comment_limiter = TokenBucket(capacity=20, refill_rate=20/60)

# 抖音关注：每小时最多50个
douyin_follow_limiter = TokenBucket(capacity=50, refill_rate=50/3600)

async def safe_comment(video_id, content):
    await douyin_comment_limiter.wait()  # 等待令牌
    return await post_comment(video_id, content)
```

---

## 3. 漏桶算法（Leaky Bucket）

### 原理

漏桶以固定速率处理请求，多余请求排队或丢弃：

- 请求进入桶（队列）
- 桶以固定速率"漏出"（处理请求）
- 桶满时新请求被丢弃

```
请求 → [桶/队列] → 固定速率处理
          ↓
     桶满时丢弃
```

### 与令牌桶的区别

| 特性 | 令牌桶 | 漏桶 |
|------|--------|------|
| 允许突发 | ✅ 桶满时可突发消费 | ❌ 固定速率处理 |
| 平滑输出 | ❌ 依赖桶中令牌数 | ✅ 严格匀速 |
| 适用场景 | 突发容忍型（如API调用） | 严格匀速型（如数据流） |

### RPA 场景建议

- **评论/互动**：令牌桶（允许短时间突发，但整体受控）
- **搜索/采集**：漏桶（严格控制请求速率，避免触发风控）

---

## 4. 平台 API 限流策略

### 各平台限流参考

| 平台 | 操作 | 建议频率 | 限流策略 |
|------|------|----------|----------|
| 抖音 | 评论 | ≤20条/分钟/账号 | 令牌桶 |
| 抖音 | 关注 | ≤50个/小时/账号 | 令牌桶 |
| 抖音 | 私信 | ≤20条/小时/账号 | 令牌桶 |
| 抖音 | 搜索 | ≤10次/分钟 | 漏桶 |
| 微博 | 评论 | ≤30条/小时/账号 | 令牌桶 |
| 小红书 | 评论 | ≤15条/分钟/账号 | 令牌桶 |

### 多层限流架构

```
全局限流（所有账号共享）
    ↓
平台限流（每个平台独立）
    ↓
账号限流（每个账号独立）
    ↓
操作限流（每种操作独立）
```

```python
class RateLimitManager:
    """多层限流管理器"""
    
    def __init__(self):
        # 全局：所有账号每分钟最多100次操作
        self.global_limiter = TokenBucket(capacity=100, refill_rate=100/60)
        
        # 平台级
        self.platform_limiters = {
            'douyin': TokenBucket(capacity=50, refill_rate=50/60),
            'weibo': TokenBucket(capacity=30, refill_rate=30/60),
        }
        
        # 账号级 + 操作级
        self.account_limiters = {}  # {account_id: {action_type: TokenBucket}}
    
    async def check_and_acquire(self, account_id, platform, action_type):
        """检查所有层级的限流"""
        # 全局
        if not self.global_limiter.acquire():
            return False
        
        # 平台
        platform_limiter = self.platform_limiters.get(platform)
        if platform_limiter and not platform_limiter.acquire():
            return False
        
        # 账号 + 操作
        key = f"{account_id}:{action_type}"
        if key not in self.account_limiters:
            self.account_limiters[key] = self._create_account_limiter(action_type)
        
        if not self.account_limiters[key].acquire():
            return False
        
        return True
    
    def _create_account_limiter(self, action_type):
        """根据操作类型创建账号级限流器"""
        limits = {
            'comment': (20, 20/60),     # 20条/分钟
            'follow': (50, 50/3600),    # 50个/小时
            'dm': (20, 20/3600),        # 20条/小时
            'search': (10, 10/60),      # 10次/分钟
        }
        capacity, rate = limits.get(action_type, (10, 10/60))
        return TokenBucket(capacity=capacity, refill_rate=rate)
```

---

## 5. 错误处理与降级

### 风控触发后的处理

```python
async def safe_action(account_id, platform, action_type, action_func):
    """带限流和错误处理的安全执行"""
    limiter = RateLimitManager()
    
    for attempt in range(3):
        if await limiter.check_and_acquire(account_id, platform, action_type):
            try:
                result = await action_func()
                return result
            except CaptchaError:
                # 验证码：冷却该账号
                await cooldown_account(account_id, minutes=30)
                return None
            except RateLimitError:
                # 被平台限流：指数退避
                await asyncio.sleep(2 ** attempt * 60)
                continue
            except LoginExpiredError:
                # 登录过期：标记账号需要重新登录
                await mark_account_expired(account_id)
                return None
        else:
            # 本地限流触发：等待后重试
            await asyncio.sleep(5)
    
    return None  # 所有重试失败
```

---

## 6. 代码验证

```python
import asyncio
import time

async def test_token_bucket():
    bucket = TokenBucket(capacity=5, refill_rate=2)  # 5个容量，每秒2个
    
    results = []
    for i in range(10):
        start = time.monotonic()
        await bucket.wait()
        elapsed = time.monotonic() - start
        results.append((i, round(elapsed, 2)))
    
    for idx, wait in results:
        print(f"请求 {idx}: 等待 {wait}s")

# 前5个立即执行，后面开始等待
asyncio.run(test_token_bucket())
```

---

<!-- MODULE_COMPLETE: rate_limiting -->
