"""Business logic for Hongguo comment API"""
import json
from datetime import datetime
from sqlalchemy.orm import Session
from models.hongguo_task import HongguoTask
from models.hongguo_record import HongguoRecord
from models.hongguo_log import HongguoLog
from models.hongguo_template import HongguoTemplate
from api.hongguo.schemas import TaskCreate, TaskUpdate


# ====== 任务 ======

def create_task(db: Session, data: TaskCreate) -> HongguoTask:
    """创建红果评论任务"""
    task = HongguoTask(
        drama_name=data.drama_name,
        comment_mode=data.comment_mode,
        start_episode=data.start_episode,
        episode_interval=data.episode_interval,
        comment_interval_sec=data.comment_interval_sec,
        random_comment_count=data.random_comment_count,
        random_min_interval=data.random_min_interval,
        random_max_interval=data.random_max_interval,
        content_source=data.content_source,
        templates_json=json.dumps(data.templates, ensure_ascii=False),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_tasks(db: Session, skip: int = 0, limit: int = 20) -> tuple:
    """获取任务列表"""
    total = db.query(HongguoTask).count()
    items = db.query(HongguoTask).order_by(HongguoTask.id.desc()).offset(skip).limit(limit).all()
    return total, items


def get_task(db: Session, task_id: int) -> HongguoTask:
    """获取任务详情"""
    return db.query(HongguoTask).filter(HongguoTask.id == task_id).first()


def update_task(db: Session, task_id: int, data: TaskUpdate) -> HongguoTask:
    """更新任务配置"""
    task = get_task(db, task_id)
    if not task:
        return None
    update_data = data.dict(exclude_unset=True)
    if "templates" in update_data:
        update_data["templates_json"] = json.dumps(update_data.pop("templates"), ensure_ascii=False)
    for key, value in update_data.items():
        setattr(task, key, value)
    db.commit()
    db.refresh(task)
    return task


def delete_task(db: Session, task_id: int) -> bool:
    """删除任务"""
    task = get_task(db, task_id)
    if not task:
        return False
    db.delete(task)
    db.commit()
    return True


def start_task(db: Session, task_id: int) -> HongguoTask:
    """启动任务"""
    task = get_task(db, task_id)
    if not task:
        return None
    task.status = "running"
    task.started_at = datetime.now()
    task.completed_at = None
    task.error_message = None
    task.current_episode = 0
    task.total_episodes = 0
    task.comments_sent = 0
    task.comments_verified = 0
    task.updated_at = datetime.now()
    db.commit()
    db.refresh(task)
    return task


def pause_task(db: Session, task_id: int) -> HongguoTask:
    """暂停任务"""
    task = get_task(db, task_id)
    if not task:
        return None
    task.status = "paused"
    task.updated_at = datetime.now()
    db.commit()
    db.refresh(task)
    return task


def stop_task(db: Session, task_id: int) -> HongguoTask:
    """停止任务"""
    task = get_task(db, task_id)
    if not task:
        return None
    task.status = "stopped"
    task.completed_at = datetime.now()
    task.updated_at = datetime.now()
    db.commit()
    db.refresh(task)
    return task


# ====== 评论记录 ======

def get_records(db: Session, task_id: int, skip: int = 0, limit: int = 50) -> tuple:
    """获取评论记录"""
    total = db.query(HongguoRecord).filter(HongguoRecord.task_id == task_id).count()
    items = db.query(HongguoRecord).filter(HongguoRecord.task_id == task_id)        .order_by(HongguoRecord.id.desc()).offset(skip).limit(limit).all()
    return total, items


def create_record(db: Session, task_id: int, episode: int, comment: str, generated_by: str = "ai") -> HongguoRecord:
    """创建评论记录"""
    record = HongguoRecord(
        task_id=task_id,
        episode_number=episode,
        comment_text=comment,
        generated_by=generated_by,
        status="sending"
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def update_record_status(db: Session, record_id: int, status: str, screenshot: str = None) -> HongguoRecord:
    """更新评论状态"""
    record = db.query(HongguoRecord).filter(HongguoRecord.id == record_id).first()
    if not record:
        return None
    record.status = status
    if status == "sent":
        record.sent_at = datetime.now()
        if screenshot:
            record.screenshot_sent = screenshot
    elif status == "verified":
        record.verified_at = datetime.now()
        if screenshot:
            record.screenshot_verified = screenshot
    record.created_at = record.created_at or datetime.now()
    db.commit()
    db.refresh(record)
    return record


# ====== 执行日志 ======

def get_logs(db: Session, task_id: int, skip: int = 0, limit: int = 100) -> tuple:
    """获取执行日志"""
    total = db.query(HongguoLog).filter(HongguoLog.task_id == task_id).count()
    items = db.query(HongguoLog).filter(HongguoLog.task_id == task_id)        .order_by(HongguoLog.id.desc()).offset(skip).limit(limit).all()
    return total, items


def add_log(db: Session, task_id: int, level: str, message: str, screenshot: str = None) -> HongguoLog:
    """添加执行日志"""
    log = HongguoLog(
        task_id=task_id,
        level=level,
        message=message,
        screenshot_path=screenshot,
        created_at=datetime.now(),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


# ====== 模板 ======

def get_templates(db: Session, skip: int = 0, limit: int = 50) -> tuple:
    """获取模板列表"""
    total = db.query(HongguoTemplate).count()
    items = db.query(HongguoTemplate).order_by(HongguoTemplate.id.desc()).offset(skip).limit(limit).all()
    return total, items


def create_template(db: Session, name: str, content: str, category: str = None) -> HongguoTemplate:
    """创建模板"""
    template = HongguoTemplate(name=name, content=content, category=category)
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def delete_template(db: Session, template_id: int) -> bool:
    """删除模板"""
    template = db.query(HongguoTemplate).filter(HongguoTemplate.id == template_id).first()
    if not template:
        return False
    db.delete(template)
    db.commit()
    return True
