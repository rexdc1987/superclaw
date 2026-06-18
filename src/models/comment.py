"""Comment model"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from models.database import Base


class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, nullable=False, index=True)
    platform = Column(String(20), nullable=False)
    video_id = Column(String(100), default="")
    video_title = Column(String(500), default="")
    video_url = Column(String(500), default="")
    author_id = Column(String(100), default="", index=True)
    author_nickname = Column(String(200), default="")
    author_region = Column(String(100), default="")
    content = Column(Text, default="")
    comment_time = Column(DateTime, nullable=True)
    is_target = Column(Boolean, default=False)
    matched_keywords = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Comment {self.author_nickname}: {self.content[:30]}>"
