"""Action service"""
from datetime import datetime
from typing import List, Dict
from models.database import get_session
from models.action import Action
from models.audit import ExecutionLog


class ActionService:
    def create_action(self, task_id, action_type, lead_id=None, account_id=None,
                      content="", template_id=None, mention_user="", image_path="") -> Action:
        session = get_session()
        try:
            action = Action(
                task_id=task_id, lead_id=lead_id, action_type=action_type,
                account_id=account_id, content=content, template_id=template_id,
                mention_user=mention_user, image_path=image_path, status="pending")
            session.add(action)
            session.commit()
            session.refresh(action)
            return action
        finally:
            session.close()

    def execute_action(self, action_id, success=True, error_message=""):
        session = get_session()
        try:
            action = session.query(Action).get(action_id)
            if not action:
                return None
            action.status = "completed" if success else "failed"
            action.error_message = error_message
            action.executed_at = datetime.utcnow()
            log = ExecutionLog(
                task_id=action.task_id, action_id=action.id,
                level="info" if success else "error",
                message=f"动作 {action.action_type} {'成功' if success else '失败'}")
            session.add(log)
            session.commit()
            session.refresh(action)
            return action
        finally:
            session.close()

    def batch_create(self, task_id, lead_ids, action_type=None, action_types=None,
                     account_id=None, contents=None, template_id=None, mention_user="") -> list:
        """Create actions per lead. Accepts action_type (str) or action_types (list)."""
        if action_types:
            if isinstance(action_types, str):
                action_types = [action_types]
        elif action_type:
            action_types = [action_type]
        else:
            action_types = ["comment"]

        session = get_session()
        try:
            actions = []
            for lid in lead_ids:
                for atype in action_types:
                    content = ""
                    if contents and isinstance(contents, list):
                        import random
                        content = random.choice(contents)
                    elif contents:
                        content = contents
                    a = Action(
                        task_id=task_id, lead_id=lid, action_type=atype,
                        account_id=account_id, content=content,
                        template_id=template_id, mention_user=mention_user,
                        status="pending")
                    session.add(a)
                    actions.append(a)
            session.commit()
            for a in actions:
                session.refresh(a)
            return actions
        finally:
            session.close()

    def get_actions(self, task_id=None, status=None, action_type=None) -> list:
        session = get_session()
        try:
            q = session.query(Action)
            if task_id:
                q = q.filter(Action.task_id == task_id)
            if status:
                q = q.filter(Action.status == status)
            if action_type:
                q = q.filter(Action.action_type == action_type)
            return q.order_by(Action.created_at.desc()).all()
        finally:
            session.close()

    def get_action_stats(self, task_id) -> Dict:
        session = get_session()
        try:
            actions = session.query(Action).filter(Action.task_id == task_id).all()
            by_type, by_status = {}, {}
            for a in actions:
                by_type[a.action_type] = by_type.get(a.action_type, 0) + 1
                by_status[a.status] = by_status.get(a.status, 0) + 1
            return {"total": len(actions), "by_type": by_type, "by_status": by_status}
        finally:
            session.close()
