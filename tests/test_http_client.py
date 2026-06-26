"""HTTP Client 模块单元测试。"""
import pytest
import httpx
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from rpa.http.retry import RetryPolicy, ExponentialBackoff, RetryExecutor
from rpa.http.client import HttpClient


# ============================================================
# RetryPolicy 测试
# ============================================================

class TestExponentialBackoff:
    def test_delay_increases(self):
        bo = ExponentialBackoff(base=1.0, max_delay=60.0, jitter=0.0)
        assert bo.delay(0) == 1.0
        assert bo.delay(1) == 2.0
        assert bo.delay(2) == 4.0
        assert bo.delay(3) == 8.0

    def test_delay_max_cap(self):
        bo = ExponentialBackoff(base=1.0, max_delay=5.0, jitter=0.0)
        assert bo.delay(10) == 5.0  # capped

    def test_delay_has_jitter(self):
        bo = ExponentialBackoff(base=1.0, max_delay=60.0, jitter=0.5)
        d1 = bo.delay(0)
        d2 = bo.delay(0)
        # jitter makes it non-deterministic, just check range
        assert 1.0 <= d1 <= 1.5


class TestRetryPolicy:
    def test_should_retry_status_code(self):
        policy = RetryPolicy(max_retries=3)
        assert policy.should_retry(0, status_code=429) is True
        assert policy.should_retry(0, status_code=500) is True
        assert policy.should_retry(0, status_code=200) is False
        assert policy.should_retry(0, status_code=404) is False

    def test_should_retry_exception(self):
        policy = RetryPolicy(max_retries=3)
        assert policy.should_retry(0, exception=httpx.TimeoutException("timeout")) is True
        assert policy.should_retry(0, exception=httpx.ConnectError("connect")) is True
        assert policy.should_retry(0, exception=ValueError("bad")) is False

    def test_should_not_retry_after_max(self):
        policy = RetryPolicy(max_retries=2)
        assert policy.should_retry(2, status_code=429) is False  # attempt >= max_retries

    def test_parse_retry_after(self):
        resp = MagicMock(spec=httpx.Response)
        resp.headers = {"Retry-After": "30"}
        assert RetryPolicy.parse_retry_after(resp) == 30.0

    def test_parse_retry_after_missing(self):
        resp = MagicMock(spec=httpx.Response)
        resp.headers = {}
        assert RetryPolicy.parse_retry_after(resp) is None

    def test_get_wait_time_with_retry_after(self):
        policy = RetryPolicy(respect_retry_after=True)
        wait = policy.get_wait_time(0, retry_after=10.0)
        assert wait == 10.0

    def test_get_wait_time_without_retry_after(self):
        policy = RetryPolicy(backoff=ExponentialBackoff(base=1.0, jitter=0.0))
        wait = policy.get_wait_time(0)
        assert wait == 1.0


class TestRetryExecutor:
    @pytest.mark.asyncio
    async def test_no_retry_on_success(self):
        executor = RetryExecutor(RetryPolicy(max_retries=3))
        call_count = 0

        async def success_func():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await executor.execute(success_func)
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_exception(self):
        policy = RetryPolicy(max_retries=2, backoff=ExponentialBackoff(base=0.01, jitter=0.0))
        executor = RetryExecutor(policy)
        call_count = 0

        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.TimeoutException("timeout")
            return "ok"

        result = await executor.execute(fail_then_succeed)
        assert result == "ok"
        assert call_count == 3


# ============================================================
# HttpClient 测试
# ============================================================

class TestHttpClient:
    @pytest.mark.asyncio
    async def test_get_request(self):
        client = HttpClient()
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock) as mock_req:
            mock_resp = MagicMock(spec=httpx.Response)
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_req.return_value = mock_resp

            resp = await client.get("https://example.com/test")
            assert resp.status_code == 200
            mock_req.assert_called_once()

    @pytest.mark.asyncio
    async def test_post_json(self):
        client = HttpClient()
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock) as mock_req:
            mock_resp = MagicMock(spec=httpx.Response)
            mock_resp.status_code = 201
            mock_resp.raise_for_status = MagicMock()
            mock_req.return_value = mock_resp

            resp = await client.post("https://example.com/api", json={"key": "value"})
            assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_stats(self):
        client = HttpClient()
        assert client.stats()["total_requests"] == 0

    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with HttpClient() as client:
            assert client._client is not None
        # after exit, client should be closed
        assert client._client.is_closed
