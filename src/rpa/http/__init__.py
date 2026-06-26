"""SuperClaw HTTP 客户端模块。

提供生产级 httpx 封装：自动重试、连接池管理、请求日志、中间件链。
"""
from .client import HttpClient
from .retry import RetryPolicy, ExponentialBackoff
from .middleware import (
    MiddlewareChain,
    Middleware,
    UARotator,
    PlatformHeaders,
    RateLimiter,
    RequestLogger,
)

__all__ = [
    "HttpClient",
    "RetryPolicy",
    "ExponentialBackoff",
    "MiddlewareChain",
    "Middleware",
    "UARotator",
    "PlatformHeaders",
    "RateLimiter",
    "RequestLogger",
]
