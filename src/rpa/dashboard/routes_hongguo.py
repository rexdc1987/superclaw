"""Hongguo comment task API routes.

Phase 1 intentionally uses PyMySQL directly because the Hongguo PRD requires
MySQL as the source of truth and defines the table contract by column name.
"""

from __future__ import annotations

import json
import os
import threading
import time
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

from rpa.hongguo.ai_usage import load_usage_stats, record_usage, reset_usage_stats
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


class StageRunRequest(BaseModel):
    start_episode: int = Field(ge=1)
    end_episode: int = Field(ge=1)


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


DEBUG_STEPS = {
    "connect",
    "launch",
    "login",
    "page-state",
    "open-search",
    "input-keyword",
    "submit-search",
    "open-drama",
    "set-speed",
    "episodes",
    "detect-ad",
    "skip-ad",
    "play-first",
    "play-target",
    "play-next",
    "observe-current",
    # Compatibility aliases for older frontend tabs/bookmarks.
    "search",
    "select",
    "find-drama",
}


def _debug_screenshot(ops: HongguoOperations, task_id: int, tag: str) -> str:
    try:
        return ops.take_screenshot(f"debug_{tag}", str(_task_screenshot_dir(task_id).as_posix()))
    except Exception:
        return ""


def _debug_response(
    step: str,
    success: bool,
    message: str,
    data: Optional[Dict[str, Any]] = None,
    screenshot_path: str = "",
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "step": step,
        "success": success,
        "message": message,
        "data": data or {},
    }
    if screenshot_path:
        result["screenshot_path"] = screenshot_path
        result["screenshot_url"] = _public_screenshot_url(screenshot_path)
    return result


def _check_hongguo_login(ops: HongguoOperations) -> Dict[str, Any]:
    result = ops.check_login()
    device_info = ops.get_device_info()
    account = ops.get_account_info()
    if account.get("logged_in") and not result.get("logged_in"):
        result = {
            **result,
            "logged_in": True,
            "status": "logged_in",
            "message": account.get("message") or "已登录",
        }
    if result.get("logged_in") and not account.get("logged_in"):
        account = {**account, "logged_in": True}
    return {**result, "device": device_info, "account": account}


def _debug_page_state(ops: HongguoOperations, task: Dict[str, Any]) -> Dict[str, Any]:
    keyword = str(task.get("drama_name") or "").strip()
    xml = ops._xml()
    launcher_visible = ops._launcher_visible(xml)
    app_foreground = ops._is_app_foreground()
    return {
        "device": ops.get_device_info(),
        "app": ops._safe_app_current(),
        "app_foreground": app_foreground,
        "launcher_visible": launcher_visible,
        "first_visible_package": ops._first_visible_package(xml),
        "hongguo_visible_area_ratio": ops._hongguo_visible_area_ratio(xml),
        "current_episode": ops.get_current_episode(),
        "total_episodes": ops.get_total_episodes(),
        "playback_visible": ops._playback_visible(xml),
        "playback_paused": ops.is_playback_paused(),
        "ad_visible": ops._ad_continue_visible(xml),
        "detail_title": ops._extract_detail_title(keyword),
        "playing_title": ops._current_playing_title(),
    }


def _stage_comment_episodes(task: Dict[str, Any], total: int, start: int, end: int) -> List[int]:
    total = max(1, int(total or end or 1))
    end = min(max(start, end), total)
    if task.get("comment_mode") == "random":
        return []
    rule_start = max(1, int(task.get("start_episode") or 1))
    interval = max(1, int(task.get("episode_interval") or 1))
    return [episode for episode in range(rule_start, end + 1, interval) if start <= episode <= end]


def _prepare_step(steps: List[Dict[str, Any]], key: str, success: bool, message: str, data: Optional[Dict[str, Any]] = None) -> None:
    steps.append(
        {
            "step": key,
            "success": bool(success),
            "message": message,
            "data": data or {},
        }
    )


class PrepareFlowError(RuntimeError):
    def __init__(self, message: str, data: Dict[str, Any]):
        super().__init__(message)
        self.data = data


def _raise_prepare_error(message: str, data: Dict[str, Any]) -> None:
    data["failed_step"] = data.get("steps", [{}])[-1].get("step") if data.get("steps") else ""
    raise PrepareFlowError(message, data)


def _run_prepare_flow(task_id: int, task: Dict[str, Any], update_task: bool = True) -> Dict[str, Any]:
    keyword = str(task.get("drama_name") or "").strip()
    if not keyword:
        raise RuntimeError("任务短剧名称为空")

    device = connect(_hongguo_device_addr())
    ops = HongguoOperations(device)
    steps: List[Dict[str, Any]] = []
    data: Dict[str, Any] = {
        "keyword": keyword,
        "device": ops.get_device_info(),
        "steps": steps,
    }

    _prepare_step(steps, "connect", True, "设备连接成功", {"device": data["device"]})

    before_state = _debug_page_state(ops, task)
    _prepare_step(steps, "page-state", True, "页面状态已识别", before_state)
    data["before_state"] = before_state

    launched = ops.launch_app()
    _prepare_step(steps, "launch", launched, "红果启动成功" if launched else "红果启动未确认")
    if not launched:
        _raise_prepare_error("红果启动未确认", data)

    login = _check_hongguo_login(ops)
    data["login"] = login
    _prepare_step(steps, "login", bool(login.get("logged_in")), login.get("message") or "登录检测完成", login)
    if not login.get("logged_in"):
        _raise_prepare_error(login.get("message") or "登录检测失败", data)

    opened = ops.open_search_page(keyword)
    data["opened"] = opened
    _prepare_step(steps, "open-search", bool(opened.get("success")), opened.get("message") or "已进入搜索框", opened)
    if not opened.get("success"):
        _raise_prepare_error(opened.get("message") or "进入搜索框失败", data)

    input_result = ops.input_search_keyword(keyword)
    data["input"] = input_result
    _prepare_step(steps, "input-keyword", bool(input_result.get("success")), input_result.get("message") or "关键词已填入", input_result)
    if not input_result.get("success"):
        _raise_prepare_error(input_result.get("message") or "关键词填入失败", data)

    search = ops.submit_search(keyword)
    data["search"] = search
    data["titles"] = search.get("titles") or []
    _prepare_step(steps, "submit-search", bool(search.get("success")), search.get("message") or "搜索完成", search)
    if not search.get("success"):
        _raise_prepare_error(search.get("message") or "提交搜索失败", data)

    titles = ops._extract_drama_titles()
    selected_title = ops._choose_title(keyword, titles)
    data["titles"] = titles
    data["selected_title"] = selected_title
    if not selected_title:
        _prepare_step(steps, "open-drama", False, "没有匹配任务短剧名称的搜索结果", {"titles": titles})
        _raise_prepare_error("没有匹配任务短剧名称的搜索结果", data)

    selected = ops.select_drama(selected_title, keyword=keyword)
    data["selected"] = selected
    data["drama_title"] = selected.get("drama_title") or selected_title
    _prepare_step(steps, "open-drama", bool(selected.get("success")), selected.get("message") or "已进入目标剧集", selected)
    if not selected.get("success"):
        _raise_prepare_error(selected.get("message") or "进入目标剧集失败", data)

    playback_speed = str(task.get("playback_speed") or "1.0x")
    speed_set = True if playback_speed == "1.0x" else ops.set_playback_speed(playback_speed)
    data["playback_speed"] = playback_speed
    data["speed_set"] = speed_set
    _prepare_step(steps, "set-speed", speed_set, f"倍速已设置: {playback_speed}" if speed_set else f"倍速设置失败: {playback_speed}")
    if not speed_set:
        _raise_prepare_error(f"倍速设置失败: {playback_speed}", data)

    total = ops.get_total_episodes()
    current = ops.get_current_episode()
    data["total_episodes"] = total
    data["current_episode_before_first"] = current
    _prepare_step(steps, "episodes", total > 0 or current > 0, f"当前第{current}集，总集数{total}", {"current_episode": current, "total_episodes": total})

    played = ops.play_episode(1)
    time.sleep(2)
    after = ops.get_current_episode()
    data["current_episode"] = after
    data["played_first"] = played
    _prepare_step(
        steps,
        "play-first",
        bool(played and after == 1),
        "第1集播放已确认" if after == 1 else "第1集播放未确认",
        {"played": played, "after_episode": after},
    )
    if not played or after != 1:
        _raise_prepare_error("第1集播放未确认", data)

    final_state = _debug_page_state(ops, task)
    data["final_state"] = final_state

    if update_task:
        with _connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE hongguo_comment_tasks
                    SET current_episode=%s,
                        total_episodes=COALESCE(NULLIF(%s, 0), total_episodes),
                        status='stopped',
                        error_message=NULL,
                        updated_at=%s
                    WHERE id=%s
                    """,
                    (1, total, datetime.now(), task_id),
                )
    return data


def _run_stage_task(task_id: int, start_episode: int, end_episode: int) -> None:
    try:
        with _connection() as conn:
            task = _fetch_one_or_404(conn, task_id)
            _insert_log(conn, task_id, f"阶段测试: 开始第{start_episode}-{end_episode}集")
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE hongguo_comment_tasks
                    SET status='running', current_episode=%s, completed_at=NULL, error_message=NULL, updated_at=%s
                    WHERE id=%s
                    """,
                    (start_episode, datetime.now(), task_id),
                )

        device = connect(_hongguo_device_addr())
        ops = HongguoOperations(device)
        task_snapshot = dict(task)

        stage_state = _debug_page_state(ops, task_snapshot)
        if not stage_state.get("playback_visible"):
            shot = _debug_screenshot(ops, task_id, f"stage_{start_episode}_{end_episode}_not_playback")
            raise RuntimeError(f"阶段测试未检测到播放页，请先执行一次性准备流程，已截图 {shot}")

        with _connection() as conn:
            _insert_log(
                conn,
                task_id,
                f"阶段测试: 使用当前播放页继续测试 | keyword={task_snapshot.get('drama_name') or ''} | current={stage_state.get('current_episode') or 0} | total={stage_state.get('total_episodes') or task_snapshot.get('total_episodes') or 0} | speed={task_snapshot.get('playback_speed') or ''}",
            )
        total = int(stage_state.get("total_episodes") or 0) or ops.get_total_episodes() or int(task_snapshot.get("total_episodes") or end_episode)
        end_episode = min(end_episode, max(start_episode, total))
        comment_hits = set(_stage_comment_episodes(task_snapshot, total, start_episode, end_episode))

        playback_speed = str(task_snapshot.get("playback_speed") or "1.0x")
        speed_set = True
        if playback_speed != "1.0x":
            speed_set = ops.set_playback_speed(playback_speed)
            with _connection() as conn:
                level = "info" if speed_set else "warn"
                message = f"阶段测试: 倍速已设置为 {playback_speed}" if speed_set else f"阶段测试: 倍速设置失败，目标 {playback_speed}"
                _insert_log(conn, task_id, message, level)

        if not ops.play_episode(start_episode):
            shot = _debug_screenshot(ops, task_id, f"stage_{start_episode}_{end_episode}_start_failed")
            raise RuntimeError(f"阶段测试无法切到第{start_episode}集，截图: {shot}")

        with _connection() as conn:
            _insert_log(
                conn,
                task_id,
                f"阶段测试: 已切到第{start_episode}集，倍速 {playback_speed}，评论命中集数 {sorted(comment_hits)}",
            )

        for episode in range(start_episode, end_episode + 1):
            current = ops.get_current_episode()
            if current and current != episode:
                raise RuntimeError(f"阶段测试跳集异常: 期望第{episode}集，当前第{current}集")

            with _connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE hongguo_comment_tasks SET current_episode=%s, updated_at=%s WHERE id=%s",
                        (episode, datetime.now(), task_id),
                    )
                _insert_log(conn, task_id, f"阶段测试: 正在观察第{episode}集")

            if episode in comment_hits:
                shot = _debug_screenshot(ops, task_id, f"stage_ep{episode}_comment_hit")
                with _connection() as conn:
                    _insert_log(conn, task_id, f"阶段测试: 第{episode}集命中评论规则，已截图留证 {shot}")

            if episode >= end_episode:
                break

            target = episode + 1
            deadline = time.time() + max(30, int(task_snapshot.get("comment_interval_sec") or 30) + 90)
            last_seen = current
            unknown_reads = 0
            stale_current_reads = 0
            stale_recoveries = 0
            last_recovery_at = 0.0
            while time.time() < deadline:
                if not ops._is_app_foreground():
                    app = ops._safe_app_current()
                    first_package = ops._first_visible_package(ops._xml())
                    shot = _debug_screenshot(ops, task_id, f"stage_ep{episode}_not_foreground")
                    with _connection() as conn:
                        _insert_log(
                            conn,
                            task_id,
                            f"阶段测试: 第{episode}集后红果不在前台，当前={app.get('package') or '-'}，可见={first_package or '-'}，已截图 {shot}，尝试拉回红果",
                            "warn",
                        )
                    foreground = ops.bring_to_foreground()
                    time.sleep(2)
                    resumed = ops.resume_playback_if_paused(allow_center_fallback=True)
                    recovered_episode = ops.get_current_episode()
                    with _connection() as conn:
                        _insert_log(conn, task_id, f"阶段测试: 红果前台恢复={foreground}，继续播放={resumed}，当前集={recovered_episode or 0}", "info")
                    if not recovered_episode and not ops._ad_continue_visible():
                        shot = _debug_screenshot(ops, task_id, f"stage_ep{episode}_lost_playback")
                        raise RuntimeError(f"阶段测试第{episode}集后已离开播放页，恢复失败，需重跑一次性准备流程，已截图 {shot}")
                    unknown_reads = 0
                    last_recovery_at = time.time()
                    continue

                if ops._ad_continue_visible():
                    shot = _debug_screenshot(ops, task_id, f"stage_ep{episode}_ad")
                    with _connection() as conn:
                        _insert_log(conn, task_id, f"阶段测试: 第{episode}集后出现广告，已截图 {shot}，尝试上滑继续")
                    ops.skip_ad_if_present()
                    time.sleep(3)
                    unknown_reads = 0
                    continue

                current = ops.get_current_episode()
                if current == target:
                    with _connection() as conn:
                        _insert_log(conn, task_id, f"阶段测试: 已自动进入第{target}集")
                    break
                if current == episode:
                    stale_current_reads += 1
                    now = time.time()
                    if stale_current_reads >= 8 and now - last_recovery_at >= 20:
                        stale_recoveries += 1
                        last_recovery_at = now
                        shot = _debug_screenshot(ops, task_id, f"stage_ep{episode}_stale_current")
                        with _connection() as conn:
                            _insert_log(
                                conn,
                                task_id,
                                f"阶段测试: 第{episode}集后长时间仍识别为第{episode}集，已截图 {shot}，尝试拉回红果/跳广告/继续播放",
                                "warn",
                            )
                        foreground = ops.bring_to_foreground()
                        time.sleep(2)
                        skipped = ops.skip_ad_if_present()
                        resumed = ops.resume_playback_if_paused(allow_center_fallback=True)
                        recovered_episode = ops.get_current_episode()
                        forced = False
                        if recovered_episode and stale_recoveries >= 2 and time.time() >= deadline - 35:
                            forced = ops.play_episode(target)
                            time.sleep(2)
                        with _connection() as conn:
                            _insert_log(
                                conn,
                                task_id,
                                f"阶段测试: 停留恢复完成，前台={foreground}，跳广告={skipped}，继续播放={resumed}，当前集={recovered_episode or 0}，强制切目标集={forced}",
                                "info" if not forced else "warn",
                            )
                        if not recovered_episode and not ops._ad_continue_visible():
                            shot = _debug_screenshot(ops, task_id, f"stage_ep{episode}_lost_playback")
                            raise RuntimeError(f"阶段测试第{episode}集后已离开播放页，恢复失败，需重跑一次性准备流程，已截图 {shot}")
                        continue
                else:
                    stale_current_reads = 0
                if current:
                    unknown_reads = 0
                if current and current > target:
                    if ops._ad_continue_visible():
                        time.sleep(2)
                        continue
                    raise RuntimeError(f"阶段测试跳过目标集: 目标第{target}集，当前第{current}集")
                if current and current < episode:
                    raise RuntimeError(f"阶段测试回退异常: 当前第{current}集，上一集第{episode}集")
                if not current:
                    unknown_reads += 1
                    now = time.time()
                    if unknown_reads >= 4 and now - last_recovery_at >= 10:
                        last_recovery_at = now
                        shot = _debug_screenshot(ops, task_id, f"stage_ep{episode}_unknown_recover")
                        with _connection() as conn:
                            _insert_log(
                                conn,
                                task_id,
                                f"阶段测试: 第{episode}集后连续无法识别当前集，已截图 {shot}，尝试恢复红果前台/跳广告/继续播放",
                                "warn",
                            )
                        skipped = ops.skip_ad_if_present()
                        foreground = ops.bring_to_foreground()
                        time.sleep(2)
                        skipped = ops.skip_ad_if_present() or skipped
                        resumed = ops.resume_playback_if_paused(allow_center_fallback=True)
                        recovered_episode = ops.get_current_episode()
                        with _connection() as conn:
                            _insert_log(
                                conn,
                                task_id,
                                f"阶段测试: 恢复动作完成，前台={foreground}，跳广告={skipped}，继续播放={resumed}，当前集={recovered_episode or 0}",
                                "info",
                            )
                        if not recovered_episode and not ops._ad_continue_visible():
                            shot = _debug_screenshot(ops, task_id, f"stage_ep{episode}_lost_playback")
                            raise RuntimeError(f"阶段测试第{episode}集后已离开播放页，恢复失败，需重跑一次性准备流程，已截图 {shot}")
                        time.sleep(2)
                        continue
                if current != last_seen:
                    last_seen = current
                    with _connection() as conn:
                        message = f"阶段测试: 等待第{target}集，当前第{current}集" if current else f"阶段测试: 等待第{target}集，当前集数无法识别"
                        _insert_log(conn, task_id, message, "warn" if not current else "info")
                time.sleep(2)
            else:
                shot = _debug_screenshot(ops, task_id, f"stage_ep{episode}_next_timeout")
                raise RuntimeError(f"阶段测试第{episode}集后未自动进入第{target}集，已截图 {shot}")

        with _connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE hongguo_comment_tasks
                    SET status='stopped', current_episode=%s, completed_at=%s, error_message=NULL, updated_at=%s
                    WHERE id=%s
                    """,
                    (end_episode, datetime.now(), datetime.now(), task_id),
                )
            _insert_log(conn, task_id, f"阶段测试: 第{start_episode}-{end_episode}集完成")
    except Exception as exc:
        with _connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE hongguo_comment_tasks
                    SET status='failed', error_message=%s, completed_at=%s, updated_at=%s
                    WHERE id=%s
                    """,
                    (str(exc), datetime.now(), datetime.now(), task_id),
                )
            _insert_log(conn, task_id, f"阶段测试失败: {exc}", "error")


def _stage_log(task_id: int, message: str, level: str = "info") -> None:
    with _connection() as conn:
        _insert_log(conn, task_id, message, level)


def _stage_templates(task: Dict[str, Any]) -> List[str]:
    value = task.get("templates_json")
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def _stage_save_record(
    task_id: int,
    episode: int,
    content: str,
    source: str,
    status: str,
    screenshot_input: str = "",
    screenshot_verified: str = "",
    error_message: Optional[str] = None,
) -> None:
    with _connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO hongguo_comment_records (
                    task_id, episode_number, comment_text, generated_by,
                    status, screenshot_input, screenshot_verified, error_message, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    task_id,
                    episode,
                    content,
                    source,
                    status,
                    screenshot_input or None,
                    screenshot_verified or None,
                    error_message,
                    datetime.now(),
                ),
            )


def _stage_comment_already_verified(task_id: int, episode: int) -> bool:
    with _connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id
                FROM hongguo_comment_records
                WHERE task_id=%s AND episode_number=%s AND status='success'
                ORDER BY id DESC
                LIMIT 1
                """,
                (task_id, episode),
            )
            return cur.fetchone() is not None


def _stage_increment_counter(task_id: int, counter: str) -> None:
    if counter not in {"sent", "verified"}:
        return
    column = "comments_verified" if counter == "verified" else "comments_sent"
    with _connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE hongguo_comment_tasks SET {column}={column}+1 WHERE id=%s", (task_id,))


def _stage_expected_total(task: Dict[str, Any], state: Dict[str, Any], end_episode: int) -> int:
    return int(task.get("total_episodes") or state.get("total_episodes") or end_episode or 0)


def _stage_total_mismatch_is_fatal(
    ops: HongguoOperations,
    task: Dict[str, Any],
    state: Dict[str, Any],
    expected_total: int,
    total: int,
    current: int = 0,
    target: int = 0,
) -> bool:
    if not expected_total or not total or total == expected_total:
        return False

    keyword = str(task.get("drama_name") or "").strip()
    detail_title = str(state.get("detail_title") or "").strip()
    title_matches = bool(detail_title and keyword and ops._title_matches(keyword, detail_title))
    if title_matches and total < expected_total:
        # On the playback page Hongguo sometimes exposes only the currently
        # visible episode label, so get_total_episodes can temporarily read
        # 143 while the prepared task total is 144. Keep the jump guard, but
        # do not treat that as a different drama when the title still matches.
        observed_floor = max(current, target)
        if observed_floor and total >= observed_floor:
            return False
        if expected_total - total <= 1:
            return False

    return True


def _stage_assert_target_playback(
    ops: HongguoOperations,
    task: Dict[str, Any],
    state: Dict[str, Any],
    expected_total: int,
) -> None:
    app = state.get("app") or {}
    if app.get("package") != "com.phoenix.read":
        raise RuntimeError(f"阶段测试未停留在红果 APP，当前 package={app.get('package') or '-'}")
    if app.get("activity") != "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity":
        raise RuntimeError(f"阶段测试未停留在目标短剧播放页，当前 activity={app.get('activity') or '-'}")
    total = int(state.get("total_episodes") or 0)
    current = int(state.get("current_episode") or 0)
    if _stage_total_mismatch_is_fatal(ops, task, state, expected_total, total, current=current):
        raise RuntimeError(f"阶段测试检测到短剧总集数不匹配: 期望 {expected_total}，实际 {total}")
    if not current:
        raise RuntimeError("阶段测试未识别到当前集数，请先确认一次性准备流程已切到目标剧播放页")
    if not ops._playback_visible():
        raise RuntimeError("阶段测试未检测到播放控件，请先确认一次性准备流程已完成")


def _stage_resume_if_paused(task_id: int, ops: HongguoOperations, episode: int) -> bool:
    if not ops.is_playback_paused():
        return False
    resumed = ops.resume_playback_if_paused(allow_center_fallback=True)
    still_paused = ops.is_playback_paused()
    ok = bool(resumed and not still_paused)
    _stage_log(
        task_id,
        f"阶段测试v3: 第{episode}集检测到暂停，已尝试恢复播放={resumed}，仍暂停={still_paused}",
        "info" if ok else "warn",
    )
    return ok


def _stage_safe_resume_playback(task_id: int, ops: HongguoOperations, episode: int, reason: str) -> bool:
    resumed = ops.resume_playback_safely()
    still_paused = ops.is_playback_paused()
    ok = bool(resumed and not still_paused)
    _stage_log(
        task_id,
        f"阶段测试v3: 第{episode}集{reason}，发送安全播放指令={resumed}，仍暂停={still_paused}",
        "info" if ok else "warn",
    )
    return ok


def _stage_wait_for_episode(
    task_id: int,
    ops: HongguoOperations,
    task: Dict[str, Any],
    target: int,
    expected_total: int,
    timeout: int = 60,
) -> bool:
    deadline = time.time() + max(20, timeout)
    last_log_at = 0.0
    while time.time() < deadline:
        state = _debug_page_state(ops, task)
        app = state.get("app") or {}
        current = int(state.get("current_episode") or 0)
        if app.get("package") != "com.phoenix.read":
            raise RuntimeError(f"阶段测试切集时红果不在前台，当前 package={app.get('package') or '-'}")
        if state.get("ad_visible"):
            shot = _debug_screenshot(ops, task_id, f"stage_seek_ep{target}_ad")
            skipped = ops.skip_ad_if_present(attempts=3)
            if not skipped:
                ops._swipe_up_continue_ad()
            _stage_log(task_id, f"阶段测试: 切第{target}集时遇到广告，已截图 {shot}，上滑继续观看", "warn")
            time.sleep(3)
            continue
        if app.get("activity") != "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity":
            raise RuntimeError(f"阶段测试切集时未停留在短剧播放页，当前 activity={app.get('activity') or '-'}")
        total = int(state.get("total_episodes") or 0)
        if _stage_total_mismatch_is_fatal(ops, task, state, expected_total, total, current=current, target=target):
            raise RuntimeError(f"阶段测试切集时短剧总集数不匹配: 期望 {expected_total}，实际 {total}")
        if current == target:
            return True
        now = time.time()
        if now - last_log_at >= 10:
            _stage_log(task_id, f"阶段测试: 正在确认第{target}集，当前识别第{current or 0}集")
            last_log_at = now
        _stage_safe_resume_playback(task_id, ops, current or target, "切集确认中")
        time.sleep(2)
    return False


def _stage_seek_start_episode(
    task_id: int,
    ops: HongguoOperations,
    task: Dict[str, Any],
    start_episode: int,
    expected_total: int,
) -> None:
    for attempt in range(1, 3):
        state = _debug_page_state(ops, task)
        current = int(state.get("current_episode") or 0)
        if current == start_episode:
            _stage_log(task_id, f"阶段测试v3: 已在阶段起始第{start_episode}集")
            return
        if state.get("ad_visible"):
            shot = _debug_screenshot(ops, task_id, f"stage_seek_ep{start_episode}_ad")
            skipped = ops.skip_ad_if_present(attempts=3)
            if not skipped:
                ops._swipe_up_continue_ad()
            _stage_log(task_id, f"阶段测试v3: 切第{start_episode}集前遇到广告，已截图 {shot}，上滑继续观看", "warn")
            time.sleep(3)
            continue
        app = state.get("app") or {}
        if app.get("package") != "com.phoenix.read":
            raise RuntimeError(f"阶段测试切第{start_episode}集前红果不在前台，当前 package={app.get('package') or '-'}")
        if app.get("activity") != "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity":
            raise RuntimeError(f"阶段测试切第{start_episode}集前未停留在短剧播放页，当前 activity={app.get('activity') or '-'}")
        total = int(state.get("total_episodes") or 0)
        if _stage_total_mismatch_is_fatal(
            ops,
            task,
            state,
            expected_total,
            total,
            current=current,
            target=start_episode,
        ):
            raise RuntimeError(f"阶段测试切第{start_episode}集前短剧总集数不匹配: 期望 {expected_total}，实际 {total}")
        if not state.get("playback_visible"):
            raise RuntimeError("阶段测试切集前未检测到播放/选集页面")
        _stage_log(task_id, f"阶段测试v3: 按阶段起始集切到第{start_episode}集，当前第{current or 0}集，尝试{attempt}/2")
        played = ops.play_episode(start_episode)
        if played or _stage_wait_for_episode(task_id, ops, task, start_episode, expected_total, timeout=60):
            _stage_log(task_id, f"阶段测试v3: 第{start_episode}集播放已确认")
            return
        time.sleep(2)
    shot = _debug_screenshot(ops, task_id, f"stage_seek_ep{start_episode}_failed")
    raise RuntimeError(f"阶段测试无法切到第{start_episode}集，已按阶段起始集重试，截图: {shot}")


def _stage_handle_comment(
    task_id: int,
    ops: HongguoOperations,
    task: Dict[str, Any],
    episode: int,
    expected_total: int,
) -> None:
    drama_title = (
        ops._current_playing_title()
        or ops._extract_detail_title(str(task.get("drama_name") or ""))
        or str(task.get("drama_name") or "")
    )
    generator = CommentGenerator(_ai_config())
    content, source, usage = generator.generate_with_usage(
        drama_title,
        task.get("content_source", "ai"),
        _stage_templates(task),
    )
    if usage:
        record_usage(usage, context=f"stage:{task_id}:episode:{episode}")

    paused = ops.pause_playback_if_playing()
    _stage_log(task_id, f"阶段测试: 第{episode}集命中评论规则，暂停播放={paused}，准备评论")
    screenshot_dir = str(_task_screenshot_dir(task_id).as_posix())
    input_path = ops.take_screenshot(f"stage_ep{episode}_before_comment", screenshot_dir)
    post = ops.post_comment(content, episode)
    if not post.get("success"):
        failed_path = ops.take_screenshot(f"stage_ep{episode}_post_failed", screenshot_dir)
        _stage_save_record(
            task_id,
            episode,
            content,
            source,
            "failed",
            input_path,
            failed_path,
            post.get("message") or "评论发送失败",
        )
        _stage_log(task_id, f"阶段测试: 第{episode}集评论发送失败 - {post.get('message')}", "error")
        ops.ensure_playback_page(episode)
        _stage_resume_if_paused(task_id, ops, episode)
        return

    _stage_increment_counter(task_id, "sent")
    verify = ops.verify_comment(content, episode, screenshot_dir)
    verify_path = verify.get("screenshot_path") or ops.take_screenshot(
        f"stage_ep{episode}_{'verified' if verify.get('verified') else 'not_found'}",
        screenshot_dir,
    )
    status = "success" if verify.get("verified") else "failed"
    error = None if verify.get("verified") else verify.get("message", "评论验证失败")
    _stage_save_record(task_id, episode, content, source, status, input_path, verify_path, error)
    if status == "success":
        _stage_increment_counter(task_id, "verified")
    _stage_log(
        task_id,
        f"阶段测试: 第{episode}集评论{'验证成功' if status == 'success' else '验证失败'}，截图 {verify_path}",
        "info" if status == "success" else "error",
    )

    ops.ensure_playback_page(episode)
    state = _debug_page_state(ops, task)
    _stage_assert_target_playback(ops, task, state, expected_total)
    _stage_resume_if_paused(task_id, ops, episode)


def _stage_wait_for_next_episode(
    task_id: int,
    ops: HongguoOperations,
    task: Dict[str, Any],
    episode: int,
    target: int,
    expected_total: int,
) -> bool:
    deadline = time.time() + max(300, int(task.get("comment_interval_sec") or 30) + 240)
    last_log_at = 0.0
    same_episode_since = 0.0
    forced_target = False
    while time.time() < deadline:
        state = _debug_page_state(ops, task)
        app = state.get("app") or {}
        current = int(state.get("current_episode") or 0)
        ad_visible = bool(state.get("ad_visible"))

        if app.get("package") != "com.phoenix.read":
            raise RuntimeError(f"阶段测试第{episode}集后红果不在前台，当前 package={app.get('package') or '-'}")
        if ad_visible:
            shot = _debug_screenshot(ops, task_id, f"stage_ep{episode}_ad")
            skipped = ops.skip_ad_if_present(attempts=3)
            if not skipped:
                ops._swipe_up_continue_ad()
                _stage_log(
                    task_id,
                    f"阶段测试: 第{episode}集后出现广告，常规跳过未确认成功，已截图 {shot}，执行兜底上滑",
                    "warn",
                )
            else:
                _stage_log(task_id, f"阶段测试: 第{episode}集后出现广告，已截图 {shot}，上滑继续观看")
            time.sleep(3)
            continue
        if app.get("activity") != "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity":
            total = int(state.get("total_episodes") or 0)
            raise RuntimeError(
                f"阶段测试第{episode}集后已离开目标短剧播放页，当前 activity={app.get('activity') or '-'}，识别总集数={total or 0}"
            )
        total = int(state.get("total_episodes") or 0)
        if current == 0 and total == 0:
            shot = _debug_screenshot(ops, task_id, f"stage_ep{episode}_unknown_ad_overlay")
            _stage_log(
                task_id,
                f"阶段测试: 第{episode}集后播放页集数不可见，按广告/遮罩页处理，已截图 {shot}，上滑继续观看",
                "warn",
            )
            ops._swipe_up_continue_ad()
            time.sleep(3)
            continue
        if _stage_total_mismatch_is_fatal(ops, task, state, expected_total, total, current=current, target=target):
            raise RuntimeError(f"阶段测试第{episode}集后跳到其他短剧: 期望总集数 {expected_total}，实际 {total}")

        if current == target:
            _stage_log(task_id, f"阶段测试: 已自动进入第{target}集")
            return True
        if current == episode:
            now = time.time()
            if same_episode_since <= 0:
                same_episode_since = now
            if now - last_log_at >= 30:
                _stage_log(
                    task_id,
                    f"阶段测试: 仍在第{episode}集，播放页=True，广告=False，等待自动播放第{target}集",
                )
                _stage_safe_resume_playback(task_id, ops, episode, "仍停留当前集，检查是否暂停")
                last_log_at = now
            if not forced_target and now - same_episode_since >= 150:
                shot = _debug_screenshot(ops, task_id, f"stage_ep{episode}_stale_force_target")
                forced_target = ops.play_episode(target)
                _stage_log(
                    task_id,
                    f"阶段测试v3: 第{episode}集停留超过150秒，已截图 {shot}，强制切第{target}集={forced_target}",
                    "warn",
                )
                time.sleep(3)
        elif current == 0:
            now = time.time()
            same_episode_since = 0.0
            if now - last_log_at >= 20:
                _stage_log(task_id, f"阶段测试: 第{episode}集后暂未识别到集数，播放页=True，广告=False，继续观察", "warn")
                _stage_safe_resume_playback(task_id, ops, episode, "集数暂未识别，检查是否暂停")
                last_log_at = now
        else:
            same_episode_since = 0.0
        if current > target:
            raise RuntimeError(f"阶段测试跳过目标集: 目标第{target}集，当前第{current}集")
        if current < episode:
            raise RuntimeError(f"阶段测试回退异常: 上一集第{episode}集，当前第{current}集")
        time.sleep(2)
    return False


def _run_stage_task_v2(task_id: int, start_episode: int, end_episode: int) -> None:
    try:
        with _connection() as conn:
            task = _fetch_one_or_404(conn, task_id)
            _insert_log(conn, task_id, f"阶段测试v3: 开始第{start_episode}-{end_episode}集")
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE hongguo_comment_tasks
                    SET status='running', current_episode=%s, completed_at=NULL, error_message=NULL, updated_at=%s
                    WHERE id=%s
                    """,
                    (start_episode, datetime.now(), task_id),
                )

        device = connect(_hongguo_device_addr())
        ops = HongguoOperations(device)
        task_snapshot = dict(task)

        stage_state = _debug_page_state(ops, task_snapshot)
        expected_total = _stage_expected_total(task_snapshot, stage_state, end_episode)
        _stage_assert_target_playback(ops, task_snapshot, stage_state, expected_total)
        current_episode = int(stage_state.get("current_episode") or 0)
        total = expected_total or int(stage_state.get("total_episodes") or end_episode)
        end_episode = min(end_episode, max(start_episode, total))
        comment_hits = set(_stage_comment_episodes(task_snapshot, total, start_episode, end_episode))
        _stage_log(
            task_id,
            f"阶段测试v3: 一次性准备状态已确认 | current={current_episode} | total={total} | hits={sorted(comment_hits)}",
        )

        playback_speed = str(task_snapshot.get("playback_speed") or "1.0x")
        if playback_speed != "1.0x":
            speed_set = ops.set_playback_speed(playback_speed)
            _stage_log(
                task_id,
                f"阶段测试v3: 倍速{'已设置' if speed_set else '设置失败'} {playback_speed}",
                "info" if speed_set else "warn",
            )

        run_start_episode = start_episode
        if start_episode <= current_episode <= end_episode:
            run_start_episode = current_episode
            _stage_log(
                task_id,
                f"阶段测试v3: 当前已在阶段范围内，从第{run_start_episode}集继续，不重跑阶段起始集",
            )
        else:
            _stage_seek_start_episode(task_id, ops, task_snapshot, start_episode, total)
        _stage_resume_if_paused(task_id, ops, run_start_episode)

        for episode in range(run_start_episode, end_episode + 1):
            state = _debug_page_state(ops, task_snapshot)
            _stage_assert_target_playback(ops, task_snapshot, state, total)
            current = int(state.get("current_episode") or 0)
            if current and current != episode:
                raise RuntimeError(f"阶段测试跳集异常: 期望第{episode}集，当前第{current}集")

            with _connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE hongguo_comment_tasks SET current_episode=%s, updated_at=%s WHERE id=%s",
                        (episode, datetime.now(), task_id),
                    )
                _insert_log(conn, task_id, f"阶段测试v3: 正在观察第{episode}集")

            _stage_resume_if_paused(task_id, ops, episode)
            if episode in comment_hits:
                if _stage_comment_already_verified(task_id, episode):
                    _stage_log(task_id, f"阶段测试v3: 第{episode}集已有成功评论记录，跳过重复评论")
                else:
                    _stage_handle_comment(task_id, ops, task_snapshot, episode, total)

            if episode >= end_episode:
                break
            target = episode + 1
            if not _stage_wait_for_next_episode(task_id, ops, task_snapshot, episode, target, total):
                shot = _debug_screenshot(ops, task_id, f"stage_ep{episode}_next_timeout")
                raise RuntimeError(f"阶段测试第{episode}集后未自动进入第{target}集，已截图 {shot}")

        with _connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE hongguo_comment_tasks
                    SET status='stopped', current_episode=%s, completed_at=%s, error_message=NULL, updated_at=%s
                    WHERE id=%s
                    """,
                    (end_episode, datetime.now(), datetime.now(), task_id),
                )
            _insert_log(conn, task_id, f"阶段测试v3: 第{start_episode}-{end_episode}集完成")
    except Exception as exc:
        with _connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE hongguo_comment_tasks
                    SET status='failed', error_message=%s, completed_at=%s, updated_at=%s
                    WHERE id=%s
                    """,
                    (str(exc), datetime.now(), datetime.now(), task_id),
                )
            _insert_log(conn, task_id, f"阶段测试v3失败: {exc}", "error")


@router.post("/tasks/{task_id}/debug/{step}")
async def debug_task_step(task_id: int, step: str):
    if step not in DEBUG_STEPS:
        raise HTTPException(status_code=400, detail=f"Invalid debug step: {step}")
    with _connection() as conn:
        task = _fetch_one_or_404(conn, task_id)
        _insert_log(conn, task_id, f"分步测试: 开始 {step}")

    try:
        device = connect(_hongguo_device_addr())
        ops = HongguoOperations(device)
        data: Dict[str, Any] = {"device": ops.get_device_info()}
        screenshot_path = ""

        if step == "connect":
            screenshot_path = _debug_screenshot(ops, task_id, step)
            result = _debug_response(step, True, "设备连接成功", data, screenshot_path)
        elif step == "launch":
            launched = ops.launch_app()
            login = _check_hongguo_login(ops) if launched else {}
            data.update({"launched": launched, "login": login, "device": ops.get_device_info()})
            screenshot_path = _debug_screenshot(ops, task_id, step)
            result = _debug_response(step, launched, "红果启动成功" if launched else "红果启动未确认", data, screenshot_path)
        elif step == "login":
            login = _check_hongguo_login(ops)
            data.update({"login": login, "account": login.get("account") or {}, "device": login.get("device") or data.get("device")})
            screenshot_path = _debug_screenshot(ops, task_id, step)
            result = _debug_response(
                step,
                bool(login.get("logged_in")),
                login.get("message") or "登录检测完成",
                data,
                screenshot_path,
            )
        elif step == "page-state":
            state = _debug_page_state(ops, task)
            data.update(state)
            screenshot_path = _debug_screenshot(ops, task_id, step)
            current = state.get("current_episode") or 0
            ad = "，检测到广告提示" if state.get("ad_visible") else ""
            result = _debug_response(
                step,
                True,
                f"当前第{current}集，播放页={bool(state.get('playback_visible'))}{ad}",
                data,
                screenshot_path,
            )
        elif step in {"open-search", "input-keyword", "submit-search", "open-drama", "set-speed", "find-drama", "search", "select"}:
            keyword = str(task.get("drama_name") or "").strip()
            if not keyword:
                raise RuntimeError("任务短剧名称为空")
            if step == "open-search":
                opened = ops.open_search_page(keyword)
                data.update({"keyword": keyword, "opened": opened})
                screenshot_path = _debug_screenshot(ops, task_id, step)
                result = _debug_response(
                    step,
                    bool(opened.get("success")),
                    opened.get("message") or "已进入搜索框",
                    data,
                    screenshot_path,
                )
            elif step == "input-keyword":
                input_result = ops.input_search_keyword(keyword)
                data.update({"keyword": keyword, "input": input_result, "input_text": input_result.get("input_text") or ""})
                screenshot_path = _debug_screenshot(ops, task_id, step)
                result = _debug_response(
                    step,
                    bool(input_result.get("success")),
                    input_result.get("message") or "关键词已填入",
                    data,
                    screenshot_path,
                )
            elif step == "submit-search":
                search = ops.submit_search(keyword)
                data.update(
                    {
                        "keyword": keyword,
                        "search": search,
                        "titles": search.get("titles") or [],
                    }
                )
                screenshot_path = _debug_screenshot(ops, task_id, step)
                result = _debug_response(
                    step,
                    bool(search.get("success")),
                    search.get("message") or "搜索完成",
                    data,
                    screenshot_path,
                )
            elif step == "search":
                launched = ops.launch_app()
                search = ops.search_drama(keyword)
                data.update(
                    {
                        "launched": launched,
                        "keyword": keyword,
                        "search": search,
                        "titles": search.get("titles") or [],
                    }
                )
                screenshot_path = _debug_screenshot(ops, task_id, step)
                result = _debug_response(
                    step,
                    bool(search.get("success")),
                    search.get("message") or "搜索完成",
                    data,
                    screenshot_path,
                )
            elif step in {"open-drama", "select"}:
                titles = ops._extract_drama_titles()
                selected_title = ops._choose_title(keyword, titles)
                if selected_title:
                    selected = ops.select_drama(selected_title, keyword=keyword)
                    success = bool(selected.get("success"))
                    message = selected.get("message") or ("已进入短剧详情" if success else "短剧不可播放")
                else:
                    selected = {}
                    success = False
                    message = "没有匹配任务短剧名称的搜索结果"
                data.update(
                    {
                        "keyword": keyword,
                        "titles": titles,
                        "selected_title": selected_title,
                        "selected": selected,
                        "drama_title": selected.get("drama_title") or selected_title,
                        "playable": bool(selected.get("playable")),
                        "detail_visible": bool(selected.get("detail_visible")),
                    }
                )
                screenshot_path = _debug_screenshot(ops, task_id, step)
                result = _debug_response(step, success, message, data, screenshot_path)
            elif step == "set-speed":
                speed = str(task.get("playback_speed") or "1.0x")
                success = True if speed == "1.0x" else ops.set_playback_speed(speed)
                data.update({"playback_speed": speed, "speed_set": success, "state": _debug_page_state(ops, task)})
                screenshot_path = _debug_screenshot(ops, task_id, step)
                result = _debug_response(
                    step,
                    bool(success),
                    f"倍速已设置: {speed}" if success else f"倍速设置失败: {speed}",
                    data,
                    screenshot_path,
                )
            else:
                launched = ops.launch_app()
                found = ops.find_drama(keyword)
                data.update({"launched": launched, **found})
                screenshot_path = _debug_screenshot(ops, task_id, step)
                result = _debug_response(
                    step,
                    bool(found.get("success")),
                    found.get("message") or "搜索并进入短剧完成",
                    data,
                    screenshot_path,
                )
        elif step == "episodes":
            total = ops.get_total_episodes()
            current = ops.get_current_episode()
            data.update(
                {
                    "current_episode": current,
                    "total_episodes": total,
                    "playback_visible": ops._playback_visible(),
                    "detail_title": ops._extract_detail_title(str(task.get("drama_name") or "")),
                    "playing_title": ops._current_playing_title(),
                }
            )
            screenshot_path = _debug_screenshot(ops, task_id, step)
            result = _debug_response(step, total > 0 or current > 0, f"当前第{current}集，总集数{total}", data, screenshot_path)
        elif step == "detect-ad":
            visible = ops._ad_continue_visible()
            data.update(_debug_page_state(ops, task))
            screenshot_path = _debug_screenshot(ops, task_id, step)
            result = _debug_response(
                step,
                True,
                "检测到广告继续观看提示" if visible else "未检测到广告继续观看提示",
                data,
                screenshot_path,
            )
        elif step == "skip-ad":
            before = _debug_page_state(ops, task)
            skipped = ops.skip_ad_if_present()
            time.sleep(2)
            after = _debug_page_state(ops, task)
            data.update({"before": before, "after": after, "skipped": skipped})
            screenshot_path = _debug_screenshot(ops, task_id, step)
            result = _debug_response(
                step,
                bool(skipped),
                "已上滑跳过广告" if skipped else "当前没有可跳过的广告提示",
                data,
                screenshot_path,
            )
        elif step in {"play-first", "play-target", "play-next"}:
            before = ops.get_current_episode()
            if step == "play-first":
                target_episode = 1
            elif step == "play-next":
                target_episode = max(1, int(before or task.get("current_episode") or 0) + 1)
            else:
                target_episode = max(1, int(task.get("start_episode") or 1))
            played = ops.play_episode(target_episode)
            time.sleep(2)
            after = ops.get_current_episode()
            data.update(
                {
                    "target_episode": target_episode,
                    "before_episode": before,
                    "after_episode": after,
                    "played": played,
                    "confirmed": after == target_episode,
                    "state": _debug_page_state(ops, task),
                }
            )
            screenshot_path = _debug_screenshot(ops, task_id, step)
            result = _debug_response(
                step,
                bool(played and after == target_episode),
                f"第{target_episode}集播放已确认" if after == target_episode else f"第{target_episode}集播放未确认",
                data,
                screenshot_path,
            )
        elif step == "observe-current":
            before = _debug_page_state(ops, task)
            time.sleep(8)
            after = _debug_page_state(ops, task)
            before_ep = int(before.get("current_episode") or 0)
            after_ep = int(after.get("current_episode") or 0)
            data.update({"before": before, "after": after})
            screenshot_path = _debug_screenshot(ops, task_id, step)
            if after.get("ad_visible"):
                message = "观察到广告提示，下一步请点“跳广告”"
            elif before_ep and after_ep and after_ep != before_ep:
                message = f"观察到集数变化: 第{before_ep}集 -> 第{after_ep}集"
            elif after_ep:
                message = f"仍在第{after_ep}集"
            else:
                message = "观察后仍无法识别当前集数"
            result = _debug_response(step, True, message, data, screenshot_path)
        else:
            target_episode = 1 if step == "play-first" else int(task.get("start_episode") or 1)
            before = ops.get_current_episode()
            played = ops.play_episode(target_episode)
            after = ops.get_current_episode()
            data.update(
                {
                    "target_episode": target_episode,
                    "before_episode": before,
                    "after_episode": after,
                    "played": played,
                    "confirmed": after == target_episode,
                    "playback_visible": ops._playback_visible(),
                }
            )
            screenshot_path = _debug_screenshot(ops, task_id, step)
            result = _debug_response(
                step,
                bool(played and after == target_episode),
                f"第{target_episode}集播放已确认" if after == target_episode else f"第{target_episode}集播放未确认",
                data,
                screenshot_path,
            )

        with _connection() as conn:
            detail = ""
            if step in {"find-drama", "search", "select", "open-search", "input-keyword", "submit-search", "open-drama", "set-speed"}:
                search = data.get("search") or {}
                submit = search.get("submit") or {}
                selected = data.get("selected") or {}
                opened = data.get("opened") or {}
                input_result = data.get("input") or {}
                detail_parts = [
                    f"keyword={data.get('keyword') or ''}",
                    f"opened={opened.get('message') or ''}",
                    f"input={data.get('input_text') or search.get('input_text') or input_result.get('input_text') or ''}",
                    f"submit={submit.get('message') or ''}",
                    f"action={submit.get('action') or ''}",
                    f"actions={submit.get('actions') or []}",
                    f"titles={(data.get('titles') or [])[:5]}",
                    f"selected={selected.get('message') or ''}",
                    f"drama={data.get('drama_title') or ''}",
                ]
                detail = " | " + " | ".join(detail_parts)
            _insert_log(
                conn,
                task_id,
                f"分步测试: {step} - {result['message']}{detail}",
                "info" if result["success"] else "warn",
            )
        return result
    except Exception as exc:
        with _connection() as conn:
            _insert_log(conn, task_id, f"分步测试: {step} 失败 - {exc}", "error")
        return _debug_response(step, False, str(exc))


@router.post("/tasks/{task_id}/prepare-run")
async def run_prepare_task(task_id: int):
    with _connection() as conn:
        task = _fetch_one_or_404(conn, task_id)
        status = _normalize_status(task.get("status"))
        if status in {"running", "paused", "waiting_login"}:
            raise HTTPException(status_code=400, detail="任务正在运行中，请先停止后再执行准备流程")
        _insert_log(conn, task_id, "一次性准备流程: 开始")

    try:
        data = _run_prepare_flow(task_id, dict(task))
        shot = ""
        try:
            device = connect(_hongguo_device_addr())
            shot = _debug_screenshot(HongguoOperations(device), task_id, "prepare")
        except Exception:
            shot = ""
        result = _debug_response("prepare", True, "一次性准备流程完成，已切到第1集", data, shot)
        with _connection() as conn:
            _insert_log(
                conn,
                task_id,
                f"一次性准备流程: 完成 | keyword={data.get('keyword') or ''} | drama={data.get('drama_title') or ''} | total={data.get('total_episodes') or 0} | speed={data.get('playback_speed') or ''}",
            )
        return result
    except Exception as exc:
        shot = ""
        try:
            device = connect(_hongguo_device_addr())
            shot = _debug_screenshot(HongguoOperations(device), task_id, "prepare_failed")
        except Exception:
            shot = ""
        data = exc.data if isinstance(exc, PrepareFlowError) else {}
        with _connection() as conn:
            _insert_log(conn, task_id, f"一次性准备流程: 失败 - {exc}", "error")
        return _debug_response("prepare", False, str(exc), data, shot)


@router.post("/tasks/{task_id}/stage-run")
async def run_stage_task(task_id: int, payload: StageRunRequest):
    if payload.end_episode < payload.start_episode:
        raise HTTPException(status_code=400, detail="end_episode must be >= start_episode")
    if payload.end_episode - payload.start_episode + 1 > 20:
        raise HTTPException(status_code=400, detail="阶段测试最多支持20集")
    with _connection() as conn:
        task = _fetch_one_or_404(conn, task_id)
        status = _normalize_status(task.get("status"))
        if status in {"running", "paused", "waiting_login"}:
            raise HTTPException(status_code=400, detail="任务正在运行中，请先停止后再启动阶段测试")
        _insert_log(conn, task_id, f"阶段测试已提交: 第{payload.start_episode}-{payload.end_episode}集")
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE hongguo_comment_tasks
                SET status='running',
                    current_episode=%s,
                    completed_at=NULL,
                    error_message=NULL,
                    updated_at=%s
                WHERE id=%s
                """,
                (payload.start_episode, datetime.now(), task_id),
            )
    thread = threading.Thread(
        target=_run_stage_task_v2,
        args=(task_id, payload.start_episode, payload.end_episode),
        name=f"hongguo-stage-{task_id}-{payload.start_episode}-{payload.end_episode}",
        daemon=True,
    )
    thread.start()
    return {
        "success": True,
        "message": f"阶段测试已启动: 第{payload.start_episode}-{payload.end_episode}集",
        "start_episode": payload.start_episode,
        "end_episode": payload.end_episode,
    }


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
    current_run_only: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    if status is not None and status not in RECORD_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid record status")
    where_clauses: List[str] = []
    params: List[Any] = [task_id]
    if status:
        where_clauses.append("status=%s")
        params.append(status)
    with _connection() as conn:
        task = _fetch_one_or_404(conn, task_id)
        if current_run_only and task.get("started_at"):
            where_clauses.append("created_at >= %s")
            params.append(task["started_at"])
        where = f"AND {' AND '.join(where_clauses)}" if where_clauses else ""
        params.extend([limit, offset])
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
    current_run_only: bool = Query(default=True),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    if level is not None and level not in LOG_LEVELS:
        raise HTTPException(status_code=400, detail="Invalid log level")
    where_clauses: List[str] = []
    params: List[Any] = [task_id]
    if level:
        where_clauses.append("level=%s")
        params.append(level)
    with _connection() as conn:
        task = _fetch_one_or_404(conn, task_id)
        if current_run_only and task.get("started_at"):
            where_clauses.append("created_at >= %s")
            params.append(task["started_at"])
        where = f"AND {' AND '.join(where_clauses)}" if where_clauses else ""
        params.extend([limit, offset])
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
        result = _check_hongguo_login(ops)
        return {"success": True, **result}
    except Exception as exc:
        return {
            "success": True,
            "logged_in": False,
            "status": "device_connect_failed",
            "device": {},
            "account": {"logged_in": False, "nickname": "", "hongguo_id": ""},
            "message": f"设备连接失败: {exc}",
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
