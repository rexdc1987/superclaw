"""Administrator API for managing web users."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.security import require_admin
from services.user_service import UserService


router = APIRouter(
    prefix="/api/v1/users",
    tags=["users"],
    dependencies=[Depends(require_admin)],
)


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    nickname: str = Field(default="", max_length=64)
    phone: str = Field(default="", max_length=20)
    position: str = Field(default="", max_length=64)
    role: str = Field(default="user", pattern="^(admin|user)$")
    usage_days: int = Field(default=30, ge=1, le=36500)


class UserUpdate(BaseModel):
    password: Optional[str] = Field(default=None, min_length=8, max_length=256)
    nickname: Optional[str] = Field(default=None, max_length=64)
    phone: Optional[str] = Field(default=None, max_length=20)
    position: Optional[str] = Field(default=None, max_length=64)
    role: Optional[str] = Field(default=None, pattern="^(admin|user)$")
    status: Optional[str] = Field(default=None, pattern="^(active|disabled)$")
    usage_days: Optional[int] = Field(default=None, ge=1, le=36500)


def _serialize(user) -> dict:
    return {
        "id": int(user.id),
        "username": user.username,
        "nickname": user.nickname or "",
        "phone": user.phone or "",
        "position": user.position or "",
        "role": user.role or "user",
        "status": user.status or "active",
        "usage_days": int(user.usage_days or 0),
        "expire_at": user.expire_at,
        "last_login": user.last_login,
        "created_at": user.created_at,
    }


@router.get("")
@router.get("/")
def list_users():
    return [_serialize(user) for user in UserService().list_users()]


@router.post("")
@router.post("/")
def create_user(payload: UserCreate):
    try:
        user = UserService().create_user(**payload.model_dump())
        return _serialize(user)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/{user_id}")
def update_user(user_id: int, payload: UserUpdate):
    data = payload.model_dump(exclude_unset=True)
    try:
        return _serialize(UserService().update_user(user_id, **data))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{user_id}")
def delete_user(user_id: int):
    try:
        UserService().delete_user(user_id)
        return {"success": True, "id": user_id}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
