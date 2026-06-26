# 赵云 Phase 2 学习笔记 — HTTP Client + 反检测 + Token 管理

> 学习人：赵云 | 日期：2026-06-20 | 任务：task_learn_zhaoyun_phase2.md

---

## 模块 1：HTTP Client Wrapper

### 1.1 为什么要封装 httpx？

httpx 本身已经很好用，但在生产环境中还需要：

- **自动重试**：网络抖动、429 限流、5xx 错误都需要重试
- **统一超时**：connect/read/write/pool 四级控制
- **连接池复用**：每次请求都新建 AsyncClient 会浪费 TCP 握手时间
- **请求日志**：生产环境需要知道每次请求的状态和耗时
- **统计信息**：成功率、平均延迟等指标

### 1.2 架构设计

```
HttpClient (对外接口)
  ├── RetryExecutor (重试执行器)
  │     └── RetryPolicy (策略配置)
  │           └── ExponentialBackoff (退避算法)
  └── httpx.AsyncClient (底层连接池)
```

### 1.3 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 重试策略 | 指数退避 + 抖动 | 抖动避免多客户端同时重试造成"惊群" |
| 429 处理 | 尊重 Retry-After 头 | 服务器明确告诉你等多久 |
| 连接池大小 | max_connections=100 | 平衡并发能力和资源占用 |
| 超时默认值 | connect=5s, read=30s | 代理可能慢（connect），页面渲染可能久（read） |
| Python 3.8 兼容 | 用 `Dict` 代替 `dict[str, str]` | 项目环境是 Python 3.8 |

### 1.4 使用示例

```python
from rpa.http import HttpClient, RetryPolicy

# 基础使用
async with HttpClient() as client:
    resp = await client.get("https://api.example.com/data")
    print(resp.json())

# 带配置
client = HttpClient(
    base_url="https://api.example.com",
    headers={"Authorization": "Bearer xxx"},
    retry=RetryPolicy(max_retries=5),
    proxy="http://127.0.0.1:7890",
)

# 流式下载
async with client.stream("GET", "https://example.com/big_file") as resp:
    async for chunk in resp.aiter_bytes():
        process(chunk)

# 查看统计
print(client.stats())
# {'total_requests': 42, 'errors': 1, 'success_rate': '97.6%', ...}
```

### 1.5 测试覆盖

- ExponentialBackoff: 退避计算、最大值限制、抖动
- RetryPolicy: 状态码重试、异常重试、次数限制、Retry-After 解析
- RetryExecutor: 成功不重试、异常自动重试
- HttpClient: GET/POST 请求、统计、上下文管理器

---

## 模块 2：反检测模块增强

### 2.1 现有代码分析

Phase 1 已经有完整的反检测模块：

| 文件 | 功能 | 完成度 |
|------|------|--------|
| `stealth.py` | WebDriver 隐藏 + CDP 注入 | ✅ 90% |
| `fingerprint.py` | 浏览器指纹伪装（5 套模板） | ✅ 85% |
| `behavior.py` | 行为模拟（鼠标/键盘/滚动） | ✅ 70% |
| `proxy_manager.py` | 代理池管理 | ✅ 75% |
| `captcha_adapter.py` | 验证码处理 | ✅ 60% |

### 2.2 Phase 2 增强内容

#### 反检测策略独立开关

给 `StealthMiddleware` 添加了 6 个独立开关：

```python
stealth = StealthMiddleware(
    profile=fingerprint,
    enable_webdriver_hiding=True,     # 隐藏 navigator.webdriver
    enable_plugins_spoof=True,        # 伪造插件列表
    enable_navigator_override=True,   # 覆盖 navigator 属性
    enable_chromedriver_cleanup=True, # 删除 ChromeDriver 标记
    enable_permissions_fix=True,      # 修复 permissions API
    enable_ua_spoof=True,             # 伪装 UA 请求头
)
```

**为什么需要独立开关？**
- 调试时可以逐个关闭，定位哪个策略被检测
- 不同平台检测维度不同，可以针对性启用
- 某个策略出问题时可以快速降级

#### Timezone 支持

给 `FingerprintProfile` 添加了 `timezone` 和 `locale` 字段：

```python
profile = FingerprintProfile(
    name="my_profile",
    timezone="Asia/Shanghai",
    locale="zh-CN",
    ...
)
```

同时生成 `Intl.DateTimeFormat` 覆盖 JS，确保 `new Date().toLocaleString()` 返回正确时区。

**为什么 timezone 重要？**
- 检测平台会对比 IP 地理位置和浏览器时区
- 如果 IP 是中国但时区是 UTC，会被标记为可疑
- 5 套设备模板都配了对应的 timezone

### 2.3 反检测验证方法

| 检测站 | 网址 | 检测内容 |
|--------|------|----------|
| bot.sannysoft.com | https://bot.sannysoft.com | 基础自动化检测 |
| pixelscan.net | https://pixelscan.net | 浏览器指纹一致性 |
| creepjs | https://abrahamjuliot.github.io/creepjs/ | 高级指纹检测 |

**验证流程：**
1. 启动反检测浏览器
2. 访问检测站
3. 截图对比（全绿 = 通过）
4. 定期回归测试（防止代码变更导致退化）

---

## 模块 3：Token Manager

### 3.1 设计目标

| 目标 | 实现 |
|------|------|
| Token 存储 | JSON 文件 + base64 编码（防明文泄露） |
| Token 刷新 | OAuth2 refresh_token 流程 |
| 多账号隔离 | 每个账号独立文件 |
| 过期检测 | `is_expired` 属性 + `get_valid()` 方法 |
| 自动续期 | `ensure_valid()` 方法 |

### 3.2 数据模型

```python
@dataclass
class TokenInfo:
    access_token: str      # 访问令牌
    refresh_token: str     # 刷新令牌
    token_type: str        # 通常是 "Bearer"
    expires_at: float      # Unix 时间戳
    scope: str             # 权限范围
    created_at: float      # 创建时间
    extra: dict            # 扩展字段
```

### 3.3 存储安全

- **base64 编码**：token 值在文件中不是明文（非真加密，但防肉眼读取）
- **文件隔离**：每个账号一个 JSON 文件，不会互相污染
- **自动加载**：`TokenManager` 初始化时自动从磁盘加载已有 token

### 3.4 使用示例

```python
from rpa.auth import TokenManager, TokenInfo

# 初始化
tm = TokenManager(storage_dir="./tokens")

# 保存 token
tm.save("account_1", TokenInfo(
    access_token="eyJhbGciOiJIUzI1NiIs...",
    refresh_token="dGhpcyBpcyBhIHJlZnJlc2g...",
    expires_at=time.time() + 3600,
))

# 获取有效 token
token = tm.get_valid("account_1")

# 获取 Authorization 头
headers = tm.auth_headers("account_1")
# {'Authorization': 'Bearer eyJhbGciOiJIUzI1NiIs...'}

# 自动刷新
new_token = await tm.refresh(
    "account_1",
    token_url="https://api.example.com/oauth/token",
    client_id="xxx",
    client_secret="yyy",
)
```

### 3.5 测试覆盖

- TokenInfo: 过期判断、剩余时间、序列化/反序列化
- TokenStore: 保存/加载/删除/列表/base64 编码/清除
- TokenManager: 保存/获取/有效检查/请求头/删除/统计/持久化

---

## 踩坑记录

### 1. Python 3.8 类型语法

Python 3.8 不支持 `dict[str, str]` 语法，必须用 `Dict[str, str]`（from typing）。一开始没注意，导致 `TypeError: 'type' object is not subscriptable`。

### 2. pytest-asyncio 警告

`asyncio_default_fixture_loop_scope` 未设置的警告。不影响测试结果，但需要在 `pyproject.toml` 中配置：
```toml
[tool.pytest.ini_options]
asyncio_default_fixture_loop_scope = "function"
```

### 3. 指数退避的抖动

不加抖动的话，多个客户端在相同时间重试会造成"惊群效应"。加了 `random.uniform(0, jitter)` 后，重试时间分散开，对服务器更友好。

### 4. Retry-After 解析

有些服务器返回 `Retry-After: 30`（秒数），有些返回 HTTP 日期格式。当前实现只处理了秒数格式，日期格式需要后续补充。

---

## 对 SuperClaw 的应用

| 模块 | 应用场景 |
|------|----------|
| HttpClient | 替换 `actions/builtin.py` 中的同步 httpx 调用 |
| RetryPolicy | 统一所有 HTTP 请求的重试策略 |
| TokenManager | 多账号运营的 Token 管理基础 |
| Stealth 增强 | 不同平台用不同反检测配置 |

---

<!-- TASK_COMPLETE: phase2_http -->
