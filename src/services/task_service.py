"""任务管理服务"""
import json
from datetime import datetime, timezone
from typing import List, Optional, Dict
from models.database import get_session
from models.task import Task
from core.constants import TaskStatus
from core.exceptions import StateTransitionError, TaskError


class TaskService:
    def create_task(self, data: dict) -> Task:
        session = get_session()
        try:
            for field in ["search_config", "filter_config", "action_config"]:
                key = field + "_json"
                if field in data and isinstance(data[field], dict):
                    data[key] = json.dumps(data[field], ensure_ascii=False)
                    del data[field]
            task = Task(**data)
            task.status = TaskStatus.DRAFT.value
            session.add(task)
            session.commit()
            session.refresh(task)
            return task
        finally:
            session.close()

    def update_task(self, task_id: int, data: dict):
        session = get_session()
        try:
            task = session.get(Task, task_id)
            if not task: return None
            for key, value in data.items():
                if hasattr(task, key): setattr(task, key, value)
            session.commit()
            session.refresh(task)
            return task
        finally:
            session.close()

    def delete_task(self, task_id: int) -> bool:
        session = get_session()
        try:
            task = session.get(Task, task_id)
            if not task: return False
            if task.status == TaskStatus.RUNNING.value:
                raise TaskError("不能删除运行中的任务")
            session.delete(task)
            session.commit()
            return True
        finally:
            session.close()

    def _transition(self, task, target: TaskStatus):
        current = TaskStatus(task.status)
        if not current.can_transition_to(target):
            raise StateTransitionError(task.status, target.value)
        task.status = target.value

    def start_task(self, task_id: int) -> Task:
        session = get_session()
        try:
            task = session.get(Task, task_id)
            if not task: raise TaskError("任务不存在")
            self._transition(task, TaskStatus.RUNNING)
            task.started_at = datetime.utcnow()
            session.commit()
            session.refresh(task)
            return task
        finally:
            session.close()

    def pause_task(self, task_id: int) -> Task:
        session = get_session()
        try:
            task = session.get(Task, task_id)
            if not task: raise TaskError("任务不存在")
            self._transition(task, TaskStatus.PAUSED)
            session.commit()
            session.refresh(task)
            return task
        finally:
            session.close()

    def resume_task(self, task_id: int) -> Task:
        session = get_session()
        try:
            task = session.get(Task, task_id)
            if not task: raise TaskError("任务不存在")
            self._transition(task, TaskStatus.RUNNING)
            session.commit()
            session.refresh(task)
            return task
        finally:
            session.close()

    def cancel_task(self, task_id: int) -> Task:
        session = get_session()
        try:
            task = session.get(Task, task_id)
            if not task: raise TaskError("任务不存在")
            self._transition(task, TaskStatus.CANCELLED)
            session.commit()
            session.refresh(task)
            return task
        finally:
            session.close()

    def complete_task(self, task_id: int) -> Task:
        session = get_session()
        try:
            task = session.get(Task, task_id)
            if not task: raise TaskError("任务不存在")
            self._transition(task, TaskStatus.COMPLETED)
            task.completed_at = datetime.utcnow()
            session.commit()
            session.refresh(task)
            return task
        finally:
            session.close()

    def fail_task(self, task_id: int, error_message: str = "") -> Task:
        session = get_session()
        try:
            task = session.get(Task, task_id)
            if not task: raise TaskError("任务不存在")
            self._transition(task, TaskStatus.FAILED)
            if error_message:
                task.error_message = error_message
            session.commit()
            session.refresh(task)
            return task
        finally:
            session.close()

    def update_progress(self, task_id, done=None, total=None):
        session = get_session()
        try:
            task = session.get(Task, task_id)
            if task:
                if done is not None: task.progress_done = done
                if total is not None: task.progress_total = total
                session.commit()
        finally:
            session.close()

    def get_tasks(self, status=None, platform=None) -> List:
        session = get_session()
        try:
            q = session.query(Task)
            if status: q = q.filter(Task.status == status)
            if platform: q = q.filter(Task.platform == platform)
            return q.order_by(Task.created_at.desc()).all()
        finally:
            session.close()

    def get_task_detail(self, task_id):
        session = get_session()
        try:
            return session.get(Task, task_id)
        finally:
            session.close()

    def get_statistics(self) -> Dict:
        session = get_session()
        try:
            tasks = session.query(Task).all()
            by_status = {}
            for t in tasks:
                by_status[t.status] = by_status.get(t.status, 0) + 1
            return {"total": len(tasks), "by_status": by_status}
        finally:
            session.close()
