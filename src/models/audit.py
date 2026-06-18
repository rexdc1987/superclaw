"""Audit model"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from models.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user = Column(String(100), default="system")
    action = Column(String(50), nullable=False)
    target_type = Column(String(50), default="")
    target_id = Column(Integer, nullable=True)
    details_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)


class ExecutionLog(Base):
    __tablename__ = "execution_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, nullable=True, index=True)
    action_id = Column(Integer, nullable=True)
    level = Column(String(10), default="info")
    message = Column(Text, nullable=False)
    details_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
