"""API routes for build metadata and in-app updates.

Everything here is admin-only: version info leaks the install layout and the
update endpoints can trigger a service restart.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from api.security import require_admin
from api.system import service
from api.system.schemas import (
    BuildInfoResponse,
    UpdateActionResponse,
    UpdateCheckResponse,
    UpdateStatusResponse,
)


router = APIRouter(prefix="/api/v1/system", tags=["system"])


def _status_payload() -> dict:
    return service.download_state()


@router.get("/version", response_model=BuildInfoResponse, summary="当前构建信息",
            dependencies=[Depends(require_admin)])
def get_version():
    return service.build_info()


@router.get("/update/check", response_model=UpdateCheckResponse, summary="检查新版本",
            dependencies=[Depends(require_admin)])
def check_update():
    return service.fetch_latest_release()


@router.get("/update/status", response_model=UpdateStatusResponse, summary="更新任务进度",
            dependencies=[Depends(require_admin)])
def update_status():
    return _status_payload()


@router.post("/update/download", response_model=UpdateActionResponse, summary="下载并校验更新包",
             dependencies=[Depends(require_admin)])
def download_update(payload: dict = Body(default_factory=dict)):
    asset = payload.get("asset")
    version = str(payload.get("version") or "").strip()
    if not isinstance(asset, dict) or not asset.get("url") or not version:
        # No explicit asset: re-resolve from the release feed so the UI can call
        # this with an empty body.
        release = service.fetch_latest_release()
        asset = release.get("asset") or {}
        version = str(release.get("latest_version") or "")
    if not asset.get("url") or not version:
        return {"ok": False, "message": "没有可下载的更新包，请先检查更新。",
                "status": _status_payload()}

    state = service.start_download(asset, version)
    if state.get("phase") == "downloading" and state.get("version") == version:
        message = "已开始下载 v%s。" % version
    else:
        message = str(state.get("message") or "下载任务已在进行中。")
    return {"ok": True, "message": message, "status": state}


@router.post("/update/apply", response_model=UpdateActionResponse, summary="重启并应用更新",
             dependencies=[Depends(require_admin)])
def apply_update():
    result = service.request_apply()
    return {"ok": result["ok"], "message": result["message"], "status": _status_payload()}
