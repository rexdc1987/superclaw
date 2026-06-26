"""Filter service — 高级筛选引擎"""
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from models.database import get_session
from models.lead import Lead


class FilterService:
    def filter_by_region(self, query, region: str):
        """按地区过滤"""
        if not region:
            return query
        return query.filter(Lead.user_region.contains(region))

    def filter_by_time(self, query, days: int):
        """按时效过滤（N天内活跃）"""
        if not days or days <= 0:
            return query
        cutoff = datetime.utcnow() - timedelta(days=days)
        return query.filter(Lead.last_active_at >= cutoff)

    def filter_by_account_type(self, query, account_type: str):
        """按账号类型过滤"""
        if not account_type:
            return query
        return query.filter(Lead.account_type == account_type)

    def filter_by_follower_count(self, query, min_count: int = 0, max_count: int = 999999999):
        """按粉丝量范围过滤"""
        if min_count > 0:
            query = query.filter(Lead.follower_count >= min_count)
        if max_count < 999999999:
            query = query.filter(Lead.follower_count <= max_count)
        return query

    def apply_filters(self, task_id: int, filter_config: dict) -> List[Lead]:
        """应用组合筛选，返回结果"""
        session = get_session()
        try:
            q = session.query(Lead).filter(Lead.task_id == task_id)

            region = filter_config.get("region", "")
            days = filter_config.get("time_days", 0)
            account_type = filter_config.get("account_type", "")
            min_fans = filter_config.get("min_follower_count", 0)
            max_fans = filter_config.get("max_follower_count", 999999999)

            q = self.filter_by_region(q, region)
            q = self.filter_by_time(q, days)
            q = self.filter_by_account_type(q, account_type)
            q = self.filter_by_follower_count(q, min_fans, max_fans)

            return q.order_by(Lead.score.desc()).all()
        finally:
            session.close()
