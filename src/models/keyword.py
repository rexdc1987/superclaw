"""Keyword model"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from models.database import Base


class KeywordGroup(Base):
    __tablename__ = "keyword_groups"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    keywords = Column(Text, default="[]")
    rotate_after_n_videos = Column(Integer, default=5)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<KeywordGroup {self.name}>"
