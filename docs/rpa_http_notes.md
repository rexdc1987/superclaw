# RPA 第一阶段学习笔记 - HTTP 直连技术

## 一、Python httpx 库

### 1.1 为什么选 httpx 而不是 requests？

| 特性 | httpx | requests |
|------|-------|----------|
| HTTP/2 支持 | ✅ | ❌ |
| 异步支持 | ✅ 原生 | ❌ (需 aiohttp) |
| 流式响应 | ✅ | ⚠️ 有限 |
| 超时控制 | ✅ 细粒度 | ⚠️ 粗粒度 |
| 会话管理 | ✅ | ✅ |

对于 RPA 场景，httpx 的异步能力 + HTTP/2 是核心优势。

### 1.2 安装与基础用法

```bash
pip install httpx
```

### 1.3 同步请求

```python
import httpx

# 基础 GET
resp = httpx.get("https://httpbin.org/get")
print(resp.status_code, resp.json())

# 带参数
resp = httpx.get("https://httpbin.org/get", params={"key": "value"})
```

### 1.4 Session 管理（关键！）

Session 在 RPA 中用于**复用连接和 Cookie**：

```python
with httpx.Client() as client:
    # 第一次请求获取 Cookie
    client.get("https://example.com/login")
    # 后续请求自动携带 Cookie
    resp = client.get("https://example.com/dashboard")
```

### 1.5 异步请求

```python
import httpx
import asyncio

async def main():
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://httpbin.org/get")
        print(resp.json())

asyncio.run(main())
```

并发请求（RPA 高效抓取利器）：

```python
async def fetch_all(urls):
    async with httpx.AsyncClient() as client:
        tasks = [client.get(url) for url in urls]
        return await asyncio.gather(*tasks)
```

### 1.6 Cookie 处理

```python
# 手动设置
cookies = {"session_id": "abc123"}
resp = client.get(url, cookies=cookies)

# 从浏览器导出的 Cookie 转换
browser_cookies = {"sessionid": "xxx", "csrftoken": "yyy"}
client.cookies.update(browser_cookies)
```

### 1.7 自定义请求头

模仿浏览器是反爬的关键：

```python
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...",
    "Referer": "https://www.douyin.com/",
    "Accept": "application/json",
}
client = httpx.Client(headers=headers)
```

### 1.8 超时与重试

```python
# 细粒度超时
timeout = httpx.Timeout(
    connect=5.0,    # 连接超时
    read=30.0,      # 读取超时
    write=5.0,      # 写入超时
    pool=5.0        # 连接池超时
)
client = httpx.Client(timeout=timeout)
```

---

## 二、抓包分析

### 2.1 为什么需要抓包？

- 浏览器请求的 Cookie、Token、签名参数需要从真实请求中提取
- 验证 API 接口的真实行为
- 分析请求/响应结构

### 2.2 mitmproxy 基础

```bash
pip install mitmproxy
```

启动代理：

```bash
mitmproxy  # 交互式 TUI
mitmweb    # Web UI（推荐）
```

默认监听 `127.0.0.1:8080`

### 2.3 浏览器配置代理

1. Chrome 设置代理 → `127.0.0.1:8080`
2. 访问 `mitm.it` 安装 CA 证书
3. 访问目标网站，抓包面板即可看到所有请求

### 2.4 分析请求结构

重点关注：
- **请求方法**：GET / POST
- **Headers**：Cookie、Authorization、User-Agent、Referer
- **Body**：表单数据或 JSON
- **Query Params**：时间戳、签名参数

### 2.5 抖音 API 分析要点

抖音关键 Cookie 字段：
- `sessionid` — 会话标识
- `ttwid` — 设备追踪
- `__ac_nonce` / `__ac_signature` — 反爬签名

关键 Headers：
- `User-Agent` — 必须真实
- `Referer` — 必须匹配
- `Cookie` — 必须完整

### 2.6 导出 Cookie 为 Python 字典

```python
# 从 Chrome DevTools 导出
cookies_str = "sessionid=xxx; ttwid=yyy; __ac_nonce=zzz"
cookies_dict = dict(item.split("=", 1) for item in cookies_str.split("; "))
```

---

## 三、API 逆向基础

### 3.1 逆向流程

```
浏览器操作 → mitmproxy 抓包 → 分析请求 → 提取参数 → httpx 复现
```

### 3.2 登录接口分析

通常流程：
1. 获取初始 Cookie（访问首页）
2. 获取 Token（如 CSRF Token）
3. 提交登录表单（POST）
4. 保存返回的 Session Cookie

### 3.3 发评论接口（以抖音为例）

典型请求结构：
```
POST https://www.douyin.com/aweme/v1/web/comment/post/
Headers:
  Cookie: sessionid=xxx; ...
  Content-Type: application/x-www-form-urlencoded
Body:
  aweme_id=VIDEO_ID
  text=COMMENT_TEXT
  csrf_token=TOKEN
```

### 3.4 安全注意事项

- Cookie 有有效期，需要定期刷新
- 签名参数可能有时间戳校验
- 请求频率需要控制（避免被封）
- 建议使用代理 IP

---

## 四、核心经验总结

### HTTP 直连 vs 浏览器自动化

| 维度 | HTTP 直连 | 浏览器自动化 |
|------|-----------|-------------|
| 速度 | ⚡ 极快 | 🐌 慢（需要渲染） |
| 资源占用 | 极低 | 高（需要浏览器进程） |
| 难度 | 较高（需逆向） | 较低（所见即所得） |
| 稳定性 | 依赖参数正确 | 较稳定 |
| 适用场景 | API 调用、批量操作 | 复杂交互、页面依赖 |

### 选择策略

- **能用 HTTP 直连就用 HTTP** — 快、轻、可控
- **浏览器只在必要时使用** — 页面渲染、复杂 JS 交互
- **混合使用** — 用浏览器抓包，用 HTTP 执行

---

_学习日期: 2026-06-18_
