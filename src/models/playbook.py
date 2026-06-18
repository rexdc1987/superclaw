"""Playbook model — 打法模板"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from models.database import Base


class Playbook(Base):
    __tablename__ = "playbooks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    playbook_type = Column(String(30), nullable=False)
    search_config_json = Column(Text, default="{}")
    action_config_json = Column(Text, default="{}")
    filter_config_json = Column(Text, default="{}")
    risk_level = Column(String(10), default="low")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Playbook {self.name} [{self.playbook_type}]>"
