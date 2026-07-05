"""
多账号管理模块单元测试

覆盖：AccountPool、AccountInfo、ContextFactory、HealthScorer、CredentialStore
"""

import asyncio
import json
import os
import sys
import tempfile
import time

import pytest

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rpa.account.account_pool import AccountInfo, AccountPool, AccountStatus
from rpa.account.health_scorer import HealthMetrics, HealthScorer
from rpa.account.credential_store import CredentialStore


# ============================================================
# AccountInfo 测试
# ============================================================

class TestAccountInfo:
    """AccountInfo 数据类测试"""

    def test_create_default(self):
        """默认状态为 ACTIVE，分数 100"""
        a = AccountInfo(account_id="a1", username="user1", platform="douyin")
        assert a.status == AccountStatus.ACTIVE
        assert a.health_score == 100.0
        assert a.is_available is True

    def test_cooldown_expiry(self):
        """冷却到期后自动恢复"""
        a = AccountInfo(account_id="a1", username="u1", platform="douyin")
        a.start_cooldown(0.1)  # 0.1秒冷却
        assert a.status == AccountStatus.COOLDOWN
        assert a.is_available is False
        time.sleep(0.15)
        assert a.is_available is True
        assert a.status == AccountStatus.ACTIVE

    def test_disabled_not_available(self):
        """DISABLED 状态不可用"""
        a = AccountInfo(account_id="a1", username="u1", platform="douyin",
                        status=AccountStatus.DISABLED)
        assert a.is_available is False

    def test_banned_not_available(self):
        """BANNED 状态不可用"""
        a = AccountInfo(account_id="a1", username="u1", platform="douyin",
                        status=AccountStatus.BANNED)
        assert a.is_available is False

    def test_record_success(self):
        """成功记录递增计数器"""
        a = AccountInfo(account_id="a1", username="u1", platform="douyin")
        a.record_success()
        assert a.success_count == 1
        assert a.use_count == 1
        assert a.consecutive_fails == 0

    def test_record_failure_cooldown(self):
        """连续失败3次自动进入冷却"""
        a = AccountInfo(account_id="a1", username="u1", platform="douyin")
        a.record_failure(cooldown_seconds=60)
        a.record_failure(cooldown_seconds=60)
        assert a.status == AccountStatus.ACTIVE  # 还没到3次
        a.record_failure(cooldown_seconds=60)
        assert a.status == AccountStatus.COOLDOWN
        assert a.consecutive_fails == 3

    def test_success_resets_consecutive_fails(self):
        """成功后重置连续失败计数"""
        a = AccountInfo(account_id="a1", username="u1", platform="douyin")
        a.consecutive_fails = 2
        a.record_success()
        assert a.consecutive_fails == 0

    def test_success_rate(self):
        """成功率计算"""
        a = AccountInfo(account_id="a1", username="u1", platform="douyin")
        assert a.success_rate == 1.0  # 无操作时为100%
        a.record_success()
        a.record_success()
        a.record_failure()
        assert abs(a.success_rate - 2 / 3) < 0.01

    def test_to_dict_from_dict(self):
        """序列化/反序列化"""
        a = AccountInfo(account_id="a1", username="u1", platform="douyin",
                        health_score=85.5, metadata={"tag": "test"})
        d = a.to_dict()
        assert d["account_id"] == "a1"
        assert d["status"] == "active"

        a2 = AccountInfo.from_dict(d)
        assert a2.account_id == "a1"
        assert a2.health_score == 85.5
        assert a2.metadata == {"tag": "test"}


# ============================================================
# AccountPool 测试
# ============================================================

class TestAccountPool:
    """AccountPool 管理器测试"""

    def _make_pool(self, strategy="round_robin", count=3, platform="douyin"):
        pool = AccountPool(strategy=strategy)
        for i in range(count):
            pool.add_account(AccountInfo(
                account_id=f"a{i}", username=f"user{i}", platform=platform
            ))
        return pool

    def test_add_remove(self):
        """增删账号"""
        pool = self._make_pool()
        assert pool.size == 3
        assert pool.remove_account("a0") is True
        assert pool.size == 2
        assert pool.remove_account("nonexistent") is False

    def test_get_account(self):
        """获取指定账号"""
        pool = self._make_pool()
        a = pool.get_account("a1")
        assert a is not None
        assert a.username == "user1"
        assert pool.get_account("nonexistent") is None

    def test_get_by_platform(self):
        """按平台过滤"""
        pool = self._make_pool(platform="douyin")
        pool.add_account(AccountInfo(account_id="b0", username="wb0", platform="weibo"))
        douyin = pool.get_by_platform("douyin")
        weibo = pool.get_by_platform("weibo")
        assert len(douyin) == 3
        assert len(weibo) == 1

    @pytest.mark.asyncio
    async def test_acquire_round_robin(self):
        """轮询策略分配"""
        pool = self._make_pool(strategy="round_robin")
        seen = set()
        for _ in range(6):
            a = await pool.acquire()
            seen.add(a.account_id)
        assert len(seen) == 3  # 3个账号都被轮到

    @pytest.mark.asyncio
    async def test_acquire_health_first(self):
        """健康度优先策略"""
        pool = self._make_pool(strategy="health_first")
        pool.get_account("a0").health_score = 50
        pool.get_account("a1").health_score = 100
        pool.get_account("a2").health_score = 80

        a = await pool.acquire()
        assert a.account_id == "a1"  # 分数最高

    @pytest.mark.asyncio
    async def test_acquire_least_used(self):
        """最少使用策略"""
        pool = self._make_pool(strategy="least_used")
        pool.get_account("a0").use_count = 10
        pool.get_account("a1").use_count = 2
        pool.get_account("a2").use_count = 5

        a = await pool.acquire()
        assert a.account_id == "a1"  # 使用次数最少

    @pytest.mark.asyncio
    async def test_acquire_platform_filter(self):
        """按平台获取"""
        pool = self._make_pool(platform="douyin")
        pool.add_account(AccountInfo(account_id="b0", username="wb", platform="weibo"))

        a = await pool.acquire(platform="weibo")
        assert a.account_id == "b0"

    @pytest.mark.asyncio
    async def test_acquire_no_available(self):
        """无可用账号返回 None"""
        pool = AccountPool()
        a = await pool.acquire()
        assert a is None

    @pytest.mark.asyncio
    async def test_release_success(self):
        """释放成功账号"""
        pool = self._make_pool()
        a = await pool.acquire()
        await pool.release(a.account_id, success=True)
        assert pool.get_account(a.account_id).success_count == 1

    @pytest.mark.asyncio
    async def test_release_failure_cooldown(self):
        """释放失败账号触发冷却"""
        pool = self._make_pool()
        a = await pool.acquire()
        # 连续失败3次
        for _ in range(3):
            await pool.release(a.account_id, success=False)
        acc = pool.get_account(a.account_id)
        assert acc.status == AccountStatus.COOLDOWN

    def test_export_import_state(self):
        """导出/导入状态"""
        pool = self._make_pool()
        pool.get_account("a0").record_success()
        state = pool.export_state()
        assert len(state) == 3

        pool2 = AccountPool()
        count = pool2.import_state(state)
        assert count == 3
        assert pool2.get_account("a0").success_count == 1

    def test_get_stats(self):
        """统计信息"""
        pool = self._make_pool()
        stats = pool.get_stats()
        assert stats["total"] == 3
        assert stats["available"] == 3
        assert stats["strategy"] == "round_robin"
        assert stats["by_status"]["active"] == 3

    def test_invalid_strategy(self):
        """无效策略报错"""
        with pytest.raises(ValueError):
            AccountPool(strategy="invalid")


# ============================================================
# HealthScorer 测试
# ============================================================

class TestHealthScorer:
    """HealthScorer 评分器测试"""

    def test_perfect_health(self):
        """完美健康账号"""
        scorer = HealthScorer()
        m = HealthMetrics(login_success=100, action_success=100,
                          last_check=time.time())
        score = scorer.calculate(m)
        assert score >= 90

    def test_ban_reduces_score(self):
        """封禁记录扣分"""
        scorer = HealthScorer()
        m1 = HealthMetrics(login_success=100, action_success=100,
                           last_check=time.time())
        m2 = HealthMetrics(login_success=100, action_success=100,
                           ban_count=1, last_check=time.time())
        s1 = scorer.calculate(m1)
        s2 = scorer.calculate(m2)
        assert s1 > s2

    def test_captcha_reduces_score(self):
        """验证码频繁触发扣分"""
        scorer = HealthScorer()
        m = HealthMetrics(login_success=100, action_success=100,
                          captcha_triggered=20, last_check=time.time())
        score = scorer.calculate(m)
        assert score < 90

    def test_classify(self):
        """分类测试"""
        scorer = HealthScorer()
        assert scorer.classify(90) == "healthy"
        assert scorer.classify(70) == "warning"
        assert scorer.classify(50) == "danger"
        assert scorer.classify(30) == "critical"

    def test_recommend_action(self):
        """推荐操作"""
        scorer = HealthScorer()
        assert "正常" in scorer.recommend_action(90)
        assert "禁用" in scorer.recommend_action(30)

    def test_evaluate_full(self):
        """完整评估"""
        scorer = HealthScorer()
        m = HealthMetrics(login_success=80, login_failure=20,
                          action_success=90, action_failure=10,
                          last_check=time.time())
        result = scorer.evaluate(m)
        assert "score" in result
        assert "classification" in result
        assert "recommendation" in result
        assert result["metrics"]["login_rate"] == 0.8


# ============================================================
# CredentialStore 测试
# ============================================================

class TestCredentialStore:
    """CredentialStore 凭据存储测试"""

    def test_add_get_remove(self):
        """增删查凭据"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CredentialStore(store_path=os.path.join(tmpdir, "creds.enc"))
            store.add("a1", "user1", "pass123", {"platform": "douyin"})
            assert store.count == 1

            cred = store.get("a1")
            assert cred["username"] == "user1"
            assert cred["password"] == "pass123"

            assert store.remove("a1") is True
            assert store.get("a1") is None
            assert store.remove("nonexistent") is False

    def test_save_load(self):
        """保存/加载持久化"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "creds.enc")
            store = CredentialStore(store_path=path)
            store.add("a1", "user1", "pass1")
            store.add("a2", "user2", "pass2")
            store.save()

            store2 = CredentialStore(store_path=path)
            count = store2.load()
            assert count == 2
            assert store2.get("a1")["username"] == "user1"

    def test_list_accounts(self):
        """列出所有账号ID"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CredentialStore(store_path=os.path.join(tmpdir, "c.enc"))
            store.add("a1", "u1", "p1")
            store.add("a2", "u2", "p2")
            ids = store.list_accounts()
            assert set(ids) == {"a1", "a2"}
