"""User authentication and management service."""
import hashlib
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

from api.security import Principal
from models.database import get_session
from models.user import User


PBKDF2_ITERATIONS = 310000


def _hash_password(password, salt=None, iterations=PBKDF2_ITERATIONS):
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        int(iterations),
    ).hex()
    return f"pbkdf2_sha256${int(iterations)}${salt}${hashed}"


def _verify_password(password, stored_hash):
    parts = str(stored_hash or "").split("$")
    if len(parts) == 4 and parts[0] == "pbkdf2_sha256":
        _, iterations, salt, expected = parts
        actual = _hash_password(password, salt, int(iterations)).rsplit("$", 1)[-1]
        return secrets.compare_digest(actual, expected)
    if len(parts) == 2:
        salt, expected = parts
        actual = hashlib.sha256((salt + password).encode()).hexdigest()
        return secrets.compare_digest(actual, expected)
    return False


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
            if not str(user.password_hash or "").startswith("pbkdf2_sha256$"):
                user.password_hash = _hash_password(password)
            user.last_login = datetime.utcnow()
            session.commit()
            session.refresh(user)
            return user
        finally:
            session.close()

    @staticmethod
    def _normalize_username(username):
        value = str(username or "").strip()
        if not value:
            raise ValueError("用户名不能为空")
        return value

    @staticmethod
    def _active_admin_count(session, exclude_user_id: Optional[int] = None):
        query = session.query(User).filter(User.role == "admin", User.status == "active")
        if exclude_user_id is not None:
            query = query.filter(User.id != int(exclude_user_id))
        return sum(1 for user in query.all() if not user.is_expired())

    def create_user(self, username, password, nickname="", role="user",
                    usage_days=30, phone="", position="", remark=""):
        username = self._normalize_username(username)
        session = get_session()
        try:
            existing = session.query(User).filter_by(username=username).first()
            if existing:
                raise ValueError(f"用户名 '{username}' 已存在")
            user = User(
                username=username,
                password_hash=_hash_password(password),
                auth_version=1,
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

    def update_user(self, user_id, actor_user_id=None, **kwargs):
        session = get_session()
        try:
            user = session.get(User, user_id)
            if not user:
                raise ValueError("用户不存在")
            target_role = kwargs.get("role", user.role)
            target_status = kwargs.get("status", user.status)
            if actor_user_id is not None and int(actor_user_id) == int(user_id):
                if target_role != "admin":
                    raise ValueError("不能取消当前登录账号的管理员权限")
                if target_status != "active":
                    raise ValueError("不能禁用当前登录账号")
            removes_active_admin = (
                user.role == "admin"
                and user.is_active()
                and (target_role != "admin" or target_status != "active")
            )
            if removes_active_admin and self._active_admin_count(session, user_id) == 0:
                raise ValueError("系统必须保留至少一个可用管理员")
            security_changed = False
            if "password" in kwargs and kwargs["password"]:
                user.password_hash = _hash_password(kwargs["password"])
                security_changed = True
            for field in ["nickname", "phone", "position", "role", "status",
                          "expire_at", "remark"]:
                if field in kwargs:
                    if field in {"role", "status", "expire_at"} and getattr(user, field) != kwargs[field]:
                        security_changed = True
                    setattr(user, field, kwargs[field])
            if "usage_days" in kwargs:
                user.usage_days = int(kwargs["usage_days"])
                user.expire_at = datetime.utcnow() + timedelta(days=user.usage_days)
                security_changed = True
            if security_changed:
                user.auth_version = int(user.auth_version or 1) + 1
            session.commit()
            return user
        finally:
            session.close()

    def delete_user(self, user_id, actor_user_id=None):
        session = get_session()
        try:
            user = session.get(User, user_id)
            if not user:
                raise ValueError("用户不存在")
            if actor_user_id is not None and int(actor_user_id) == int(user_id):
                raise ValueError("不能删除当前登录账号")
            if user.role == "admin" and user.is_active():
                if self._active_admin_count(session, user_id) == 0:
                    raise ValueError("系统必须保留至少一个可用管理员")
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

    def validate_principal(self, principal: Principal) -> Principal:
        session = get_session()
        try:
            user = session.get(User, int(principal.user_id))
            if not user or user.username != principal.username:
                raise ValueError("登录账号不存在")
            if not user.is_active():
                raise ValueError("登录账号已禁用或已到期")
            if int(user.auth_version or 1) != int(principal.auth_version or 1):
                raise ValueError("登录状态已失效，请重新登录")
            return Principal(
                user_id=int(user.id),
                username=str(user.username),
                role=str(user.role or "user"),
                auth_version=int(user.auth_version or 1),
            )
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
            user.auth_version = int(user.auth_version or 1) + 1
            session.commit()
            return user
        finally:
            session.close()

    def init_admin(self):
        session = get_session()
        try:
            count = session.query(User).count()
            if count == 0:
                password = os.environ.get("SUPERCLAW_ADMIN_PASSWORD", "")
                if len(password) < 8:
                    raise ValueError("SUPERCLAW_ADMIN_PASSWORD must contain at least 8 characters")
                admin = User(
                    username=os.environ.get("SUPERCLAW_ADMIN_USERNAME", "admin").strip() or "admin",
                    password_hash=_hash_password(password),
                    auth_version=1,
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
