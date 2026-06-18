"""Risk service 增强测试 — 行业风控分级"""
import pytest
from core.constants import IndustryRiskLevel


class TestIndustryRiskLevel:
    def test_enum_values(self):
        assert IndustryRiskLevel.LOW.value == "low"
        assert IndustryRiskLevel.MEDIUM.value == "medium"
        assert IndustryRiskLevel.HIGH.value == "high"

    def test_set_and_get_risk_level(self):
        from services.risk_service import RiskService
        svc = RiskService()
        svc.set_industry_risk_level(8001, "high")
        level = svc.get_industry_risk_level(8001)
        assert level == "high"

    def test_default_risk_level_is_low(self):
        from services.risk_service import RiskService
        svc = RiskService()
        level = svc.get_industry_risk_level(99999)
        assert level == "low"

    def test_upsert_risk_level(self):
        from services.risk_service import RiskService
        svc = RiskService()
        svc.set_industry_risk_level(8002, "low")
        svc.set_industry_risk_level(8002, "high")  # upsert
        level = svc.get_industry_risk_level(8002)
        assert level == "high"

    def test_validate_low_risk_all_actions_allowed(self):
        from services.risk_service import RiskService
        svc = RiskService()
        for action in ["comment", "dm", "like", "follow", "favorite", "reply"]:
            ok, msg = svc.validate_action_by_risk_level(action, "low")
            assert ok

    def test_validate_medium_risk_dm_needs_review(self):
        from services.risk_service import RiskService
        svc = RiskService()
        ok, msg = svc.validate_action_by_risk_level("dm", "medium")
        assert ok
        assert "审核" in msg
        ok2, msg2 = svc.validate_action_by_risk_level("comment", "medium")
        assert ok2

    def test_validate_high_risk_stealth_only(self):
        from services.risk_service import RiskService
        svc = RiskService()
        # Stealth actions allowed
        for action in ["like", "follow", "favorite"]:
            ok, msg = svc.validate_action_by_risk_level(action, "high")
            assert ok
        # Non-stealth actions blocked
        for action in ["comment", "dm", "reply"]:
            ok, msg = svc.validate_action_by_risk_level(action, "high")
            assert not ok
            assert "HIGH风险" in msg

    def test_invalid_risk_level_defaults_to_low(self):
        from services.risk_service import RiskService
        svc = RiskService()
        ok, msg = svc.validate_action_by_risk_level("dm", "unknown_level")
        assert ok
        assert "LOW" in msg
