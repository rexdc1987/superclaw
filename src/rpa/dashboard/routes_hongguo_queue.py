"""HTTP surface for the serial batch queue, the playlist and the daily timer.

Kept in its own module rather than appended to ``routes_hongguo`` so the
dispatch logic stays readable next to its endpoints, and so that module keeps
its byte-level history clean.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from contextlib import contextmanager

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from rpa.hongguo import dbresilience
from rpa.hongguo import queue as queue_service
from rpa.dashboard.routes_hongguo import _connection, _owner_user_id

router = APIRouter(prefix="/api/v1/hongguo/queue", tags=["hongguo-queue"])

playlist_router = APIRouter(prefix="/api/v1/hongguo/playlist", tags=["hongguo-queue"])


class QueueDevice(BaseModel):
    addr: str = Field(min_length=1, max_length=120)
    label: Optional[str] = Field(default=None, max_length=200)
    worker_id: Optional[str] = Field(default=None, max_length=120)


class PlaylistAdd(BaseModel):
    names: Optional[List[str]] = None
    text: Optional[str] = None


class PlaylistPatch(BaseModel):
    enabled: Optional[bool] = None
    drama_name: Optional[str] = Field(default=None, max_length=200)


class QueueCreate(BaseModel):
    """Enqueue dramas. Either an explicit list, a pasted block, or the playlist."""

    names: Optional[List[str]] = None
    text: Optional[str] = None
    use_playlist: bool = False
    shuffle: bool = False
    devices: List[QueueDevice] = Field(default_factory=list)
    template: Dict[str, Any] = Field(default_factory=dict)
    remember_settings: bool = True

    @field_validator("names")
    @classmethod
    def validate_names(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return value
        if len(value) > 200:
            raise ValueError("一次最多 200 部短剧")
        return value


class QueueCancel(BaseModel):
    queue_id: Optional[str] = Field(default=None, max_length=64)


class QueueConfigUpdate(BaseModel):
    daily_enabled: Optional[bool] = None
    daily_time: Optional[str] = Field(default=None, max_length=8)
    daily_mode: Optional[str] = Field(default=None, max_length=20)
    devices: Optional[List[QueueDevice]] = None
    template: Optional[Dict[str, Any]] = None

    @field_validator("daily_mode")
    @classmethod
    def validate_mode(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if value not in queue_service.DAILY_MODES:
            raise ValueError("daily_mode must be all_random or random_one")
        return value

    @field_validator("daily_time")
    @classmethod
    def validate_time(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        parsed = queue_service.parse_daily_time(value)
        return parsed.strftime("%H:%M")


@contextmanager
def _request_connection():
    """``_connection`` with a mid-query blip turned into a 503.

    ``routes_hongguo._connection`` deliberately lets an error raised *inside* the
    block through untouched so each handler can decide what it means (pinned by
    ``tests/test_dashboard_db_unavailable.py``).  On these screens the operator is
    only ever clicking a button, and when the remote MySQL link drops
    mid-statement the one useful answer is "try again shortly" - a 500 carrying a
    pymysql traceback just reads as "the feature is broken".
    """
    try:
        with _connection() as conn:
            yield conn
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - non-transient re-raised below
        if dbresilience.is_transient_error(exc):
            raise HTTPException(
                status_code=503,
                detail="数据库暂时不可用（{0}），请稍后重试".format(type(exc).__name__),
                headers={"Retry-After": str(int(dbresilience.DOWN_PROBE_INTERVAL_SECONDS))},
            ) from exc
        raise


def _serialize_config(row: Dict[str, Any]) -> Dict[str, Any]:
    last_fired = row.get("last_fired_date")
    return {
        "daily_enabled": bool(row.get("daily_enabled")),
        "daily_time": str(row.get("daily_time") or queue_service.DEFAULT_DAILY_TIME),
        "daily_mode": str(row.get("daily_mode") or "all_random"),
        "devices": queue_service._devices_from(row),
        "template": queue_service._template_from(row),
        "last_fired_date": last_fired.isoformat() if hasattr(last_fired, "isoformat") else last_fired,
    }


def _serialize_item(row: Dict[str, Any]) -> Dict[str, Any]:
    def stamp(value):
        return value.isoformat(sep=" ", timespec="seconds") if hasattr(value, "isoformat") else value

    return {
        "id": int(row.get("id") or 0),
        "seq": int(row.get("seq") or 0),
        "drama_name": row.get("drama_name"),
        "status": str(row.get("status") or "pending"),
        "source": str(row.get("source") or "manual"),
        "multi_run_id": row.get("multi_run_id"),
        "device_count": len(queue_service._devices_from(row)),
        "attempt": int(row.get("attempt") or 0),
        "error_message": row.get("error_message"),
        "created_at": stamp(row.get("created_at")),
        "started_at": stamp(row.get("started_at")),
        "finished_at": stamp(row.get("finished_at")),
    }


def _state() -> Dict[str, Any]:
    with _request_connection() as conn:
        config = queue_service._ensure_config(conn)
        active = queue_service.active_queue_snapshot(conn)
        return {
            "success": True,
            "config": _serialize_config(config),
            "playlist": [
                {
                    "id": int(row["id"]),
                    "drama_name": row.get("drama_name"),
                    "enabled": bool(row.get("enabled")),
                    "sort_order": int(row.get("sort_order") or 0),
                    "run_count": int(row.get("run_count") or 0),
                    "last_run_at": row.get("last_run_at").isoformat(sep=" ", timespec="seconds")
                    if hasattr(row.get("last_run_at"), "isoformat")
                    else row.get("last_run_at"),
                }
                for row in queue_service.list_playlist(conn)
            ],
            "active": {
                "queue_id": active["queue_id"],
                "summary": active["summary"],
                "items": [_serialize_item(row) for row in active["items"]],
            },
            "dispatcher": {
                "enabled": queue_service.dispatcher_enabled(),
                "seconds": 20,
            },
        }


@playlist_router.get("")
def get_playlist() -> Dict[str, Any]:
    with _request_connection() as conn:
        return {"success": True, "items": queue_service.list_playlist(conn)}


@playlist_router.post("")
def add_playlist(payload: PlaylistAdd) -> Dict[str, Any]:
    names = queue_service.normalize_names(list(payload.names or []) + [payload.text or ""])
    if not names:
        raise HTTPException(status_code=400, detail="请至少填写一个短剧名称")
    with _request_connection() as conn:
        items = queue_service.add_playlist_names(conn, names, _owner_user_id())
    return {"success": True, "added": names, "items": items}


@playlist_router.post("/import-history")
def import_playlist_history() -> Dict[str, Any]:
    """Seed the 剧单 from dramas that were already run, newest first."""
    with _request_connection() as conn:
        result = queue_service.import_history_names(conn, _owner_user_id())
    return {"success": True, **result}


@playlist_router.patch("/{entry_id}")
def patch_playlist(entry_id: int, payload: PlaylistPatch) -> Dict[str, Any]:
    with _request_connection() as conn:
        changed = queue_service.update_playlist_entry(
            conn, entry_id, enabled=payload.enabled, drama_name=payload.drama_name
        )
        if not changed:
            raise HTTPException(status_code=404, detail="剧单里没有这一条")
        return {"success": True, "items": queue_service.list_playlist(conn)}


@playlist_router.delete("/{entry_id}")
def delete_playlist(entry_id: int) -> Dict[str, Any]:
    with _request_connection() as conn:
        if not queue_service.delete_playlist_entry(conn, entry_id):
            raise HTTPException(status_code=404, detail="剧单里没有这一条")
        return {"success": True, "items": queue_service.list_playlist(conn)}


@router.get("")
def get_queue_state() -> Dict[str, Any]:
    return _state()


@router.post("")
def create_queue(payload: QueueCreate) -> Dict[str, Any]:
    with _request_connection() as conn:
        names = queue_service.normalize_names(list(payload.names or []) + [payload.text or ""])
        if payload.use_playlist:
            names = names + [name for name in queue_service.enabled_playlist_names(conn) if name not in names]
        if not names:
            raise HTTPException(status_code=400, detail="没有可执行的短剧：请填写剧名，或先在剧单里勾选")
        devices = [item.model_dump() for item in payload.devices]
        if not devices:
            raise HTTPException(status_code=400, detail="请至少选择一台已登录实例")
        if queue_service._unfinished_queue_id(conn):
            raise HTTPException(status_code=409, detail="已有一个队列没跑完，请等它结束或先取消")
        if payload.shuffle:
            import random

            random.shuffle(names)
        queue_id = queue_service.create_queue(
            conn,
            names,
            devices,
            payload.template,
            source="manual",
            owner_user_id=_owner_user_id(),
        )
        if payload.remember_settings:
            queue_service.save_config(
                conn,
                devices=devices,
                template=payload.template,
            )
        active = queue_service.active_queue_snapshot(conn)
        return {
            "success": True,
            "queue_id": queue_id,
            "enqueued": names,
            "active": {
                "queue_id": active["queue_id"],
                "summary": active["summary"],
                "items": [_serialize_item(row) for row in active["items"]],
            },
        }


@router.post("/cancel")
def cancel_queue(payload: QueueCancel) -> Dict[str, Any]:
    with _request_connection() as conn:
        cancelled = queue_service.cancel_pending(conn, payload.queue_id)
        active = queue_service.active_queue_snapshot(conn)
        return {
            "success": True,
            "cancelled": cancelled,
            "active": {
                "queue_id": active["queue_id"],
                "summary": active["summary"],
                "items": [_serialize_item(row) for row in active["items"]],
            },
        }


@router.post("/tick")
def tick_now() -> Dict[str, Any]:
    """Advance the queue by hand. Also how the daily timer can be tested."""
    result = queue_service.run_queue_tick()
    plan = {
        "daily_fired": result.get("daily_fired"),
        "finalized": result.get("finalized"),
        "start": {key: value for key, value in (result.get("start") or {}).items() if key != "devices"},
        "failures": result.get("failures"),
        "waiting": result.get("waiting"),
        "notes": result.get("notes"),
        "queue_id": result.get("queue_id"),
        "summary": result.get("summary"),
    }
    return {"success": True, "plan": plan, **_state()}


@router.get("/config")
def get_config() -> Dict[str, Any]:
    with _request_connection() as conn:
        return {"success": True, "config": _serialize_config(queue_service._ensure_config(conn))}


@router.put("/config")
def put_config(payload: QueueConfigUpdate) -> Dict[str, Any]:
    with _request_connection() as conn:
        config = queue_service.save_config(
            conn,
            daily_enabled=payload.daily_enabled,
            daily_time=payload.daily_time,
            daily_mode=payload.daily_mode,
            devices=[item.model_dump() for item in payload.devices] if payload.devices is not None else None,
            template=payload.template,
        )
    return {"success": True, "config": _serialize_config(config)}
