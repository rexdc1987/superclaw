"""Client-side event logging API."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api/v1/client-events", tags=["client-events"])


class ClientEvent(BaseModel):
    event_type: str = Field(default="event", max_length=80)
    route: str = Field(default="", max_length=300)
    session_id: str = Field(default="", max_length=80)
    user: str = Field(default="", max_length=120)
    message: str = Field(default="", max_length=500)
    detail: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = Field(default=None, max_length=80)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _log_dir() -> Path:
    path = _project_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _client_log_path(day: Optional[str] = None) -> Path:
    suffix = day or datetime.now().strftime("%Y%m%d")
    return _log_dir() / f"client-events-{suffix}.jsonl"


def _trim_value(value: Any, max_len: int = 1000) -> Any:
    if isinstance(value, str):
        return value[:max_len]
    if isinstance(value, dict):
        return {str(k)[:80]: _trim_value(v, max_len) for k, v in value.items()}
    if isinstance(value, list):
        return [_trim_value(item, max_len) for item in value[:50]]
    return value


@router.post("")
async def create_client_event(event: ClientEvent, request: Request):
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "server_at": now,
        "client_at": event.created_at,
        "event_type": event.event_type,
        "route": event.route,
        "session_id": event.session_id,
        "user": event.user,
        "message": event.message,
        "detail": _trim_value(event.detail),
        "client": {
            "host": request.client.host if request.client else "",
            "user_agent": request.headers.get("user-agent", "")[:300],
            "referer": request.headers.get("referer", "")[:500],
        },
    }
    with _client_log_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    return {"success": True}


@router.get("/recent")
async def recent_client_events(limit: int = Query(default=200, ge=1, le=1000)):
    path = _client_log_path()
    if not path.exists():
        return {"items": []}
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    items: List[Dict[str, Any]] = []
    for line in lines:
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return {"items": items}
