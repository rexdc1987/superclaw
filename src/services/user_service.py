"""User authentication and management service."""
import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from models.database import get_session
from models.user import User


def _hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}${hashed}"


def _verify_password(password, stored_hash):
    parts = stored_hash.split("$", 1)
    if len(parts) != 2:
        return False
    salt, _ = parts
    return _hash_password(password, salt) == stored_hash


class UserService:
    def authenticate(self, username, password):
        session = get_session()
        try:
            user = session.query(User).filter_by(username=username).first()
            if not user:
                return None
            if not _verify_password(password, user.password_hash):
                return None
            if not user.is_active():
                return None
            user.last_login = datetime.utcnow()
            session.commit()
            session.refresh(user)
            return user
        finally:
            session.close()

    def create_user(self, username, password, nickname="", role="user",
                    usage_days=30, phone="", position="", remark=""):
        session = get_session()
        try:
            existing = session.query(User).filter_by(username=username).first()
            if existing:
                raise ValueError(f"用户名 '{username}' 已存在")
            user = User(
                username=username,
                password_hash=_hash_password(password),
                nickname=nickname or username,
                phone=phone,
                position=position,
                role=role,
                usage_days=usage_days,
                expire_at=datetime.utcnow() + timedelta(days=usage_days),
                remark=remark,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            return user
        finally:
            session.close()

    def update_user(self, user_id, **kwargs):
        session = get_session()
        try:
            user = session.get(User, user_id)
            if not user:
                raise ValueError("用户不存在")
            if "password" in kwargs and kwargs["password"]:
                user.password_hash = _hash_password(kwargs["password"])
            for field in ["nickname", "phone", "position", "role", "status",
                          "usage_days", "expire_at", "remark"]:
                if field in kwargs:
                    setattr(user, field, kwargs[field])
            session.commit()
            return user
        finally:
            session.close()

    def delete_user(self, user_id):
        session = get_session()
        try:
            user = session.get(User, user_id)
            if not user:
                raise ValueError("用户不存在")
            if user.role == "admin":
                admin_count = session.query(User).filter_by(role="admin").count()
                if admin_count <= 1:
                    raise ValueError("不能删除最后一个管理员")
            session.delete(user)
            session.commit()
        finally:
            session.close()

    def list_users(self):
        session = get_session()
        try:
            return session.query(User).order_by(User.created_at.desc()).all()
        finally:
            session.close()

    def get_user(self, user_id):
        session = get_session()
        try:
            return session.get(User, user_id)
        finally:
            session.close()

    def change_password(self, user_id, old_password, new_password):
        session = get_session()
        try:
            user = session.get(User, user_id)
            if not user:
                raise ValueError("用户不存在")
            if not _verify_password(old_password, user.password_hash):
                raise ValueError("原密码错误")
            user.password_hash = _hash_password(new_password)
            session.commit()
        finally:
            session.close()

    def init_admin(self):
        session = get_session()
        try:
            count = session.query(User).count()
            if count == 0:
                admin = User(
                    username="admin",
                    password_hash=_hash_password("admin123"),
                    nickname="Administrator",
                    phone="",
                    position="系统管理员",
                    role="admin",
                    usage_days=36500,
                    expire_at=datetime.utcnow() + timedelta(days=36500),
                    remark="Default admin account",
                )
                session.add(admin)
                session.commit()
                return True
            return False
        finally:
            session.close()
