"""Playbook service — 打法模板管理"""
import json
from typing import List, Dict
from models.database import get_session
from models.playbook import Playbook
from models.task import Task
from core.constants import TaskStatus


# ── 5 套预设打法 ──
PRESET_PLAYBOOKS = [
    {
        "name": "自动曝光",
        "playbook_type": "auto_exposure",
        "description": "关键词搜索同行视频，自动评论+私信触达潜在客户",
        "icon": "🔍",
        "scenario": "新品推广、品牌曝光",
        "risk_level": "medium",
        "search_config": {"video_count": 20, "comment_count": 50},
        "filter_config": {"keywords": [], "max_comments_per_video": 30},
        "action_config": {"action_types": ["comment", "dm"], "mention_user": ""},
    },
    {
        "name": "定向曝光",
        "playbook_type": "targeted_exposure",
        "description": "从同行账号粉丝列表定向触达精准用户",
        "icon": "🎯",
        "scenario": "竞品截流、精准获客",
        "risk_level": "high",
        "search_config": {"video_count": 10, "comment_count": 30},
        "filter_config": {"keywords": [], "max_comments_per_video": 20},
        "action_config": {"action_types": ["comment", "dm"], "mention_user": ""},
    },
    {
        "name": "链接曝光",
        "playbook_type": "link_exposure",
        "description": "针对付费投流视频URL，评论+私信引导转化",
        "icon": "🔗",
        "scenario": "付费投流配合、落地页引流",
        "risk_level": "high",
        "search_config": {"video_count": 5, "comment_count": 100},
        "filter_config": {"keywords": [], "max_comments_per_video": 50},
        "action_config": {"action_types": ["comment", "dm"], "mention_user": ""},
    },
    {
        "name": "搜索账号",
        "playbook_type": "account_search",
        "description": "按行业关键词搜索目标账号，直接私信建联",
        "icon": "👤",
        "scenario": "KOL建联、行业合作",
        "risk_level": "medium",
        "search_config": {"video_count": 0, "comment_count": 0},
        "filter_config": {"keywords": [], "max_comments_per_video": 0},
        "action_config": {"action_types": ["dm"], "mention_user": ""},
    },
    {
        "name": "留痕曝光",
        "playbook_type": "stealth_exposure",
        "description": "关键词搜视频，仅点赞+关注+收藏，低调建立存在感",
        "icon": "👻",
        "scenario": "养号初期、低风险曝光",
        "risk_level": "low",
        "search_config": {"video_count": 30, "comment_count": 0},
        "filter_config": {"keywords": [], "max_comments_per_video": 0},
        "action_config": {"action_types": ["like", "follow", "favorite"], "mention_user": ""},
    },
]


class PlaybookService:
    def create_playbook(self, data: dict) -> Playbook:
        session = get_session()
        try:
            for field in ["search_config", "filter_config", "action_config"]:
                key = field + "_json"
                if field in data and isinstance(data[field], dict):
                    data[key] = json.dumps(data[field], ensure_ascii=False)
                    del data[field]
            pb = Playbook(**data)
            session.add(pb)
            session.commit()
            session.refresh(pb)
            return pb
        finally:
            session.close()

    def get_playbooks(self, active_only=True) -> List[Playbook]:
        session = get_session()
        try:
            q = session.query(Playbook)
            if active_only:
                q = q.filter(Playbook.is_active == True)
            return q.order_by(Playbook.created_at.desc()).all()
        finally:
            session.close()

    def delete_playbook(self, playbook_id: int) -> bool:
        session = get_session()
        try:
            pb = session.query(Playbook).get(playbook_id)
            if not pb:
                return False
            session.delete(pb)
            session.commit()
            return True
        finally:
            session.close()

    def get_preset_playbooks(self) -> List[dict]:
        return PRESET_PLAYBOOKS

    def apply_playbook(self, task_id: int, playbook_id: int) -> Task:
        """将打法配置应用到已有任务"""
        session = get_session()
        try:
            pb = session.query(Playbook).get(playbook_id)
            if not pb:
                raise ValueError(f"Playbook {playbook_id} not found")
            task = session.query(Task).get(task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found")
            task.search_config_json = pb.search_config_json
            task.filter_config_json = pb.filter_config_json
            task.action_config_json = pb.action_config_json
            session.commit()
            session.refresh(task)
            return task
        finally:
            session.close()

    def apply_preset_to_task(self, task_id: int, playbook_type: str) -> Task:
        """将预设打法配置应用到任务"""
        preset = next((p for p in PRESET_PLAYBOOKS if p["playbook_type"] == playbook_type), None)
        if not preset:
            raise ValueError(f"Unknown playbook type: {playbook_type}")
        session = get_session()
        try:
            task = session.query(Task).get(task_id)
            if not task:
                raise ValueError(f"Task {task_id} not found")
            task.search_config_json = json.dumps(preset["search_config"], ensure_ascii=False)
            task.filter_config_json = json.dumps(preset["filter_config"], ensure_ascii=False)
            task.action_config_json = json.dumps(preset["action_config"], ensure_ascii=False)
            session.commit()
            session.refresh(task)
            return task
        finally:
            session.close()
