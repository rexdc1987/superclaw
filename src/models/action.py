"""Action model"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from models.database import Base


class Action(Base):
    __tablename__ = "actions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, nullable=False, index=True)
    lead_id = Column(Integer, nullable=True)
    action_type = Column(String(20), nullable=False)
    account_id = Column(Integer, nullable=True)
    content = Column(Text, default="")
    template_id = Column(Integer, nullable=True)
    mention_user = Column(String(100), default="")
    image_path = Column(String(500), default="")
    status = Column(String(20), default="pending")
    error_message = Column(Text, default="")
    executed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Action {self.action_type} [{self.status}]>"
