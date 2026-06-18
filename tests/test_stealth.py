"""Stealth service 测试"""
import pytest


class TestStealthService:
    def _svc(self):
        from services.stealth_service import StealthService
        return StealthService()

    def test_execute_stealth_task_no_leads(self):
        """无适配器无线索时返回空结果"""
        from services.task_service import TaskService
        task = TaskService().create_task({"name": "stealth_empty_" + str(id(self)), "platform": "douyin"})
        result = self._svc().execute_stealth_task(task.id)
        assert result["mode"] == "stealth"
        assert result["success"] is False
        assert "No leads" in result["error"]

    def test_execute_stealth_task_with_leads(self):
        """有线索时创建 like + follow + favorite 动作"""
        from services.task_service import TaskService
        from services.lead_service import LeadService
        from services.stealth_service import StealthService

        task = TaskService().create_task({"name": "stealth_leads_" + str(id(self)), "platform": "douyin"})
        svc = LeadService()
        l1 = svc.create_lead({"task_id": task.id, "platform": "douyin", "user_id": "su1"})
        l2 = svc.create_lead({"task_id": task.id, "platform": "douyin", "user_id": "su2"})

        result = StealthService().execute_stealth_task(task.id)
        assert result["success"] is True
        assert result["users_processed"] == 2
        assert result["actions_created"] == 6  # 2 users x 3 action types

    def test_stealth_actions_only_three_types(self):
        """留痕操作只创建 like/follow/favorite"""
        from services.stealth_service import StealthService
        svc = StealthService()
        assert set(svc.STEALTH_ACTION_TYPES) == {"like", "follow", "favorite"}

    def test_get_stealth_stats(self):
        from services.task_service import TaskService
        from services.lead_service import LeadService
        from services.stealth_service import StealthService

        task = TaskService().create_task({"name": "stealth_stats_" + str(id(self)), "platform": "douyin"})
        svc = LeadService()
        svc.create_lead({"task_id": task.id, "platform": "douyin", "user_id": "stat_u"})
        StealthService().execute_stealth_task(task.id)

        stats = StealthService().get_stealth_stats(task.id)
        assert stats["total_actions"] == 3
        assert stats["by_type"]["like"] == 1
        assert stats["by_type"]["follow"] == 1
        assert stats["by_type"]["favorite"] == 1
