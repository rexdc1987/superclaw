"""Task Executor - orchestrates the full workflow with rhythm control"""
import asyncio
import json
import logging
import random
from datetime import datetime
from typing import Dict, List, Optional
from models.database import get_session
from models.task import Task
from services.collector_service import CollectorService
from services.lead_service import LeadService
from services.action_service import ActionService
from services.risk_service import RiskService
from services.keyword_service import KeywordService
from services.account_service import AccountService
from core.constants import TaskStatus, ActionType, DEFAULT_RATE_LIMITS

logger = logging.getLogger(__name__)


class RhythmController:
    """Controls task execution rhythm: intervals, rest, keyword rotation."""

    def __init__(self, config=None):
        cfg = config or {}
        self.interval_min = cfg.get("interval_min", 5)
        self.interval_max = cfg.get("interval_max", 10)
        self.rest_after = cfg.get("rest_after", 10)
        self.rest_min = cfg.get("rest_min", 60)
        self.rest_max = cfg.get("rest_max", 200)
        self.keyword_rotate_after = cfg.get("keyword_rotate_after", 5)
        self._action_count = 0
        self._keyword_count = 0

    def _rand_range(self, lo, hi):
        return random.uniform(max(1, lo), max(1, hi))

    async def before_action(self):
        """Called before each action. Handles interval delay."""
        delay = self._rand_range(self.interval_min, self.interval_max)
        logger.debug(f"Rhythm: interval {delay:.1f}s")
        await asyncio.sleep(delay)

    async def after_action(self):
        """Called after each action. Handles rest logic."""
        self._action_count += 1
        self._keyword_count += 1
        if self.rest_after > 0 and self._action_count >= self.rest_after:
            rest = self._rand_range(self.rest_min, self.rest_max)
            logger.info(f"Rhythm: resting {rest:.0f}s after {self._action_count} actions")
            self._action_count = 0
            await asyncio.sleep(rest)

    def should_rotate_keyword(self) -> bool:
        if self.keyword_rotate_after <= 0:
            return False
        return self._keyword_count >= self.keyword_rotate_after

    def reset_keyword_counter(self):
        self._keyword_count = 0


class TemplatePool:
    """Randomly selects templates without immediate repeats."""

    def __init__(self, templates):
        self._all = templates or []
        self._available = list(self._all)
        self._used = []

    def pick(self):
        if not self._all:
            return None
        if not self._available:
            self._available = list(self._all)
            random.shuffle(self._available)
        t = self._available.pop()
        self._used.append(t)
        return t


class TaskExecutor:
    """Execute a task end-to-end: search -> collect -> filter -> score -> actions"""

    def __init__(self):
        self.collector = CollectorService()
        self.lead_svc = LeadService()
        self.action_svc = ActionService()
        self.risk_svc = RiskService()
        self.keyword_svc = KeywordService()
        self.account_svc = AccountService()
        self._task_state = {}
        self._task_logs = {}  # {task_id: [log_entries]}

    def get_task_logs(self, task_id, limit=100):
        return self._task_logs.get(task_id, [])[-limit:]

    def _log(self, task_id, level, message):
        entry = {
            "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,
            "message": message,
        }
        self._task_logs.setdefault(task_id, []).append(entry)
        if len(self._task_logs[task_id]) > 2000:
            self._task_logs[task_id] = self._task_logs[task_id][-1000:]
        if level == "error":
            logger.error(f"[Task {task_id}] {message}")
        else:
            logger.info(f"[Task {task_id}] {message}")

    async def execute(self, task_id: int, adapter=None) -> Dict:
        session = get_session()
        try:
            task = session.query(Task).get(task_id)
            if not task:
                return {"success": False, "error": "Task not found"}
            if task.status != TaskStatus.RUNNING.value:
                return {"success": False, "error": f"Task status is {task.status}"}

            search_config = json.loads(task.search_config_json or "{}")
            filter_config = json.loads(task.filter_config_json or "{}")
            action_config = json.loads(task.action_config_json or "{}")
            rhythm_config = json.loads(task.rhythm_config_json or "{}")
            task_platform = task.platform
            task_keyword_group_id = task.keyword_group_id
        finally:
            session.close()

        self._task_state[task_id] = {"running": True, "paused": False}
        self._task_logs[task_id] = []
        rhythm = RhythmController(rhythm_config)
        result = {
            "task_id": task_id, "steps": [], "success": False,
            "started_at": datetime.utcnow().isoformat(),
        }

        self._log(task_id, "info", f"任务开始执行 platform={task_platform}")
        self._update_state(task_id, "running")

        try:
            # Step 1: Get keywords
            keywords = filter_config.get("keywords", [])
            if not keywords and task_keyword_group_id:
                keywords = self.keyword_svc.get_group_keywords(task_keyword_group_id)
            if not keywords:
                self._log(task_id, "error", "没有配置关键词")
                return {"success": False, "error": "No keywords configured"}
            self._log(task_id, "info", f"关键词: {', '.join(keywords)}")
            result["steps"].append({"step": "keywords", "count": len(keywords)})

            # Step 2: Get available accounts
            accounts = self.account_svc.get_available_accounts(platform=task_platform)
            if not accounts:
                self._log(task_id, "error", "没有可用账号")
                return {"success": False, "error": "No available accounts"}
            self._log(task_id, "info", f"可用账号: {len(accounts)} 个")

            # Step 3: Load templates for random pool
            templates = []
            template_ids = action_config.get("template_ids", [])
            if template_ids:
                session = get_session()
                try:
                    from models.template import MessageTemplate
                    templates = session.query(MessageTemplate).filter(
                        MessageTemplate.id.in_(template_ids)).all()
                    templates = [{"id": t.id, "content": t.content} for t in templates]
                finally:
                    session.close()
            pool = TemplatePool(templates)
            self._log(task_id, "info", f"话术池: {len(templates)} 条模板")

            # Step 4: Search and collect
            if adapter:
                video_count = search_config.get("video_count", 10)
                comment_count = search_config.get("comment_count", 50)
                total_comments = 0
                total_targets = 0
                total_leads = 0
                rotated_keywords = list(keywords)

                for kw_idx, keyword in enumerate(rotated_keywords):
                    if not self._check_running(task_id):
                        break

                    self._log(task_id, "info", f"搜索关键词: {keyword}")
                    videos = await adapter.search_keyword(keyword, video_count)
                    self._log(task_id, "info", f"找到 {len(videos)} 个视频")
                    result["steps"].append({"step": f"search_{keyword}", "videos": len(videos)})

                    for video in videos:
                        if not self._check_running(task_id):
                            break

                        comments_data = await adapter.get_comments(
                            video.get("video_url", ""), comment_count)
                        total_comments += len(comments_data)

                        if comments_data:
                            video_data = {
                                "platform": task_platform,
                                "video_id": video.get("video_id", ""),
                                "video_title": video.get("video_title", ""),
                                "video_url": video.get("video_url", ""),
                            }
                            self.collector.collect_comments(task_id, video_data, comments_data)

                            # Enhanced filtering
                            max_per_video = filter_config.get("max_comments_per_video", 50)
                            exclude = filter_config.get("exclude_words", [])
                            time_days = filter_config.get("time_range_days")
                            regions = filter_config.get("exclude_regions", [])

                            targets = self.collector.filter_target_comments(
                                task_id, [keyword],
                                exclude_words=exclude,
                                time_range_days=time_days,
                                max_count=max_per_video,
                                exclude_regions=regions,
                            )
                            total_targets += len(targets)
                            leads = self.collector.create_leads_from_comments(task_id, targets)
                            total_leads += len(leads)

                    # Keyword rotation check
                    if rhythm.should_rotate_keyword() and kw_idx < len(rotated_keywords) - 1:
                        self._log(task_id, "info",
                                  f"关键词轮换: 已执行 {rhythm.keyword_rotate_after} 次")
                        rhythm.reset_keyword_counter()

                    self._update_progress(task_id, done=kw_idx + 1, total=len(rotated_keywords))

                self._log(task_id, "info",
                          f"采集完成: 评论{total_comments} 筛选{total_targets} 线索{total_leads}")
                result["steps"].append({
                    "step": "collect",
                    "comments": total_comments,
                    "targets": total_targets,
                    "leads": total_leads,
                })
            else:
                self._log(task_id, "info", "无适配器，跳过采集")
                result["steps"].append({"step": "collect", "note": "No adapter"})

            # Step 5: Score leads
            strong_kw = filter_config.get("keywords", [])
            scored = self.lead_svc.score_leads(task_id, strong_keywords=strong_kw)
            self._log(task_id, "info", f"评分完成: {scored} 条线索")
            result["steps"].append({"step": "score", "scored": scored})

            # Step 6: Generate actions with rhythm
            action_types = action_config.get("action_types",
                                              [action_config.get("action_type", "comment")])
            if isinstance(action_types, str):
                action_types = [action_types]

            if action_types:
                leads_result = self.lead_svc.get_leads(task_id=task_id, min_score=30)
                lead_items = leads_result.get("items", [])
                if lead_items:
                    self._log(task_id, "info",
                              f"生成动作: {len(action_types)} 种类型 x {len(lead_items)} 条线索")
                    created_count = 0
                    for idx, lead in enumerate(lead_items):
                        if not self._check_running(task_id):
                            break

                        # Rhythm: wait before action
                        await rhythm.before_action()

                        # Pick random template content
                        tpl = pool.pick()
                        content = tpl["content"] if tpl else action_config.get("content", "")
                        template_id = tpl["id"] if tpl else None
                        mention = action_config.get("mention_user", "")

                        for atype in action_types:
                            a = self.action_svc.create_action(
                                task_id, atype, lead_id=lead.id,
                                content=content, template_id=template_id,
                                mention_user=mention,
                            )
                            created_count += 1

                        # Rhythm: handle rest after action
                        await rhythm.after_action()

                        if idx % 10 == 0 and idx > 0:
                            self._log(task_id, "info",
                                      f"进度: {idx}/{len(lead_items)} 已生成 {created_count} 个动作")

                    self._log(task_id, "info", f"动作生成完成: 共 {created_count} 个")
                    result["steps"].append({"step": "actions_created", "count": created_count})

            # Complete
            from services.task_service import TaskService
            TaskService().complete_task(task_id)
            result["success"] = True
            result["completed_at"] = datetime.utcnow().isoformat()
            self._log(task_id, "info", "任务执行完成!")

        except Exception as e:
            logger.error(f"Task execution failed: {e}")
            self._log(task_id, "error", f"执行失败: {str(e)}")
            result["error"] = str(e)
            from services.task_service import TaskService
            try:
                TaskService().fail_task(task_id, str(e))
            except Exception as inner_e:
                logger.error(f"Failed to mark task as failed: {inner_e}")

        self._task_state.pop(task_id, None)
        return result

    def _check_running(self, task_id):
        state = self._task_state.get(task_id, {})
        if not state.get("running"):
            return False
        while state.get("paused"):
            import time
            time.sleep(1)
            state = self._task_state.get(task_id, {})
            if not state.get("running"):
                return False
        return True

    def _update_state(self, task_id, status):
        session = get_session()
        try:
            task = session.query(Task).get(task_id)
            if task:
                task.status = status
                session.commit()
        finally:
            session.close()

    def pause(self, task_id=None):
        if task_id:
            if task_id in self._task_state:
                self._task_state[task_id]["paused"] = True
                self._log(task_id, "info", "任务已暂停")
        else:
            for tid, state in self._task_state.items():
                state["paused"] = True

    def resume(self, task_id=None):
        if task_id:
            if task_id in self._task_state:
                self._task_state[task_id]["paused"] = False
                self._log(task_id, "info", "任务已恢复")
        else:
            for state in self._task_state.values():
                state["paused"] = False

    def stop(self, task_id=None):
        if task_id:
            if task_id in self._task_state:
                self._task_state[task_id]["running"] = False
                self._log(task_id, "info", "任务已停止")
        else:
            for state in self._task_state.values():
                state["running"] = False

    def _update_progress(self, task_id, done, total):
        session = get_session()
        try:
            task = session.query(Task).get(task_id)
            if task:
                task.progress_done = done
                task.progress_total = total
                session.commit()
        finally:
            session.close()
