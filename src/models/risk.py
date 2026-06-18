"""Risk model"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from models.database import Base


class RiskRule(Base):
    __tablename__ = "risk_rules"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    rule_type = Column(String(30), nullable=False)
    platform = Column(String(20), default="all")
    action_type = Column(String(20), default="all")
    config_json = Column(Text, default="{}")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SensitiveWord(Base):
    __tablename__ = "sensitive_words"
    id = Column(Integer, primary_key=True, autoincrement=True)
    word = Column(String(100), nullable=False, unique=True)
    category = Column(String(50), default="general")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Blacklist(Base):
    __tablename__ = "blacklist"
    id = Column(Integer, primary_key=True, autoincrement=True)
    platform = Column(String(20), nullable=False)
    user_id = Column(String(100), nullable=False)
    reason = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
