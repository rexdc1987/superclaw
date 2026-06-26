"""
RPA HTTP 直连客户端 - 示例代码
赵云 RPA 第一阶段学习产出

功能：
1. Session 管理（Cookie 自动维护）
2. 反爬 Header 模拟
3. 异步并发请求
4. Cookie 从浏览器导入
5. 请求重试与超时控制
"""

from __future__ import annotations

import httpx
import asyncio
import time
import json
from typing import Optional, List
from dataclasses import dataclass, field


# ============================================================
# 1. 基础同步客户端
# ============================================================

class SyncHttpClient:
    """同步 HTTP 客户端 — 适合简单场景"""

    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
    }

    def __init__(self, base_url: str = "", cookies: Optional[dict] = None):
        self.base_url = base_url.rstrip("/")
        timeout = httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=5.0)
        self.client = httpx.Client(
            headers=self.DEFAULT_HEADERS,
            timeout=timeout,
            follow_redirects=True,
        )
        if cookies:
            self.client.cookies.update(cookies)

    def get(self, path: str, **kwargs) -> httpx.Response:
        url = f"{self.base_url}{path}"
        resp = self.client.get(url, **kwargs)
        resp.raise_for_status()
        return resp

    def post(self, path: str, **kwargs) -> httpx.Response:
        url = f"{self.base_url}{path}"
        resp = self.client.post(url, **kwargs)
        resp.raise_for_status()
        return resp

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ============================================================
# 2. 异步并发客户端（RPA 核心）
# ============================================================

class AsyncHttpClient:
    """异步 HTTP 客户端 — 高并发场景"""

    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
    }

    def __init__(self, cookies: Optional[dict] = None, max_concurrent: int = 5):
        timeout = httpx.Timeout(connect=5.0, read=30.0)
        self.client = httpx.AsyncClient(
            headers=self.DEFAULT_HEADERS,
            timeout=timeout,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=max_concurrent),
        )
        if cookies:
            self.client.cookies.update(cookies)

    async def get(self, path: str, **kwargs) -> httpx.Response:
        resp = await self.client.get(path, **kwargs)
        resp.raise_for_status()
        return resp

    async def post(self, path: str, **kwargs) -> httpx.Response:
        resp = await self.client.post(path, **kwargs)
        resp.raise_for_status()
        return resp

    async def fetch_all(self, urls: List[str]) -> List[httpx.Response]:
        """并发请求多个 URL"""
        tasks = [self.client.get(url) for url in urls]
        return await asyncio.gather(*tasks, return_exceptions=False)

    async def close(self):
        await self.client.aclose()


# ============================================================
# 3. 带重试的请求封装
# ============================================================

@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 1.0
    backoff_factor: float = 2.0
    retry_status_codes: List = field(default_factory=lambda: [429, 500, 502, 503, 504])


def retry_request(
    client: httpx.Client,
    method: str,
    url: str,
    config: RetryConfig = None,
    **kwargs,
) -> httpx.Response:
    """带指数退避重试的请求"""
    config = config or RetryConfig()
    last_exception = None

    for attempt in range(config.max_retries):
        try:
            resp = client.request(method, url, **kwargs)

            if resp.status_code not in config.retry_status_codes:
                return resp

            # 429 Too Many Requests: 尊重 Retry-After
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    delay = float(retry_after)
                else:
                    delay = config.base_delay * (config.backoff_factor ** attempt)
            else:
                delay = config.base_delay * (config.backoff_factor ** attempt)

            print(f"[重试] {attempt + 1}/{config.max_retries}, 等待 {delay:.1f}s, 状态码={resp.status_code}")
            time.sleep(delay)

        except (httpx.ConnectError, httpx.ReadTimeout) as e:
            last_exception = e
            delay = config.base_delay * (config.backoff_factor ** attempt)
            print(f"[重试] {attempt + 1}/{config.max_retries}, 连接错误: {e}, 等待 {delay:.1f}s")
            time.sleep(delay)

    raise last_exception or httpx.HTTPError("重试次数用尽")


# ============================================================
# 4. Cookie 管理工具
# ============================================================

def parse_cookie_string(cookie_str: str) -> dict:
    """从浏览器 DevTools 复制的 Cookie 字符串解析为 dict"""
    cookies = {}
    for item in cookie_str.split(";"):
        item = item.strip()
        if "=" in item:
            key, value = item.split("=", 1)
            cookies[key.strip()] = value.strip()
    return cookies


def load_cookies_from_json(filepath: str) -> dict:
    """从 JSON 文件加载 Cookie"""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def save_cookies_to_json(cookies: dict, filepath: str):
    """保存 Cookie 到 JSON 文件"""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2, ensure_ascii=False)


# ============================================================
# 5. 实战示例：模拟 API 调用
# ============================================================

def demo_basic_request():
    """基础请求演示"""
    print("=" * 50)
    print("演示1: 基础 GET 请求")
    print("=" * 50)

    with SyncHttpClient() as client:
        resp = client.get("https://httpbin.org/get")
        data = resp.json()
        print(f"状态码: {resp.status_code}")
        print(f"Origin: {data.get('origin')}")
        print(f"Cookies: {resp.cookies}")


def demo_session_cookie():
    """Session + Cookie 演示"""
    print("\n" + "=" * 50)
    print("演示2: Session Cookie 管理")
    print("=" * 50)

    with SyncHttpClient() as client:
        # 第一次请求设置 Cookie
        resp1 = client.get("https://httpbin.org/cookies/set?name=zhaoyun&role=executor")
        print(f"设置后 Cookie: {dict(client.client.cookies)}")

        # 第二次请求自动携带
        resp2 = client.get("https://httpbin.org/cookies")
        print(f"服务端收到: {resp2.json()}")


def demo_with_browser_cookies():
    """从浏览器导入 Cookie 演示"""
    print("\n" + "=" * 50)
    print("演示3: 使用浏览器 Cookie")
    print("=" * 50)

    # 模拟从浏览器复制的 Cookie
    cookie_str = "sessionid=abc123def456; ttwid=xyz789; __ac_nonce=0123456789"
    cookies = parse_cookie_string(cookie_str)
    print(f"解析后的 Cookie: {cookies}")

    with SyncHttpClient(cookies=cookies) as client:
        resp = client.get("https://httpbin.org/cookies")
        print(f"服务端收到: {resp.json()}")


def demo_retry():
    """重试机制演示"""
    print("\n" + "=" * 50)
    print("演示4: 请求重试（模拟失败）")
    print("=" * 50)

    with SyncHttpClient() as client:
        try:
            # httpbin 返回 500，会触发重试
            resp = retry_request(
                client.client,
                "GET",
                "https://httpbin.org/status/500",
                config=RetryConfig(max_retries=2, base_delay=0.5),
            )
        except Exception as e:
            print(f"最终失败（预期行为）: {type(e).__name__}")


def demo_concurrent():
    """异步并发演示"""
    print("\n" + "=" * 50)
    print("演示5: 异步并发请求")
    print("=" * 50)

    async def run():
        async with httpx.AsyncClient() as client:
            urls = [
                "https://httpbin.org/get",
                "https://httpbin.org/delay/1",
                "https://httpbin.org/get",
            ]
            start = time.time()
            tasks = [client.get(url) for url in urls]
            results = await asyncio.gather(*tasks)
            elapsed = time.time() - start

            print(f"并发请求 {len(urls)} 个 URL，耗时: {elapsed:.2f}s")
            for i, r in enumerate(results):
                print(f"  [{i}] 状态码={r.status_code}")

    asyncio.run(run())


def demo_post_json():
    """POST JSON 请求演示"""
    print("\n" + "=" * 50)
    print("演示6: POST JSON 数据")
    print("=" * 50)

    with SyncHttpClient() as client:
        payload = {
            "aweme_id": "demo_video_id",
            "text": "赵云测试评论 - HTTP直连",
            "csrf_token": "fake_token_123",
        }
        resp = client.post("https://httpbin.org/post", json=payload)
        data = resp.json()
        print(f"状态码: {resp.status_code}")
        print(f"收到的 JSON Body: {data.get('json')}")


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    print("⚔️  赵云 RPA - HTTP 直连客户端演示\n")
    demo_basic_request()
    demo_session_cookie()
    demo_with_browser_cookies()
    demo_retry()
    demo_concurrent()
    demo_post_json()
    print("\n✅ 所有演示完成")
