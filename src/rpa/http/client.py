"""生产级 HTTP 客户端 — httpx 封装、自动重试、连接池、日志。

使用方式:
    async with HttpClient() as client:
        resp = await client.get("https://api.example.com/data")
        data = resp.json()

    # 带配置
    client = HttpClient(
        base_url="https://api.example.com",
        headers={"Authorization": "Bearer xxx"},
        retry=RetryPolicy(max_retries=3),
    )
"""
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import httpx

from .retry import RetryExecutor, RetryPolicy

logger = logging.getLogger(__name__)


class HttpClient:
    """SuperClaw 生产级 HTTP 客户端。

    封装 httpx.AsyncClient，提供：
    - 统一的 get/post/put/delete 方法
    - 自动重试（指数退避 + 429 限流感知）
    - 分级超时配置
    - 连接池管理（复用 AsyncClient）
    - 请求/响应日志

    Attributes:
        base_url: 基础 URL
        default_headers: 默认请求头
        retry_policy: 重试策略
    """

    def __init__(
        self,
        base_url: str = "",
        headers: Optional[Dict[str, str]] = None,
        cookies: Optional[Dict[str, str]] = None,
        timeout: Optional[httpx.Timeout] = None,
        retry: Optional[RetryPolicy] = None,
        follow_redirects: bool = True,
        verify: bool = True,
        proxy: Optional[str] = None,
        http2: bool = False,
    ):
        """初始化 HTTP 客户端。

        Args:
            base_url: 基础 URL，所有请求路径会拼接在此之后
            headers: 默认请求头
            cookies: 默认 Cookie
            timeout: 超时配置（默认 connect=5s, read=30s, write=5s, pool=5s）
            retry: 重试策略（默认 3 次重试）
            follow_redirects: 是否跟随重定向
            verify: 是否验证 SSL 证书
            proxy: 代理地址（如 http://127.0.0.1:7890）
            http2: 是否启用 HTTP/2
        """
        self.base_url = base_url
        self.default_headers = headers or {}
        self.default_cookies = cookies or {}
        self.retry_policy = retry or RetryPolicy()
        self._follow_redirects = follow_redirects
        self._verify = verify
        self._proxy = proxy
        self._http2 = http2

        if timeout is None:
            self._timeout = httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=5.0)
        else:
            self._timeout = timeout

        self._client = None  # type: Optional[httpx.AsyncClient]
        self._retry_executor = RetryExecutor(self.retry_policy)
        self._request_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0

    async def _ensure_client(self) -> httpx.AsyncClient:
        """确保底层 httpx.AsyncClient 已创建。"""
        if self._client is None or self._client.is_closed:
            transport_kwargs = {}
            if self._proxy:
                transport_kwargs["proxy"] = self._proxy

            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self.default_headers,
                cookies=self.default_cookies,
                timeout=self._timeout,
                follow_redirects=self._follow_redirects,
                verify=self._verify,
                http2=self._http2,
                limits=httpx.Limits(
                    max_connections=100,
                    max_keepalive_connections=20,
                    keepalive_expiry=30,
                ),
                **transport_kwargs,
            )
            logger.debug("HTTP 客户端已创建: base_url=%s", self.base_url)
        return self._client

    async def close(self):
        """关闭客户端，释放连接池。"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            logger.debug("HTTP 客户端已关闭")

    async def __aenter__(self):
        await self._ensure_client()
        return self

    async def __aexit__(self, *args):
        await self.close()

    # ================================================================
    # 核心请求方法
    # ================================================================

    async def request(
        self,
        method: str,
        url: str,
        *,
        params=None,
        json: Any = None,
        data: Any = None,
        headers=None,
        cookies=None,
        content=None,
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        """发送 HTTP 请求（带自动重试）。

        Args:
            method: HTTP 方法（GET/POST/PUT/DELETE 等）
            url: 请求 URL（相对路径或完整 URL）
            params: 查询参数
            json: JSON 请求体
            data: 表单数据
            headers: 额外请求头（与默认头合并）
            cookies: 额外 Cookie
            content: 原始字节请求体
            timeout: 单次请求超时覆盖（秒）

        Returns:
            httpx.Response 对象
        """
        client = await self._ensure_client()
        self._request_count += 1

        # 合并请求头
        merged_headers = dict(self.default_headers)
        if headers:
            merged_headers.update(headers)

        merged_cookies = dict(self.default_cookies)
        if cookies:
            merged_cookies.update(cookies)

        # 单次请求超时覆盖
        request_kwargs = {
            "method": method,
            "url": url,
            "headers": merged_headers if merged_headers else None,
            "cookies": merged_cookies if merged_cookies else None,
            "params": params,
            "json": json,
            "data": data,
            "content": content,
        }
        if timeout is not None:
            request_kwargs["timeout"] = timeout

        t0 = time.monotonic()

        async def _do_request(**kwargs):
            return await client.request(**kwargs)

        try:
            response = await self._retry_executor.execute(_do_request, **request_kwargs)
            elapsed = (time.monotonic() - t0) * 1000
            self._total_latency_ms += elapsed

            logger.info(
                "%s %s -> %d (%.0fms)",
                method, url[:80], response.status_code, elapsed,
            )
            return response

        except Exception as e:
            self._error_count += 1
            elapsed = (time.monotonic() - t0) * 1000
            logger.error(
                "%s %s -> FAILED (%.0fms): %s",
                method, url[:80], elapsed, type(e).__name__,
            )
            raise

    # ================================================================
    # 便捷方法
    # ================================================================

    async def get(self, url: str, **kwargs) -> httpx.Response:
        """GET 请求。"""
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> httpx.Response:
        """POST 请求。"""
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs) -> httpx.Response:
        """PUT 请求。"""
        return await self.request("PUT", url, **kwargs)

    async def patch(self, url: str, **kwargs) -> httpx.Response:
        """PATCH 请求。"""
        return await self.request("PATCH", url, **kwargs)

    async def delete(self, url: str, **kwargs) -> httpx.Response:
        """DELETE 请求。"""
        return await self.request("DELETE", url, **kwargs)

    # ================================================================
    # 高级功能
    # ================================================================

    @asynccontextmanager
    async def stream(self, method: str, url: str, **kwargs):
        """流式请求上下文管理器。

        用法:
            async with client.stream("GET", url) as resp:
                async for chunk in resp.aiter_bytes():
                    process(chunk)
        """
        client = await self._ensure_client()
        async with client.stream(method, url, **kwargs) as resp:
            yield resp

    def stats(self) -> dict:
        """获取请求统计。"""
        avg_latency = (
            self._total_latency_ms / self._request_count
            if self._request_count > 0
            else 0
        )
        return {
            "total_requests": self._request_count,
            "errors": self._error_count,
            "success_rate": (
                "{:.1%}".format(
                    (self._request_count - self._error_count) / self._request_count
                )
                if self._request_count > 0
                else "N/A"
            ),
            "avg_latency_ms": round(avg_latency, 1),
            "total_latency_ms": round(self._total_latency_ms, 1),
        }

    def reset_stats(self):
        """重置统计计数器。"""
        self._request_count = 0
        self._error_count = 0
        self._total_latency_ms = 0.0
