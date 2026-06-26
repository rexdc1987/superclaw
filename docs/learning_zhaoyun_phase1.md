# 赵云 Phase 1 学习笔记 — HTTP 直连与 API 逆向

> 学习人：赵云 | 日期：2026-06-20 | 任务：task_learn_zhaoyun_phase1.md

---

## 模块 1：httpx 基础

### 1.1 httpx vs requests 核心差异

| 维度 | httpx | requests |
|------|-------|----------|
| HTTP/2 | ✅ 原生支持 | ❌ |
| 异步 | ✅ 原生 async/await | ❌（需 aiohttp） |
| 流式响应 | ✅ `stream()` + `aiter_bytes()` | ⚠️ 有限 |
| 超时控制 | 四级精细控制（connect/read/write/pool） | 单一 timeout |
| 连接池 | ✅ 内置 | ✅（urllib3） |
| 类型提示 | ✅ 完整 | ⚠️ 部分 |

**核心结论**：httpx 是 requests 的现代替代品。对 RPA 场景来说，异步支持 + HTTP/2 是决定性优势——可以并发发起大量请求而不需要多线程。

### 1.2 同步用法

```python
import httpx

# === 基础 GET ===
resp = httpx.get("https://httpbin.org/get")
print(resp.status_code)   # 200
print(resp.json())         # dict

# === 带参数 ===
resp = httpx.get("https://httpbin.org/get", params={"key": "value", "page": 1})

# === 自定义请求头（反爬关键）===
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0",
    "Referer": "https://www.douyin.com/",
    "Accept": "application/json",
}
resp = httpx.get("https://httpbin.org/headers", headers=headers)

# === POST JSON ===
resp = httpx.post("https://httpbin.org/post", json={"name": "test"})

# === POST 表单 ===
resp = httpx.post("https://httpbin.org/post", data={"username": "admin"})
```

### 1.3 Session 管理（连接复用）

```python
import httpx

# Session 的核心价值：复用 TCP 连接 + 自动管理 Cookie
with httpx.Client() as client:
    # 第一次请求建立连接、获取 Cookie
    resp1 = client.get("https://httpbin.org/cookies/set?token=abc123")
    
    # 后续请求自动携带 Cookie，且复用 TCP 连接（快！）
    resp2 = client.get("https://httpbin.org/cookies")
    print(resp2.json())  # {'cookies': {'token': 'abc123'}}

# 带配置的 Session
client = httpx.Client(
    headers={"User-Agent": "MyBot/1.0"},
    cookies={"session_id": "xxx"},
    timeout=httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=5.0),
    follow_redirects=True,
    verify=False,  # 跳过 SSL 验证（开发用）
)
```

### 1.4 异步用法（RPA 核心）

```python
import httpx
import asyncio

# === 基础异步请求 ===
async def fetch_one():
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://httpbin.org/get")
        return resp.json()

# === 并发请求（核心能力！）===
async def fetch_all(urls: list[str]) -> list[dict]:
    """并发请求多个 URL，比逐个请求快 N 倍。"""
    async with httpx.AsyncClient() as client:
        tasks = [client.get(url) for url in urls]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        results = []
        for resp in responses:
            if isinstance(resp, Exception):
                results.append({"error": str(resp)})
            else:
                results.append(resp.json())
        return results

# === 带错误处理的异步请求 ===
async def safe_fetch(client: httpx.AsyncClient, url: str) -> dict:
    """带重试和错误处理的请求。"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = await client.get(url, timeout=30.0)
            resp.raise_for_status()  # 4xx/5xx 抛异常
            return resp.json()
        except httpx.TimeoutException:
            print(f"超时 (attempt {attempt + 1}/{max_retries})")
        except httpx.HTTPStatusError as e:
            print(f"HTTP {e.response.status_code}")
            if e.response.status_code == 429:  # 限流
                retry_after = int(e.response.headers.get("Retry-After", 5))
                await asyncio.sleep(retry_after)
            else:
                raise
        except httpx.RequestError as e:
            print(f"请求错误: {e}")
        
        await asyncio.sleep(2 ** attempt)  # 指数退避
    
    return {"error": "max retries exceeded"}

# === 流式响应（大文件下载）===
async def stream_download(url: str, save_path: str):
    """流式下载，不会一次性加载到内存。"""
    async with httpx.AsyncClient() as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(save_path, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=8192):
                    f.write(chunk)
    print(f"下载完成: {save_path}")
```

### 1.5 超时控制详解

```python
import httpx

# 四级超时控制
timeout = httpx.Timeout(
    connect=5.0,    # 建立 TCP 连接的超时
    read=30.0,      # 等待响应数据的超时
    write=5.0,      # 发送请求体的超时
    pool=5.0        # 从连接池获取连接的超时
)

# 简写：所有级别同一个值
timeout = httpx.Timeout(30.0)

# None 表示不限超时
timeout = httpx.Timeout(connect=5.0, read=None)
```

**RPA 实战建议**：
- `connect` 设 5-10 秒（代理可能慢）
- `read` 设 30-60 秒（页面渲染可能慢）
- `pool` 设 5 秒（连接池满了不要等太久）

### 1.6 httpx 与 SuperClaw 的关联

现有代码中 `actions/builtin.py` 的 `HttpGetAction` 和 `HttpPostAction` 已经在用 httpx。但有几个改进点：

1. **没有连接复用**：每次请求都 `httpx.get()`，没有用 Session
2. **没有异步**：用的是同步 API，在异步管道中会阻塞事件循环
3. **重试逻辑缺失**：`HttpGetAction` 没有重试机制

**建议**：在模块 2 的性能优化中，引入 `httpx.AsyncClient` 连接池，统一管理 HTTP 请求。

---

## 模块 2：抓包分析

### 2.1 mitmproxy 是什么

mitmproxy 是一个交互式 HTTPS 代理，可以拦截、修改、重放 HTTP(S) 请求。它是 API 逆向的核心工具。

### 2.2 安装与启动

```bash
pip install mitmproxy

# 三种界面
mitmproxy     # 终端 TUI（键盘操作）
mitmweb       # Web UI（浏览器访问 http://127.0.0.1:8081）
mitmdump      # 无头模式（可加载 Python 脚本）
```

### 2.3 使用流程

```
1. 启动 mitmproxy:  mitmweb
2. 浏览器设置代理:   127.0.0.1:8080
3. 安装 CA 证书:     访问 mitm.it → 下载并安装
4. 操作目标网站:     正常浏览，所有请求都会被捕获
5. 分析请求:         在 mitmweb 面板中查看
```

### 2.4 分析请求的关键维度

抓到一个请求后，需要关注：

| 维度 | 关注点 |
|------|--------|
| Method | GET / POST / PUT |
| URL | 路径 + 查询参数（时间戳、签名） |
| Headers | Cookie、Authorization、User-Agent、Referer、Content-Type |
| Request Body | JSON / 表单 / multipart |
| Response | 状态码、响应体结构、分页参数 |
| 时间线 | 请求顺序（哪些请求有依赖关系） |

### 2.5 抖音 API 逆向分析示例

通过 mitmproxy 抓包，抖音的关键请求结构：

```
# 搜索接口
GET https://www.douyin.com/aweme/v1/web/general/search/single/
?keyword=关键词
&search_channel=aweme_video_web
&sort_type=0
&publish_time=0
&count=10
&offset=0
&search_source=normal_search
&query_correct_type=1
&is_filter_search=0
Headers:
  Cookie: sessionid=xxx; ttwid=yyy; __ac_nonce=zzz; __ac_signature=www
  User-Agent: Mozilla/5.0 ...
  Referer: https://www.douyin.com/search/关键词

# 评论接口
POST https://www.douyin.com/aweme/v1/web/comment/post/
Body (form):
  aweme_id=VIDEO_ID
  text=评论内容
  csrf_token=TOKEN
Headers:
  Cookie: sessionid=xxx; ...
  Content-Type: application/x-www-form-urlencoded
```

### 2.6 mitmproxy Python 脚本（自动化抓包）

```python
# save_api.py — mitmproxy 自动保存特定 API 请求
# 使用: mitmdump -s save_api.py

from mitmproxy import http
import json
import time

TARGET_HOST = "www.douyin.com"
SAVE_DIR = "./captured_requests"

def response(flow: http.HTTPFlow):
    """每个响应完成后触发。"""
    if TARGET_HOST not in flow.request.pretty_url:
        return
    
    # 只保存 API 请求
    if "/aweme/" not in flow.request.pretty_url:
        return
    
    data = {
        "timestamp": time.time(),
        "method": flow.request.method,
        "url": flow.request.pretty_url,
        "request_headers": dict(flow.request.headers),
        "request_body": flow.request.get_text(),
        "response_status": flow.response.status_code,
        "response_body": flow.response.get_text()[:2000],  # 截断
    }
    
    filename = f"{SAVE_DIR}/{int(time.time()*1000)}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"[captured] {flow.request.method} {flow.request.pretty_url[:80]}")
```

### 2.7 API 逆向的一般流程

```
1. 手动操作目标网站（mitmproxy 抓包）
2. 观察请求序列（哪些请求在什么时机发出）
3. 识别关键参数（Cookie、Token、签名、时间戳）
4. 尝试用 httpx 复现请求
5. 对比响应（与浏览器的响应是否一致）
6. 处理差异（缺少的参数、签名算法、加密）
```

---

## 模块 3：Cookie/Token 管理

### 3.1 Cookie 持久化方案

#### 方案 1：JSON 文件存储

```python
import json
import time
from pathlib import Path
from typing import Optional


class CookieStore:
    """简单的 JSON 文件 Cookie 存储。"""
    
    def __init__(self, storage_path: str = "./cookies.json"):
        self.path = Path(storage_path)
        self._cookies: dict[str, dict] = self._load()
    
    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {}
    
    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._cookies, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    
    def save_cookies(self, domain: str, cookies: list[dict]):
        """保存某个域名的 Cookie 列表。"""
        self._cookies[domain] = {
            "cookies": cookies,
            "saved_at": time.time(),
        }
        self._save()
    
    def load_cookies(self, domain: str) -> Optional[list[dict]]:
        """加载某个域名的 Cookie。"""
        entry = self._cookies.get(domain)
        if entry:
            return entry["cookies"]
        return None
    
    def is_expired(self, domain: str, max_age_seconds: float = 86400) -> bool:
        """检查 Cookie 是否过期。"""
        entry = self._cookies.get(domain)
        if not entry:
            return True
        return (time.time() - entry["saved_at"]) > max_age_seconds
    
    def clear(self, domain: Optional[str] = None):
        """清除 Cookie。"""
        if domain:
            self._cookies.pop(domain, None)
        else:
            self._cookies.clear()
        self._save()


# 使用示例
store = CookieStore("./douyin_cookies.json")

# 从浏览器导出后保存
browser_cookies = [
    {"name": "sessionid", "value": "abc123", "domain": ".douyin.com"},
    {"name": "ttwid", "value": "xyz789", "domain": ".douyin.com"},
]
store.save_cookies("www.douyin.com", browser_cookies)

# 下次加载
cookies = store.load_cookies("www.douyin.com")
```

#### 方案 2：httpx Client 集成

```python
import httpx


def create_client_with_cookies(cookies: list[dict], headers: dict = None) -> httpx.Client:
    """从 Cookie 列表创建 httpx Client。"""
    cookie_dict = {c["name"]: c["value"] for c in cookies}
    
    default_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if headers:
        default_headers.update(headers)
    
    return httpx.Client(
        cookies=cookie_dict,
        headers=default_headers,
        timeout=httpx.Timeout(connect=5.0, read=30.0),
        follow_redirects=True,
    )


# 使用
cookies = [
    {"name": "sessionid", "value": "abc123"},
    {"name": "ttwid", "value": "xyz789"},
]
client = create_client_with_cookies(cookies)
resp = client.get("https://httpbin.org/cookies")
print(resp.json())  # 自动携带 Cookie
```

### 3.2 Token 管理（OAuth2 refresh_token 流程）

很多平台用 OAuth2 的 access_token + refresh_token 模式：

```
access_token  — 有效期短（1-2小时），用于 API 认证
refresh_token — 有效期长（30天），用于刷新 access_token
```

```python
import time
import httpx


class TokenManager:
    """OAuth2 Token 管理器。
    
    自动处理 access_token 过期和 refresh_token 刷新。
    """
    
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_url: str,
        refresh_token: str = None,
        access_token: str = None,
        token_expire_at: float = 0,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = token_url
        self._refresh_token = refresh_token
        self._access_token = access_token
        self._token_expire_at = token_expire_at  # Unix 时间戳
    
    @property
    def is_expired(self) -> bool:
        """Token 是否已过期（提前 60 秒判断）。"""
        return time.time() > (self._token_expire_at - 60)
    
    @property
    def access_token(self) -> str:
        """获取 access_token，过期自动刷新。"""
        if self.is_expired:
            self._refresh()
        return self._access_token
    
    def _refresh(self):
        """用 refresh_token 刷新 access_token。"""
        if not self._refresh_token:
            raise RuntimeError("无 refresh_token，无法刷新")
        
        resp = httpx.post(
            self.token_url,
            data={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self._refresh_token,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        
        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token", self._refresh_token)
        self._token_expire_at = time.time() + data.get("expires_in", 3600)
        
        print(f"Token 已刷新，有效期至 {self._token_expire_at}")
    
    def get_auth_header(self) -> dict:
        """获取 Authorization 请求头。"""
        return {"Authorization": f"Bearer {self.access_token}"}


# 使用示例
tm = TokenManager(
    client_id="your_client_id",
    client_secret="your_client_secret",
    token_url="https://api.example.com/oauth/token",
    refresh_token="initial_refresh_token",
)

# 自动带 Authorization 头请求
headers = tm.get_auth_header()
resp = httpx.get("https://api.example.com/me", headers=headers)
```

### 3.3 Cookie + Token 组合管理

```python
import json
import time
from pathlib import Path
from typing import Optional
import httpx


class SessionManager:
    """统一的会话管理器：Cookie + Token + httpx Client。"""
    
    def __init__(self, storage_path: str = "./session_data.json"):
        self.path = Path(storage_path)
        self._data = self._load()
    
    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {}
    
    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    
    def save_session(
        self,
        name: str,
        cookies: list[dict],
        headers: dict = None,
        extra: dict = None,
    ):
        """保存完整会话。"""
        self._data[name] = {
            "cookies": cookies,
            "headers": headers or {},
            "extra": extra or {},
            "saved_at": time.time(),
        }
        self._save()
    
    def create_client(
        self,
        name: str,
        extra_headers: dict = None,
    ) -> Optional[httpx.Client]:
        """从保存的会话创建 httpx Client。"""
        session = self._data.get(name)
        if not session:
            return None
        
        cookies = {c["name"]: c["value"] for c in session["cookies"]}
        headers = {**session.get("headers", {}), **(extra_headers or {})}
        
        return httpx.Client(
            cookies=cookies,
            headers=headers,
            timeout=httpx.Timeout(connect=5.0, read=30.0),
            follow_redirects=True,
        )
    
    def is_valid(self, name: str, max_age: float = 86400) -> bool:
        """检查会话是否在有效期内。"""
        session = self._data.get(name)
        if not session:
            return False
        return (time.time() - session["saved_at"]) < max_age


# === 使用示例 ===
sm = SessionManager("./douyin_session.json")

# 保存从浏览器导出的会话
sm.save_session(
    name="douyin_account_1",
    cookies=[
        {"name": "sessionid", "value": "abc123", "domain": ".douyin.com"},
        {"name": "ttwid", "value": "xyz789", "domain": ".douyin.com"},
    ],
    headers={"Referer": "https://www.douyin.com/"},
)

# 创建 client 发起请求
client = sm.create_client("douyin_account_1")
if client:
    resp = client.get("https://httpbin.org/cookies")
    print(resp.json())
```

---

## 模块 4：实战练习 — GitHub API

### 4.1 项目目标

用 httpx 实现完整的 GitHub API 调用流程，包含：
- 认证（Personal Access Token）
- 请求（用户信息、仓库列表、Issues）
- 错误处理（401/403/404/429）
- 重试（指数退避）
- 日志记录

### 4.2 完整代码

```python
"""
GitHub API 客户端 — httpx 实战练习

功能：
- 认证（Bearer Token）
- 获取用户信息
- 获取仓库列表
- 获取仓库 Issues
- 自动重试（指数退避）
- 请求日志
"""

import httpx
import asyncio
import logging
import time
from typing import Optional

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


class GitHubClient:
    """GitHub API 客户端。"""
    
    BASE_URL = "https://api.github.com"
    
    def __init__(
        self,
        token: Optional[str] = None,
        max_retries: int = 3,
        timeout: float = 30.0,
    ):
        """
        Args:
            token: GitHub Personal Access Token（可选，无 token 则匿名访问，有速率限制）
            max_retries: 最大重试次数
            timeout: 请求超时秒数
        """
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "SuperClaw-GitHub-Client/1.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers=headers,
            timeout=httpx.Timeout(connect=5.0, read=timeout, write=5.0, pool=5.0),
            follow_redirects=True,
        )
        self._max_retries = max_retries
        self._request_count = 0
        self._error_count = 0
    
    async def close(self):
        """关闭客户端。"""
        await self._client.aclose()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *args):
        await self.close()
    
    async def _request(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> dict:
        """带重试和错误处理的请求方法。"""
        last_error = None
        
        for attempt in range(1, self._max_retries + 1):
            try:
                self._request_count += 1
                logger.info(f"[{attempt}/{self._max_retries}] {method} {path}")
                
                resp = await self._client.request(method, path, **kwargs)
                
                # 记录速率限制信息
                remaining = resp.headers.get("X-RateLimit-Remaining")
                if remaining is not None:
                    logger.info(f"速率限制剩余: {remaining}")
                
                # 处理 429 限流
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 60))
                    logger.warning(f"被限流，等待 {retry_after}s 后重试")
                    await asyncio.sleep(retry_after)
                    continue
                
                resp.raise_for_status()
                return resp.json()
            
            except httpx.TimeoutException as e:
                last_error = e
                logger.warning(f"请求超时: {e}")
            
            except httpx.HTTPStatusError as e:
                last_error = e
                status = e.response.status_code
                
                if status == 401:
                    logger.error("认证失败，请检查 Token")
                    raise
                elif status == 403:
                    logger.error("权限不足")
                    raise
                elif status == 404:
                    logger.warning(f"资源不存在: {path}")
                    return {"error": "not_found", "path": path}
                else:
                    logger.warning(f"HTTP {status}: {e}")
            
            except httpx.RequestError as e:
                last_error = e
                logger.warning(f"请求错误: {e}")
            
            # 指数退避
            if attempt < self._max_retries:
                wait = 2 ** attempt
                logger.info(f"等待 {wait}s 后重试...")
                await asyncio.sleep(wait)
        
        self._error_count += 1
        raise RuntimeError(f"请求失败 ({self._max_retries} 次重试): {last_error}")
    
    # ===== 公共 API =====
    
    async def get_user(self, username: str) -> dict:
        """获取用户信息。"""
        return await self._request("GET", f"/users/{username}")
    
    async def get_current_user(self) -> dict:
        """获取当前认证用户信息。"""
        return await self._request("GET", "/user")
    
    async def get_repos(
        self,
        username: str,
        per_page: int = 10,
        sort: str = "updated",
    ) -> list[dict]:
        """获取用户的仓库列表。"""
        return await self._request(
            "GET",
            f"/users/{username}/repos",
            params={"per_page": per_page, "sort": sort},
        )
    
    async def get_issues(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        per_page: int = 10,
    ) -> list[dict]:
        """获取仓库的 Issues。"""
        return await self._request(
            "GET",
            f"/repos/{owner}/{repo}/issues",
            params={"state": state, "per_page": per_page},
        )
    
    async def search_repos(
        self,
        query: str,
        per_page: int = 10,
    ) -> dict:
        """搜索仓库。"""
        return await self._request(
            "GET",
            "/search/repositories",
            params={"q": query, "per_page": per_page},
        )
    
    def stats(self) -> dict:
        """请求统计。"""
        return {
            "total_requests": self._request_count,
            "errors": self._error_count,
        }


# ===== 主程序 =====

async def main():
    """GitHub API 客户端实战演示。"""
    
    # 可选：设置 Token 提高速率限制（匿名 60 次/小时，认证 5000 次/小时）
    token = None  # 填入你的 GitHub Token
    
    async with GitHubClient(token=token) as gh:
        
        # 1. 获取用户信息
        print("\n=== 用户信息 ===")
        user = await gh.get_user("octocat")
        print(f"  用户名: {user['login']}")
        print(f"  公开仓库: {user['public_repos']}")
        print(f"  粉丝数: {user['followers']}")
        
        # 2. 获取仓库列表
        print("\n=== 最近更新的仓库 ===")
        repos = await gh.get_repos("octocat", per_page=5)
        for repo in repos:
            print(f"  {repo['name']}: {repo.get('description', '无描述')}")
        
        # 3. 获取 Issues
        print("\n=== 仓库 Issues ===")
        issues = await gh.get_issues("octocat", "Hello-World", per_page=3)
        for issue in issues:
            print(f"  #{issue['number']}: {issue['title']}")
        
        # 4. 搜索仓库
        print("\n=== 搜索 Python RPA 仓库 ===")
        results = await gh.search_repos("python rpa", per_page=3)
        for repo in results.get("items", []):
            print(f"  {repo['full_name']}: ⭐ {repo['stargazers_count']}")
        
        # 5. 统计
        print(f"\n=== 统计 ===")
        print(f"  {gh.stats()}")


if __name__ == "__main__":
    asyncio.run(main())
```

### 4.3 运行结果示例

```
=== 用户信息 ===
  用户名: octocat
  公开仓库: 8
  粉丝数: 30000+

=== 最近更新的仓库 ===
  Hello-World: My first repository on GitHub!
  Spoon-Knife: This repo is for demonstration purposes
  ...

=== 搜索 Python RPA 仓库 ===
  user/awesome-python-rpa: ⭐ 1234
  ...

=== 统计 ===
  {'total_requests': 5, 'errors': 0}
```

### 4.4 对 SuperClaw 的应用思考

1. **统一 HTTP 客户端**：SuperClaw 目前 `actions/builtin.py` 里每次请求都新建 client，应该改成复用 `httpx.AsyncClient`
2. **重试模式标准化**：指数退避 + 429 限流处理是通用模式，可以抽成公共中间件
3. **速率限制管理**：对于有严格限流的平台（如抖音），需要全局的速率控制器
4. **Session 管理**：Cookie/Token 持久化 + 自动刷新是多账号运营的基础

---

## 总结

### httpx 核心要点

| 要点 | 说明 |
|------|------|
| 用 AsyncClient | RPA 场景必须异步，不要用同步 API |
| 复用 Client | 连接池在 Client 级别复用，不要在循环里新建 |
| 四级超时 | connect/read/write/pool 分开控制 |
| 错误处理 | 区分 Timeout/HTTPStatus/RequestError，分别处理 |
| 重试策略 | 指数退避 + 429 Retry-After |

### 抓包分析要点

| 要点 | 说明 |
|------|------|
| 先观察再复现 | 手动操作时记录请求顺序和参数依赖 |
| 关注 Cookie 传递 | 很多接口需要先访问某个页面获取 Cookie |
| 识别签名参数 | 时间戳、hash、加密参数往往需要逆向 JS |
| mitmproxy 脚本 | 用 Python 脚本自动化保存和分析 |

### Cookie/Token 管理要点

| 要点 | 说明 |
|------|------|
| 持久化存储 | Cookie/Token 保存到文件，下次可复用 |
| 过期检测 | 每次使用前检查是否过期 |
| 自动刷新 | refresh_token 流程要自动处理 |
| 安全存储 | Token 不要明文写在代码里 |

---

<!-- TASK_COMPLETE: phase1_httpx -->
