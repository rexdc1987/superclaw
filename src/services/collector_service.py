"""Collector service with enhanced filtering"""
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from models.database import get_session
from models.comment import Comment
from models.lead import Lead


class CollectorService:
    def collect_comments(self, task_id, video_data, comments_data):
        session = get_session()
        try:
            created = []
            for item in comments_data:
                c = Comment(
                    task_id=task_id, platform=video_data.get("platform", ""),
                    video_id=video_data.get("video_id", ""),
                    video_title=video_data.get("video_title", ""),
                    video_url=video_data.get("video_url", ""),
                    author_id=item.get("author_id", ""),
                    author_nickname=item.get("author_nickname", ""),
                    author_region=item.get("author_region", ""),
                    content=item.get("content", ""),
                    comment_time=item.get("comment_time"),
                    is_target=False,
                )
                session.add(c)
                created.append(c)
            session.commit()
            result = []
            for c in created:
                session.refresh(c)
                result.append({
                    "id": c.id, "task_id": c.task_id, "platform": c.platform,
                    "video_id": c.video_id, "video_title": c.video_title,
                    "video_url": c.video_url, "author_id": c.author_id,
                    "author_nickname": c.author_nickname,
                    "author_region": c.author_region,
                    "content": c.content, "comment_time": c.comment_time,
                    "is_target": c.is_target, "matched_keywords": c.matched_keywords,
                })
            return result
        finally:
            session.close()

    def filter_target_comments(self, task_id, keywords, exclude_words=None,
                               time_range_days=None, max_count=None,
                               exclude_regions=None, batch_size=500):
        session = get_session()
        try:
            q = session.query(Comment).filter(Comment.task_id == task_id)

            # Time filter
            if time_range_days:
                cutoff = datetime.utcnow() - timedelta(days=time_range_days)
                q = q.filter(Comment.comment_time >= cutoff)

            # Region filter
            if exclude_regions:
                for region in exclude_regions:
                    q = q.filter(~Comment.author_region.contains(region))

            # Batch iteration with keyword matching
            results = []
            last_id = 0
            while True:
                batch = q.filter(Comment.id > last_id).order_by(
                    Comment.id.asc()).limit(batch_size).all()
                if not batch:
                    break
                for c in batch:
                    last_id = c.id
                    content = c.content or ""

                    # Exclude words filter
                    if exclude_words and any(w in content for w in exclude_words):
                        continue

                    # Keyword match
                    matched = [kw for kw in keywords if kw in content]
                    if matched:
                        c.is_target = True
                        c.matched_keywords = json.dumps(matched, ensure_ascii=False)
                        results.append({
                            "id": c.id, "task_id": c.task_id, "platform": c.platform,
                            "video_id": c.video_id, "video_title": c.video_title,
                            "author_id": c.author_id, "author_nickname": c.author_nickname,
                            "author_region": c.author_region or "",
                            "content": c.content, "is_target": True,
                            "matched_keywords": c.matched_keywords,
                        })
                        # Max count limit
                        if max_count and len(results) >= max_count:
                            session.commit()
                            return results

            session.commit()
            return results
        finally:
            session.close()

    def deduplicate_comments(self, task_id):
        session = get_session()
        try:
            comments = session.query(Comment).filter(Comment.task_id == task_id).all()
            seen = {}
            removed = 0
            for c in comments:
                key = f"{c.platform}:{c.author_id}"
                if key in seen:
                    session.delete(c)
                    removed += 1
                else:
                    seen[key] = c.id
            session.commit()
            return removed
        finally:
            session.close()

    def create_leads_from_comments(self, task_id, target_comments):
        session = get_session()
        try:
            existing = set(r[0] for r in session.query(
                Lead.user_id).filter(Lead.task_id == task_id).all())
            leads = []
            for c in target_comments:
                uid = c["author_id"] if isinstance(c, dict) else c.author_id
                nick = c["author_nickname"] if isinstance(c, dict) else c.author_nickname
                cid = c["id"] if isinstance(c, dict) else c.id
                plat = c["platform"] if isinstance(c, dict) else c.platform
                region = (c.get("author_region", "") if isinstance(c, dict)
                          else getattr(c, "author_region", "") or "")
                if uid in existing:
                    continue
                lead = Lead(task_id=task_id, platform=plat, user_id=uid,
                            user_nickname=nick, user_region=region,
                            source_comment_id=cid, status="new")
                session.add(lead)
                leads.append(lead)
                existing.add(uid)
            session.commit()
            for l in leads:
                session.refresh(l)
            return leads
        finally:
            session.close()

    def get_comments(self, task_id, is_target=None, page=1, page_size=50):
        session = get_session()
        try:
            q = session.query(Comment).filter(Comment.task_id == task_id)
            if is_target is not None:
                q = q.filter(Comment.is_target == is_target)
            total = q.count()
            items = q.offset((page - 1) * page_size).limit(page_size).all()
            return {"total": total, "page": page, "page_size": page_size, "items": items}
        finally:
            session.close()
