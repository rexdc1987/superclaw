"""HTTP 中间件链 — UA 轮换、平台头注入、账号级限流、请求日志。

使用方式:
    from rpa.http.middleware import MiddlewareChain, UARotator, PlatformHeaders, RateLimiter

    chain = MiddlewareChain()
    chain.add(UARotator())
    chain.add(PlatformHeaders(platform="douyin"))
    chain.add(RateLimiter(max_per_minute=30))

    # 在 HttpClient.request() 前调用
    headers, cookies = await chain.process_request(account_id="acc1", url="https://...")
"""

import asyncio
import logging
import random
import time
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# UA 池
# ============================================================

USER_AGENTS = [
    # Chrome Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Chrome Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    # Firefox
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:126.0) Gecko/20100101 Firefox/126.0",
    # Edge
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
]


# ============================================================
# 中间件基类
# ============================================================

class Middleware(ABC):
    """HTTP 中间件基类"""

    @abstractmethod
    async def process_request(
        self,
        account_id: str,
        url: str,
        method: str,
        headers: Dict[str, str],
        cookies: Dict[str, str],
    ) -> Tuple[Dict[str, str], Dict[str, str]]:
        """处理请求，返回修改后的 (headers, cookies)

        Args:
            account_id: 账号 ID
            url: 请求 URL
            method: HTTP 方法
            headers: 请求头（可修改）
            cookies: Cookie（可修改）

        Returns:
            (修改后的 headers, 修改后的 cookies)
        """
        ...

    async def process_response(
        self,
        account_id: str,
        url: str,
        status_code: int,
        headers: Dict[str, str],
    ) -> None:
        """处理响应（可选覆写，用于统计/日志）"""
        pass


# ============================================================
# UA 轮换中间件
# ============================================================

class UARotator(Middleware):
    """自动轮换 User-Agent

    每次请求随机选择一个 UA，避免固定 UA 被检测。
    支持 per-account 绑定（同一账号始终用同一 UA）。
    """

    def __init__(
        self,
        user_agents: Optional[List[str]] = None,
        bind_to_account: bool = False,
    ):
        """
        Args:
            user_agents: 自定义 UA 列表，None 则使用内置池
            bind_to_account: 是否绑定账号（同一账号始终用同一 UA）
        """
        self._ua_pool = user_agents or USER_AGENTS
        self._bind_to_account = bind_to_account
        self._account_ua: Dict[str, str] = {}

    async def process_request(
        self, account_id, url, method, headers, cookies
    ):
        if self._bind_to_account:
            if account_id not in self._account_ua:
                self._account_ua[account_id] = random.choice(self._ua_pool)
            ua = self._account_ua[account_id]
        else:
            ua = random.choice(self._ua_pool)

        headers["User-Agent"] = ua
        return headers, cookies


# ============================================================
# 平台头注入中间件
# ============================================================

# 各平台的默认请求头
PLATFORM_HEADERS: Dict[str, Dict[str, str]] = {
    "douyin": {
        "Referer": "https://www.douyin.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Sec-Ch-Ua": '"Chromium";v="125", "Not.A/Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    },
    "weibo": {
        "Referer": "https://weibo.com/",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
    },
    "xiaohongshu": {
        "Referer": "https://www.xiaohongshu.com/",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.xiaohongshu.com",
    },
    "bilibili": {
        "Referer": "https://www.bilibili.com/",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.bilibili.com",
    },
}


class PlatformHeaders(Middleware):
    """注入平台特定的请求头"""

    def __init__(self, platform: str = "", extra_headers: Optional[Dict[str, str]] = None):
        """
        Args:
            platform: 平台名称（douyin/weibo/xiaohongshu/bilibili）
            extra_headers: 额外的固定请求头
        """
        self._platform = platform.lower()
        self._extra = extra_headers or {}

    async def process_request(
        self, account_id, url, method, headers, cookies
    ):
        # 注入平台默认头
        if self._platform in PLATFORM_HEADERS:
            for k, v in PLATFORM_HEADERS[self._platform].items():
                if k not in headers:
                    headers[k] = v

        # 注入额外头
        headers.update(self._extra)

        return headers, cookies


# ============================================================
# 账号级限流中间件
# ============================================================

class RateLimiter(Middleware):
    """令牌桶限流器（per-account）

    每个账号独立限流，防止单个账号请求过快被封。
    """

    def __init__(
        self,
        max_per_minute: int = 30,
        max_per_second: float = 2.0,
    ):
        """
        Args:
            max_per_minute: 每分钟最大请求数
            max_per_second: 每秒最大请求数（防突发）
        """
        self._max_per_minute = max_per_minute
        self._max_per_second = max_per_second
        # per-account 令牌桶状态
        self._buckets: Dict[str, Dict] = {}

    def _get_bucket(self, account_id: str) -> Dict:
        if account_id not in self._buckets:
            self._buckets[account_id] = {
                "tokens": self._max_per_minute,
                "last_refill": time.time(),
                "second_tokens": self._max_per_second,
                "last_second_refill": time.time(),
            }
        return self._buckets[account_id]

    async def process_request(
        self, account_id, url, method, headers, cookies
    ):
        bucket = self._get_bucket(account_id)
        now = time.time()

        # 补充分钟级令牌
        elapsed_min = now - bucket["last_refill"]
        bucket["tokens"] = min(
            self._max_per_minute,
            bucket["tokens"] + elapsed_min * (self._max_per_minute / 60.0),
        )
        bucket["last_refill"] = now

        # 补充秒级令牌
        elapsed_sec = now - bucket["last_second_refill"]
        bucket["second_tokens"] = min(
            self._max_per_second,
            bucket["second_tokens"] + elapsed_sec * self._max_per_second,
        )
        bucket["last_second_refill"] = now

        # 检查令牌
        if bucket["tokens"] < 1:
            wait = (1 - bucket["tokens"]) * (60.0 / self._max_per_minute)
            logger.warning("Rate limit hit for %s, waiting %.1fs", account_id, wait)
            await asyncio.sleep(wait)
            bucket["tokens"] = 0
        else:
            bucket["tokens"] -= 1

        if bucket["second_tokens"] < 1:
            await asyncio.sleep(0.5)
            bucket["second_tokens"] = 0
        else:
            bucket["second_tokens"] -= 1

        return headers, cookies


# ============================================================
# 请求日志中间件
# ============================================================

class RequestLogger(Middleware):
    """记录每个账号的请求日志"""

    def __init__(self, log_level: str = "INFO"):
        self._level = getattr(logging, log_level.upper(), logging.INFO)
        self._stats: Dict[str, Dict] = {}

    async def process_request(
        self, account_id, url, method, headers, cookies
    ):
        logger.log(
            self._level,
            "[%s] %s %s", account_id, method, url[:80],
        )
        return headers, cookies

    async def process_response(
        self, account_id, url, status_code, headers
    ):
        if account_id not in self._stats:
            self._stats[account_id] = {"requests": 0, "errors": 0}
        self._stats[account_id]["requests"] += 1
        if status_code >= 400:
            self._stats[account_id]["errors"] += 1

        logger.log(
            self._level,
            "[%s] <- %d %s", account_id, status_code, url[:60],
        )

    def get_stats(self) -> Dict:
        return dict(self._stats)


# ============================================================
# 中间件链
# ============================================================

class MiddlewareChain:
    """中间件链 — 按顺序执行所有中间件

    使用方式:
        chain = MiddlewareChain()
        chain.add(UARotator())
        chain.add(PlatformHeaders("douyin"))
        chain.add(RateLimiter(max_per_minute=30))
        chain.add(RequestLogger())

        headers, cookies = await chain.process_request(
            account_id="acc1",
            url="https://api.douyin.com/...",
            method="GET",
            headers={},
            cookies={},
        )
    """

    def __init__(self):
        self._middlewares: List[Middleware] = []

    def add(self, middleware: Middleware) -> "MiddlewareChain":
        """添加中间件（按添加顺序执行）"""
        self._middlewares.append(middleware)
        return self  # 支持链式调用

    async def process_request(
        self,
        account_id: str,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        cookies: Optional[Dict[str, str]] = None,
    ) -> Tuple[Dict[str, str], Dict[str, str]]:
        """执行所有中间件的请求处理

        Returns:
            (最终 headers, 最终 cookies)
        """
        h = dict(headers or {})
        c = dict(cookies or {})

        for mw in self._middlewares:
            h, c = await mw.process_request(account_id, url, method, h, c)

        return h, c

    async def process_response(
        self,
        account_id: str,
        url: str,
        status_code: int,
        response_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """执行所有中间件的响应处理"""
        rh = dict(response_headers or {})
        for mw in self._middlewares:
            await mw.process_response(account_id, url, status_code, rh)

    def clear(self) -> None:
        """清空中间件链"""
        self._middlewares.clear()

    @property
    def count(self) -> int:
        return len(self._middlewares)
