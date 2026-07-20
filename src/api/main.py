"""FastAPI application entry point."""

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from api.auth import router as auth_router
from api.audit import record_api_action
from api.deps import get_db
from api.security import (
    LOCAL_PRINCIPAL,
    auth_required,
    principal_from_authorization,
    reset_current_principal,
    set_current_principal,
    validate_security_config,
)
from api.users import router as users_router
from api.settings import router as settings_router
from rpa.dashboard.routes_hongguo import (
    hongguo_runtime_health,
    reconcile_runtime_state,
    router as hongguo_router,
)
from models.database import init_db
from models.task import Task


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_security_config()
    init_db()
    reconcile_runtime_state()
    yield


app = FastAPI(
    title="SuperClaw API",
    description="社交媒体评论引流运营系统",
    version="0.2.0",
    lifespan=lifespan,
)

allowed_origins = [
    value.strip()
    for value in os.environ.get(
        "SUPERCLAW_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://test.openclaw.com:3000",
    ).split(",")
    if value.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        public = path in {"/", "/health", "/docs", "/openapi.json"} or path.startswith("/api/v1/auth/")
        principal = None
        auth_error = None
        try:
            principal = principal_from_authorization(request.headers.get("Authorization", ""))
        except Exception as exc:
            auth_error = exc
        if principal is None:
            if auth_required() and path.startswith("/api/v1/") and not public:
                detail = getattr(auth_error, "detail", "Authentication required")
                return JSONResponse(status_code=401, content={"detail": detail})
            principal = LOCAL_PRINCIPAL
        token = set_current_principal(principal)
        request.state.principal = principal
        request_id = request.headers.get("X-Request-ID", "").strip()[:40] or str(uuid.uuid4())
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            record_api_action(
                principal,
                request.method,
                path,
                response.status_code,
                request.client.host if request.client else "",
                request_id,
            )
            return response
        finally:
            reset_current_principal(token)


app.add_middleware(AuthenticationMiddleware)

# The Hongguo router owns its full /api/v1/hongguo prefix.
app.include_router(settings_router)
app.include_router(hongguo_router)
app.include_router(auth_router)
app.include_router(users_router)

frontend_dist = Path(
    os.environ.get(
        "SUPERCLAW_FRONTEND_DIST",
        str(Path(__file__).resolve().parents[2] / "frontend" / "dist"),
    )
).resolve()
if (frontend_dist / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="frontend-assets")


@app.get("/")
def root():
    index = frontend_dist / "index.html"
    if index.is_file():
        return FileResponse(str(index))
    return {"message": "SuperClaw API", "version": "0.2.0"}


@app.get("/health")
def health():
    runtime = hongguo_runtime_health()
    return {
        "status": "ok" if runtime.get("database") else "degraded",
        "auth_required": auth_required(),
        **runtime,
    }


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


@app.get("/{frontend_path:path}", include_in_schema=False)
def frontend_spa(frontend_path: str):
    if frontend_path.startswith("api/"):
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    target = (frontend_dist / frontend_path).resolve()
    try:
        target.relative_to(frontend_dist)
    except ValueError:
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    if target.is_file():
        return FileResponse(str(target))
    index = frontend_dist / "index.html"
    if index.is_file():
        return FileResponse(str(index))
    return JSONResponse(status_code=404, content={"detail": "Frontend build not found"})
