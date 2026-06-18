"""constants 单元测试"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from core.constants import (
    Platform, AccountStatus, TaskStatus, ActionType,
    LeadStatus, SCORE_WEIGHTS, DEFAULT_RATE_LIMITS,
)


class TestPlatform:
    def test_values(self):
        assert Platform.DOUYIN == "douyin"
        assert Platform.XIAOHONGSHU == "xiaohongshu"
        assert Platform.KUAISHOU == "kuaishou"
        assert Platform.BILIBILI == "bilibili"


class TestTaskStatus:
    def test_transitions(self):
        assert TaskStatus.DRAFT.can_transition_to(TaskStatus.PENDING)
        assert not TaskStatus.DRAFT.can_transition_to(TaskStatus.COMPLETED)
        assert TaskStatus.RUNNING.can_transition_to(TaskStatus.PAUSED)
        assert TaskStatus.RUNNING.can_transition_to(TaskStatus.COMPLETED)
        assert not TaskStatus.COMPLETED.can_transition_to(TaskStatus.RUNNING)

    def test_all_statuses_exist(self):
        assert len(TaskStatus) >= 7


class TestActionType:
    def test_values(self):
        assert ActionType.COMMENT == "comment"
        assert ActionType.REPLY == "reply"
        assert ActionType.DM == "dm"


class TestConstants:
    def test_score_weights(self):
        assert "strong_intent_keyword" in SCORE_WEIGHTS
        assert SCORE_WEIGHTS["strong_intent_keyword"] > 0
        assert SCORE_WEIGHTS["already_contacted"] < 0

    def test_rate_limits(self):
        assert "comment" in DEFAULT_RATE_LIMITS
        assert "dm" in DEFAULT_RATE_LIMITS
        assert DEFAULT_RATE_LIMITS["comment"]["max_per_hour"] > 0
