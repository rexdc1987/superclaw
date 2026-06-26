"""Global system settings API."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator
from pymysql.cursors import DictCursor

from rpa.hongguo.ai_usage import load_usage_stats, record_usage, reset_usage_stats
from rpa.hongguo.comment_gen import CommentGenerator
from rpa.hongguo.engine import DEFAULT_SCREENSHOT_ROOT, TaskEngineManager
from services.ai_config_service import (
    ai_config,
    app_config,
    hongguo_config,
    public_ai_settings,
    public_hongguo_settings,
    update_ai_config,
    update_hongguo_config,
)


router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


class AISettingsUpdate(BaseModel):
    enabled: bool = True
    provider: str = "openai_compatible"
    api_key_env: str = "OPENAI_API_KEY"
    api_key: Optional[str] = None
    base_url: str = Field(default="https://api.openai.com/v1")
    model: str = Field(default="gpt-4.1-mini")
    timeout: int = Field(default=30, ge=5, le=180)
    temperature: float = Field(default=0.8, ge=0, le=2)
    max_tokens: int = Field(default=512, ge=32, le=4096)
    fallback_to_local: bool = True
    comment_scope: str = Field(default="", max_length=200)

    @field_validator("base_url", "model", "provider", "api_key_env")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value is required")
        return value

    @field_validator("comment_scope")
    @classmethod
    def normalize_comment_scope(cls, value: str) -> str:
        return value.strip()


class HongguoSettingsUpdate(BaseModel):
    device_addr: str = Field(default="127.0.0.1:5555", max_length=80)

    @field_validator("device_addr")
    @classmethod
    def validate_device_addr(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("device_addr is required")
        return value


def _refresh_consumers() -> None:
    # Hongguo is currently the first consumer of the global AI settings.
    cfg = app_config()
    db = cfg.get("database", {})
    TaskEngineManager.get_instance(
        db_config={
            "host": db.get("host", "localhost"),
            "port": int(db.get("port", 3308)),
            "database": db.get("name", "superclaw"),
            "user": db.get("user", "superclaw"),
            "password": os.environ.get("SUPERCLAW_DB_PASSWORD") or db.get("password", ""),
            "charset": "utf8mb4",
            "cursorclass": DictCursor,
            "autocommit": False,
        },
        ai_config=ai_config(),
        screenshot_root=str(Path(DEFAULT_SCREENSHOT_ROOT).as_posix()),
        device_addr=hongguo_config().get("device_addr"),
    )


@router.get("/ai")
async def get_ai_settings():
    return public_ai_settings()


@router.put("/ai")
async def update_ai_settings(payload: AISettingsUpdate):
    current = update_ai_config(payload.model_dump())
    _refresh_consumers()
    return public_ai_settings(current)


@router.post("/ai/test")
async def test_ai_settings(payload: Optional[AISettingsUpdate] = None):
    if payload is None:
        current = ai_config()
    else:
        current = payload.model_dump()
        api_key_env = current.get("api_key_env") or "OPENAI_API_KEY"
        current["api_key"] = current.get("api_key") or os.environ.get(api_key_env, "")
        current["fallback_to_local"] = False
    try:
        content, source, usage = CommentGenerator(current).generate_with_usage("红果短剧", "ai")
        stats = record_usage(usage, context="settings:test") if usage else load_usage_stats()
        return {"success": True, "source": source, "comment": content, "usage": usage, "stats": stats}
    except Exception as exc:
        return {"success": False, "message": str(exc)}


@router.get("/ai/usage")
async def get_ai_usage():
    return load_usage_stats()


@router.post("/ai/usage/reset")
async def reset_ai_usage():
    return reset_usage_stats()


@router.get("/hongguo")
async def get_hongguo_settings():
    return public_hongguo_settings()


@router.put("/hongguo")
async def update_hongguo_settings(payload: HongguoSettingsUpdate):
    current = update_hongguo_config(payload.model_dump())
    _refresh_consumers()
    return public_hongguo_settings(current)
