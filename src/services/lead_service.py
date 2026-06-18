"""线索管理服务"""
import json
from datetime import datetime
from typing import List, Dict
from models.database import get_session
from models.lead import Lead
from models.comment import Comment
from core.constants import SCORE_WEIGHTS, LeadStatus


class LeadService:
    def create_lead(self, data: dict) -> Lead:
        session = get_session()
        try:
            lead = Lead(**data)
            session.add(lead)
            session.commit()
            session.refresh(lead)
            return lead
        finally:
            session.close()

    def update_lead(self, lead_id, data):
        session = get_session()
        try:
            lead = session.query(Lead).get(lead_id)
            if not lead: return None
            for key, value in data.items():
                if hasattr(lead, key): setattr(lead, key, value)
            session.commit()
            session.refresh(lead)
            return lead
        finally:
            session.close()

    def get_leads(self, task_id=None, status=None, min_score=None, platform=None, page=1, page_size=50) -> Dict:
        session = get_session()
        try:
            q = session.query(Lead)
            if task_id: q = q.filter(Lead.task_id == task_id)
            if status: q = q.filter(Lead.status == status)
            if min_score is not None: q = q.filter(Lead.score >= min_score)
            if platform: q = q.filter(Lead.platform == platform)
            total = q.count()
            items = q.order_by(Lead.score.desc()).offset((page-1)*page_size).limit(page_size).all()
            return {"total": total, "page": page, "page_size": page_size, "items": items}
        finally:
            session.close()

    def score_leads(self, task_id, strong_keywords=None, weak_keywords=None, exclude_keywords=None) -> int:
        session = get_session()
        try:
            leads = session.query(Lead).filter(Lead.task_id == task_id).all() if task_id else session.query(Lead).all()
            updated = 0
            for lead in leads:
                score = 50.0
                details = {"base": 50}
                if lead.source_comment_id:
                    comment = session.query(Comment).get(lead.source_comment_id)
                    if comment and comment.content:
                        content = comment.content
                        if strong_keywords and any(w in content for w in strong_keywords):
                            score += SCORE_WEIGHTS["strong_intent_keyword"]
                            details["strong_intent"] = SCORE_WEIGHTS["strong_intent_keyword"]
                        if exclude_keywords and any(w in content for w in exclude_keywords):
                            score = 0
                            details["excluded"] = True
                        if comment.comment_time:
                            days = (datetime.utcnow() - comment.comment_time).days
                            if days <= 7:
                                score += SCORE_WEIGHTS["recent_7_days"]
                                details["recent_7d"] = SCORE_WEIGHTS["recent_7_days"]
                if lead.status == LeadStatus.CONTACTED.value and lead.contact_count > 0:
                    score += SCORE_WEIGHTS["already_contacted"]
                    details["already_contacted"] = SCORE_WEIGHTS["already_contacted"]
                lead.score = max(0, score)
                lead.score_details_json = json.dumps(details, ensure_ascii=False)
                updated += 1
            session.commit()
            return updated
        finally:
            session.close()

    def assign_lead(self, lead_id, assignee) -> bool:
        session = get_session()
        try:
            lead = session.query(Lead).get(lead_id)
            if not lead: return False
            lead.assigned_to = assignee
            session.commit()
            return True
        finally:
            session.close()

    def update_status(self, lead_id, status) -> bool:
        session = get_session()
        try:
            lead = session.query(Lead).get(lead_id)
            if not lead: return False
            lead.status = status
            if status == LeadStatus.CONTACTED.value:
                lead.last_contacted_at = datetime.utcnow()
                lead.contact_count += 1
            session.commit()
            return True
        finally:
            session.close()

    def get_lead_statistics(self, task_id=None) -> Dict:
        session = get_session()
        try:
            q = session.query(Lead)
            if task_id: q = q.filter(Lead.task_id == task_id)
            leads = q.all()
            by_status = {}
            total_score = 0
            for l in leads:
                by_status[l.status] = by_status.get(l.status, 0) + 1
                total_score += l.score
            return {"total": len(leads), "by_status": by_status, "avg_score": round(total_score/len(leads),1) if leads else 0}
        finally:
            session.close()
