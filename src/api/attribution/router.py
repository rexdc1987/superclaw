"""机器归属 API（全 admin-only）。

为什么 admin-only：这些接口能看到**全部账号**的机器与产出，跨租户。
普通账号只能看自己的任务（`routes_hongguo::_owner_filter`），归属统计
如果放开就等于绕过那道隔离。
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from api.attribution import service
from api.attribution.schemas import BindRequest, BindResponse
from api.security import require_admin


router = APIRouter(prefix="/api/v1/attribution", tags=["attribution"])

_ADMIN = [Depends(require_admin)]


@router.get("/machines", summary="机器归属档案与产出统计", dependencies=_ADMIN)
def list_machines():
    """每台机器归属哪个账号，以及它跑了多少任务、发出多少评论。"""
    return service.overview()


@router.get("/gaps", summary="归属缺口清单", dependencies=_ADMIN)
def list_gaps():
    """无主任务、无机器任务各有多少。"""
    return service.audit_gaps()


@router.get("/inference", summary="从历史任务推断机器归属（只读建议）", dependencies=_ADMIN)
def list_inference():
    """给出建议归属，不改任何数据；要落地请调 machines/{worker_id}/bind。"""
    return service.inference()


@router.post(
    "/machines/{worker_id}/bind",
    response_model=BindResponse,
    summary="把机器归属给某个账号",
    dependencies=_ADMIN,
)
def bind_machine(
    worker_id: str,
    payload: BindRequest = Body(...),
    backfill: bool = Query(
        False,
        description="是否同时把这台机器上 owner_user_id=0 的历史任务认领给该账号",
    ),
):
    try:
        return service.bind_machine(
            worker_id, payload.username, force=payload.force, backfill=backfill
        )
    except service.AttributionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
