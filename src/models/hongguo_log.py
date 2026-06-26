"""Hongguo Execution Log model"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from models.database import Base


class HongguoLog(Base):
    __tablename__ = "hongguo_execution_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("hongguo_comment_tasks.id"), nullable=False)

    level = Column(String(10), default="info", comment="info/warn/error/success")
    message = Column(Text, nullable=False, comment="日志消息")
    screenshot_path = Column(String(500), nullable=True, comment="关联截图路径")

    created_at = Column(DateTime, default=datetime.now)

    def __repr__(self):
        return f"<HongguoLog [{self.level}] {self.message[:30]}>"
