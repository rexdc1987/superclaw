"""Strategy service 测试"""
import pytest
import json


class TestStrategyService:
    def _svc(self):
        from services.strategy_service import StrategyService
        return StrategyService()

    def test_create_and_get(self):
        svc = self._svc()
        st = svc.create_strategy({
            "name": "测试策略_" + str(id(self)),
            "platform": "douyin",
            "rules": [
                {"name": "精准层", "keywords": ["买"], "template_id": None, "priority": 1},
                {"name": "广泛层", "keywords": ["*"], "template_id": None, "priority": 2},
            ],
        })
        assert st.id is not None
        assert "精准层" in st.rules_json
        strategies = svc.get_strategies()
        assert any(s.id == st.id for s in strategies)

    def test_delete(self):
        svc = self._svc()
        st = svc.create_strategy({"name": "del_" + str(id(self)), "rules": []})
        assert svc.delete_strategy(st.id) is True
        assert svc.delete_strategy(99999) is False

    def test_match_precision_layer(self):
        svc = self._svc()
        st = svc.create_strategy({
            "name": "match_test_" + str(id(self)),
            "rules": [
                {"name": "精准层", "keywords": ["买", "购买", "多少钱"], "template_id": None, "priority": 1},
                {"name": "广泛层", "keywords": ["*"], "template_id": None, "priority": 2},
            ],
        })
        rule = svc.match_strategy("这个多少钱啊", st.id)
        assert rule is not None
        assert rule["name"] == "精准层"

    def test_match_broad_layer(self):
        svc = self._svc()
        st = svc.create_strategy({
            "name": "broad_test_" + str(id(self)),
            "rules": [
                {"name": "精准层", "keywords": ["买"], "template_id": None, "priority": 1},
                {"name": "广泛层", "keywords": ["*"], "template_id": None, "priority": 2},
            ],
        })
        rule = svc.match_strategy("好视频啊", st.id)
        assert rule is not None
        assert rule["name"] == "广泛层"

    def test_match_no_strategy(self):
        svc = self._svc()
        result = svc.match_strategy("test", 99999)
        assert result is None

    def test_execute_strategy(self):
        from services.task_service import TaskService
        from services.lead_service import LeadService

        task = TaskService().create_task({"name": "strat_exec_" + str(id(self)), "platform": "douyin"})
        lsvc = LeadService()
        # Precision lead (has keyword "买")
        l1 = lsvc.create_lead({"task_id": task.id, "platform": "douyin", "user_id": "p_u1"})
        # Broad lead (no keyword)
        l2 = lsvc.create_lead({"task_id": task.id, "platform": "douyin", "user_id": "b_u1"})

        # We need to set lead content for matching - use lead notes field as proxy
        from models.database import get_session
        from models.lead import Lead
        session = get_session()
        try:
            lead1 = session.get(Lead, l1.id)
            lead1.notes = "我想买这个产品"
            lead2 = session.get(Lead, l2.id)
            lead2.notes = "好视频"
            session.commit()
        finally:
            session.close()

        svc = self._svc()
        st = svc.create_strategy({
            "name": "exec_" + str(id(self)),
            "rules": [
                {"name": "精准层", "keywords": ["买", "购买"], "template_id": None, "priority": 1},
                {"name": "广泛层", "keywords": ["*"], "template_id": None, "priority": 2},
            ],
        })

        result = svc.execute_strategy(task.id, st.id)
        assert result["success"] is True
        assert result["precision_count"] == 1
        assert result["broad_count"] == 1
        assert result["total_actions"] == 2

    def test_default_rules_available(self):
        from services.strategy_service import DEFAULT_RULES
        assert len(DEFAULT_RULES) == 2
        assert DEFAULT_RULES[0]["name"] == "精准层"
        assert DEFAULT_RULES[1]["name"] == "广泛层"
        assert "*" in DEFAULT_RULES[1]["keywords"]
