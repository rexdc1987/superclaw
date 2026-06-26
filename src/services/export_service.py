"""Export service"""
import os
import csv
from datetime import datetime
from models.database import get_session
from models.lead import Lead
from models.comment import Comment
from models.task import Task


class ExportService:
    def export_leads_csv(self, task_id=None, output_dir="data/exports") -> str:
        session = get_session()
        try:
            q = session.query(Lead)
            if task_id:
                q = q.filter(Lead.task_id == task_id)
            leads = q.all()
            os.makedirs(output_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(output_dir, f"leads_{ts}.csv")
            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["ID","Platform","UserID","Nickname","Score","Status","Assigned","Contacts","LastContact","Created"])
                for l in leads:
                    lc = l.last_contacted_at.strftime("%Y-%m-%d %H:%M") if l.last_contacted_at else ""
                    ct = l.created_at.strftime("%Y-%m-%d %H:%M") if l.created_at else ""
                    writer.writerow([l.id, l.platform, l.user_id, l.user_nickname, l.score, l.status, l.assigned_to or "", l.contact_count, lc, ct])
            return filepath
        finally:
            session.close()

    def export_comments_csv(self, task_id, output_dir="data/exports") -> str:
        session = get_session()
        try:
            comments = session.query(Comment).filter(Comment.task_id == task_id).all()
            os.makedirs(output_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(output_dir, f"comments_{task_id}_{ts}.csv")
            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["ID","Platform","Video","Author","Content","Time","Target","Keywords"])
                for c in comments:
                    ct = c.comment_time.strftime("%Y-%m-%d %H:%M") if c.comment_time else ""
                    writer.writerow([c.id, c.platform, c.video_title, c.author_nickname, c.content, ct, "Y" if c.is_target else "N", c.matched_keywords])
            return filepath
        finally:
            session.close()

    def export_task_report(self, task_id, output_dir="data/exports") -> str:
        session = get_session()
        try:
            task = session.get(Task, task_id)
            if not task:
                return ""
            lc = session.query(Lead).filter(Lead.task_id == task_id).count()
            cc = session.query(Comment).filter(Comment.task_id == task_id).count()
            tc = session.query(Comment).filter(Comment.task_id == task_id, Comment.is_target == True).count()
            os.makedirs(output_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(output_dir, f"report_{task_id}_{ts}.txt")
            NL = chr(10)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"Task: {task.name}{NL}")
                f.write(f"Platform: {task.platform}{NL}")
                f.write(f"Status: {task.status}{NL}")
                f.write(f"Comments: {cc} | Target: {tc} | Leads: {lc}{NL}")
            return filepath
        finally:
            session.close()