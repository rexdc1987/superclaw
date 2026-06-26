"""FastAPI application entry point."""

from typing import Optional

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from api.deps import get_db
from api.settings import router as settings_router
from rpa.dashboard.routes_hongguo import router as hongguo_router
from models.task import Task

app = FastAPI(
    title="SuperClaw API",
    description="社交媒体评论引流运营系统",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# The Hongguo router owns its full /api/v1/hongguo prefix.
app.include_router(settings_router)
app.include_router(hongguo_router)


@app.get("/")
def root():
    return {"message": "SuperClaw API", "version": "1.0.0"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/accounts/")
@app.get("/api/v1/accounts")
def list_accounts():
    return []


def _task_to_response(task: Task) -> dict:
    return {
        "id": task.id,
        "name": task.name,
        "platform": task.platform,
        "status": task.status or "pending",
        "priority": task.priority or 0,
        "account_group_id": task.account_group_id,
        "keyword_group_id": task.keyword_group_id,
        "playbook_id": task.playbook_id,
        "search_config_json": task.search_config_json or "{}",
        "filter_config_json": task.filter_config_json or "{}",
        "action_config_json": task.action_config_json or "{}",
        "rhythm_config_json": task.rhythm_config_json or "{}",
        "progress_total": task.progress_total or 0,
        "progress_done": task.progress_done or 0,
        "started_at": getattr(task, "started_at", None),
        "completed_at": getattr(task, "completed_at", None),
        "duration_seconds": None,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "progress_percent": getattr(task, "progress_percent", 0),
    }


@app.get("/api/v1/tasks/")
@app.get("/api/v1/tasks")
def list_tasks(
    status: Optional[str] = Query(default=None),
    platform: Optional[str] = Query(default=None),
    db=Depends(get_db),
):
    try:
        query = db.query(Task)
        if status:
            query = query.filter(Task.status == status)
        if platform:
            query = query.filter(Task.platform == platform)
        items = query.order_by(Task.id.desc()).all()
        return [_task_to_response(task) for task in items]
    finally:
        db.close()


@app.get("/api/v1/leads/")
@app.get("/api/v1/leads")
def list_leads():
    return []


@app.get("/api/v1/actions/")
@app.get("/api/v1/actions")
def list_actions():
    return []
