# 赵云 Phase 3 学习笔记 — 多账号管理 + 反检测集成 + HTTP 中间件

> 学习人：赵云 | 日期：2026-06-20 | 任务：task_learn_zhaoyun_phase3.md

---

## 模块 1：Account Pool Manager

### 1.1 设计架构

```
AccountPool
  ├── AccountInfo (数据模型)
  │     ├── status: ACTIVE / COOLDOWN / DISABLED / BANNED
  │     ├── health_score: 0-100
  │     └── cooldown_until: 冷却结束时间戳
  ├── 选策略: round_robin / health_first / random / least_used
  └── 并发控制: asyncio.Lock
```

### 1.2 账号状态机

```
ACTIVE ──失败3次──> COOLDOWN ──超时──> ACTIVE
ACTIVE ──人工──> DISABLED
ACTIVE ──封禁──> BANNED
COOLDOWN ──人工──> DISABLED
```

关键设计：**连续失败 3 次自动冷却**，冷却期间 `is_available` 返回 False。冷却结束后自动恢复 ACTIVE。

### 1.3 选策略对比

| 策略 | 适用场景 | 特点 |
|------|----------|------|
| round_robin | 均匀分配负载 | 简单公平，最常用 |
| health_first | 优先用健康账号 | 避免用问题账号 |
| random | 打散请求模式 | 防止平台识别轮换规律 |
| least_used | 均衡使用次数 | 避免某些账号过度使用 |

### 1.4 数据模型分离

Phase 3 将 `AccountInfo`、`AccountStatus`、`HealthMetrics` 等数据模型提取到 `models.py`，与池逻辑分离。好处：
- 数据模型可独立复用（如 API 响应序列化）
- 池逻辑更纯粹（只管选策略和并发控制）
- 测试更容易（不需要实例化整个池就能测模型）

---

## 模块 2：Browser Context Factory

### 2.1 核心设计

```
ContextFactory
  ├── 每个账号 → 独立 BrowserContext
  ├── 集成 StealthMiddleware（反检测 JS 注入）
  ├── 集成 FingerprintManager（指纹伪装）
  ├── storage_state 持久化（Cookie/LocalStorage 保存恢复）
  └── 资源限制
        ├── max_contexts: 最大并发上下文数
        └── idle_timeout: 空闲超时自动回收
```

### 2.2 反检测集成

Phase 3 的关键改进：**ContextFactory 自动应用反检测措施**。

```python
factory = ContextFactory(browser)
factory.set_stealth(StealthMiddleware())          # 注入反检测 JS
factory.set_fingerprint_manager(FingerprintManager())  # 注入指纹伪装

# 创建上下文时自动应用
ctx = await factory.create_context("account_1", anti_detect=True)
```

**为什么在 ContextFactory 层集成？**
- 业务代码不需要关心反检测细节
- 每个账号上下文自动隔离反检测配置
- 方便统一管理和调试

### 2.3 资源管理

- **max_contexts=10**：防止同时打开太多浏览器上下文导致内存爆炸
- **idle_timeout=600s**：10 分钟未使用的上下文自动回收（保存状态后关闭）
- 回收策略：创建新上下文时，如果已达上限，先回收空闲最久的

### 2.4 Context 生命周期

```
create_context() → 使用中 → save_state() → close_context()
                     ↑                        ↓
                     └── idle_timeout 自动回收 ─┘
```

---

## 模块 3：HTTP 中间件链

### 3.1 中间件架构

```
MiddlewareChain
  ├── UARotator         → 每次请求随机/绑定 UA
  ├── PlatformHeaders   → 注入平台特定请求头
  ├── RateLimiter       → 令牌桶限流（per-account）
  └── RequestLogger     → 请求日志和统计
```

### 3.2 中间件执行流程

```
请求 → [UARotator] → [PlatformHeaders] → [RateLimiter] → [RequestLogger] → 发送
响应 → [RequestLogger] → [RateLimiter] → ... → 返回
```

每个中间件可以修改 headers/cookies，也可以做限流等待、日志记录等副作用。

### 3.3 各中间件详解

#### UARotator

- **随机模式**：每次请求随机选一个 UA
- **绑定模式**：同一账号始终用同一 UA（防指纹不一致）
- 内置 9 个 UA（Chrome/Firefox/Edge，Win/Mac/Linux）

#### PlatformHeaders

- 内置 4 个平台的默认请求头（douyin/weibo/xiaohongshu/bilibili）
- 包含 Referer、Sec-Ch-Ua、Sec-Fetch-* 等反爬关键头
- 已有的头不会被覆盖（安全）

#### RateLimiter

- **双层限流**：每分钟令牌桶 + 每秒突发控制
- **per-account 隔离**：每个账号独立计数
- 令牌不够时自动等待（不是拒绝）

#### RequestLogger

- 记录每个账号的请求和响应
- 统计每个账号的请求数和错误数
- 支持自定义日志级别

### 3.4 使用示例

```python
from rpa.http import MiddlewareChain, UARotator, PlatformHeaders, RateLimiter, RequestLogger

# 构建中间件链
chain = MiddlewareChain()
chain.add(UARotator(bind_to_account=True))           # 同账号同 UA
chain.add(PlatformHeaders("douyin"))                  # 抖音请求头
chain.add(RateLimiter(max_per_minute=30))             # 每分钟 30 次
chain.add(RequestLogger())                            # 日志

# 在请求前调用
headers, cookies = await chain.process_request(
    account_id="acc1",
    url="https://api.douyin.com/aweme/v1/web/search/",
    method="GET",
)

# 发送请求后
await chain.process_response("acc1", url, response.status_code, dict(response.headers))
```

---

## 踩坑记录

### 1. Pool acquire 不锁定账号

`acquire()` 只是返回一个可用账号并更新 `last_used`，不会把账号标记为"使用中"。这是因为：
- RPA 场景中，acquire → 操作 → release 是一个流程
- 中间不需要"锁定"状态（不像数据库连接池）
- 如果需要严格锁定，可以在 `release()` 时才扣减

### 2. 中间件顺序很重要

- UA 轮换要在平台头之前（平台头不包含 UA）
- 限流要在日志之前（限流等待后也要记录）
- 日志要放最后（记录最终的 headers）

### 3. Python 3.8 兼容

所有类型标注用 `Dict`、`List`、`Optional`（from typing），不用 `dict[str, str]`。

---

## 测试覆盖

| 模块 | 测试数 | 覆盖内容 |
|------|--------|----------|
| AccountInfo | 13 | 状态判断、冷却、成功率、序列化 |
| AccountPool | 11 | 增删查、4 种策略、acquire/release、导入导出 |
| HealthScorer | 4 | 健康评分、分类、建议 |
| UARotator | 3 | 随机/绑定/自定义 UA 池 |
| PlatformHeaders | 5 | 4 个平台 + 未知平台 + 不覆盖已有头 |
| RateLimiter | 2 | 正常速率 + per-account 隔离 |
| RequestLogger | 2 | 请求日志 + 响应统计 |
| MiddlewareChain | 4 | 链式执行 + 全链 + 链式 API + 清空 |
| **总计** | **44** | |

---

<!-- TASK_COMPLETE: phase3_accounts -->
