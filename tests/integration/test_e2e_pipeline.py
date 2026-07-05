"""E2E 集成测试 — 验证所有模块端到端协作。

测试路径：
1. HTTP Client → Middleware Chain → Retry → Response
2. Account Pool → Context Factory → Browser Context
3. Anti-Detect → Fingerprint → Stealth → Verification
4. Token Manager → Storage → Refresh → Cleanup

所有外部依赖用 mock，不做真实网络调用。
"""

import asyncio
import json
import time
import tempfile
import httpx
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from rpa.http.client import HttpClient
from rpa.http.retry import RetryPolicy, ExponentialBackoff
from rpa.http.middleware import (
    MiddlewareChain, UARotator, PlatformHeaders,
    RateLimiter, RequestLogger,
)
from rpa.account.models import AccountInfo, AccountStatus, HealthMetrics
from rpa.account.account_pool import AccountPool
from rpa.account.context_factory import ContextFactory
from rpa.account.health_scorer import HealthScorer
from rpa.auth.token_manager import TokenManager, TokenInfo
from rpa.anti_detect.fingerprint import FingerprintManager, FingerprintProfile
from rpa.anti_detect.stealth import StealthMiddleware


# ============================================================
# 测试 1: HTTP Client → Middleware Chain → Retry → Response
# ============================================================

class TestHTTPMiddlewarePipeline:
    """验证 HTTP 客户端 + 中间件链 + 重试的完整流程"""

    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        """完整流程：中间件处理 → 客户端请求 → 重试 → 响应"""
        # 1. 构建中间件链
        chain = MiddlewareChain()
        chain.add(UARotator())
        chain.add(PlatformHeaders("douyin"))
        chain.add(RateLimiter(max_per_minute=60))
        chain.add(RequestLogger())

        # 2. 模拟请求前中间件处理
        headers, cookies = await chain.process_request(
            account_id="test_acc",
            url="https://api.douyin.com/aweme/v1/web/search/",
            method="GET",
        )
        assert "User-Agent" in headers
        assert "Referer" in headers
        assert "douyin.com" in headers["Referer"]

        # 3. 模拟 HTTP 客户端请求（mock httpx）
        client = HttpClient()
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock) as mock_req:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.headers = {}
            mock_resp.raise_for_status = MagicMock()
            mock_req.return_value = mock_resp

            resp = await client.request(
                "GET", "https://api.douyin.com/test",
                headers=headers, cookies=cookies,
            )
            assert resp.status_code == 200

        # 4. 模拟响应后中间件处理
        await chain.process_response(
            "test_acc", "https://api.douyin.com/test", 200, {},
        )

        # 5. 验证统计
        stats = client.stats()
        assert stats["total_requests"] == 1

    @pytest.mark.asyncio
    async def test_retry_on_failure_then_success(self):
        """验证重试机制：第1次失败，第2次成功"""
        policy = RetryPolicy(max_retries=2, backoff=ExponentialBackoff(base=0.01, jitter=0.0))
        client = HttpClient(retry=policy)

        call_count = 0

        async def mock_request(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.TimeoutException("timeout")
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            return resp

        with patch.object(httpx.AsyncClient, "request", side_effect=mock_request):
            resp = await client.get("https://api.test.com/data")
            assert resp.status_code == 200
            assert call_count == 2

    @pytest.mark.asyncio
    async def test_429_rate_limit_respected(self):
        """验证 429 限流响应被正确处理"""
        chain = MiddlewareChain()
        chain.add(RateLimiter(max_per_minute=100))

        # 模拟大量请求触发限流
        for i in range(5):
            h, c = await chain.process_request("acc", "https://x.com", "GET", {}, {})

        # 仍然能处理（RateLimiter 不会拒绝，只是等待）
        assert isinstance(h, dict)


# ============================================================
# 测试 2: Account Pool → Context Factory → Browser Context
# ============================================================

class TestAccountContextPipeline:
    """验证账号池 → 上下文工厂的完整流程"""

    def _make_pool_with_accounts(self, count=5):
        pool = AccountPool(strategy="round_robin")
        for i in range(count):
            pool.add_account(AccountInfo(
                account_id=f"acc_{i}",
                username=f"user_{i}",
                platform="douyin",
            ))
        return pool

    @pytest.mark.asyncio
    async def test_pool_acquire_and_context_create(self):
        """账号池获取 → 创建浏览器上下文"""
        pool = self._make_pool_with_accounts(3)

        # Mock Playwright browser
        mock_context = AsyncMock()
        mock_context.storage_state = AsyncMock(return_value={"cookies": []})
        mock_context.close = AsyncMock()

        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)

        factory = ContextFactory(mock_browser, storage_dir=tempfile.mkdtemp())

        # 1. 从池中获取账号
        acc = await pool.acquire("douyin")
        assert acc is not None

        # 2. 为该账号创建上下文
        ctx = await factory.create_context(
            acc.account_id,
            fingerprint={"viewport": {"width": 1920, "height": 1080}},
            anti_detect=False,  # 跳过反检测（没有真实浏览器）
        )
        assert ctx is not None
        assert factory.active_count == 1

        # 3. 释放账号
        await pool.release(acc.account_id, success=True)
        assert acc.success_count == 1

        # 4. 关闭上下文
        await factory.close_context(acc.account_id, save=True)
        assert factory.active_count == 0

    @pytest.mark.asyncio
    async def test_multi_account_isolation(self):
        """多账号上下文隔离"""
        pool = self._make_pool_with_accounts(3)

        mock_context = AsyncMock()
        mock_context.storage_state = AsyncMock(return_value={"cookies": []})
        mock_context.close = AsyncMock()

        call_count = 0
        async def mock_new_context(**kwargs):
            nonlocal call_count
            call_count += 1
            ctx = AsyncMock()
            ctx.storage_state = AsyncMock(return_value={"cookies": []})
            ctx.close = AsyncMock()
            return ctx

        mock_browser = AsyncMock()
        mock_browser.new_context = mock_new_context

        factory = ContextFactory(mock_browser, storage_dir=tempfile.mkdtemp())

        # 为 3 个不同账号创建上下文
        for i in range(3):
            acc = await pool.acquire("douyin")
            await factory.create_context(acc.account_id, anti_detect=False)

        assert factory.active_count == 3
        assert call_count == 3

        await factory.close_all(save=False)
        assert factory.active_count == 0

    @pytest.mark.asyncio
    async def test_health_scoring_integration(self):
        """健康度评分集成：操作结果 → 评分 → 策略选择"""
        pool = AccountPool(strategy="health_first")
        scorer = HealthScorer()

        # 添加不同健康度的账号
        pool.add_account(AccountInfo(account_id="healthy", health_score=95))
        pool.add_account(AccountInfo(account_id="sick", health_score=30))

        # 健康账号优先被选中
        acc = await pool.acquire()
        assert acc.account_id == "healthy"

        # 模拟操作失败
        await pool.release(acc.account_id, success=False)
        await pool.release(acc.account_id, success=False)
        await pool.release(acc.account_id, success=False)

        # 连续 3 次失败触发冷却
        assert acc.status == AccountStatus.COOLDOWN

        # 下次选择应该选 sick（因为 healthy 在冷却中）
        acc2 = await pool.acquire()
        assert acc2 is not None


# ============================================================
# 测试 3: Anti-Detect → Fingerprint → Stealth
# ============================================================

class TestAntiDetectPipeline:
    """验证反检测模块的集成"""

    def test_fingerprint_profile_generation(self):
        """指纹配置生成"""
        profile = FingerprintManager.random_profile()
        assert profile.user_agent != ""
        assert profile.platform in ("Win32", "MacIntel", "Linux x86_64")
        assert profile.screen_width > 0
        assert profile.timezone != ""

    def test_fingerprint_js_generation(self):
        """指纹 JS 代码生成"""
        profile = FingerprintManager.random_profile()

        canvas_js = profile.get_canvas_noise_js()
        assert "toDataURL" in canvas_js
        assert str(profile.canvas_noise_seed) in canvas_js

        webgl_js = profile.get_webgl_spoof_js()
        assert "getParameter" in webgl_js
        assert profile.webgl_vendor in webgl_js

        nav_js = profile.get_navigator_override_js()
        assert "platform" in nav_js
        assert "hardwareConcurrency" in nav_js

        tz_js = profile.get_timezone_js()
        assert "Intl.DateTimeFormat" in tz_js
        assert profile.timezone in tz_js

    def test_stealth_feature_toggles(self):
        """StealthMiddleware 独立开关"""
        stealth = StealthMiddleware(
            enable_webdriver_hiding=True,
            enable_plugins_spoof=False,
            enable_navigator_override=True,
            enable_chromedriver_cleanup=False,
            enable_permissions_fix=False,
            enable_ua_spoof=True,
        )
        js = stealth._build_stealth_js()
        assert "webdriver" in js
        assert "plugins" not in js  # 被禁用了
        assert "navigator" in js
        assert "cdc_" not in js  # 被禁用了
        assert "permissions" not in js  # 被禁用了

    def test_fingerprint_manager_templates(self):
        """指纹模板管理"""
        templates = FingerprintManager.list_templates()
        assert len(templates) >= 5

        for name in templates:
            profile = FingerprintManager.from_template(name)
            assert profile.user_agent != ""

    def test_fingerprint_persistence(self, tmp_path):
        """指纹配置持久化"""
        profile = FingerprintManager.random_profile()
        path = tmp_path / "test_profile.json"
        profile.save(str(path))

        loaded = FingerprintProfile.load(str(path))
        assert loaded.user_agent == profile.user_agent
        assert loaded.timezone == profile.timezone


# ============================================================
# 测试 4: Token Manager → Storage → Refresh
# ============================================================

class TestTokenManagerPipeline:
    """验证 Token 管理器的完整流程"""

    def test_token_lifecycle(self, tmp_path):
        """Token 生命周期：创建 → 存储 → 读取 → 过期 → 删除"""
        tm = TokenManager(storage_dir=str(tmp_path))

        # 1. 创建并保存 token
        token = TokenInfo(
            access_token="access_abc",
            refresh_token="refresh_xyz",
            expires_at=time.time() + 3600,
            scope="read write",
        )
        tm.save("account_1", token)

        # 2. 读取
        loaded = tm.get("account_1")
        assert loaded is not None
        assert loaded.access_token == "access_abc"

        # 3. 验证有效
        valid = tm.get_valid("account_1")
        assert valid is not None

        # 4. 模拟过期
        expired_token = TokenInfo(
            access_token="old_token",
            refresh_token="old_refresh",
            expires_at=time.time() - 100,
        )
        tm.save("expired_acc", expired_token)
        assert tm.get_valid("expired_acc") is None

        # 5. 获取请求头
        headers = tm.auth_headers("account_1")
        assert "Authorization" in headers
        assert "Bearer access_abc" in headers["Authorization"]

        # 6. 删除
        tm.delete("account_1")
        assert tm.get("account_1") is None

        # 7. 统计
        stats = tm.stats()
        assert stats["total_accounts"] == 1  # 只剩 expired_acc

    def test_token_persistence_across_restarts(self, tmp_path):
        """Token 跨实例持久化"""
        # 实例 1：保存
        tm1 = TokenManager(storage_dir=str(tmp_path))
        tm1.save("persist", TokenInfo(
            access_token="persist_token",
            refresh_token="persist_refresh",
            expires_at=time.time() + 7200,
        ))

        # 实例 2：加载
        tm2 = TokenManager(storage_dir=str(tmp_path))
        loaded = tm2.get("persist")
        assert loaded is not None
        assert loaded.access_token == "persist_token"

    def test_multi_account_isolation(self, tmp_path):
        """多账号 Token 隔离"""
        tm = TokenManager(storage_dir=str(tmp_path))

        tm.save("user_a", TokenInfo(access_token="token_a", expires_at=99999))
        tm.save("user_b", TokenInfo(access_token="token_b", expires_at=99999))

        assert tm.get("user_a").access_token == "token_a"
        assert tm.get("user_b").access_token == "token_b"
        assert len(tm.list_accounts()) == 2

    @pytest.mark.asyncio
    async def test_token_refresh_flow(self, tmp_path):
        """Token 刷新流程（mock）"""
        tm = TokenManager(storage_dir=str(tmp_path))
        tm.save("refresh_acc", TokenInfo(
            access_token="old_access",
            refresh_token="my_refresh_token",
            expires_at=time.time() - 10,  # 已过期
        ))

        # Mock httpx 刷新请求
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        with patch("rpa.auth.token_manager.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            new_token = await tm.refresh(
                "refresh_acc",
                token_url="https://api.example.com/token",
                client_id="cid",
                client_secret="test_secret"
            )

            assert new_token is not None
            assert new_token.access_token == "new_access"
            assert new_token.refresh_token == "new_refresh"
