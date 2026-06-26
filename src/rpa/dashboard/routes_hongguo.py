"""Hongguo comment task API routes.

Phase 1 intentionally uses PyMySQL directly because the Hongguo PRD requires
MySQL as the source of truth and defines the table contract by column name.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import pymysql
import yaml
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from pymysql.cursors import DictCursor

from rpa.hongguo.ai_usage import load_usage_stats, reset_usage_stats
from rpa.hongguo.comment_gen import CommentGenerator
from rpa.hongguo.device import DEFAULT_ADDR, connect, connect_exact, discover_addrs
from rpa.hongguo.engine import DEFAULT_SCREENSHOT_ROOT, TaskEngineManager
from rpa.hongguo.operations import HongguoOperations
from services.ai_config_service import (
    ai_config,
    app_config,
    hongguo_config,
    public_hongguo_settings,
    public_ai_settings,
    save_app_config,
    update_ai_config,
)


router = APIRouter(prefix="/api/v1/hongguo", tags=["hongguo"])

TASK_STATUSES = {
    "pending",
    "waiting_login",
    "running",
    "paused",
    "completed",
    "failed",
    "stopped",
}
COMMENT_MODES = {"random", "specified"}
CONTENT_SOURCES = {"ai", "template", "mixed"}
RECORD_STATUSES = {"success", "failed", "skipped"}
LOG_LEVELS = {"info", "warn", "error"}
PLAYBACK_SPEEDS = {"0.75x", "1.0x", "1.25x", "1.5x", "2.0x", "3.0x"}

AI_MODEL_PRESETS = [
    {
        "label": "小米 MiMo v2.5",
        "provider": "openai_compatible",
        "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
        "model": "mimo-v2.5",
        "api_key_env": "XIAOMI_API_KEY",
    },
    {
        "label": "OpenAI GPT-4.1 mini",
        "provider": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
        "api_key_env": "OPENAI_API_KEY",
    },
    {
        "label": "OpenAI GPT-4o mini",
        "provider": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
    },
]

# Allowed status transitions: current_status -> set of allowed new statuses
STATUS_TRANSITIONS = {
    "pending": {"running", "stopped", "failed"},
    "waiting_login": {"running", "stopped", "failed"},
    "running": {"paused", "completed", "failed", "stopped"},
    "paused": {"running", "stopped", "failed"},
    "completed": {"pending", "running", "stopped"},
    "failed": {"pending", "running", "stopped"},
    "stopped": {"pending", "running", "stopped"},
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _screenshot_root() -> Path:
    return Path(DEFAULT_SCREENSHOT_ROOT)


def _task_screenshot_dir(task_id: int) -> Path:
    return _screenshot_root() / str(task_id)


def _engine_manager() -> TaskEngineManager:
    return TaskEngineManager.get_instance(
        _db_config(),
        str(_screenshot_root().as_posix()),
        _ai_config(),
        device_addr=_hongguo_device_addr(),
    )


def _app_config() -> Dict[str, Any]:
    return app_config()


def _ai_config() -> Dict[str, Any]:
    return ai_config()


def _hongguo_config() -> Dict[str, Any]:
    return hongguo_config()


def _hongguo_device_addr() -> str:
    return str(_hongguo_config().get("device_addr") or DEFAULT_ADDR).strip() or DEFAULT_ADDR


def _save_app_config(cfg: Dict[str, Any]) -> None:
    save_app_config(cfg)


def _db_config() -> Dict[str, Any]:
    cfg = _app_config()
    db = cfg.get("database", {})
    return {
        "host": db.get("host", "localhost"),
        "port": int(db.get("port", 3308)),
        "database": db.get("name", "superclaw"),
        "user": db.get("user", "superclaw"),
        "password": os.environ.get("SUPERCLAW_DB_PASSWORD") or db.get("password", ""),
        "charset": "utf8mb4",
        "cursorclass": DictCursor,
        "autocommit": False,
    }


def _normalize_playback_speed(value: Optional[str]) -> str:
    text = str(value or "1.0x").strip().lower().replace(" ", "")
    if text.endswith("x"):
        text = text[:-1]
    aliases = {
        "0.75": "0.75x",
        "1": "1.0x",
        "1.0": "1.0x",
        "1.25": "1.25x",
        "1.5": "1.5x",
        "2": "2.0x",
        "2.0": "2.0x",
        "3": "3.0x",
        "3.0": "3.0x",
    }
    normalized = aliases.get(text)
    if normalized not in PLAYBACK_SPEEDS:
        raise ValueError("playback_speed must be one of 0.75x, 1.0x, 1.25x, 1.5x, 2.0x, 3.0x")
    return normalized


def _ensure_task_schema(conn) -> None:
    db_name = _db_config()["database"]
    with conn.cursor() as cur:
        existing: set[str] = set()
        cur.execute(
            """
            SELECT COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=%s
              AND TABLE_NAME='hongguo_comment_tasks'
              AND COLUMN_NAME IN ('playback_speed', 'execution_plan_json')
            """,
            (db_name,),
        )
        for row in cur.fetchall() or []:
            name = row.get("COLUMN_NAME")
            if name:
                existing.add(str(name))
        if "playback_speed" not in existing:
            cur.execute(
                """
                ALTER TABLE hongguo_comment_tasks
                ADD COLUMN playback_speed VARCHAR(10) DEFAULT '1.0x'
                AFTER templates_json
                """
            )
            cur.execute(
                """
                UPDATE hongguo_comment_tasks
                SET playback_speed='1.0x'
                WHERE playback_speed IS NULL OR playback_speed=''
                """
            )
        if "execution_plan_json" not in existing:
            cur.execute(
                """
                ALTER TABLE hongguo_comment_tasks
                ADD COLUMN execution_plan_json TEXT DEFAULT NULL
                AFTER playback_speed
                """
            )


@contextmanager
def _connection():
    conn = pymysql.connect(**_db_config())
    try:
        _ensure_task_schema(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False)


def _json_loads(value: Any) -> Any:
    if value in (None, ""):
        return []
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []


def _normalize_status(status: Any) -> str:
    return status if status in TASK_STATUSES else "pending"


def _serialize_task(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    row = dict(row)
    row["status"] = _normalize_status(row.get("status"))
    row["playback_speed"] = _normalize_playback_speed(row.get("playback_speed") or "1.0x")
    row["templates"] = _json_loads(row.get("templates_json"))
    row["execution_plan"] = _json_loads(row.get("execution_plan_json"))
    return row


def _public_screenshot_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"/api/v1/hongguo/tasks/screenshot/proxy?path={quote_plus(path)}"


def _fetch_one_or_404(conn, task_id: int) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM hongguo_comment_tasks WHERE id=%s", (task_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return row


def _insert_log(
    conn,
    task_id: int,
    message: str,
    level: str = "info",
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO hongguo_execution_logs (task_id, level, message, created_at)
            VALUES (%s, %s, %s, %s)
            """,
            (task_id, level, message, datetime.now()),
        )


class TaskBase(BaseModel):
    drama_name: str = Field(max_length=200)
    comment_mode: str = "specified"
    content_source: str = "ai"
    playback_speed: str = "1.0x"
    start_episode: int = Field(default=1, ge=1)
    episode_interval: int = Field(default=1, ge=1)
    comment_interval_sec: int = Field(default=30, ge=0)
    random_comment_count: int = Field(default=10, ge=1)
    random_min_interval: int = Field(default=20, ge=0)
    random_max_interval: int = Field(default=60, ge=0)
    templates: List[str] = Field(default_factory=list)

    @field_validator("comment_mode")
    @classmethod
    def validate_comment_mode(cls, value: str) -> str:
        if value not in COMMENT_MODES:
            raise ValueError("comment_mode must be random or specified")
        return value

    @field_validator("content_source")
    @classmethod
    def validate_content_source(cls, value: str) -> str:
        if value not in CONTENT_SOURCES:
            raise ValueError("content_source must be ai, template, or mixed")
        return value

    @field_validator("playback_speed")
    @classmethod
    def validate_playback_speed(cls, value: str) -> str:
        return _normalize_playback_speed(value)

    @field_validator("drama_name")
    @classmethod
    def validate_drama_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("drama_name is required")
        return value


class TaskCreate(TaskBase):
    pass


class AISettingsUpdate(BaseModel):
    enabled: bool = True
    provider: str = "openai_compatible"
    api_key_env: str = "XIAOMI_API_KEY"
    api_key: Optional[str] = None
    base_url: str = Field(default="https://token-plan-cn.xiaomimimo.com/v1")
    model: str = Field(default="mimo-v2.5")
    timeout: int = Field(default=30, ge=5, le=180)
    temperature: float = Field(default=0.8, ge=0, le=2)
    max_tokens: int = Field(default=512, ge=32, le=4096)
    fallback_to_local: bool = True

    @field_validator("base_url", "model", "provider", "api_key_env")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value is required")
        return value


def _public_ai_settings(ai: Dict[str, Any]) -> Dict[str, Any]:
    return public_ai_settings(ai)


class TaskUpdate(BaseModel):
    drama_name: Optional[str] = Field(default=None, max_length=200)
    comment_mode: Optional[str] = None
    content_source: Optional[str] = None
    playback_speed: Optional[str] = None
    start_episode: Optional[int] = Field(default=None, ge=1)
    episode_interval: Optional[int] = Field(default=None, ge=1)
    comment_interval_sec: Optional[int] = Field(default=None, ge=0)
    random_comment_count: Optional[int] = Field(default=None, ge=1)
    random_min_interval: Optional[int] = Field(default=None, ge=0)
    random_max_interval: Optional[int] = Field(default=None, ge=0)
    templates: Optional[List[str]] = None
    status: Optional[str] = None
    total_episodes: Optional[int] = Field(default=None, ge=0)
    current_episode: Optional[int] = Field(default=None, ge=0)
    comments_sent: Optional[int] = Field(default=None, ge=0)
    comments_verified: Optional[int] = Field(default=None, ge=0)
    error_message: Optional[str] = None

    @field_validator("comment_mode")
    @classmethod
    def validate_comment_mode(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in COMMENT_MODES:
            raise ValueError("comment_mode must be random or specified")
        return value

    @field_validator("content_source")
    @classmethod
    def validate_content_source(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in CONTENT_SOURCES:
            raise ValueError("content_source must be ai, template, or mixed")
        return value

    @field_validator("playback_speed")
    @classmethod
    def validate_playback_speed(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        return _normalize_playback_speed(value)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in TASK_STATUSES:
            raise ValueError("invalid task status")
        return value


class TemplateCreate(BaseModel):
    content: str
    category: str = "通用"
    is_default: bool = False

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content is required")
        return value


class TemplateUpdate(BaseModel):
    content: Optional[str] = None
    category: Optional[str] = None
    is_default: Optional[bool] = None

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("content cannot be empty")
        return value


@router.post("/tasks")
async def create_task(payload: TaskCreate):
    now = datetime.now()
    with _connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO hongguo_comment_tasks (
                    drama_name, comment_mode, content_source,
                    start_episode, episode_interval, comment_interval_sec,
                    random_comment_count, random_min_interval, random_max_interval,
                    templates_json, playback_speed, status, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    payload.drama_name,
                    payload.comment_mode,
                    payload.content_source,
                    payload.start_episode,
                    payload.episode_interval,
                    payload.comment_interval_sec,
                    payload.random_comment_count,
                    payload.random_min_interval,
                    payload.random_max_interval,
                    _json_dumps(payload.templates),
                    payload.playback_speed,
                    "pending",
                    now,
                    now,
                ),
            )
            task_id = cur.lastrowid
        _insert_log(conn, task_id, "任务已创建")
        return _serialize_task(_fetch_one_or_404(conn, task_id))


@router.get("/tasks")
async def list_tasks(
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    if status is not None and status not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    where = "WHERE status=%s" if status else ""
    params: List[Any] = [status] if status else []
    params.extend([limit, offset])
    with _connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM hongguo_comment_tasks
                {where}
                ORDER BY id DESC
                LIMIT %s OFFSET %s
                """,
                params,
            )
            rows = cur.fetchall()
    return [_serialize_task(row) for row in rows]


@router.get("/tasks/{task_id}")
async def get_task(task_id: int):
    with _connection() as conn:
        return _serialize_task(_fetch_one_or_404(conn, task_id))


@router.put("/tasks/{task_id}")
async def update_task(task_id: int, payload: TaskUpdate):
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "templates" in data:
        data["templates_json"] = _json_dumps(data.pop("templates"))

    allowed = {
        "drama_name",
        "comment_mode",
        "content_source",
        "playback_speed",
        "start_episode",
        "episode_interval",
        "comment_interval_sec",
        "random_comment_count",
        "random_min_interval",
        "random_max_interval",
        "templates_json",
        "status",
        "total_episodes",
        "current_episode",
        "comments_sent",
        "comments_verified",
        "error_message",
    }
    assignments = []
    values = []
    for key, value in data.items():
        if key not in allowed:
            continue
        assignments.append(f"{key}=%s")
        values.append(value)
    if not assignments:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    assignments.append("updated_at=%s")
    values.append(datetime.now())
    values.append(task_id)

    with _connection() as conn:
        current = _fetch_one_or_404(conn, task_id)
        if "status" in data:
            current_status = _normalize_status(current.get("status"))
            target_status = data["status"]
            allowed = STATUS_TRANSITIONS.get(current_status, set())
            if target_status not in allowed:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot transition from '{current_status}' to '{target_status}'",
                )
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE hongguo_comment_tasks
                SET {", ".join(assignments)}
                WHERE id=%s
                """,
                values,
            )
        _insert_log(conn, task_id, "任务配置已更新")
        return _serialize_task(_fetch_one_or_404(conn, task_id))


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int):
    with _connection() as conn:
        _fetch_one_or_404(conn, task_id)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM hongguo_execution_logs WHERE task_id=%s", (task_id,))
            cur.execute("DELETE FROM hongguo_comment_records WHERE task_id=%s", (task_id,))
            cur.execute("DELETE FROM hongguo_comment_tasks WHERE id=%s", (task_id,))
    return {"success": True, "id": task_id}


def _set_task_status(task_id: int, status: str, log_message: str) -> Dict[str, Any]:
    now = datetime.now()
    with _connection() as conn:
        current = _fetch_one_or_404(conn, task_id)
        values: List[Any] = [status]
        if status == "running":
            extra = ", started_at=COALESCE(started_at, %s), completed_at=NULL, duration_seconds=NULL, error_message=NULL, updated_at=%s"
            values.extend([now, now])
        elif status in {"completed", "failed", "stopped"}:
            started_at = current.get("started_at")
            duration_seconds = None
            if started_at:
                try:
                    duration_seconds = max(0, int((now - started_at).total_seconds()))
                except Exception:
                    duration_seconds = None
            extra = ", completed_at=%s, duration_seconds=%s, updated_at=%s"
            values.extend([now, duration_seconds, now])
        else:
            extra = ", updated_at=%s"
            values.append(now)
        values.append(task_id)
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE hongguo_comment_tasks SET status=%s{extra} WHERE id=%s",
                values,
            )
        _insert_log(conn, task_id, log_message)
        return _serialize_task(_fetch_one_or_404(conn, task_id))


def _validate_transition(current_status: str, target_status: str) -> None:
    """Raise 400 if the status transition is not allowed."""
    current_status = _normalize_status(current_status)
    allowed = STATUS_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from '{current_status}' to '{target_status}'",
        )


@router.get("/settings/ai")
async def get_ai_settings():
    return _public_ai_settings(_app_config().get("ai", {}))


@router.put("/settings/ai")
async def update_ai_settings(payload: AISettingsUpdate):
    current = update_ai_config(payload.model_dump())
    TaskEngineManager.get_instance(
        _db_config(),
        str(_screenshot_root().as_posix()),
        _ai_config(),
        device_addr=_hongguo_device_addr(),
    )
    return _public_ai_settings(current)


@router.post("/settings/ai/test")
async def test_ai_settings(payload: Optional[AISettingsUpdate] = None):
    if payload is None:
        ai = _ai_config()
    else:
        ai = payload.model_dump()
        api_key_env = ai.get("api_key_env") or "OPENAI_API_KEY"
        ai["api_key"] = ai.get("api_key") or os.environ.get(api_key_env, "")
        ai["fallback_to_local"] = False
    try:
        content, source, usage = CommentGenerator(ai).generate_with_usage("红果短剧", "ai")
        from rpa.hongguo.ai_usage import record_usage
        stats = record_usage(usage, context="settings:test") if usage else load_usage_stats()
        return {"success": True, "source": source, "comment": content, "usage": usage, "stats": stats}
    except Exception as exc:
        return {"success": False, "message": str(exc)}


@router.get("/settings/ai/usage")
async def get_ai_usage():
    return load_usage_stats()


@router.post("/settings/ai/usage/reset")
async def reset_ai_usage():
    return reset_usage_stats()


@router.post("/tasks/{task_id}/start")
async def start_task(task_id: int):
    with _connection() as conn:
        current = _fetch_one_or_404(conn, task_id)
        now = datetime.now()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE hongguo_comment_tasks
                SET status=%s,
                    started_at=%s,
                    completed_at=NULL,
                    duration_seconds=NULL,
                    error_message=NULL,
                    current_episode=0,
                    comments_sent=0,
                    comments_verified=0,
                    updated_at=%s
                WHERE id=%s
                """,
                ("running", now, now, task_id),
            )
    _validate_transition(current.get("status"), "running")
    started = _engine_manager().start_task(task_id)
    if not started:
        raise HTTPException(status_code=409, detail="Task is already running")
    with _connection() as conn:
        return _serialize_task(_fetch_one_or_404(conn, task_id))


@router.post("/tasks/{task_id}/pause")
async def pause_task(task_id: int):
    with _connection() as conn:
        current = _fetch_one_or_404(conn, task_id)
    _validate_transition(current["status"], "paused")
    if not _engine_manager().pause_task(task_id):
        raise HTTPException(status_code=409, detail="Task engine is not running")
    with _connection() as conn:
        return _serialize_task(_fetch_one_or_404(conn, task_id))


@router.post("/tasks/{task_id}/resume")
async def resume_task(task_id: int):
    with _connection() as conn:
        current = _fetch_one_or_404(conn, task_id)
    if current["status"] != "paused":
        raise HTTPException(status_code=409, detail="Only paused tasks can be resumed")
    if not _engine_manager().resume_task(task_id):
        raise HTTPException(status_code=409, detail="Task engine is not running")
    with _connection() as conn:
        return _serialize_task(_fetch_one_or_404(conn, task_id))


@router.post("/tasks/{task_id}/stop")
async def stop_task(task_id: int):
    with _connection() as conn:
        current = _fetch_one_or_404(conn, task_id)
    _validate_transition(current["status"], "stopped")
    if not _engine_manager().stop_task(task_id):
        return _set_task_status(task_id, "stopped", "任务已停止")
    with _connection() as conn:
        return _serialize_task(_fetch_one_or_404(conn, task_id))


@router.get("/tasks/{task_id}/records")
async def list_records(
    task_id: int,
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    if status is not None and status not in RECORD_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid record status")
    where = "AND status=%s" if status else ""
    params: List[Any] = [task_id]
    if status:
        params.append(status)
    params.extend([limit, offset])
    with _connection() as conn:
        _fetch_one_or_404(conn, task_id)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM hongguo_comment_records
                WHERE task_id=%s {where}
                ORDER BY created_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                params,
            )
            rows = cur.fetchall()
            for row in rows:
                row["screenshot_input_url"] = _public_screenshot_url(row.get("screenshot_input"))
                row["screenshot_verified_url"] = _public_screenshot_url(row.get("screenshot_verified"))
                row["screenshot_sent_url"] = _public_screenshot_url(row.get("screenshot_sent"))
            return rows


@router.get("/tasks/{task_id}/logs")
async def list_logs(
    task_id: int,
    level: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    if level is not None and level not in LOG_LEVELS:
        raise HTTPException(status_code=400, detail="Invalid log level")
    where = "AND level=%s" if level else ""
    params: List[Any] = [task_id]
    if level:
        params.append(level)
    params.extend([limit, offset])
    with _connection() as conn:
        _fetch_one_or_404(conn, task_id)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM hongguo_execution_logs
                WHERE task_id=%s {where}
                ORDER BY id DESC
                LIMIT %s OFFSET %s
                """,
                params,
            )
            return cur.fetchall()


@router.get("/tasks/{task_id}/screenshot")
async def latest_screenshot(task_id: int):
    latest = _latest_screenshot_file(task_id)
    if latest:
        return {"task_id": task_id, "screenshot_path": latest}

    with _connection() as conn:
        _fetch_one_or_404(conn, task_id)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT screenshot_verified, screenshot_input
                FROM hongguo_comment_records
                WHERE task_id=%s
                  AND (screenshot_verified IS NOT NULL OR screenshot_input IS NOT NULL)
                ORDER BY id DESC
                LIMIT 1
                """,
                (task_id,),
            )
            row = cur.fetchone()
    if not row:
        return {"task_id": task_id, "screenshot_path": None}
    return {
        "task_id": task_id,
        "screenshot_path": row.get("screenshot_verified") or row.get("screenshot_input"),
    }


@router.get("/tasks/{task_id}/screenshot/latest")
async def latest_screenshot_file(task_id: int):
    with _connection() as conn:
        _fetch_one_or_404(conn, task_id)
    return {"task_id": task_id, "screenshot_path": _latest_screenshot_file(task_id)}


@router.get("/tasks/{task_id}/screenshot/image")
async def screenshot_image(task_id: int):
    latest = _latest_screenshot_file(task_id)
    if not latest or not Path(latest).exists():
        raise HTTPException(status_code=404, detail="No screenshot available")
    return FileResponse(latest, media_type="image/png")


@router.get("/tasks/screenshot/proxy")
async def screenshot_proxy(path: str):
    if not path:
        raise HTTPException(status_code=404, detail="No screenshot available")
    decoded = path.replace("+", " ")
    if not Path(decoded).exists():
        raise HTTPException(status_code=404, detail="No screenshot available")
    return FileResponse(decoded, media_type="image/png")


def _latest_screenshot_file(task_id: int) -> Optional[str]:
    screenshot_dir = _task_screenshot_dir(task_id)
    if not screenshot_dir.exists():
        return None
    files = [
        path
        for path in screenshot_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg"}
    ]
    if not files:
        return None
    return str(max(files, key=lambda path: path.stat().st_mtime).as_posix())


@router.post("/check-login")
def check_login():
    try:
        device = connect(_hongguo_device_addr())
        ops = HongguoOperations(device)
        device_info = ops.get_device_info()
        launched = ops.launch_app()
        device_info = ops.get_device_info()
        if not launched and device_info.get("current_package") != "com.phoenix.read":
            return {
                "success": True,
                "logged_in": False,
                "status": "app_launch_failed",
                "device": device_info,
                "account": {"logged_in": False, "nickname": "", "hongguo_id": ""},
                "message": "红果短剧启动失败",
            }
        result = ops.check_login()
        device_info = ops.get_device_info()
        account = ops.get_account_info()
        if account.get("logged_in") and not result.get("logged_in"):
            result = {
                **result,
                "logged_in": True,
                "status": "logged_in",
                "message": account.get("message") or "\u5df2\u767b\u5f55",
            }
        if result.get("logged_in") and not account.get("logged_in"):
            account = {**account, "logged_in": True}
        return {"success": True, **result, "device": device_info, "account": account}
    except Exception as exc:
        return {
            "success": True,
            "logged_in": False,
            "status": "check_failed",
            "device": {},
            "account": {"logged_in": False, "nickname": "", "hongguo_id": ""},
            "message": str(exc),
        }


@router.get("/devices")
def list_devices():
    configured = _hongguo_device_addr()
    devices: List[Dict[str, Any]] = []
    for addr in discover_addrs():
        entry: Dict[str, Any] = {
            "serial": addr,
            "addr": addr,
            "online": False,
            "selected": addr == configured,
            "device": {},
            "message": "",
        }
        try:
            device = connect_exact(addr)
            ops = HongguoOperations(device)
            info = ops.get_device_info()
            serial = info.get("serial") or addr
            entry.update(
                {
                    "serial": serial,
                    "addr": serial,
                    "online": True,
                    "selected": serial == configured or addr == configured,
                    "device": info,
                    "message": "online",
                }
            )
        except Exception as exc:
            entry["message"] = str(exc)
        if entry.get("online"):
            devices.append(entry)
    return {
        "success": True,
        "selected_device_addr": configured,
        "configured_device_online": any(
            item.get("addr") == configured or item.get("serial") == configured for item in devices
        ),
        "settings": public_hongguo_settings(_hongguo_config()),
        "devices": devices,
    }


@router.get("/templates")
async def list_templates(
    category: Optional[str] = Query(default=None),
    include_default: bool = True,
):
    clauses: List[str] = []
    params: List[Any] = []
    if category:
        clauses.append("category=%s")
        params.append(category)
    if not include_default:
        clauses.append("is_default=0")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM hongguo_comment_templates
                {where}
                ORDER BY is_default DESC, id ASC
                """,
                params,
            )
            return cur.fetchall()


@router.post("/templates")
async def create_template(payload: TemplateCreate):
    with _connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO hongguo_comment_templates (content, category, is_default)
                VALUES (%s, %s, %s)
                """,
                (payload.content, payload.category, int(payload.is_default)),
            )
            template_id = cur.lastrowid
            cur.execute("SELECT * FROM hongguo_comment_templates WHERE id=%s", (template_id,))
            return cur.fetchone()


@router.get("/templates/{template_id}")
async def get_template(template_id: int):
    with _connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM hongguo_comment_templates WHERE id=%s", (template_id,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Template not found")
    return row


@router.put("/templates/{template_id}")
async def update_template(template_id: int, payload: TemplateUpdate):
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "is_default" in data:
        data["is_default"] = int(data["is_default"])
    assignments = [f"{key}=%s" for key in data]
    values = list(data.values())
    values.append(template_id)
    with _connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM hongguo_comment_templates WHERE id=%s", (template_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Template not found")
            cur.execute(
                f"""
                UPDATE hongguo_comment_templates
                SET {", ".join(assignments)}
                WHERE id=%s
                """,
                values,
            )
            cur.execute("SELECT * FROM hongguo_comment_templates WHERE id=%s", (template_id,))
            return cur.fetchone()


@router.delete("/templates/{template_id}")
async def delete_template(template_id: int):
    with _connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM hongguo_comment_templates WHERE id=%s", (template_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Template not found")
            cur.execute("DELETE FROM hongguo_comment_templates WHERE id=%s", (template_id,))
    return {"success": True, "id": template_id}
