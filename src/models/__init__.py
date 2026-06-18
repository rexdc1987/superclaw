"""Import all models so Base.metadata knows about every table."""
from models.account import AccountGroup, Account
from models.task import Task
from models.lead import Lead
from models.action import Action
from models.template import MessageTemplate, Material
from models.risk import RiskRule, SensitiveWord, Blacklist
from models.audit import AuditLog, ExecutionLog
from models.comment import Comment
from models.keyword import KeywordGroup
from models.user import User

__all__ = [
    "AccountGroup", "Account",
    "Task", "Lead", "Action",
    "MessageTemplate", "Material",
    "RiskRule", "SensitiveWord", "Blacklist",
    "AuditLog", "ExecutionLog",
    "Comment", "KeywordGroup",
    "User",
]
