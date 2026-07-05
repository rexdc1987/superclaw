"""Hongguo Comment Record model"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from models.database import Base


class HongguoRecord(Base):
    __tablename__ = "hongguo_comment_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("hongguo_comment_tasks.id"), nullable=False)

    # 评论详情
    episode_number = Column(Integer, nullable=False, comment="评论所在集数")
    episode_title = Column(String(200), nullable=True, comment="集数标题")
    comment_text = Column(Text, nullable=False, comment="评论内容")
    generated_by = Column(String(20), nullable=True, comment="生成方式: ai/template/mixed")

    # 执行结果
    status = Column(String(20), default="sending", comment="sending/sent/verified/failed")
    sent_at = Column(DateTime, nullable=True, comment="发送时间")
    verified_at = Column(DateTime, nullable=True, comment="验证时间")

    # 截图证据
    screenshot_input = Column(String(500), nullable=True, comment="输入评论截图路径")
    screenshot_sent = Column(String(500), nullable=True, comment="发送成功截图路径")
    screenshot_verified = Column(String(500), nullable=True, comment="验证截图路径")

    # 错误
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.now)

    def __repr__(self):
        return f"<HongguoRecord ep{self.episode_number} [{self.status}]>"

    @property
    def is_verified(self):
        return self.status == "verified"
