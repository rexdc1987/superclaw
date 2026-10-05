"""Soda Music track model"""
from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String, Text
from models.database import Base


class SodaSong(Base):
    __tablename__ = "soda_songs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(200), nullable=False, comment="曲名")
    artist = Column(String(200), nullable=False, default="", comment="歌手")
    album = Column(String(200), nullable=True, comment="专辑")
    genre = Column(String(50), nullable=True, comment="曲风")
    language = Column(String(50), nullable=True, comment="语种")
    duration_sec = Column(Integer, default=0, comment="时长(秒)")
    heat = Column(Integer, default=0, comment="热度值")
    rank_position = Column(Integer, nullable=True, comment="榜单排名, 空表示未上榜")
    release_date = Column(String(20), nullable=True, comment="发行日期 YYYY-MM-DD")
    tags = Column(String(200), nullable=True, comment="标签, 逗号分隔")
    cover_url = Column(String(500), nullable=True, comment="封面地址")
    remark = Column(Text, nullable=True, comment="备注")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<SodaSong {self.title} - {self.artist}>"

    @property
    def duration_text(self):
        total = max(0, int(self.duration_sec or 0))
        return "{:02d}:{:02d}".format(total // 60, total % 60)
