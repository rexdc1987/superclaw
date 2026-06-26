"""Hongguo Comment Task model"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from models.database import Base


class HongguoTask(Base):
    __tablename__ = "hongguo_comment_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 基础配置
    drama_name = Column(String(200), nullable=False, comment="搜索剧名")
    comment_mode = Column(String(20), default="specified", comment="评论模式: random/specified")

    # 指定模式参数
    start_episode = Column(Integer, default=1, comment="起始评论集数")
    episode_interval = Column(Integer, default=1, comment="每隔N集评论一次")
    comment_interval_sec = Column(Integer, default=30, comment="评论间隔秒数")

    # 随机模式参数
    random_comment_count = Column(Integer, default=10, comment="随机评论总次数")
    random_min_interval = Column(Integer, default=20, comment="随机最小间隔秒")
    random_max_interval = Column(Integer, default=60, comment="随机最大间隔秒")

    # 评论内容配置
    content_source = Column(String(20), default="ai", comment="内容来源: ai/template/mixed")
    templates_json = Column(Text, default="[]", comment="模板列表JSON")
    playback_speed = Column(String(10), default="1.0x", comment="播放倍速")

    # 执行状态
    status = Column(String(20), default="pending", comment="pending/running/paused/completed/failed/stopped")
    current_episode = Column(Integer, default=0, comment="当前集数")
    total_episodes = Column(Integer, default=0, comment="总集数")
    comments_sent = Column(Integer, default=0, comment="已发送评论数")
    comments_verified = Column(Integer, default=0, comment="已验证评论数")
    error_message = Column(Text, nullable=True, comment="错误信息")

    # 时间
    started_at = Column(DateTime, nullable=True, comment="开始执行时间")
    completed_at = Column(DateTime, nullable=True, comment="完成时间")
    duration_seconds = Column(Integer, nullable=True, comment="总耗时秒")

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def __repr__(self):
        return f"<HongguoTask {self.drama_name} [{self.status}]>"

    @property
    def progress_percent(self):
        total = self.total_episodes or 0
        if total == 0:
            return 0
        current = self.current_episode or 0
        return round(current / total * 100, 1)

    @property
    def is_running(self):
        return self.status == "running"

    @property
    def is_finished(self):
        return self.status in ("completed", "failed", "stopped")
