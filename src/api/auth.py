"""Web authentication endpoints backed by the existing users table."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.security import (
    Principal,
    auth_required,
    current_principal,
    issue_access_token,
    require_principal,
)
from services.user_service import UserService


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
_login_attempts = defaultdict(deque)
_login_attempts_lock = threading.Lock()


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


def _serialize_principal(principal: Principal) -> dict:
    return {
        "id": principal.user_id,
        "username": principal.username,
        "role": principal.role,
        "local_mode": not auth_required(),
    }


@router.get("/status")
def auth_status():
    return {"auth_required": auth_required()}


def _check_login_rate_limit(key: str) -> None:
    now = time.monotonic()
    with _login_attempts_lock:
        attempts = _login_attempts[key]
        while attempts and now - attempts[0] > 60:
            attempts.popleft()
        if len(attempts) >= 5:
            raise HTTPException(status_code=429, detail="Too many login attempts; retry in one minute")
        attempts.append(now)


@router.post("/login")
def login(payload: LoginRequest, request: Request):
    rate_key = f"{request.client.host if request.client else ''}|{payload.username.strip().lower()}"
    _check_login_rate_limit(rate_key)
    if not auth_required():
        principal = Principal(user_id=1, username=payload.username.strip() or "local", role="admin")
        token = issue_access_token(principal.user_id, principal.username, principal.role)
        with _login_attempts_lock:
            _login_attempts.pop(rate_key, None)
        return {"access_token": token, "token_type": "bearer", "user": _serialize_principal(principal)}

    user = UserService().authenticate(payload.username.strip(), payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not user.is_active():
        raise HTTPException(status_code=403, detail="User is disabled or expired")
    principal = Principal(user_id=int(user.id), username=str(user.username), role=str(user.role or "user"))
    with _login_attempts_lock:
        _login_attempts.pop(rate_key, None)
    return {
        "access_token": issue_access_token(
            principal.user_id,
            principal.username,
            principal.role,
            int(user.auth_version or 1),
        ),
        "token_type": "bearer",
        "user": _serialize_principal(principal),
    }


@router.get("/me")
def me(_: Principal = Depends(require_principal)):
    return _serialize_principal(current_principal())


@router.post("/change-password")
def change_password(payload: ChangePasswordRequest, principal: Principal = Depends(require_principal)):
    if not auth_required():
        raise HTTPException(status_code=400, detail="本地免登录模式不能修改密码")
    if payload.old_password == payload.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")
    try:
        user = UserService().change_password(
            principal.user_id,
            payload.old_password,
            payload.new_password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    refreshed = Principal(
        user_id=int(user.id),
        username=str(user.username),
        role=str(user.role or "user"),
        auth_version=int(user.auth_version or 1),
    )
    return {
        "access_token": issue_access_token(
            refreshed.user_id,
            refreshed.username,
            refreshed.role,
            refreshed.auth_version,
        ),
        "token_type": "bearer",
        "user": _serialize_principal(refreshed),
    }
