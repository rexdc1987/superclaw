"""重试策略模块 — 指数退避、限流感知、可配置策略。

使用方式:
    policy = RetryPolicy(max_retries=3, backoff=ExponentialBackoff(base=1.0, max=30.0))
    async with policy:
        resp = await client.get(url)
"""
import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Optional, Tuple, Type

import httpx

logger = logging.getLogger(__name__)


@dataclass
class ExponentialBackoff:
    """指数退避算法。

    wait_time = min(base * 2^attempt + jitter, max_delay)

    Attributes:
        base: 基础延迟秒数
        max_delay: 最大延迟秒数
        jitter: 随机抖动范围 (0, jitter)
    """
    base: float = 1.0
    max_delay: float = 60.0
    jitter: float = 0.5

    def delay(self, attempt: int) -> float:
        """计算第 N 次重试的等待时间。"""
        wait = self.base * (2 ** attempt)
        wait = min(wait, self.max_delay)
        wait += random.uniform(0, self.jitter)
        return wait


@dataclass
class RetryPolicy:
    """重试策略配置。

    Attributes:
        max_retries: 最大重试次数（不含首次请求）
        backoff: 退避算法实例
        retryable_status_codes: 可重试的 HTTP 状态码
        retryable_exceptions: 可重试的异常类型
        respect_retry_after: 是否尊重 Retry-After 响应头
    """
    max_retries: int = 3
    backoff: ExponentialBackoff = field(default_factory=ExponentialBackoff)
    retryable_status_codes: Tuple[int, ...] = (429, 500, 502, 503, 504)
    retryable_exceptions: Tuple[Type[Exception], ...] = (
        httpx.TimeoutException,
        httpx.ConnectError,
        httpx.RemoteProtocolError,
    )
    respect_retry_after: bool = True

    def should_retry(self, attempt: int, exception: Optional[Exception] = None,
                     status_code: Optional[int] = None) -> bool:
        """判断是否应该重试。

        Args:
            attempt: 当前已尝试次数（从 0 开始）
            exception: 请求异常（如有）
            status_code: HTTP 状态码（如有）

        Returns:
            True 表示应该重试
        """
        if attempt >= self.max_retries:
            return False

        if exception and isinstance(exception, self.retryable_exceptions):
            return True

        if status_code and status_code in self.retryable_status_codes:
            return True

        return False

    def get_wait_time(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """获取重试等待时间。

        Args:
            attempt: 当前重试次数（从 0 开始）
            retry_after: 服务器返回的 Retry-After 值（秒）

        Returns:
            等待秒数
        """
        if self.respect_retry_after and retry_after is not None and retry_after > 0:
            return min(retry_after, self.max_delay if hasattr(self, 'max_delay') else 60.0)
        return self.backoff.delay(attempt)

    @staticmethod
    def parse_retry_after(response: httpx.Response) -> Optional[float]:
        """从响应头解析 Retry-After 值。"""
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return None
        try:
            return float(retry_after)
        except ValueError:
            return None


class RetryExecutor:
    """重试执行器 — 封装重试逻辑。

    使用方式:
        executor = RetryExecutor(policy=RetryPolicy(max_retries=3))
        result = await executor.execute(lambda: client.get(url))
    """

    def __init__(self, policy: Optional[RetryPolicy] = None):
        self.policy = policy or RetryPolicy()

    async def execute(self, func, *args, **kwargs):
        """执行函数并自动重试。

        Args:
            func: 异步可调用对象（如 client.get）

        Returns:
            函数返回值

        Raises:
            最后一次重试仍失败时抛出原始异常
        """
        last_exception = None

        for attempt in range(self.policy.max_retries + 1):
            try:
                result = await func(*args, **kwargs)

                # 检查 HTTP 状态码
                if isinstance(result, httpx.Response):
                    if self.policy.should_retry(attempt, status_code=result.status_code):
                        retry_after = RetryPolicy.parse_retry_after(result)
                        wait = self.policy.get_wait_time(attempt, retry_after)
                        logger.warning(
                            "请求返回 %d，第 %d/%d 次重试，等待 %.1fs",
                            result.status_code, attempt + 1, self.policy.max_retries, wait,
                        )
                        await asyncio.sleep(wait)
                        continue
                    result.raise_for_status()

                return result

            except Exception as e:
                last_exception = e
                if self.policy.should_retry(attempt, exception=e):
                    wait = self.policy.get_wait_time(attempt)
                    logger.warning(
                        "请求异常: %s，第 %d/%d 次重试，等待 %.1fs",
                        type(e).__name__, attempt + 1, self.policy.max_retries, wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    raise

        # 不应到达此处，但作为安全网
        if last_exception:
            raise last_exception
