"""API routes for Hongguo comment"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from api.deps import get_db
from api.hongguo.schemas import (
    TaskCreate, TaskUpdate, TaskResponse, TaskListResponse,
    RecordResponse, RecordListResponse,
    LogResponse, LogListResponse,
    TemplateCreate, TemplateResponse, TemplateListResponse
)
from api.hongguo import service

router = APIRouter()


# ====== 任务 ======

@router.post("/tasks", response_model=TaskResponse, summary="创建任务")
def create_task(data: TaskCreate, db: Session = Depends(get_db)):
    task = service.create_task(db, data)
    return _task_to_response(task)


@router.get("/tasks", response_model=TaskListResponse, summary="任务列表")
def list_tasks(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    total, items = service.get_tasks(db, skip, limit)
    return TaskListResponse(total=total, items=[_task_to_response(t) for t in items])


@router.get("/tasks/{task_id}", response_model=TaskResponse, summary="任务详情")
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = service.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _task_to_response(task)


@router.put("/tasks/{task_id}", response_model=TaskResponse, summary="更新任务")
def update_task(task_id: int, data: TaskUpdate, db: Session = Depends(get_db)):
    task = service.update_task(db, task_id, data)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _task_to_response(task)


@router.delete("/tasks/{task_id}", summary="删除任务")
def delete_task(task_id: int, db: Session = Depends(get_db)):
    success = service.delete_task(db, task_id)
    if not success:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"message": "删除成功"}


@router.post("/tasks/{task_id}/start", response_model=TaskResponse, summary="开启任务")
def start_task(task_id: int, db: Session = Depends(get_db)):
    task = service.start_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _task_to_response(task)


@router.post("/tasks/{task_id}/pause", response_model=TaskResponse, summary="暂停任务")
def pause_task(task_id: int, db: Session = Depends(get_db)):
    task = service.pause_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _task_to_response(task)


@router.post("/tasks/{task_id}/stop", response_model=TaskResponse, summary="停止任务")
def stop_task(task_id: int, db: Session = Depends(get_db)):
    task = service.stop_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _task_to_response(task)


# ====== 评论记录 ======

@router.get("/tasks/{task_id}/records", response_model=RecordListResponse, summary="评论记录")
def list_records(
    task_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    total, items = service.get_records(db, task_id, skip, limit)
    return RecordListResponse(total=total, items=[_record_to_response(r) for r in items])


# ====== 执行日志 ======

@router.get("/tasks/{task_id}/logs", response_model=LogListResponse, summary="执行日志")
def list_logs(
    task_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db)
):
    total, items = service.get_logs(db, task_id, skip, limit)
    return LogListResponse(total=total, items=[_log_to_response(l) for l in items])


# ====== 模板 ======

@router.get("/templates", response_model=TemplateListResponse, summary="模板列表")
def list_templates(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    total, items = service.get_templates(db, skip, limit)
    return TemplateListResponse(total=total, items=[_template_to_response(t) for t in items])


@router.post("/templates", response_model=TemplateResponse, summary="创建模板")
def create_template(data: TemplateCreate, db: Session = Depends(get_db)):
    template = service.create_template(db, data.name, data.content, data.category)
    return _template_to_response(template)


@router.delete("/templates/{template_id}", summary="删除模板")
def delete_template(template_id: int, db: Session = Depends(get_db)):
    success = service.delete_template(db, template_id)
    if not success:
        raise HTTPException(status_code=404, detail="模板不存在")
    return {"message": "删除成功"}


# ====== 工具函数 ======

def _task_to_response(task) -> TaskResponse:
    """转换任务模型为响应"""
    return TaskResponse(
        id=task.id,
        drama_name=task.drama_name,
        comment_mode=task.comment_mode,
        start_episode=task.start_episode or 1,
        episode_interval=task.episode_interval or 1,
        comment_interval_sec=task.comment_interval_sec or 30,
        random_comment_count=task.random_comment_count or 10,
        random_min_interval=task.random_min_interval or 20,
        random_max_interval=task.random_max_interval or 60,
        content_source=task.content_source or "ai",
        templates_json=task.templates_json or "[]",
        status=task.status or "pending",
        current_episode=task.current_episode or 0,
        total_episodes=task.total_episodes or 0,
        comments_sent=task.comments_sent or 0,
        comments_verified=task.comments_verified or 0,
        error_message=task.error_message,
        started_at=task.started_at,
        completed_at=task.completed_at,
        duration_seconds=task.duration_seconds,
        created_at=task.created_at,
        updated_at=task.updated_at,
        progress_percent=task.progress_percent
    )


def _record_to_response(record) -> RecordResponse:
    """转换评论记录为响应"""
    return RecordResponse(
        id=record.id,
        task_id=record.task_id,
        episode_number=record.episode_number,
        episode_title=record.episode_title,
        comment_text=record.comment_text,
        generated_by=record.generated_by,
        status=record.status,
        sent_at=record.sent_at,
        verified_at=record.verified_at,
        screenshot_input=record.screenshot_input,
        screenshot_sent=record.screenshot_sent,
        screenshot_verified=record.screenshot_verified,
        screenshot_input_url=_screenshot_url(record.screenshot_input),
        screenshot_sent_url=_screenshot_url(record.screenshot_sent),
        screenshot_verified_url=_screenshot_url(record.screenshot_verified),
        error_message=record.error_message,
        created_at=record.created_at
    )


def _screenshot_url(path):
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"/api/v1/hongguo/tasks/screenshot/proxy?path={path}"


def _log_to_response(log) -> LogResponse:
    """转换日志为响应"""
    return LogResponse(
        id=log.id,
        task_id=log.task_id,
        level=log.level,
        message=log.message,
        screenshot_path=log.screenshot_path,
        created_at=log.created_at
    )


def _template_to_response(template) -> TemplateResponse:
    """转换模板为响应"""
    return TemplateResponse(
        id=template.id,
        name=template.name,
        content=template.content,
        category=template.category,
        is_default=template.is_default,
        use_count=template.use_count,
        created_at=template.created_at
    )
