"""User model for login and access control."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime
from models.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(128), nullable=False)
    nickname = Column(String(64), default="")
    phone = Column(String(20), default="")
    position = Column(String(64), default="")
    role = Column(String(16), default="user")
    status = Column(String(16), default="active")
    usage_days = Column(Integer, default=30)
    expire_at = Column(DateTime, nullable=True)
    max_concurrent = Column(Integer, default=1)
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    remark = Column(String(256), default="")

    def is_expired(self):
        if self.expire_at and datetime.utcnow() > self.expire_at:
            return True
        return False

    def is_active(self):
        return self.status == "active" and not self.is_expired()

    def days_remaining(self):
        if not self.expire_at:
            return -1
        delta = self.expire_at - datetime.utcnow()
        return max(0, delta.days)

    def __repr__(self):
        return f"<User {self.username} role={self.role} status={self.status}>"
