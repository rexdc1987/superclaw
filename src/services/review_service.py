"""Review service - manage high-risk action review queue"""
import json
from datetime import datetime
from typing import List, Dict
from models.database import get_session
from models.action import Action
from models.audit import AuditLog


HIGH_RISK_ACTIONS = {"dm", "at_user", "send_image"}
BATCH_THRESHOLD = 10  # Actions >= this count need review


class ReviewService:
    """Manage review queue for high-risk actions"""

    def needs_review(self, action_type: str, batch_size: int = 1) -> bool:
        """Check if action needs human review"""
        if action_type in HIGH_RISK_ACTIONS:
            return True
        if batch_size >= BATCH_THRESHOLD:
            return True
        return False

    def submit_for_review(self, action_ids: List[int]) -> int:
        """Move actions to review queue"""
        session = get_session()
        try:
            count = 0
            for aid in action_ids:
                action = session.get(Action, aid)
                if action and action.status == "pending":
                    action.status = "reviewing"
                    count += 1
            session.commit()
            return count
        finally:
            session.close()

    def approve(self, action_ids: List[int], reviewer: str = "admin") -> int:
        """Approve actions for execution"""
        session = get_session()
        try:
            count = 0
            for aid in action_ids:
                action = session.get(Action, aid)
                if action and action.status == "reviewing":
                    action.status = "approved"
                    # Log the review
                    log = AuditLog(
                        user=reviewer,
                        action="approve",
                        target_type="action",
                        target_id=aid,
                    )
                    session.add(log)
                    count += 1
            session.commit()
            return count
        finally:
            session.close()

    def reject(self, action_ids: List[int], reason: str = "", reviewer: str = "admin") -> int:
        """Reject actions"""
        session = get_session()
        try:
            count = 0
            for aid in action_ids:
                action = session.get(Action, aid)
                if action and action.status == "reviewing":
                    action.status = "rejected"
                    action.error_message = f"Rejected by {reviewer}: {reason}"
                    log = AuditLog(
                        user=reviewer,
                        action="reject",
                        target_type="action",
                        target_id=aid,
                        details_json=json.dumps({"reason": reason}, ensure_ascii=False),
                    )
                    session.add(log)
                    count += 1
            session.commit()
            return count
        finally:
            session.close()

    def get_pending_reviews(self, action_type: str = None) -> List[Action]:
        """Get actions waiting for review"""
        session = get_session()
        try:
            q = session.query(Action).filter(Action.status == "reviewing")
            if action_type:
                q = q.filter(Action.action_type == action_type)
            return q.order_by(Action.created_at.desc()).all()
        finally:
            session.close()

    def get_review_stats(self) -> Dict:
        session = get_session()
        try:
            reviewing = session.query(Action).filter(Action.status == "reviewing").count()
            approved = session.query(Action).filter(Action.status == "approved").count()
            rejected = session.query(Action).filter(Action.status == "rejected").count()
            return {"reviewing": reviewing, "approved": approved, "rejected": rejected}
        finally:
            session.close()
