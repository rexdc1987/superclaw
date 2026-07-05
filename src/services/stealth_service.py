"""Stealth service — 留痕曝光模式（只点赞+关注+收藏，不发评论私信）"""
import logging
from datetime import datetime
from typing import Dict, List
from models.database import get_session
from models.task import Task
from models.action import Action
from services.action_service import ActionService

logger = logging.getLogger(__name__)


class StealthService:
    """留痕曝光：对目标用户执行 like + follow + favorite，不发评论/私信"""

    STEALTH_ACTION_TYPES = ["like", "follow", "favorite"]

    def __init__(self):
        self.action_svc = ActionService()

    def execute_stealth_task(self, task_id: int, adapter=None) -> Dict:
        """
        执行留痕曝光任务:
        1. 从 Task 的 filter_config 读取关键词
        2. 搜索视频 -> 采集评论 -> 筛选高意向用户
        3. 对每个用户执行: 点赞评论 -> 关注用户 -> 收藏视频
        4. 所有操作记入 Action 表
        """
        session = get_session()
        try:
            task = session.get(Task, task_id)
            if not task:
                return {"success": False, "error": "Task not found"}
            import json
            search_config = json.loads(task.search_config_json or "{}")
            filter_config = json.loads(task.filter_config_json or "{}")
            task_platform = task.platform
        finally:
            session.close()

        result = {
            "task_id": task_id, "mode": "stealth", "success": False,
            "actions_created": 0, "users_processed": 0,
        }

        try:
            # Collect leads via adapter or existing data
            leads = []
            if adapter:
                leads = self._collect_via_adapter(
                    adapter, task_id, task_platform, search_config, filter_config)
            else:
                # Fallback: use existing leads from DB (no min_score for stealth)
                from services.lead_service import LeadService
                leads_data = LeadService().get_leads(task_id=task_id)
                leads = leads_data.get("items", [])

            if not leads:
                result["error"] = "No leads found"
                return result

            # Execute stealth actions for each lead
            total_actions = 0
            for lead in leads:
                if adapter:
                    actions = self.stealth_interact(adapter, lead)
                else:
                    # DB-only mode: just create action records
                    actions = self._create_stealth_actions(task_id, lead)

                total_actions += len(actions)
                result["users_processed"] += 1

            result["actions_created"] = total_actions
            result["success"] = True
            logger.info(f"Stealth task {task_id}: {result['users_processed']} users, "
                        f"{total_actions} actions")
        except Exception as e:
            logger.error(f"Stealth task {task_id} failed: {e}")
            result["error"] = str(e)

        return result

    def stealth_interact(self, adapter, lead) -> List:
        """
        对单个用户执行留痕操作:
        1. 点赞该用户的评论
        2. 关注该用户
        3. 收藏视频
        """
        actions = []
        user_url = getattr(lead, "user_url", "") or ""
        video_url = getattr(lead, "video_url", "") or ""
        comment_id = getattr(lead, "source_comment_id", None)

        # Like the comment
        try:
            success = adapter.like_comment(str(comment_id)) if comment_id else False
            actions.append({"type": "like", "success": success})
        except Exception as e:
            logger.debug(f"Like failed for lead {lead.id}: {e}")
            actions.append({"type": "like", "success": False})

        # Follow the user
        if user_url:
            try:
                success = adapter.follow_user(user_url)
                actions.append({"type": "follow", "success": success})
            except Exception as e:
                logger.debug(f"Follow failed for lead {lead.id}: {e}")
                actions.append({"type": "follow", "success": False})

        # Favorite the video
        if video_url:
            try:
                success = adapter.favorite_video(video_url)
                actions.append({"type": "favorite", "success": success})
            except Exception as e:
                logger.debug(f"Favorite failed for lead {lead.id}: {e}")
                actions.append({"type": "favorite", "success": False})

        return actions

    def _collect_via_adapter(self, adapter, task_id, platform, search_config, filter_config):
        """通过适配器搜索并采集线索"""
        from services.collector_service import CollectorService
        from services.lead_service import LeadService

        collector = CollectorService()
        keywords = filter_config.get("keywords", [])
        video_count = search_config.get("video_count", 10)
        comment_count = search_config.get("comment_count", 50)

        all_leads = []
        for keyword in keywords:
            videos = adapter.search_keyword(keyword, video_count)
            for video in videos:
                comments = adapter.get_comments(video.get("video_url", ""), comment_count)
                if comments:
                    video_data = {
                        "platform": platform,
                        "video_id": video.get("video_id", ""),
                        "video_title": video.get("video_title", ""),
                        "video_url": video.get("video_url", ""),
                    }
                    collector.collect_comments(task_id, video_data, comments)
                    targets = collector.filter_target_comments(task_id, [keyword])
                    leads = collector.create_leads_from_comments(task_id, targets)
                    all_leads.extend(leads)

        return all_leads

    def _create_stealth_actions(self, task_id, lead) -> List:
        """DB-only 模式：创建 like + follow + favorite 动作记录"""
        actions = []
        for atype in self.STEALTH_ACTION_TYPES:
            a = self.action_svc.create_action(
                task_id, atype, lead_id=lead.id,
                content="", template_id=None)
            actions.append(a)
        return actions

    def get_stealth_stats(self, task_id: int) -> Dict:
        """获取留痕曝光统计"""
        session = get_session()
        try:
            actions = session.query(Action).filter(
                Action.task_id == task_id,
                Action.action_type.in_(self.STEALTH_ACTION_TYPES),
            ).all()

            by_type = {}
            by_status = {}
            for a in actions:
                by_type[a.action_type] = by_type.get(a.action_type, 0) + 1
                by_status[a.status] = by_status.get(a.status, 0) + 1

            return {
                "task_id": task_id,
                "mode": "stealth",
                "total_actions": len(actions),
                "by_type": by_type,
                "by_status": by_status,
            }
        finally:
            session.close()
