"""账号和账号组模型"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from models.database import Base


class AccountGroup(Base):
    __tablename__ = "account_groups"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, default="")
    accounts = relationship("Account", backref="group")

    def __repr__(self):
        return f"<AccountGroup {self.name}>"


class Account(Base):
    __tablename__ = "accounts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String(20), nullable=False)
    username = Column(String(100), nullable=False)
    display_name = Column(String(200), default="")
    status = Column(String(20), default="available")
    account_group_id = Column(Integer, ForeignKey("account_groups.id"), nullable=True)
    browser_profile_path = Column(String(500), default="")
    daily_comment_count = Column(Integer, default=0)
    daily_dm_count = Column(Integer, default=0)
    daily_follow_count = Column(Integer, default=0)
    daily_fail_count = Column(Integer, default=0)
    last_active_at = Column(DateTime, nullable=True)
    error_message = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Account {self.platform}/{self.username} [{self.status}]>"

    def is_available(self):
        return self.status == "available"

    def reset_daily_counters(self):
        self.daily_comment_count = 0
        self.daily_dm_count = 0
        self.daily_follow_count = 0
        self.daily_fail_count = 0

    def record_action(self, action_type):
        self.last_active_at = datetime.utcnow()
        if action_type == "comment":
            self.daily_comment_count += 1
        elif action_type == "dm":
            self.daily_dm_count += 1
        elif action_type == "follow":
            self.daily_follow_count += 1
