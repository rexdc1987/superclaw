"""关键词管理服务"""
import json
from typing import List
from models.database import get_session
from models.keyword import KeywordGroup


class KeywordService:
    def add_group(self, name, keywords, rotate_after_n=5):
        session = get_session()
        try:
            g = KeywordGroup(name=name, keywords=json.dumps(keywords, ensure_ascii=False), rotate_after_n_videos=rotate_after_n)
            session.add(g)
            session.commit()
            session.refresh(g)
            return g
        finally:
            session.close()

    def update_group(self, group_id, data):
        session = get_session()
        try:
            g = session.query(KeywordGroup).get(group_id)
            if not g: return None
            if "keywords" in data and isinstance(data["keywords"], list):
                data["keywords"] = json.dumps(data["keywords"], ensure_ascii=False)
            for k, v in data.items():
                if hasattr(g, k): setattr(g, k, v)
            session.commit()
            session.refresh(g)
            return g
        finally:
            session.close()

    def delete_group(self, group_id) -> bool:
        session = get_session()
        try:
            g = session.query(KeywordGroup).get(group_id)
            if not g: return False
            session.delete(g)
            session.commit()
            return True
        finally:
            session.close()

    def get_groups(self) -> list:
        session = get_session()
        try:
            return session.query(KeywordGroup).all()
        finally:
            session.close()

    def get_group_keywords(self, group_id) -> list:
        session = get_session()
        try:
            g = session.query(KeywordGroup).get(group_id)
            return json.loads(g.keywords) if g else []
        finally:
            session.close()

    def get_next_keyword(self, group_id, current_index):
        keywords = self.get_group_keywords(group_id)
        if not keywords: return ("", 0)
        idx = current_index % len(keywords)
        return (keywords[idx], idx + 1)

    def import_keywords(self, group_id, new_keywords) -> int:
        session = get_session()
        try:
            g = session.query(KeywordGroup).get(group_id)
            if not g: return 0
            existing = json.loads(g.keywords)
            merged = list(set(existing + new_keywords))
            g.keywords = json.dumps(merged, ensure_ascii=False)
            session.commit()
            return len(merged) - len(existing)
        finally:
            session.close()
