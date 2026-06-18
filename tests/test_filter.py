"""Filter service 测试"""
import pytest
from datetime import datetime, timedelta


class TestFilterService:
    def _svc(self):
        from services.filter_service import FilterService
        return FilterService()

    def _make_leads(self):
        from models.database import get_session
        from models.lead import Lead
        session = get_session()
        try:
            leads = [
                Lead(task_id=9900, platform="douyin", user_id="f_u1", user_nickname="北京用户",
                     user_region="北京", account_type="personal", follower_count=1000,
                     last_active_at=datetime.utcnow()),
                Lead(task_id=9900, platform="douyin", user_id="f_u2", user_nickname="上海用户",
                     user_region="上海", account_type="business", follower_count=50000,
                     last_active_at=datetime.utcnow() - timedelta(days=10)),
                Lead(task_id=9900, platform="douyin", user_id="f_u3", user_nickname="广州用户",
                     user_region="广州", account_type="verified", follower_count=200000,
                     last_active_at=datetime.utcnow() - timedelta(days=40)),
            ]
            for l in leads:
                session.add(l)
            session.commit()
            return leads
        finally:
            session.close()

    def test_filter_by_region(self):
        self._make_leads()
        svc = self._svc()
        result = svc.apply_filters(9900, {"region": "北京"})
        assert len(result) == 1
        assert result[0].user_region == "北京"

    def test_filter_by_time(self):
        self._make_leads()
        svc = self._svc()
        result = svc.apply_filters(9900, {"time_days": 7})
        # Only u1 (active today) should match
        assert all(l.user_id == "f_u1" for l in result)

    def test_filter_by_account_type(self):
        self._make_leads()
        svc = self._svc()
        result = svc.apply_filters(9900, {"account_type": "business"})
        assert len(result) == 1
        assert result[0].account_type == "business"

    def test_filter_by_follower_count(self):
        self._make_leads()
        svc = self._svc()
        result = svc.apply_filters(9900, {"min_follower_count": 10000})
        assert len(result) == 2  # u2 (50k) and u3 (200k)

    def test_combined_filters(self):
        self._make_leads()
        svc = self._svc()
        result = svc.apply_filters(9900, {
            "region": "上海",
            "min_follower_count": 10000,
            "time_days": 30,
        })
        assert len(result) == 1
        assert result[0].user_id == "f_u2"

    def test_empty_filter_returns_all(self):
        self._make_leads()
        svc = self._svc()
        result = svc.apply_filters(9900, {})
        assert len(result) == 3
