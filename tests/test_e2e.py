"""E2E工作流测试 — 模拟完整业务流程（不依赖外部网络）"""
import pytest
from models.database import get_session


def _start_task(svc, task):
    """Helper: draft -> pending -> running"""
    task = svc.update_task(task.id, {"status": "pending"})
    return svc.start_task(task.id)


class TestE2ECollectAndScore:
    """模拟: 创建任务 -> 采集评论 -> 过滤目标 -> 生成线索 -> 评分"""

    def test_full_pipeline(self):
        from services.task_service import TaskService
        from services.collector_service import CollectorService
        from services.lead_service import LeadService
        from services.risk_service import RiskService
        from services.action_service import ActionService

        task_svc = TaskService()
        collector = CollectorService()
        lead_svc = LeadService()
        risk_svc = RiskService()
        action_svc = ActionService()

        # Step 1: 创建任务
        task = task_svc.create_task({"name": "E2E测试任务_" + str(id(self)), "platform": "douyin"})
        assert task.status == "draft"
        task = _start_task(task_svc, task)
        assert task.status == "running"

        # Step 2: 模拟采集评论
        video = {"platform": "douyin", "video_id": "vid_001", "video_title": "产品测评", "video_url": "https://dy.com/v/001"}
        comments_data = [
            {"author_id": "user_a", "author_nickname": "Alice", "content": "这个产品怎么买？"},
            {"author_id": "user_b", "author_nickname": "Bob", "content": "太贵了吧"},
            {"author_id": "user_c", "author_nickname": "Charlie", "content": "求购买链接"},
            {"author_id": "user_d", "author_nickname": "Dave", "content": "路过看看"},
            {"author_id": "user_e", "author_nickname": "Eve", "content": "我也想买一个"},
        ]
        saved = collector.collect_comments(task.id, video, comments_data)
        assert len(saved) == 5

        # Step 3: 过滤目标评论
        targets = collector.filter_target_comments(task.id, keywords=["买", "购买", "链接"])
        assert len(targets) == 3  # Alice, Charlie, Eve

        # Step 4: 生成线索
        leads = collector.create_leads_from_comments(task.id, targets)
        assert len(leads) == 3
        assert all(l.status == "new" for l in leads)

        # Step 5: 评分
        scored = lead_svc.score_leads(task.id, strong_keywords=["买", "购买"])
        assert scored == 3

        # Step 6: 验证评分结果
        result = lead_svc.get_leads(task_id=task.id)
        assert result["total"] == 3
        for lead in result["items"]:
            assert lead.score > 0

        # Step 7: 风控验证
        ok, reason = risk_svc.validate_action("comment", "感谢关注我们的产品", 1, "douyin")
        assert ok

        # Step 8: 创建并执行动作
        lead_ids = [l.id for l in leads]
        actions = action_svc.batch_create(task.id, lead_ids, action_type="comment", contents="感谢关注")
        assert len(actions) == 3
        for a in actions:
            executed = action_svc.execute_action(a.id, success=True)
            assert executed.status == "completed"

        # Step 9: 完成任务
        task = task_svc.complete_task(task.id)
        assert task.status == "completed"

        # Step 10: 统计验证
        task_stats = task_svc.get_statistics()
        assert task_stats["by_status"].get("completed", 0) >= 1

        lead_stats = lead_svc.get_lead_statistics(task.id)
        assert lead_stats["total"] == 3

        action_stats = action_svc.get_action_stats(task.id)
        assert action_stats["total"] == 3
        assert action_stats["by_status"].get("completed", 0) == 3


class TestE2EWithRiskControl:
    """模拟: 风控拦截场景"""

    def test_sensitive_word_blocks_action(self):
        from services.risk_service import RiskService
        svc = RiskService()
        word = "赌博_" + str(id(self))
        svc.add_sensitive_word(word, "abuse")
        ok, reason = svc.validate_action("comment", "来" + word + "网站看看", 1, "douyin")
        assert not ok
        assert "敏感词" in reason

    def test_blacklist_blocks_action(self):
        from services.risk_service import RiskService
        svc = RiskService()
        uid = "spammer_" + str(id(self))
        svc.add_to_blacklist("douyin", uid, "发广告")
        ok, reason = svc.validate_action("comment", "正常内容", 1, "douyin", target_user_id=uid)
        assert not ok
        assert "黑名单" in reason

    def test_normal_action_passes(self):
        from services.risk_service import RiskService
        svc = RiskService()
        ok, reason = svc.validate_action("comment", "好视频，支持！", 1, "douyin")
        assert ok
        assert reason == "通过"


class TestE2ETaskStateMachine:
    """模拟: 任务状态机完整路径"""

    def test_draft_to_completed(self):
        from services.task_service import TaskService
        svc = TaskService()
        t = svc.create_task({"name": "状态机测试_" + str(id(self)), "platform": "douyin"})
        t = svc.update_task(t.id, {"status": "pending"})  # draft -> pending
        t = svc.start_task(t.id)    # pending -> running
        t = svc.pause_task(t.id)    # running -> paused
        t = svc.resume_task(t.id)   # paused -> running
        t = svc.complete_task(t.id) # running -> completed
        assert t.status == "completed"

    def test_draft_to_cancelled(self):
        from services.task_service import TaskService
        svc = TaskService()
        t = svc.create_task({"name": "取消测试_" + str(id(self)), "platform": "douyin"})
        t = svc.cancel_task(t.id)
        assert t.status == "cancelled"

    def test_running_to_failed(self):
        from services.task_service import TaskService
        svc = TaskService()
        t = svc.create_task({"name": "失败测试_" + str(id(self)), "platform": "douyin"})
        t = _start_task(svc, t)
        t = svc.fail_task(t.id)
        assert t.status == "failed"

    def test_failed_can_retry(self):
        from services.task_service import TaskService
        svc = TaskService()
        t = svc.create_task({"name": "重试测试_" + str(id(self)), "platform": "douyin"})
        t = _start_task(svc, t)
        t = svc.fail_task(t.id)
        assert t.status == "failed"
        # failed -> pending -> running (retry path)
        t = svc.update_task(t.id, {"status": "pending"})
        t = svc.start_task(t.id)
        assert t.status == "running"
