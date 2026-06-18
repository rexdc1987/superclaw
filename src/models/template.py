"""Template model"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from models.database import Base


class MessageTemplate(Base):
    __tablename__ = "message_templates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    content = Column(Text, nullable=False)
    action_type = Column(String(20), nullable=False)
    variables_json = Column(Text, default="[]")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<MessageTemplate {self.name} [{self.action_type}]>"

    def render(self, variables):
        result = self.content
        for k, v in variables.items():
            result = result.replace("{" + k + "}", str(v))
        return result


class Material(Base):
    __tablename__ = "materials"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    type = Column(String(20), nullable=False)
    file_path = Column(String(500), default="")
    category = Column(String(50), default="")
    description = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Material {self.name} [{self.type}]>"
