"""风控服务"""
from datetime import datetime, timedelta
from typing import List, Tuple
from models.database import get_session
from models.risk import RiskRule, SensitiveWord, Blacklist
from models.action import Action
from core.constants import DEFAULT_RATE_LIMITS, IndustryRiskLevel


class RiskService:
    def add_risk_rule(self, data):
        session = get_session()
        try:
            rule = RiskRule(**data)
            session.add(rule)
            session.commit()
            session.refresh(rule)
            return rule
        finally:
            session.close()

    def get_risk_rules(self, rule_type=None, platform=None) -> list:
        session = get_session()
        try:
            q = session.query(RiskRule).filter(RiskRule.is_active == True)
            if rule_type: q = q.filter(RiskRule.rule_type == rule_type)
            if platform: q = q.filter((RiskRule.platform == platform) | (RiskRule.platform == "all"))
            return q.all()
        finally:
            session.close()

    def delete_risk_rule(self, rule_id) -> bool:
        session = get_session()
        try:
            r = session.query(RiskRule).get(rule_id)
            if not r: return False
            session.delete(r)
            session.commit()
            return True
        finally:
            session.close()

    def add_sensitive_word(self, word, category="general"):
        session = get_session()
        try:
            sw = SensitiveWord(word=word, category=category)
            session.add(sw)
            session.commit()
            session.refresh(sw)
            return sw
        finally:
            session.close()

    def get_sensitive_words(self, category=None) -> list:
        session = get_session()
        try:
            q = session.query(SensitiveWord).filter(SensitiveWord.is_active == True)
            if category: q = q.filter(SensitiveWord.category == category)
            return q.all()
        finally:
            session.close()

    def check_sensitive_words(self, text) -> list:
        words = self.get_sensitive_words()
        return [w.word for w in words if w.word in text]

    def delete_sensitive_word(self, word_id) -> bool:
        session = get_session()
        try:
            sw = session.query(SensitiveWord).get(word_id)
            if not sw: return False
            session.delete(sw)
            session.commit()
            return True
        finally:
            session.close()

    def add_to_blacklist(self, platform, user_id, reason=""):
        session = get_session()
        try:
            bl = Blacklist(platform=platform, user_id=user_id, reason=reason)
            session.add(bl)
            session.commit()
            session.refresh(bl)
            return bl
        finally:
            session.close()

    def is_blacklisted(self, platform, user_id) -> bool:
        session = get_session()
        try:
            return session.query(Blacklist).filter(Blacklist.platform==platform, Blacklist.user_id==user_id).count() > 0
        finally:
            session.close()

    def get_blacklist(self, platform=None) -> list:
        session = get_session()
        try:
            q = session.query(Blacklist)
            if platform: q = q.filter(Blacklist.platform == platform)
            return q.all()
        finally:
            session.close()

    def remove_from_blacklist(self, bl_id) -> bool:
        session = get_session()
        try:
            bl = session.query(Blacklist).get(bl_id)
            if not bl: return False
            session.delete(bl)
            session.commit()
            return True
        finally:
            session.close()

    def check_rate_limit(self, account_id, action_type) -> Tuple:
        limits = DEFAULT_RATE_LIMITS.get(action_type, {})
        max_per_hour = limits.get("max_per_hour", 999)
        session = get_session()
        try:
            one_hour_ago = datetime.utcnow() - timedelta(hours=1)
            count = session.query(Action).filter(
                Action.account_id == account_id, Action.action_type == action_type,
                Action.executed_at >= one_hour_ago, Action.status == "completed").count()
            return (count < max_per_hour, count, max_per_hour)
        finally:
            session.close()

    def validate_action(self, action_type, content, account_id, platform, target_user_id=None) -> Tuple:
        matched = self.check_sensitive_words(content)
        if matched: return (False, f"敏感词: {', '.join(matched)}")
        if target_user_id and self.is_blacklisted(platform, target_user_id):
            return (False, "用户在黑名单中")
        allowed, current, limit = self.check_rate_limit(account_id, action_type)
        if not allowed: return (False, f"频控: {action_type} 近1小时{current}次，上限{limit}")
        return (True, "通过")

    # ── 行业风控分级 ──

    def set_industry_risk_level(self, task_id: int, risk_level: str):
        """设置任务的行业风险等级（存入 risk_rules 表）"""
        session = get_session()
        try:
            # Upsert: check if rule exists for this task
            existing = session.query(RiskRule).filter(
                RiskRule.rule_type == "industry_risk",
                RiskRule.config_json.contains(f'"task_id": {task_id}'),
            ).first()
            if existing:
                import json
                cfg = json.loads(existing.config_json or "{}")
                cfg["risk_level"] = risk_level
                existing.config_json = json.dumps(cfg, ensure_ascii=False)
            else:
                import json
                rule = RiskRule(
                    name=f"industry_risk_task_{task_id}",
                    rule_type="industry_risk",
                    platform="all",
                    action_type="all",
                    config_json=json.dumps({"task_id": task_id, "risk_level": risk_level}, ensure_ascii=False),
                )
                session.add(rule)
            session.commit()
        finally:
            session.close()

    def get_industry_risk_level(self, task_id: int) -> str:
        """获取任务的行业风险等级，默认 LOW"""
        session = get_session()
        try:
            import json
            rules = session.query(RiskRule).filter(
                RiskRule.rule_type == "industry_risk",
                RiskRule.is_active == True,
            ).all()
            for r in rules:
                cfg = json.loads(r.config_json or "{}")
                if cfg.get("task_id") == task_id:
                    return cfg.get("risk_level", IndustryRiskLevel.LOW.value)
            return IndustryRiskLevel.LOW.value
        finally:
            session.close()

    def validate_action_by_risk_level(self, action_type: str, risk_level: str) -> Tuple[bool, str]:
        """
        按行业风险等级校验动作是否允许:
        - LOW: 全部动作可用
        - MEDIUM: 可私信但需内容审核（调用方需额外审核）
        - HIGH: 仅 like/follow/favorite，禁止 dm/comment/reply
        """
        risk = IndustryRiskLevel(risk_level) if risk_level in [e.value for e in IndustryRiskLevel] else IndustryRiskLevel.LOW

        if risk == IndustryRiskLevel.LOW:
            return (True, "LOW风险：全部动作可用")

        if risk == IndustryRiskLevel.MEDIUM:
            if action_type == "dm":
                return (True, "MEDIUM风险：私信需要内容审核")
            return (True, f"MEDIUM风险：{action_type} 可执行")

        # HIGH risk
        allowed_stealth = {"like", "follow", "favorite"}
        if action_type in allowed_stealth:
            return (True, f"HIGH风险：{action_type} 允许（留痕模式）")
        return (False, f"HIGH风险：{action_type} 被禁止，仅允许留痕操作(点赞/关注/收藏)")
