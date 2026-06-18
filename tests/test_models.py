"""数据库模型层测试"""
import pytest
import models.database as db_module  # use module reference for monkeypatch
from models.account import Account, AccountGroup
from models.task import Task
from models.comment import Comment
from models.lead import Lead
from models.action import Action
from models.risk import RiskRule, SensitiveWord, Blacklist
from models.audit import ExecutionLog, AuditLog


class TestAccountModel:
    def test_create_account(self):
        session = db_module.get_session()
        try:
            acc = Account(platform="douyin", username="test_user", display_name="测试用户")
            session.add(acc)
            session.commit()
            session.refresh(acc)
            assert acc.id is not None
            assert acc.status == "available"
        finally:
            session.close()

    def test_account_group(self):
        session = db_module.get_session()
        try:
            group = AccountGroup(name="测试组_" + str(id(self)), description="测试描述")
            session.add(group)
            session.commit()
            session.refresh(group)
            assert group.id is not None
        finally:
            session.close()

    def test_account_is_available(self):
        session = db_module.get_session()
        try:
            acc = Account(platform="douyin", username="u1_isavail")
            session.add(acc)
            session.commit()
            session.refresh(acc)
            assert acc.is_available()
            acc.status = "cooling"
            assert not acc.is_available()
        finally:
            session.close()

    def test_reset_daily_counters(self):
        acc = Account(platform="douyin", username="u1", daily_comment_count=10, daily_dm_count=5)
        acc.reset_daily_counters()
        assert acc.daily_comment_count == 0
        assert acc.daily_dm_count == 0

    def test_record_action(self):
        acc = Account(platform="douyin", username="u1", daily_comment_count=0, daily_dm_count=0, daily_follow_count=0)
        acc.record_action("comment")
        assert acc.daily_comment_count == 1
        assert acc.last_active_at is not None
        acc.record_action("dm")
        assert acc.daily_dm_count == 1
        acc.record_action("follow")
        assert acc.daily_follow_count == 1


class TestTaskModel:
    def test_create_task(self):
        session = db_module.get_session()
        try:
            task = Task(name="测试任务", platform="douyin")
            session.add(task)
            session.commit()
            session.refresh(task)
            assert task.id is not None
            assert task.status == "draft"
        finally:
            session.close()

    def test_progress_percent(self):
        task = Task(name="t", platform="douyin", progress_total=100, progress_done=50)
        assert task.progress_percent == 50.0
        task2 = Task(name="t2", platform="douyin", progress_total=0, progress_done=0)
        assert task2.progress_percent == 0


class TestCommentModel:
    def test_create_comment(self):
        session = db_module.get_session()
        try:
            c = Comment(task_id=1, platform="douyin", author_id="u123", author_nickname="用户", content="好视频")
            session.add(c)
            session.commit()
            session.refresh(c)
            assert c.id is not None
            assert c.is_target is False
        finally:
            session.close()


class TestLeadModel:
    def test_create_lead(self):
        session = db_module.get_session()
        try:
            lead = Lead(task_id=1, platform="douyin", user_id="u1", user_nickname="线索用户")
            session.add(lead)
            session.commit()
            session.refresh(lead)
            assert lead.id is not None
            assert lead.status == "new"
            assert lead.score == 0.0
        finally:
            session.close()


class TestActionModel:
    def test_create_action(self):
        session = db_module.get_session()
        try:
            action = Action(task_id=1, action_type="comment", content="测试评论")
            session.add(action)
            session.commit()
            session.refresh(action)
            assert action.id is not None
            assert action.status == "pending"
        finally:
            session.close()


class TestRiskModel:
    def test_risk_rule(self):
        session = db_module.get_session()
        try:
            rule = RiskRule(name="日限50_" + str(id(self)), rule_type="daily_limit", platform="all", action_type="comment")
            session.add(rule)
            session.commit()
            session.refresh(rule)
            assert rule.id is not None
            assert rule.is_active is True
        finally:
            session.close()

    def test_sensitive_word(self):
        session = db_module.get_session()
        try:
            sw = SensitiveWord(word="敏感词_" + str(id(self)), category="general")
            session.add(sw)
            session.commit()
            session.refresh(sw)
            assert sw.id is not None
        finally:
            session.close()

    def test_blacklist(self):
        session = db_module.get_session()
        try:
            bl = Blacklist(platform="douyin", user_id="bad_user_" + str(id(self)), reason="spam")
            session.add(bl)
            session.commit()
            session.refresh(bl)
            assert bl.id is not None
        finally:
            session.close()


class TestAuditModel:
    def test_execution_log(self):
        session = db_module.get_session()
        try:
            log = ExecutionLog(task_id=1, level="info", message="测试日志")
            session.add(log)
            session.commit()
            session.refresh(log)
            assert log.id is not None
        finally:
            session.close()

    def test_audit_log(self):
        session = db_module.get_session()
        try:
            log = AuditLog(user="admin", action="create_task", target_type="task", target_id="1")
            session.add(log)
            session.commit()
            session.refresh(log)
            assert log.id is not None
        finally:
            session.close()
