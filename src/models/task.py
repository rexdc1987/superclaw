"""Task model"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from models.database import Base


class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    status = Column(String(20), default="draft")
    priority = Column(Integer, default=0)
    platform = Column(String(20), nullable=False)
    account_group_id = Column(Integer, nullable=True)
    keyword_group_id = Column(Integer, nullable=True)
    playbook_id = Column(Integer, nullable=True)
    search_config_json = Column(Text, default="{}")
    filter_config_json = Column(Text, default="{}")
    action_config_json = Column(Text, default="{}")
    rhythm_config_json = Column(Text, default="{}")
    progress_total = Column(Integer, default=0)
    progress_done = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<Task {self.name} [{self.status}]>"

    @property
    def progress_percent(self):
        if self.progress_total == 0:
            return 0
        return round(self.progress_done / self.progress_total * 100, 1)
