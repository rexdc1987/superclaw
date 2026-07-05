"""Hongguo Comment Template model"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime
from models.database import Base


class HongguoTemplate(Base):
    __tablename__ = "hongguo_comment_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=True, comment="模板名称")
    content = Column(Text, nullable=False, comment="模板内容")
    category = Column(String(50), nullable=True, comment="分类: 通用/重生/逆袭/甜宠/...")
    is_default = Column(Integer, default=0, comment="是否默认模板")
    use_count = Column(Integer, default=0, comment="使用次数")

    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<HongguoTemplate {self.name}>"

    @property
    def short_content(self):
        return self.content[:20] + "..." if len(self.content) > 20 else self.content
