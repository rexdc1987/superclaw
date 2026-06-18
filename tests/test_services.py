"""Service层集成测试 — 使用内存数据库"""
import pytest
from models.database import get_session
from models.account import Account
from models.task import Task
from models.comment import Comment
from models.lead import Lead


class TestAccountService:
    def test_add_and_get(self):
        from services.account_service import AccountService
        svc = AccountService()
        acc = svc.add_account({"platform": "douyin", "username": "svc_user", "display_name": "服务测试"})
        assert acc.id is not None
        accounts = svc.get_accounts()
        assert len(accounts) >= 1

    def test_filter_by_platform(self):
        from services.account_service import AccountService
        svc = AccountService()
        svc.add_account({"platform": "douyin", "username": "dy_user"})
        svc.add_account({"platform": "kuaishou", "username": "ks_user"})
        dy = svc.get_accounts(platform="douyin")
        assert all(a.platform == "douyin" for a in dy)

    def test_update_account(self):
        from services.account_service import AccountService
        svc = AccountService()
        acc = svc.add_account({"platform": "douyin", "username": "upd_user"})
        updated = svc.update_account(acc.id, {"display_name": "更新后"})
        assert updated.display_name == "更新后"

    def test_delete_account(self):
        from services.account_service import AccountService
        svc = AccountService()
        acc = svc.add_account({"platform": "douyin", "username": "del_user"})
        assert svc.delete_account(acc.id) is True
        assert svc.delete_account(99999) is False

    def test_update_status(self):
        from services.account_service import AccountService
        svc = AccountService()
        acc = svc.add_account({"platform": "douyin", "username": "status_user"})
        svc.update_status(acc.id, "cooling", "test error")
        # Re-query through service to verify
        accounts = svc.get_accounts(platform="douyin")
        updated = [a for a in accounts if a.id == acc.id]
        assert len(updated) == 1
        assert updated[0].status == "cooling"

    def test_health_report(self):
        from services.account_service import AccountService
        svc = AccountService()
        svc.add_account({"platform": "douyin", "username": "h1"})
        svc.add_account({"platform": "douyin", "username": "h2"})
        report = svc.get_health_report()
        assert report["total"] >= 2
        assert "available" in report["by_status"]

    def test_group_crud(self):
        from services.account_service import AccountService
        svc = AccountService()
        g = svc.add_group("测试组_" + str(id(self)), "描述")
        assert g.id is not None
        groups = svc.get_groups()
        assert len(groups) >= 1
        assert svc.delete_group(g.id) is True


class TestTaskService:
    def _create_task(self):
        from services.task_service import TaskService
        svc = TaskService()
        return svc, svc.create_task({"name": "测试任务_" + str(id(self)), "platform": "douyin"})

    def test_create_task(self):
        svc, task = self._create_task()
        assert task.id is not None
        assert task.status == "draft"

    def test_task_lifecycle(self):
        svc, task = self._create_task()
        # draft -> pending -> running -> paused -> running -> completed
        from services.task_service import TaskService
        task = svc.update_task(task.id, {"status": "pending"})
        task = svc.start_task(task.id)
        assert task.status == "running"
        assert task.started_at is not None
        task = svc.pause_task(task.id)
        assert task.status == "paused"
        task = svc.resume_task(task.id)
        assert task.status == "running"
        task = svc.complete_task(task.id)
        assert task.status == "completed"
        assert task.completed_at is not None

    def test_invalid_transition(self):
        from core.exceptions import StateTransitionError
        svc, task = self._create_task()
        with pytest.raises(StateTransitionError):
            svc.complete_task(task.id)  # draft -> completed is invalid

    def test_cancel_task(self):
        svc, task = self._create_task()
        task = svc.cancel_task(task.id)
        assert task.status == "cancelled"

    def test_delete_task(self):
        svc, task = self._create_task()
        assert svc.delete_task(task.id) is True

    def test_get_statistics(self):
        svc, _ = self._create_task()
        stats = svc.get_statistics()
        assert stats["total"] >= 1
        assert "draft" in stats["by_status"]


class TestRiskService:
    def test_risk_rule_crud(self):
        from services.risk_service import RiskService
        svc = RiskService()
        rule = svc.add_risk_rule({"name": "日限_" + str(id(self)), "rule_type": "daily_limit", "platform": "all", "action_type": "comment"})
        assert rule.id is not None
        rules = svc.get_risk_rules()
        assert len(rules) >= 1
        assert svc.delete_risk_rule(rule.id) is True

    def test_sensitive_word_crud(self):
        from services.risk_service import RiskService
        svc = RiskService()
        word = "测试词_" + str(id(self))
        sw = svc.add_sensitive_word(word, "general")
        assert sw.id is not None
        words = svc.get_sensitive_words()
        assert len(words) >= 1
        found = svc.check_sensitive_words("这是一个" + word + "在句子里")
        assert word in found
        assert svc.delete_sensitive_word(sw.id) is True

    def test_blacklist_crud(self):
        from services.risk_service import RiskService
        svc = RiskService()
        uid = "bad_user_" + str(id(self))
        bl = svc.add_to_blacklist("douyin", uid, "spam")
        assert bl.id is not None
        assert svc.is_blacklisted("douyin", uid) is True
        assert svc.is_blacklisted("douyin", "good_user") is False
        assert svc.remove_from_blacklist(bl.id) is True

    def test_rate_limit(self):
        from services.risk_service import RiskService
        svc = RiskService()
        allowed, current, limit = svc.check_rate_limit(999, "comment")
        assert allowed is True
        assert current == 0

    def test_validate_action(self):
        from services.risk_service import RiskService
        svc = RiskService()
        svc.add_sensitive_word("违禁_" + str(id(self)), "general")
        word = "违禁_" + str(id(self))
        ok, reason = svc.validate_action("comment", "这是" + word + "内容", 1, "douyin")
        assert not ok
        assert "敏感词" in reason
        ok2, reason2 = svc.validate_action("comment", "正常内容", 1, "douyin")
        assert ok2


class TestActionService:
    def test_create_and_execute(self):
        from services.action_service import ActionService
        svc = ActionService()
        action = svc.create_action(task_id=1, action_type="comment", content="测试")
        assert action.status == "pending"
        executed = svc.execute_action(action.id, success=True)
        assert executed.status == "completed"
        assert executed.executed_at is not None

    def test_execute_failure(self):
        from services.action_service import ActionService
        svc = ActionService()
        action = svc.create_action(task_id=1, action_type="dm", content="私信")
        executed = svc.execute_action(action.id, success=False, error_message="发送失败")
        assert executed.status == "failed"
        assert executed.error_message == "发送失败"

    def test_batch_create(self):
        from services.action_service import ActionService
        svc = ActionService()
        actions = svc.batch_create(task_id=1, action_type="like", lead_ids=[1, 2, 3])
        assert len(actions) == 3
        assert all(a.status == "pending" for a in actions)

    def test_get_action_stats(self):
        from services.action_service import ActionService
        svc = ActionService()
        svc.create_action(task_id=10, action_type="comment")
        svc.create_action(task_id=10, action_type="like")
        stats = svc.get_action_stats(10)
        assert stats["total"] == 2
        assert "comment" in stats["by_type"]


class TestCollectorService:
    def _setup_comments(self):
        from services.collector_service import CollectorService
        svc = CollectorService()
        video = {"platform": "douyin", "video_id": "v1", "video_title": "测试视频", "video_url": "https://example.com"}
        comments_data = [
            {"author_id": "u1", "author_nickname": "用户1", "content": "我想买这个产品"},
            {"author_id": "u2", "author_nickname": "用户2", "content": "普通评论"},
            {"author_id": "u3", "author_nickname": "用户3", "content": "怎么购买啊"},
        ]
        saved = svc.collect_comments(task_id=1, video_data=video, comments_data=comments_data)
        return svc, saved

    def test_collect_comments(self):
        svc, saved = self._setup_comments()
        assert len(saved) == 3
        assert saved[0]["content"] == "我想买这个产品"

    def test_filter_target_comments(self):
        svc, _ = self._setup_comments()
        targets = svc.filter_target_comments(task_id=1, keywords=["买", "购买"])
        assert len(targets) == 2

    def test_filter_with_exclude(self):
        svc, _ = self._setup_comments()
        targets = svc.filter_target_comments(task_id=1, keywords=["买"], exclude_words=["不想"])
        assert len(targets) >= 1

    def test_deduplicate(self):
        from services.collector_service import CollectorService
        svc = CollectorService()
        video = {"platform": "douyin", "video_id": "v1", "video_title": "t", "video_url": ""}
        data = [
            {"author_id": "u_dup", "author_nickname": "用户1", "content": "c1"},
            {"author_id": "u_dup", "author_nickname": "用户1", "content": "c2"},
        ]
        svc.collect_comments(task_id=2, video_data=video, comments_data=data)
        removed = svc.deduplicate_comments(task_id=2)
        assert removed == 1

    def test_create_leads_from_comments(self):
        svc, _ = self._setup_comments()
        targets = svc.filter_target_comments(task_id=1, keywords=["买"])
        leads = svc.create_leads_from_comments(task_id=1, target_comments=targets)
        assert len(leads) >= 1
        assert leads[0].status == "new"

    def test_get_comments_paginated(self):
        svc, _ = self._setup_comments()
        result = svc.get_comments(task_id=1, page=1, page_size=2)
        assert result["total"] == 3
        assert len(result["items"]) == 2


class TestLeadService:
    def _create_lead(self, task_id=1, user_id="lead_u1"):
        from services.lead_service import LeadService
        svc = LeadService()
        lead = svc.create_lead({"task_id": task_id, "platform": "douyin", "user_id": user_id, "user_nickname": "线索"})
        return svc, lead

    def test_create_lead(self):
        svc, lead = self._create_lead()
        assert lead.id is not None
        assert lead.status == "new"

    def test_assign_lead(self):
        svc, lead = self._create_lead(user_id="assign_u")
        assert svc.assign_lead(lead.id, "sales_1") is True

    def test_update_status(self):
        svc, lead = self._create_lead(user_id="status_u")
        assert svc.update_status(lead.id, "contacted") is True

    def test_get_leads_paginated(self):
        svc, _ = self._create_lead(task_id=99, user_id="page_u")
        result = svc.get_leads(task_id=99, page=1, page_size=10)
        assert result["total"] >= 1

    def test_get_statistics(self):
        svc, _ = self._create_lead(task_id=50, user_id="stat_u")
        stats = svc.get_lead_statistics(task_id=50)
        assert stats["total"] >= 1
        assert "new" in stats["by_status"]
