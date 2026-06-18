"""SuperClaw Constants and Enums"""
from enum import Enum


class Platform(str, Enum):
    DOUYIN = "douyin"
    XIAOHONGSHU = "xiaohongshu"
    KUAISHOU = "kuaishou"
    BILIBILI = "bilibili"


class AccountStatus(str, Enum):
    AVAILABLE = "available"
    COOLING = "cooling"
    LOGIN_EXPIRED = "login_expired"
    ERROR = "error"
    RESTRICTED = "restricted"


class TaskStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REVIEWING = "reviewing"

    @classmethod
    def allowed_transitions(cls):
        return {
            cls.DRAFT: [cls.PENDING, cls.CANCELLED],
            cls.PENDING: [cls.RUNNING, cls.CANCELLED],
            cls.RUNNING: [cls.PAUSED, cls.COMPLETED, cls.FAILED],
            cls.PAUSED: [cls.RUNNING, cls.CANCELLED],
            cls.FAILED: [cls.PENDING, cls.CANCELLED],
            cls.COMPLETED: [],
            cls.CANCELLED: [],
            cls.REVIEWING: [cls.PENDING, cls.CANCELLED],
        }

    def can_transition_to(self, target):
        return target in self.allowed_transitions().get(self, [])


class PlaybookType(str, Enum):
    AUTO_EXPOSURE = "auto_exposure"
    TARGETED_EXPOSURE = "targeted_exposure"
    LINK_EXPOSURE = "link_exposure"
    ACCOUNT_SEARCH = "account_search"
    STEALTH_EXPOSURE = "stealth_exposure"


class IndustryRiskLevel(str, Enum):
    LOW = "low"          # 装修/教育/餐饮 - 全部动作可用
    MEDIUM = "medium"    # 电商/本地生活 - 可私信但需内容审核
    HIGH = "high"        # 医美/金融/保险 - 仅点赞+关注+收藏，禁止私信


class ActionType(str, Enum):
    COMMENT = "comment"
    REPLY = "reply"
    LIKE = "like"
    FOLLOW = "follow"
    FAVORITE = "favorite"
    DM = "dm"
    AT_USER = "at_user"
    SEND_IMAGE = "send_image"


class LeadStatus(str, Enum):
    NEW = "new"
    CONTACTED = "contacted"
    REPLIED = "replied"
    CONVERTED = "converted"
    LOST = "lost"


class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


SCORE_WEIGHTS = {
    "strong_intent_keyword": 30,
    "weak_intent_keyword": 15,
    "recent_7_days": 20,
    "recent_30_days": 10,
    "user_replied": 20,
    "already_contacted": -20,
    "exclude_keyword": -100,
}

DEFAULT_RATE_LIMITS = {
    "comment": {"max_per_hour": 20, "max_per_day": 100, "interval_seconds": 30},
    "reply": {"max_per_hour": 30, "max_per_day": 150, "interval_seconds": 20},
    "like": {"max_per_hour": 50, "max_per_day": 300, "interval_seconds": 10},
    "follow": {"max_per_hour": 10, "max_per_day": 50, "interval_seconds": 60},
    "dm": {"max_per_hour": 5, "max_per_day": 30, "interval_seconds": 120},
    "favorite": {"max_per_hour": 30, "max_per_day": 200, "interval_seconds": 15},
}
