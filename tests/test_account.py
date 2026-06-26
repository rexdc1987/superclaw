"""Account 模块单元测试"""
import time
import pytest
from rpa.account.models import AccountInfo, AccountStatus, AccountCredentials, HealthMetrics
from rpa.account.account_pool import AccountPool
from rpa.account.health_scorer import HealthScorer


# ============================================================
# AccountInfo 测试
# ============================================================

class TestAccountInfo:
    def test_is_available_active(self):
        acc = AccountInfo(account_id="a1", status=AccountStatus.ACTIVE)
        assert acc.is_available is True

    def test_is_available_disabled(self):
        acc = AccountInfo(account_id="a1", status=AccountStatus.DISABLED)
        assert acc.is_available is False

    def test_is_available_banned(self):
        acc = AccountInfo(account_id="a1", status=AccountStatus.BANNED)
        assert acc.is_available is False

    def test_cooldown_auto_recover(self):
        acc = AccountInfo(account_id="a1", status=AccountStatus.COOLDOWN,
                          cooldown_until=time.time() - 1)
        assert acc.is_available is True
        assert acc.status == AccountStatus.ACTIVE

    def test_cooldown_still_active(self):
        acc = AccountInfo(account_id="a1", status=AccountStatus.COOLDOWN,
                          cooldown_until=time.time() + 300)
        assert acc.is_available is False

    def test_success_rate(self):
        acc = AccountInfo(account_id="a1", success_count=8, fail_count=2)
        assert acc.success_rate == 0.8

    def test_success_rate_no_data(self):
        acc = AccountInfo(account_id="a1")
        assert acc.success_rate == 1.0

    def test_record_success(self):
        acc = AccountInfo(account_id="a1")
        acc.record_success()
        assert acc.success_count == 1
        assert acc.use_count == 1
        assert acc.consecutive_fails == 0

    def test_record_failure_triggers_cooldown(self):
        acc = AccountInfo(account_id="a1", cooldown_seconds=60)
        acc.record_failure()
        acc.record_failure()
        acc.record_failure()
        assert acc.status == AccountStatus.COOLDOWN
        assert acc.consecutive_fails == 3

    def test_record_success_resets_consecutive_fails(self):
        acc = AccountInfo(account_id="a1")
        acc.consecutive_fails = 2
        acc.record_success()
        assert acc.consecutive_fails == 0

    def test_to_dict_and_back(self):
        acc = AccountInfo(account_id="a1", username="test", platform="douyin",
                          health_score=85.5)
        d = acc.to_dict()
        acc2 = AccountInfo.from_dict(d)
        assert acc2.account_id == "a1"
        assert acc2.platform == "douyin"
        assert acc2.health_score == 85.5

    def test_cooldown_remaining(self):
        acc = AccountInfo(account_id="a1", status=AccountStatus.COOLDOWN,
                          cooldown_until=time.time() + 100)
        remaining = acc.cooldown_remaining
        assert 95 <= remaining <= 105

    def test_cooldown_remaining_not_in_cooldown(self):
        acc = AccountInfo(account_id="a1", status=AccountStatus.ACTIVE)
        assert acc.cooldown_remaining == 0.0


# ============================================================
# AccountPool 测试
# ============================================================

class TestAccountPool:
    def _make_pool(self):
        pool = AccountPool(strategy="round_robin")
        pool.add_account(AccountInfo(account_id="a1", platform="douyin"))
        pool.add_account(AccountInfo(account_id="a2", platform="douyin"))
        pool.add_account(AccountInfo(account_id="a3", platform="weibo"))
        return pool

    def test_add_and_size(self):
        pool = self._make_pool()
        assert pool.size == 3

    def test_get_by_platform(self):
        pool = self._make_pool()
        douyin = pool.get_by_platform("douyin")
        assert len(douyin) == 2

    def test_remove_account(self):
        pool = self._make_pool()
        assert pool.remove_account("a1") is True
        assert pool.size == 2
        assert pool.remove_account("nonexistent") is False

    def test_get_stats(self):
        pool = self._make_pool()
        stats = pool.get_stats()
        assert stats["total"] == 3
        assert stats["by_platform"]["douyin"] == 2
        assert stats["by_platform"]["weibo"] == 1

    @pytest.mark.asyncio
    async def test_acquire_and_release(self):
        pool = self._make_pool()
        acc = await pool.acquire("douyin")
        assert acc is not None
        assert acc.platform == "douyin"
        assert acc.is_available is True  # acquire 不改变状态，只更新 last_used

        await pool.release(acc.account_id, success=True)
        assert acc.success_count == 1

    @pytest.mark.asyncio
    async def test_acquire_failure_cooldown(self):
        pool = AccountPool(strategy="round_robin")
        pool.add_account(AccountInfo(account_id="a1", cooldown_seconds=60))
        acc = await pool.acquire()
        await pool.release(acc.account_id, success=False, cooldown_seconds=60)
        assert acc.consecutive_fails == 1

    @pytest.mark.asyncio
    async def test_acquire_no_available(self):
        pool = AccountPool(strategy="round_robin")
        pool.add_account(AccountInfo(account_id="a1", status=AccountStatus.BANNED))
        acc = await pool.acquire()
        assert acc is None

    def test_export_import_state(self):
        pool = self._make_pool()
        state = pool.export_state()
        assert len(state) == 3

        pool2 = AccountPool()
        count = pool2.import_state(state)
        assert count == 3

    def test_health_first_strategy(self):
        pool = AccountPool(strategy="health_first")
        pool.add_account(AccountInfo(account_id="low", health_score=40))
        pool.add_account(AccountInfo(account_id="high", health_score=95))
        candidates = pool.get_available()
        selected = pool._select(candidates)
        assert selected.account_id == "high"

    def test_least_used_strategy(self):
        pool = AccountPool(strategy="least_used")
        pool.add_account(AccountInfo(account_id="busy", use_count=100))
        pool.add_account(AccountInfo(account_id="idle", use_count=5))
        candidates = pool.get_available()
        selected = pool._select(candidates)
        assert selected.account_id == "idle"

    def test_invalid_strategy(self):
        with pytest.raises(ValueError):
            AccountPool(strategy="invalid")


# ============================================================
# HealthScorer 测试
# ============================================================

class TestHealthScorer:
    def test_healthy_score(self):
        scorer = HealthScorer()
        metrics = HealthMetrics(
            login_success=100, login_failure=0,
            action_success=200, action_failure=5,
            captcha_triggered=1, ban_count=0,
            last_check=time.time(),
        )
        result = scorer.evaluate(metrics)
        assert result["score"] >= 80
        assert result["classification"] == "healthy"

    def test_critical_score(self):
        scorer = HealthScorer()
        metrics = HealthMetrics(
            login_success=10, login_failure=40,
            action_success=5, action_failure=95,
            captcha_triggered=20, ban_count=3,
            flagged_count=5,
            last_check=time.time() - 86400 * 30,
        )
        result = scorer.evaluate(metrics)
        assert result["score"] < 40
        assert result["classification"] == "critical"

    def test_classify(self):
        scorer = HealthScorer()
        assert scorer.classify(90) == "healthy"
        assert scorer.classify(70) == "warning"
        assert scorer.classify(50) == "danger"
        assert scorer.classify(20) == "critical"

    def test_recommend_action(self):
        scorer = HealthScorer()
        assert "正常" in scorer.recommend_action(90)
        assert "禁用" in scorer.recommend_action(10)
