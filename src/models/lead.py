"""Lead model"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean
from models.database import Base


class Lead(Base):
    __tablename__ = "leads"
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, nullable=False, index=True)
    platform = Column(String(20), nullable=False)
    user_id = Column(String(100), nullable=False, index=True)
    user_nickname = Column(String(200), default="")
    user_region = Column(String(100), default="")
    user_ip_location = Column(String(100), default="")
    account_type = Column(String(20), default="personal")
    follower_count = Column(Integer, default=0)
    is_following = Column(Boolean, default=False)
    last_active_at = Column(DateTime, nullable=True)
    user_avatar_url = Column(String(500), default="")
    source_comment_id = Column(Integer, nullable=True)
    score = Column(Float, default=0.0)
    score_details_json = Column(Text, default="{}")
    status = Column(String(20), default="new")
    assigned_to = Column(String(100), nullable=True)
    last_contacted_at = Column(DateTime, nullable=True)
    contact_count = Column(Integer, default=0)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Lead {self.user_nickname} score={self.score} [{self.status}]>"
