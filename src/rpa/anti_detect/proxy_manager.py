"""Proxy pool manager - health check, rotation, multi-protocol support."""
from __future__ import annotations
import asyncio
import time
import random
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from enum import Enum


class ProxyProtocol(Enum):
    HTTP = "http"
    SOCKS5 = "socks5"


@dataclass
class Proxy:
    """Represents a single proxy server."""
    host: str
    port: int
    protocol: ProxyProtocol = ProxyProtocol.HTTP
    username: Optional[str] = None
    password: Optional[str] = None
    # Health tracking
    is_healthy: bool = True
    last_check: float = 0.0
    response_time_ms: float = 0.0
    fail_count: int = 0
    success_count: int = 0
    weight: float = 1.0

    @property
    def url(self) -> str:
        """Return the proxy URL string."""
        if self.username and self.password:
            return f"{self.protocol.value}://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"{self.protocol.value}://{self.host}:{self.port}"

    @property
    def server(self) -> str:
        """Return the server address (for Playwright)."""
        return f"{self.protocol.value}://{self.host}:{self.port}"


class ProxyManager:
    """Manage a pool of proxies with health checks and rotation."""

    def __init__(
        self,
        health_check_url: str = "https://httpbin.org/ip",
        max_fails: int = 3,
        check_interval: float = 300.0,
    ):
        self._proxies: List[Proxy] = []
        self._current_index: int = 0
        self._health_check_url = health_check_url
        self._max_fails = max_fails
        self._check_interval = check_interval

    def add_proxy(self, proxy: Proxy) -> None:
        """Add a proxy to the pool."""
        self._proxies.append(proxy)

    def add_proxies(self, proxies: List[Proxy]) -> None:
        """Add multiple proxies to the pool."""
        self._proxies.extend(proxies)

    def remove_proxy(self, host: str, port: int) -> bool:
        """Remove a proxy by host:port. Returns True if found."""
        for i, p in enumerate(self._proxies):
            if p.host == host and p.port == port:
                self._proxies.pop(i)
                return True
        return False

    @property
    def pool_size(self) -> int:
        return len(self._proxies)

    @property
    def healthy_count(self) -> int:
        return sum(1 for p in self._proxies if p.is_healthy)

    def get_proxy(self) -> Optional[Proxy]:
        """Get next proxy using weighted round-robin.

        Prefers healthy proxies with lower response time.
        """
        healthy = [p for p in self._proxies if p.is_healthy]
        if not healthy:
            # Fall back to any proxy if none are healthy
            healthy = self._proxies
        if not healthy:
            return None

        # Weighted random selection (lower response time = higher weight)
        weights = []
        for p in healthy:
            w = p.weight
            if p.response_time_ms > 0:
                w *= 1000.0 / p.response_time_ms
            weights.append(max(0.1, w))

        return random.choices(healthy, weights=weights, k=1)[0]

    def get_random_proxy(self) -> Optional[Proxy]:
        """Get a completely random proxy (no weighting)."""
        healthy = [p for p in self._proxies if p.is_healthy]
        if not healthy:
            healthy = self._proxies
        return random.choice(healthy) if healthy else None

    async def check_health(self, proxy: Proxy, timeout: float = 10.0) -> bool:
        """Check if a proxy is working by making a test request.

        Args:
            proxy: Proxy to check.
            timeout: Request timeout in seconds.

        Returns:
            True if proxy is reachable and working.
        """
        import aiohttp

        start = time.monotonic()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self._health_check_url,
                    proxy=proxy.url,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    if resp.status == 200:
                        elapsed = (time.monotonic() - start) * 1000
                        proxy.response_time_ms = elapsed
                        proxy.is_healthy = True
                        proxy.success_count += 1
                        proxy.fail_count = 0
                        proxy.last_check = time.monotonic()
                        return True
        except Exception:
            pass

        proxy.fail_count += 1
        if proxy.fail_count >= self._max_fails:
            proxy.is_healthy = False
        proxy.last_check = time.monotonic()
        return False

    async def check_all(self) -> Dict[str, bool]:
        """Health check all proxies in parallel."""
        tasks = {p.url: self.check_health(p) for p in self._proxies}
        results = {}
        for url, coro in tasks.items():
            results[url] = await coro
        return results

    def mark_failed(self, proxy: Proxy) -> None:
        """Mark a proxy as failed after a request error."""
        proxy.fail_count += 1
        if proxy.fail_count >= self._max_fails:
            proxy.is_healthy = False

    def mark_success(self, proxy: Proxy) -> None:
        """Mark a proxy as successful."""
        proxy.success_count += 1
        proxy.fail_count = max(0, proxy.fail_count - 1)
        proxy.is_healthy = True

    @staticmethod
    def parse_proxy_url(url: str) -> Proxy:
        """Parse a proxy URL string into a Proxy object.

        Supports: http://user:pass@host:port, socks5://host:port
        """
        from urllib.parse import urlparse
        parsed = urlparse(url)
        protocol = ProxyProtocol.SOCKS5 if "socks" in parsed.scheme else ProxyProtocol.HTTP
        return Proxy(
            host=parsed.hostname or "",
            port=parsed.port or 8080,
            protocol=protocol,
            username=parsed.username,
            password=parsed.password,
        )
