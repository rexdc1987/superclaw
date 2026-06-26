"""HTTP 中间件单元测试"""
import asyncio
import pytest
from rpa.http.middleware import (
    MiddlewareChain, UARotator, PlatformHeaders,
    RateLimiter, RequestLogger, PLATFORM_HEADERS,
)


# ============================================================
# UARotator 测试
# ============================================================

class TestUARotator:
    @pytest.mark.asyncio
    async def test_rotate_ua(self):
        rotator = UARotator()
        headers, cookies = await rotator.process_request(
            "acc1", "https://example.com", "GET", {}, {}
        )
        assert "User-Agent" in headers
        assert "Chrome" in headers["User-Agent"] or "Firefox" in headers["User-Agent"]

    @pytest.mark.asyncio
    async def test_bind_to_account(self):
        rotator = UARotator(bind_to_account=True)
        h1, _ = await rotator.process_request("acc1", "https://a.com", "GET", {}, {})
        h2, _ = await rotator.process_request("acc1", "https://b.com", "GET", {}, {})
        assert h1["User-Agent"] == h2["User-Agent"]  # 同账号同 UA

        h3, _ = await rotator.process_request("acc2", "https://c.com", "GET", {}, {})
        # 不同账号可能不同 UA（概率性，但 bind 模式下各账号独立）
        assert "User-Agent" in h3

    @pytest.mark.asyncio
    async def test_custom_ua_pool(self):
        custom = ["CustomBot/1.0", "CustomBot/2.0"]
        rotator = UARotator(user_agents=custom)
        h, _ = await rotator.process_request("a", "https://x.com", "GET", {}, {})
        assert h["User-Agent"] in custom


# ============================================================
# PlatformHeaders 测试
# ============================================================

class TestPlatformHeaders:
    @pytest.mark.asyncio
    async def test_douyin_headers(self):
        mw = PlatformHeaders("douyin")
        h, _ = await mw.process_request("a", "https://api.douyin.com/", "GET", {}, {})
        assert "Referer" in h
        assert "douyin.com" in h["Referer"]
        assert "Sec-Ch-Ua" in h

    @pytest.mark.asyncio
    async def test_weibo_headers(self):
        mw = PlatformHeaders("weibo")
        h, _ = await mw.process_request("a", "https://api.weibo.com/", "GET", {}, {})
        assert "weibo.com" in h["Referer"]

    @pytest.mark.asyncio
    async def test_unknown_platform(self):
        mw = PlatformHeaders("unknown")
        h, _ = await mw.process_request("a", "https://x.com", "GET", {}, {})
        # 不崩溃，不注入额外头
        assert isinstance(h, dict)

    @pytest.mark.asyncio
    async def test_extra_headers(self):
        mw = PlatformHeaders("douyin", extra_headers={"X-Custom": "test"})
        h, _ = await mw.process_request("a", "https://x.com", "GET", {}, {})
        assert h["X-Custom"] == "test"

    @pytest.mark.asyncio
    async def test_does_not_overwrite_existing(self):
        mw = PlatformHeaders("douyin")
        h, _ = await mw.process_request("a", "https://x.com", "GET", {"Referer": "custom"}, {})
        assert h["Referer"] == "custom"  # 已有的不覆盖


# ============================================================
# RateLimiter 测试
# ============================================================

class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_allows_normal_rate(self):
        limiter = RateLimiter(max_per_minute=60, max_per_second=10)
        for _ in range(5):
            h, c = await limiter.process_request("a", "https://x.com", "GET", {}, {})
        assert isinstance(h, dict)

    @pytest.mark.asyncio
    async def test_per_account_isolation(self):
        limiter = RateLimiter(max_per_minute=2, max_per_second=2)
        # acc1 用完令牌
        await limiter.process_request("acc1", "https://x.com", "GET", {}, {})
        await limiter.process_request("acc1", "https://x.com", "GET", {}, {})
        # acc2 应该不受影响
        h, _ = await limiter.process_request("acc2", "https://x.com", "GET", {}, {})
        assert isinstance(h, dict)


# ============================================================
# RequestLogger 测试
# ============================================================

class TestRequestLogger:
    @pytest.mark.asyncio
    async def test_logs_request(self):
        logger = RequestLogger()
        h, _ = await logger.process_request("acc1", "https://x.com/api", "GET", {}, {})
        # process_request 只记录日志，不更新 stats；stats 由 process_response 更新
        await logger.process_response("acc1", "https://x.com/api", 200, {})
        stats = logger.get_stats()
        assert "acc1" in stats

    @pytest.mark.asyncio
    async def test_logs_response(self):
        logger = RequestLogger()
        await logger.process_response("acc1", "https://x.com", 200, {})
        await logger.process_response("acc1", "https://x.com", 500, {})
        stats = logger.get_stats()
        assert stats["acc1"]["requests"] == 2
        assert stats["acc1"]["errors"] == 1


# ============================================================
# MiddlewareChain 测试
# ============================================================

class TestMiddlewareChain:
    @pytest.mark.asyncio
    async def test_chain_execution(self):
        chain = MiddlewareChain()
        chain.add(UARotator())
        chain.add(PlatformHeaders("douyin"))

        h, c = await chain.process_request("a", "https://api.douyin.com/", "GET")
        assert "User-Agent" in h
        assert "Referer" in h
        assert chain.count == 2

    @pytest.mark.asyncio
    async def test_chain_with_all_middleware(self):
        chain = MiddlewareChain()
        chain.add(UARotator())
        chain.add(PlatformHeaders("douyin"))
        chain.add(RateLimiter(max_per_minute=60))
        chain.add(RequestLogger())

        h, c = await chain.process_request("acc1", "https://api.douyin.com/", "GET")
        assert "User-Agent" in h
        assert "Referer" in h

    @pytest.mark.asyncio
    async def test_chain_fluent_api(self):
        chain = MiddlewareChain()
        result = chain.add(UARotator()).add(PlatformHeaders("douyin"))
        assert result is chain
        assert chain.count == 2

    def test_chain_clear(self):
        chain = MiddlewareChain()
        chain.add(UARotator())
        chain.clear()
        assert chain.count == 0
