"""Threaded task engine for Hongguo comment automation."""

from __future__ import annotations

import json
import os
import random
import re
import threading
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import pymysql
from pymysql.cursors import DictCursor

from .ai_usage import record_usage
from .comment_gen import CommentGenerator
from .device import DEFAULT_ADDR, check_connection, connect
from .leases import DeviceLeaseStore
from .operations import LIVE_LITE_ACTIVITY, SHORT_SERIES_ACTIVITY, HongguoOperations


DEFAULT_SCREENSHOT_ROOT = os.environ.get(
    "SUPERCLAW_SCREENSHOT_ROOT",
    str((Path(__file__).resolve().parents[3] / "screenshots" / "hongguo").as_posix()),
)
REGULAR_RECOVERY_BUDGET_SECONDS = 90


class TaskEngine:
    """Runs one Hongguo task in a daemon thread."""

    def __init__(
        self,
        task_id: int,
        db_config: Dict[str, Any],
        screenshot_dir: str,
        ai_config: Optional[Dict[str, Any]] = None,
        device_addr: str = DEFAULT_ADDR,
        lease_heartbeat: Optional[Callable[[int], None]] = None,
    ):
        self.task_id = int(task_id)
        self.db_config = dict(db_config)
        self.screenshot_dir = str(Path(screenshot_dir).as_posix())
        self.ai_config = dict(ai_config or {})
        self.device_addr = device_addr
        self._pause_event = threading.Event()
        self._stop_event = threading.Event()
        self._resume_playback_check = False
        self._comment_recovered_at: Dict[int, float] = {}
        self._completed_engagement_episodes: Dict[str, set[int]] = {
            "like": set(),
            "favorite": set(),
        }
        self._device_info_cache: Dict[str, Any] = {}
        self._ai_comment_disabled_reason = ""
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._generator = CommentGenerator(self.ai_config)
        self._lease_heartbeat = lease_heartbeat
        self._last_lease_heartbeat = 0.0

    @property
    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> bool:
        with self._lock:
            if self.is_alive:
                return False
            self._pause_event.clear()
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name=f"hongguo-task-{self.task_id}",
                daemon=True,
            )
            self._thread.start()
            return True

    def pause(self) -> bool:
        self._pause_event.set()
        self._update_task(status="paused")
        self._log("info", "任务已暂停")
        return True

    def resume(self) -> bool:
        self._pause_event.clear()
        self._resume_playback_check = True
        self._update_task(status="running")
        self._log("info", "任务已恢复")
        return True

    def stop(self) -> bool:
        self._stop_event.set()
        self._pause_event.clear()
        self._update_task(status="stopped", completed_at=datetime.now())
        self._log("info", "任务已停止")
        return True

    def wait_stopped(self, timeout: float = 0) -> bool:
        thread = self._thread
        if not thread or not thread.is_alive():
            return True
        if threading.current_thread() is thread:
            return False
        thread.join(max(0, float(timeout)))
        return not thread.is_alive()

    def _run_verified_flow(self) -> None:
        Path(self.screenshot_dir).mkdir(parents=True, exist_ok=True)
        self._ai_comment_disabled_reason = ""
        try:
            os.environ.pop("PYTHONPATH", None)
            now = datetime.now()
            self._update_task(
                status="running",
                started_at=now,
                completed_at=None,
                duration_seconds=None,
                error_message=None,
                current_episode=0,
                comments_sent=0,
                comments_verified=0,
                likes_completed=0,
                favorites_completed=0,
                completion_screenshot_path=None,
                updated_at=now,
            )
            self._log("info", "全流程v3: 开始执行，从打开红果到刷完整部短剧")
            if not check_connection(self.device_addr):
                raise RuntimeError(f"设备未连接: {self.device_addr}")

            device = connect(self.device_addr)
            ops = HongguoOperations(device)
            task = self._load_task()
            if not task:
                raise RuntimeError("任务不存在")

            prepare = self._prepare_verified_playback(ops, task)
            total = int(prepare.get("total_episodes") or 0)
            if total <= 0:
                raise RuntimeError("未识别到短剧总集数")
            drama_title = str(prepare.get("drama_title") or task.get("drama_name") or "")
            comment_episodes = set(self._comment_episode_plan(task, total))
            like_episodes = set(self._engagement_episode_plan(task, total, "random_like_count", 5))
            favorite_episodes = set(
                self._engagement_episode_plan(task, total, "random_favorite_count", 1)
            )
            self._completed_engagement_episodes = {"like": set(), "favorite": set()}
            completed_episodes = self._completed_comment_episodes()
            if completed_episodes:
                comment_episodes -= completed_episodes

            execution_plan = {
                "watch_episodes": list(range(1, total + 1)),
                "comment_episodes": sorted(comment_episodes),
                "like_episodes": sorted(like_episodes),
                "favorite_episodes": sorted(favorite_episodes),
                "skipped_comment_episodes": sorted(completed_episodes),
                "rule": self._task_rule_snapshot(task),
                "flow": "verified_v3_full",
            }
            execution_plan_json = json.dumps(execution_plan, ensure_ascii=False)
            self._update_task(
                current_episode=1,
                total_episodes=total,
                execution_plan_json=execution_plan_json,
                updated_at=datetime.now(),
            )
            task["execution_plan_json"] = execution_plan_json
            self._log(
                "info",
                f"全流程v3: 准备完成，短剧={drama_title}，总集数={total}，"
                f"评论集数={sorted(comment_episodes)}，点赞集数={sorted(like_episodes)}，"
                f"收藏集数={sorted(favorite_episodes)}",
            )
            if 1 not in comment_episodes or self._comment_already_verified(1):
                self._resume_if_paused(ops, 1)

            for episode in range(1, total + 1):
                self._check_pause_stop()
                state = self._page_state(ops, task)
                app = state.get("app") or {}
                if (
                    app.get("package") != "com.phoenix.read"
                    or app.get("activity") != "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity"
                ):
                    self._log(
                        "warn",
                        f"全流程v3: 第{episode}集观察前不在播放页，package={app.get('package') or '-'}，"
                        f"activity={app.get('activity') or '-'}，尝试恢复",
                    )
                    if self._recover_to_verified_episode(ops, task, episode, total, "主循环观察前离开播放页"):
                        state = self._page_state(ops, task)
                state = self._ensure_target_playback_context(ops, task, state, episode, total)
                current = int(state.get("current_episode") or 0)
                if current and current != episode:
                    pending_episodes = (
                        self._pending_comment_episodes_between(task, episode, current)
                        if current > episode
                        else []
                    )
                    if current > episode and not pending_episodes:
                        self._log(
                            "info",
                            f"全流程v3: 第{episode}集已自然播放越过到第{current}集，未命中评论或互动计划，顺延观察",
                        )
                        continue
                    recovery_episode = pending_episodes[0] if pending_episodes else episode
                    self._log(
                        "warn",
                        f"全流程v3: 期望第{episode}集，当前识别第{current}集，"
                        f"尝试恢复第{recovery_episode}集",
                    )
                    if self._recover_to_verified_episode(
                        ops,
                        task,
                        recovery_episode,
                        total,
                        f"主循环集数偏移，当前第{current}集",
                    ):
                        # Recovery already performs stable episode verification. Process the
                        # pending action immediately so fast playback cannot outrun it again.
                        episode = recovery_episode
                        current = recovery_episode
                    if current > episode and not self._pending_comment_episodes_between(task, episode, current):
                        self._log(
                            "info",
                            f"全流程v3: 恢复确认时已播放到第{current}集，跳过的集数未命中评论或互动计划，顺延观察",
                        )
                        continue
                    if current and current != episode:
                        raise RuntimeError(
                            f"全流程v3跳集异常: 期望第{recovery_episode}集，当前第{current}集"
                        )

                self._update_task(current_episode=episode, updated_at=datetime.now())
                self._log("info", f"全流程v3: 正在观察第{episode}集")
                self._process_engagement_episode(
                    ops,
                    episode,
                    like_episodes,
                    favorite_episodes,
                    total=total,
                    task=task,
                )
                if not self._process_comment_episode(
                    ops,
                    task,
                    drama_title,
                    episode,
                    total,
                    comment_episodes,
                ):
                    self._resume_if_paused(ops, episode)

                if episode >= total:
                    break
                target = episode + 1
                if not self._wait_for_next_episode_verified(ops, task, episode, target, total):
                    shot = ops.take_screenshot(f"ep{episode}_next_timeout", self.screenshot_dir)
                    raise RuntimeError(f"全流程v3: 第{episode}集后未自动进入第{target}集，已截图 {shot}")

            completed_at = datetime.now()
            missing_comments = self._missing_verified_comment_episodes(comment_episodes)
            if missing_comments:
                self._log(
                    "warn",
                    f"全流程v3: 正常刷完后仍有未验证评论集数={missing_comments}，开始最终补偿重发",
                )
                missing_comments = self._retry_missing_comments_before_completion(
                    ops,
                    task,
                    drama_title,
                    total,
                    missing_comments,
                )
                completed_at = datetime.now()
            self._retry_missing_engagements_before_completion(
                ops,
                task,
                total,
                like_episodes,
                favorite_episodes,
            )
            completed_at = datetime.now()
            completion_screenshot = ops.take_screenshot("task_completed_summary", self.screenshot_dir)
            likes_completed = len(self._completed_engagement_episodes["like"])
            favorites_completed = len(self._completed_engagement_episodes["favorite"])
            self._update_task(completion_screenshot_path=completion_screenshot, updated_at=completed_at)
            engagement_level = (
                "info"
                if likes_completed == len(like_episodes) and favorites_completed == len(favorite_episodes)
                else "warn"
            )
            engagement_complete = engagement_level == "info"
            self._log(
                engagement_level,
                f"全流程v3: 互动统计 点赞={likes_completed}/{len(like_episodes)}，"
                f"收藏={favorites_completed}/{len(favorite_episodes)}，完成截图 {completion_screenshot}",
            )
            if missing_comments or not engagement_complete:
                failures = []
                if missing_comments:
                    failures.append(
                        f"评论验证未达标: 未验证成功集数={missing_comments}，计划评论集数={sorted(comment_episodes)}"
                    )
                if not engagement_complete:
                    failures.append(
                        f"互动未达标: 点赞={likes_completed}/{len(like_episodes)}，"
                        f"收藏={favorites_completed}/{len(favorite_episodes)}"
                    )
                message = "；".join(failures)
                self._update_task(
                    status="failed",
                    error_message=message,
                    completed_at=completed_at,
                    duration_seconds=self._duration_seconds(completed_at),
                    updated_at=completed_at,
                )
                self._log("error", f"全流程v3: {message}")
            else:
                self._update_task(
                    status="completed",
                    completed_at=completed_at,
                    duration_seconds=self._duration_seconds(completed_at),
                    error_message=None,
                    updated_at=completed_at,
                )
                self._log("info", "全流程v3: 任务执行完成")
        except StopRequested:
            completed_at = datetime.now()
            self._update_task(
                status="stopped",
                completed_at=completed_at,
                duration_seconds=self._duration_seconds(completed_at),
                updated_at=completed_at,
            )
            self._log("info", "全流程v3: 任务已停止")
        except Exception as exc:
            completed_at = datetime.now()
            self._update_task(
                status="failed",
                error_message=str(exc),
                completed_at=completed_at,
                duration_seconds=self._duration_seconds(completed_at),
                updated_at=completed_at,
            )
            self._log("error", f"任务失败: {exc}")

    def _process_comment_episode(
        self,
        ops: HongguoOperations,
        task: Dict[str, Any],
        drama_title: str,
        episode: int,
        expected_total: int,
        comment_episodes: set[int],
    ) -> bool:
        if episode not in comment_episodes:
            return False
        if self._comment_already_verified(episode):
            self._log("info", f"全流程v3: 第{episode}集已有成功评论记录，跳过重复评论")
            return False
        self._handle_verified_comment(
            ops,
            task,
            drama_title,
            episode,
            expected_total,
            avoid_contents=self._comment_contents_for_batch(),
        )
        return True

    def _process_engagement_episode(
        self,
        ops: HongguoOperations,
        episode: int,
        like_episodes: set[int],
        favorite_episodes: set[int],
        total: int = 0,
        task: Optional[Dict[str, Any]] = None,
    ) -> None:
        actions = (
            ("like", "点赞", like_episodes, ops.like_current_episode),
            ("favorite", "收藏", favorite_episodes, ops.favorite_current_episode),
        )
        for action, label, planned, operation in actions:
            if episode not in planned or episode in self._completed_engagement_episodes[action]:
                continue
            self._check_pause_stop()
            result = operation()
            success = bool(result.get("success"))
            verified = bool(result.get("verified"))
            self._log(
                "info" if success and verified else "warn",
                f"全流程v3: 第{episode}集随机{label}={'成功' if success else '失败'}，"
                f"已验证={verified}，{result.get('message') or '-'}",
            )
            if success and verified:
                if result.get("already_active"):
                    if action == "favorite":
                        self._completed_engagement_episodes[action].add(episode)
                        self._increment_engagement_counter(action)
                        self._log("info", "全流程v3: 当前短剧原本已收藏，收藏目标已达成")
                        continue
                    replacement = self._reschedule_engagement_episode(
                        action,
                        label,
                        episode,
                        planned,
                        total,
                        task,
                    )
                    if replacement:
                        self._log(
                            "info",
                            f"全流程v3: 第{episode}集原本已{label}，不消耗新增名额，顺延到第{replacement}集",
                        )
                    else:
                        self._log(
                            "warn",
                            f"全流程v3: 第{episode}集原本已{label}，后续没有可顺延集数，不计入新增{label}",
                        )
                    continue
                self._completed_engagement_episodes[action].add(episode)
                self._increment_engagement_counter(action)

    def _retry_missing_engagements_before_completion(
        self,
        ops: HongguoOperations,
        task: Dict[str, Any],
        total: int,
        like_episodes: set[int],
        favorite_episodes: set[int],
    ) -> None:
        actions = (
            ("like", "点赞", like_episodes, ops.like_current_episode),
            ("favorite", "收藏", favorite_episodes, ops.favorite_current_episode),
        )
        for action, label, planned, operation in actions:
            missing = len(planned) - len(self._completed_engagement_episodes[action])
            if missing <= 0:
                continue
            attempted = set(planned) | set(self._completed_engagement_episodes[action])
            candidates = [episode for episode in range(1, total + 1) if episode not in attempted]
            random.shuffle(candidates)
            self._log(
                "warn",
                f"全流程v3: 刷完后仍缺少{missing}次{label}，开始回访未尝试集数补偿",
            )
            for episode in candidates:
                if len(self._completed_engagement_episodes[action]) >= len(planned):
                    break
                self._check_pause_stop()
                if not self._recover_to_verified_episode(
                    ops,
                    task,
                    episode,
                    total,
                    f"最终补偿{label}",
                ):
                    self._log("warn", f"全流程v3: 最终补偿{label}无法恢复到第{episode}集，继续尝试其他集")
                    continue
                result = operation()
                success = bool(result.get("success"))
                verified = bool(result.get("verified"))
                already_active = bool(result.get("already_active"))
                self._log(
                    "info" if success and verified else "warn",
                    f"全流程v3: 第{episode}集最终补偿{label}={'成功' if success else '失败'}，"
                    f"已验证={verified}，{result.get('message') or '-'}",
                )
                if not success or not verified:
                    continue
                if action == "like" and already_active:
                    continue
                unresolved = sorted(planned - self._completed_engagement_episodes[action])
                if unresolved:
                    planned.discard(unresolved[0])
                planned.add(episode)
                self._completed_engagement_episodes[action].add(episode)
                self._increment_engagement_counter(action)
                self._update_execution_plan_engagement(task, action, planned)

    def _ensure_target_playback_context(
        self,
        ops: HongguoOperations,
        task: Dict[str, Any],
        state: Dict[str, Any],
        episode: int,
        expected_total: int,
    ) -> Dict[str, Any]:
        try:
            self._assert_target_playback(ops, task, state, expected_total)
            return state
        except RuntimeError as exc:
            if "未识别到当前集数" in str(exc):
                confirmed = self._confirm_current_episode(ops, episode)
                if confirmed == episode:
                    confirmed_state = dict(state)
                    confirmed_state["current_episode"] = confirmed
                    self._log(
                        "info",
                        f"全流程v3: 第{episode}集观察前控件隐藏，强确认仍为第{confirmed}集，继续执行",
                    )
                    return confirmed_state
                self._log(
                    "warn",
                    f"全流程v3: 第{episode}集观察前当前集不可读，强确认={confirmed or 0}，恢复目标集",
                )
                if self._recover_to_verified_episode(
                    ops,
                    task,
                    episode,
                    expected_total,
                    f"主循环观察前当前集不可读，强确认={confirmed or 0}",
                ):
                    recovered_state = self._page_state(ops, task)
                    recovered_current = self._confirm_current_episode(ops, episode)
                    if recovered_current == episode:
                        recovered_state = dict(recovered_state)
                        recovered_state["current_episode"] = recovered_current
                        return recovered_state
                raise
            mismatch_markers = ("总集数不匹配", "非目标合集", "标题不匹配")
            if not any(marker in str(exc) for marker in mismatch_markers):
                raise
            self._log(
                "warn",
                f"全流程v3: 第{episode}集观察前检测到错误合集，尝试恢复目标短剧，原因={exc}",
            )
            if not self._recover_to_verified_episode(
                ops,
                task,
                episode,
                expected_total,
                f"主循环观察前目标短剧校验失败: {exc}",
            ):
                raise
            recovered_state = self._page_state(ops, task)
            self._assert_target_playback(ops, task, recovered_state, expected_total)
            return recovered_state

    def _reschedule_engagement_episode(
        self,
        action: str,
        label: str,
        episode: int,
        planned: set[int],
        total: int,
        task: Optional[Dict[str, Any]],
    ) -> int:
        candidates = [
            value
            for value in range(episode + 1, int(total or 0) + 1)
            if value not in planned and value not in self._completed_engagement_episodes[action]
        ]
        if not candidates:
            return 0
        replacement = random.choice(candidates)
        planned.discard(episode)
        planned.add(replacement)
        self._update_execution_plan_engagement(task, action, planned)
        return replacement

    def _update_execution_plan_engagement(
        self,
        task: Optional[Dict[str, Any]],
        action: str,
        planned: set[int],
    ) -> None:
        if not task:
            return
        try:
            plan = json.loads(task.get("execution_plan_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            plan = {}
        key = "like_episodes" if action == "like" else "favorite_episodes"
        plan[key] = sorted(planned)
        serialized = json.dumps(plan, ensure_ascii=False)
        task["execution_plan_json"] = serialized
        self._update_task(execution_plan_json=serialized, updated_at=datetime.now())

    def _prepare_verified_playback(self, ops: HongguoOperations, task: Dict[str, Any]) -> Dict[str, Any]:
        keyword = str(task.get("drama_name") or "").strip()
        if not keyword:
            raise RuntimeError("任务短剧名称为空")

        self._check_pause_stop()
        self._log("info", "全流程v3: 打开红果APP")
        if not ops.launch_app():
            raise RuntimeError("红果启动未确认")

        login = self._check_login(ops)
        self._log("info", f"全流程v3: 登录检测 - {login.get('message') or login.get('status')}")
        if not login.get("logged_in"):
            raise RuntimeError(login.get("message") or "登录检测失败")

        if not self._reset_search_context(ops, "首次选剧"):
            raise RuntimeError("首次选剧前无法重置到红果主页面")

        self._check_pause_stop()
        opened = ops.open_search_page(keyword)
        self._log("info", opened.get("message") or "全流程v3: 已进入搜索框")
        if not opened.get("success"):
            raise RuntimeError(opened.get("message") or "进入搜索框失败")

        input_result = ops.input_search_keyword(keyword)
        self._log("info", input_result.get("message") or f"全流程v3: 已填入搜索词 {keyword}")
        if not input_result.get("success"):
            raise RuntimeError(input_result.get("message") or "关键词填入失败")

        search = ops.submit_search(keyword)
        submit = search.get("submit") or {}
        self._log(
            "info",
            f"{search.get('message') or '全流程v3: 搜索完成'}，提交动作={submit.get('action') or search.get('action') or '-'}，"
            f"结果页={bool(submit.get('tabs_visible') or search.get('tabs_visible'))}，候选={bool(submit.get('candidate_visible') or search.get('candidate_visible'))}",
        )
        if not search.get("success"):
            raise RuntimeError(search.get("message") or "提交搜索失败")

        titles = ops._extract_drama_titles()
        selected_title = ops._choose_title(keyword, titles)
        self._log("info", f"全流程v3: 搜索结果={titles[:5]}，命中={selected_title or '-'}")
        if not selected_title:
            self._log("warn", "全流程v3: 未找到可读文字标题命中，尝试无文字海报兜底校验")

        task_total = int(task.get("total_episodes") or 0)
        selected = ops.select_drama(
            selected_title,
            keyword=keyword,
            expected_total=task_total,
        )
        drama_title = selected.get("drama_title") or selected_title
        self._log("info", selected.get("message") or f"全流程v3: 已进入目标剧集 {drama_title}")
        if not selected.get("success"):
            shot = ops.take_screenshot("select_drama_failed", self.screenshot_dir)
            self._log(
                "warn",
                f"全流程v3: 首次选剧失败，已截图 {shot}，尝试强制重搜目标短剧",
            )
            if self._retry_reopen_target_from_main(ops, keyword, 1, task_total, task):
                drama_title = keyword
                selected = {"success": True, "drama_title": drama_title}
            else:
                raise RuntimeError(f"{selected.get('message') or '进入目标剧集失败'}，已截图 {shot}")

        wrong_collection = ops._mismatched_collection_title(keyword)
        if wrong_collection:
            shot = ops.take_screenshot("select_drama_wrong_collection", self.screenshot_dir)
            self._log(
                "warn",
                f"全流程v3: 进入错误合集，期望 {keyword}，实际 {wrong_collection}，已截图 {shot}，尝试强制重搜",
            )
            if self._retry_reopen_target_from_main(ops, keyword, 1, task_total, task):
                drama_title = keyword
            else:
                raise RuntimeError(
                    f"进入的合集与目标短剧不匹配: 期望 {keyword}，实际 {wrong_collection}，已截图 {shot}"
                )

        playback_speed = str(task.get("playback_speed") or "1.0x")
        if playback_speed != "1.0x":
            speed_set = ops.set_playback_speed(playback_speed)
            self._log("info" if speed_set else "warn", f"全流程v3: 倍速设置 {playback_speed} = {speed_set}")
            if not speed_set:
                raise RuntimeError(f"倍速设置失败: {playback_speed}")

        if ops.skip_ad_if_present():
            self._log("info", "全流程v3: 切第1集前检测到广告，已上滑继续观看")
            time.sleep(2)

        total_before = int(ops.get_total_episodes() or 0)
        if task_total and total_before and task_total != total_before:
            shot = ops.take_screenshot("select_drama_total_mismatch", self.screenshot_dir)
            self._log(
                "warn",
                f"全流程v3: 进入短剧总集数不匹配，期望 {task_total}，实际 {total_before}，已截图 {shot}，尝试重新进入目标短剧",
            )
            if self._recover_to_verified_episode(ops, task, 1, task_total, f"选剧后总集数不匹配，实际{total_before}"):
                total_before = task_total
            else:
                raise RuntimeError(
                    f"进入短剧总集数不匹配: 期望 {task_total}，实际 {total_before}，已截图 {shot}"
                )
        total_before = total_before or task_total
        self._log("info", f"全流程v3: 切换到第1集，当前识别总集数={total_before or 0}")
        pre_seek_xml = ops._xml()
        pre_seek_app = ops._safe_app_current()
        short_series_active = (
            pre_seek_app.get("package") == "com.phoenix.read"
            and pre_seek_app.get("activity") == "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity"
        )
        if not short_series_active and (ops._launcher_visible(pre_seek_xml) or not ops._is_app_foreground()):
            foreground = ops.bring_to_foreground()
            self._log("info" if foreground else "warn", f"全流程v3: 切第1集前拉回红果前台={foreground}")
        if not ops.play_episode(1):
            self._log("warn", "全流程v3: 第1集播放触发未确认，继续等待页面识别")
        if not self._wait_for_episode_verified(ops, task, 1, total_before, timeout=90):
            shot = ops.take_screenshot("ep1_play_failed", self.screenshot_dir)
            raise RuntimeError(f"首集播放失败，已截图 {shot}")

        state = self._page_state_with_empty_retry(ops, task)
        total = int(state.get("total_episodes") or total_before or task_total or 0)
        verified_total = int(total_before or task_total or total or 0)
        try:
            self._assert_target_playback(
                ops,
                task,
                state,
                verified_total,
                allow_unreadable_first_episode=True,
            )
        except RuntimeError as exc:
            if "非目标合集" not in str(exc):
                raise
            shot = ops.take_screenshot("select_drama_late_wrong_collection", self.screenshot_dir)
            self._log(
                "warn",
                f"全流程v3: 首集播放后延迟识别到错误合集，已截图 {shot}，尝试精确标题重搜",
            )
            if not self._retry_reopen_target_from_main(ops, keyword, 1, task_total, task):
                raise RuntimeError(f"{exc}，重搜目标短剧失败，已截图 {shot}") from exc
            state = self._page_state_with_empty_retry(ops, task)
            total = int(state.get("total_episodes") or total)
            self._assert_target_playback(
                ops,
                task,
                state,
                int(task_total or total or 0),
                allow_unreadable_first_episode=True,
            )
        return {
            "drama_title": drama_title,
            "total_episodes": total,
            "current_episode": int(state.get("current_episode") or 1),
        }

    @staticmethod
    def _is_ai_auth_error(message: str) -> bool:
        value = str(message or "").lower()
        return "401" in value or "invalid api key" in value or "invalid_key" in value

    @classmethod
    def _is_ai_non_retryable_error(cls, message: str) -> bool:
        value = str(message or "").lower()
        quota_exhausted = "429" in value and any(
            marker in value
            for marker in ("quota exhausted", "insufficient_quota", "limitation")
        )
        return cls._is_ai_auth_error(value) or quota_exhausted

    def _generate_comment_content(
        self,
        task: Dict[str, Any],
        drama_title: str,
        episode: int,
        avoid_contents: Optional[set[str]],
    ) -> tuple[str, str, Optional[Dict[str, Any]]]:
        generator = CommentGenerator(self._current_ai_config())
        requested_source = str(task.get("content_source") or "ai")
        if self._ai_comment_disabled_reason and requested_source in {"ai", "mixed"}:
            content = generator.generate_local_comment_excluding(drama_title, avoid_contents or set())
            self._log(
                "info",
                f"全流程v3: 第{episode}集AI服务已熔断，本任务直接使用本地评论",
            )
            return content, "local", {}

        content = ""
        source = ""
        usage: Optional[Dict[str, Any]] = None
        for _ in range(3):
            content, source, usage = generator.generate_with_usage(
                drama_title,
                requested_source,
                self._templates(task),
            )
            if not avoid_contents or content not in avoid_contents:
                break
        if avoid_contents and content in avoid_contents:
            content = generator.generate_local_comment_excluding(drama_title, avoid_contents)
            source = "local"
            usage = {}
            self._log("info", f"全流程v3: 第{episode}集AI评论重复，已改用本地去重内容")
        if source == "local" and requested_source in {"ai", "mixed"} and generator.last_error:
            fallback_error = re.sub(r"\s+", " ", generator.last_error).strip()[:300]
            non_retryable_error = self._is_ai_non_retryable_error(fallback_error)
            if non_retryable_error:
                self._ai_comment_disabled_reason = fallback_error
            suffix = "，本任务后续评论直接使用本地生成" if non_retryable_error else ""
            self._log(
                "warn",
                f"全流程v3: 第{episode}集AI评论生成失败，已回退本地评论，原因={fallback_error}{suffix}",
            )
        return content, source, usage

    def _handle_verified_comment(
        self,
        ops: HongguoOperations,
        task: Dict[str, Any],
        drama_title: str,
        episode: int,
        expected_total: int,
        count_sent: bool = True,
        avoid_contents: Optional[set[str]] = None,
    ) -> None:
        current = self._confirm_current_episode(ops, episode)
        if current != episode:
            self._log(
                "warn",
                f"全流程v3: 第{episode}集评论前强确认当前集={current or 0}，重新恢复评论目标集",
            )
            if not self._recover_to_verified_episode(
                ops,
                task,
                episode,
                expected_total,
                f"评论前当前集未确认或已漂移，实际={current or 0}",
            ):
                raise RuntimeError(f"第{episode}集评论前无法从当前集{current or 0}恢复目标集")

        paused = ops.pause_playback_if_playing()
        panel_ready = ops.prepare_comment_window(episode)
        self._log(
            "info" if panel_ready else "warn",
            f"全流程v3: 第{episode}集命中评论规则，暂停播放={paused}，评论面板={panel_ready}",
        )
        if not panel_ready:
            if not self._recover_to_verified_episode(
                ops,
                task,
                episode,
                expected_total,
                "评论前未能立即打开评论面板",
            ):
                raise RuntimeError(f"第{episode}集评论前无法恢复播放页")
            paused = ops.pause_playback_if_playing()
            panel_ready = ops.prepare_comment_window(episode)
            self._log(
                "info" if panel_ready else "warn",
                f"全流程v3: 第{episode}集恢复后准备评论，暂停播放={paused}，评论面板={panel_ready}",
            )
            if not panel_ready:
                current = self._confirm_current_episode(ops, episode)
                if current != episode:
                    self._log(
                        "warn",
                        f"全流程v3: 第{episode}集评论面板重试时当前集={current or 0}，再次恢复目标集",
                    )
                    recovered = self._recover_to_verified_episode(
                        ops,
                        task,
                        episode,
                        expected_total,
                        f"评论面板重试时当前集未确认或已漂移，实际={current or 0}",
                    )
                    confirmed = self._confirm_current_episode(ops, episode) if recovered else 0
                    if recovered and confirmed == episode:
                        paused = ops.pause_playback_if_playing()
                        panel_ready = ops.prepare_comment_window(episode)
                        self._log(
                            "info" if panel_ready else "warn",
                            f"全流程v3: 第{episode}集二次恢复后准备评论，当前集={confirmed or 0}，"
                            f"暂停播放={paused}，评论面板={panel_ready}",
                        )
                if panel_ready:
                    current = episode
                else:
                    current = self._confirm_current_episode(ops, episode)
            if not panel_ready:
                restarted = ops.restart_app()
                self._log(
                    "warn" if restarted else "error",
                    f"全流程v3: 第{episode}集评论按钮持续被遮挡，冷启动红果={restarted}",
                )
                recovered = restarted and self._recover_to_verified_episode(
                    ops,
                    task,
                    episode,
                    expected_total,
                    "评论按钮持续被奖励或直播透明层遮挡，冷启动后恢复",
                    allow_reopen=True,
                )
                if recovered:
                    paused = ops.pause_playback_if_playing()
                    panel_ready = ops.prepare_comment_window(episode)
                    current = self._confirm_current_episode(ops, episode)
                    self._log(
                        "info" if panel_ready else "warn",
                        f"全流程v3: 第{episode}集冷启动恢复后准备评论，当前集={current or 0}，"
                        f"暂停播放={paused}，评论面板={panel_ready}",
                    )
                    if not panel_ready and current != episode:
                        self._log(
                            "warn",
                            f"全流程v3: 第{episode}集冷启动评论重试时当前集={current or 0}，"
                            "最后一次恢复目标集",
                        )
                        recovered = self._recover_to_verified_episode(
                            ops,
                            task,
                            episode,
                            expected_total,
                            f"冷启动评论重试时当前集未确认或已漂移，实际={current or 0}",
                            allow_reopen=True,
                        )
                        confirmed = self._confirm_current_episode(ops, episode) if recovered else 0
                        if recovered and confirmed == episode:
                            paused = ops.pause_playback_if_playing()
                            panel_ready = ops.prepare_comment_window(episode)
                            current = self._confirm_current_episode(ops, episode)
                            self._log(
                                "info" if panel_ready else "warn",
                                f"全流程v3: 第{episode}集最终恢复后准备评论，当前集={current or 0}，"
                                f"暂停播放={paused}，评论面板={panel_ready}",
                            )
            if not panel_ready:
                failed_path = ops.take_screenshot(f"ep{episode}_comment_panel_open_failed", self.screenshot_dir)
                resumed = ops.resume_playback_safely()
                still_paused = ops.is_playback_paused()
                self._log(
                    "info" if not still_paused else "warn",
                    f"全流程v3: 第{episode}集评论面板打开失败，强确认当前集={current or 0}，截图 {failed_path}，"
                    f"退出前恢复播放={resumed}，仍暂停={still_paused}",
                )
                raise RuntimeError(f"第{episode}集评论面板打开失败，已截图 {failed_path}")

        content, source, usage = self._generate_comment_content(
            task,
            drama_title,
            episode,
            avoid_contents,
        )
        if usage:
            record_usage(usage, context=f"task:{self.task_id}:episode:{episode}")

        if episode:
            current = ops.get_current_episode()
            if current and current != episode:
                failed_path = ops.take_screenshot(f"ep{episode}_comment_missed", self.screenshot_dir)
                self._save_record(
                    episode,
                    content,
                    source,
                    "failed",
                    failed_path,
                    failed_path,
                    f"评论前已播放到第{current}集，取消第{episode}集评论发布",
                )
                self._log("error", f"全流程v3: 第{episode}集评论窗口已错过，当前第{current}集，取消发布")
                self._restore_playback_after_comment(ops, task, current, expected_total)
                return

        self._log("info", f"全流程v3: 第{episode}集评论内容已生成，来源={source or 'unknown'}，准备评论")
        input_path = ops.take_screenshot(f"ep{episode}_before_comment", self.screenshot_dir)
        post = ops.post_comment(content, episode)
        if not post.get("success"):
            failed_path = ops.take_screenshot(f"ep{episode}_post_failed", self.screenshot_dir)
            self._save_record(episode, content, source, "failed", input_path, failed_path, post.get("message") or "评论发送失败")
            self._log("error", f"全流程v3: 第{episode}集评论发送失败 - {post.get('message')}")
            try:
                self._restore_playback_after_comment(ops, task, episode, expected_total)
            except RuntimeError as exc:
                self._log("warn", f"全流程v3: 第{episode}集评论失败后恢复播放异常: {exc}")
            return

        sent_at = datetime.now()
        try:
            sent_path = ops.take_screenshot(f"ep{episode}_comment_sent", self.screenshot_dir)
        except Exception:
            sent_path = ""
        if count_sent:
            self._increment_counter("sent")
        verify = self._verify_comment_with_retry(ops, task, content, episode, expected_total)
        if not verify.get("verified"):
            self._log("warn", f"全流程v3: 第{episode}集评论验证仍未通过，准备回到目标集重发一次")
            try:
                if self._recover_to_verified_episode(ops, task, episode, expected_total, "评论验证失败后重发"):
                    self._log("info", f"全流程v3: 第{episode}集重发前等待评论列表同步并再次验证")
                    time.sleep(4)
                    delayed_verify = ops.verify_comment(content, episode, self.screenshot_dir)
                    if delayed_verify.get("verified"):
                        verify = delayed_verify
                        self._log("info", f"全流程v3: 第{episode}集重发前延迟验证成功，取消重发")
                    else:
                        self._log("warn", f"全流程v3: 第{episode}集重发前仍未找到评论，执行第2次发送")
                        retry_post = ops.post_comment(content, episode)
                        if retry_post.get("success"):
                            verify = self._verify_comment_with_retry(ops, task, content, episode, expected_total)
                        else:
                            self._log("warn", f"全流程v3: 第{episode}集评论重发失败 - {retry_post.get('message')}")
                else:
                    self._log("warn", f"全流程v3: 第{episode}集评论重发前恢复目标集失败")
            except Exception as exc:
                self._log("warn", f"全流程v3: 第{episode}集评论重发异常: {exc}")
        verify_path = verify.get("screenshot_path") or ops.take_screenshot(
            f"ep{episode}_{'verified' if verify.get('verified') else 'not_found'}",
            self.screenshot_dir,
        )
        status = "success" if verify.get("verified") else "failed"
        error = None if verify.get("verified") else verify.get("message", "评论验证失败")
        verified_at = datetime.now() if verify.get("verified") else None
        self._save_record(
            episode,
            content,
            source,
            status,
            input_path,
            verify_path,
            error,
            screenshot_sent=sent_path,
            sent_at=sent_at,
            verified_at=verified_at,
        )
        if status == "success":
            self._increment_counter("verified")
        self._log(
            "info" if status == "success" else "error",
            f"全流程v3: 第{episode}集评论{'验证成功' if status == 'success' else '验证失败'}，截图 {verify_path}",
        )

        self._restore_playback_after_comment(ops, task, episode, expected_total)

    def _retry_missing_comments_before_completion(
        self,
        ops: HongguoOperations,
        task: Dict[str, Any],
        drama_title: str,
        expected_total: int,
        missing_comments: Iterable[int],
    ) -> List[int]:
        for episode in sorted(set(int(value) for value in missing_comments)):
            self._check_pause_stop()
            if self._comment_already_verified(episode):
                continue
            if not self._recover_to_verified_episode(
                ops,
                task,
                episode,
                expected_total,
                "整剧结束前补偿未验证评论",
            ):
                self._log("error", f"全流程v3: 第{episode}集最终补偿前无法恢复目标集")
                continue
            avoid_contents = self._comment_contents_for_episode(episode)
            try:
                self._handle_verified_comment(
                    ops,
                    task,
                    drama_title,
                    episode,
                    expected_total,
                    count_sent=False,
                    avoid_contents=avoid_contents,
                )
            except Exception as exc:
                self._log("error", f"全流程v3: 第{episode}集最终补偿异常: {exc}")
        return self._missing_verified_comment_episodes(missing_comments)

    def _comment_contents_for_episode(self, episode: int) -> set[str]:
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT comment_text
                        FROM hongguo_comment_records
                        WHERE task_id=%s AND episode_number=%s
                        """,
                        (self.task_id, episode),
                    )
                    return {
                        str(row.get("comment_text") or "").strip()
                        for row in cur.fetchall() or []
                        if str(row.get("comment_text") or "").strip()
                    }
        except Exception:
            return set()

    def _comment_contents_for_batch(self) -> set[str]:
        """Collect comment text already used by this multi-device batch."""
        try:
            task = self._load_task() or {}
            multi_run_id = str(task.get("multi_run_id") or "").strip()
            with self._connection() as conn:
                with conn.cursor() as cur:
                    if multi_run_id:
                        cur.execute(
                            """
                            SELECT record.comment_text
                            FROM hongguo_comment_records AS record
                            JOIN hongguo_comment_tasks AS task ON task.id=record.task_id
                            WHERE task.multi_run_id=%s
                              AND record.comment_text IS NOT NULL
                              AND TRIM(record.comment_text) <> ''
                            """,
                            (multi_run_id,),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT comment_text
                            FROM hongguo_comment_records
                            WHERE task_id=%s
                              AND comment_text IS NOT NULL
                              AND TRIM(comment_text) <> ''
                            """,
                            (self.task_id,),
                        )
                    return {
                        str(row.get("comment_text") or "").strip()
                        for row in cur.fetchall() or []
                        if str(row.get("comment_text") or "").strip()
                    }
        except Exception:
            return set()

    def _verify_comment_with_retry(
        self,
        ops: HongguoOperations,
        task: Dict[str, Any],
        content: str,
        episode: int,
        expected_total: int,
    ) -> Dict[str, Any]:
        verify = ops.verify_comment(content, episode, self.screenshot_dir)
        if verify.get("verified"):
            return verify
        self._log(
            "warn",
            f"全流程v3: 第{episode}集评论首次验证失败 - {verify.get('message') or '未找到评论内容'}，准备恢复播放页后重试",
        )
        try:
            if not ops.ensure_playback_page(episode):
                self._recover_to_verified_episode(ops, task, episode, expected_total, "评论验证前未回到目标播放页")
            time.sleep(2)
            retry = ops.verify_comment(content, episode, self.screenshot_dir)
            if retry.get("verified"):
                self._log("info", f"全流程v3: 第{episode}集评论二次验证成功")
                return retry
            if retry.get("screenshot_path"):
                return retry
        except Exception as exc:
            self._log("warn", f"全流程v3: 第{episode}集评论二次验证异常: {exc}")
        return verify

    def _wait_for_episode_verified(
        self,
        ops: HongguoOperations,
        task: Dict[str, Any],
        target: int,
        expected_total: int,
        timeout: int = 60,
        allow_reopen: bool = True,
    ) -> bool:
        deadline = time.time() + max(20, timeout)
        last_log_at = 0.0
        reseek_attempts = 0
        max_reseek_attempts = 8
        stable_target_confirmations = 0
        unreadable_state_recovery_attempted = False
        while time.time() < deadline:
            self._check_pause_stop()
            state = self._page_state(ops, task)
            app = state.get("app") or {}
            current = int(state.get("current_episode") or 0)
            if (
                not app.get("package")
                and not state.get("first_visible_package")
                and not state.get("launcher_visible")
                and not state.get("playback_visible")
            ):
                if not unreadable_state_recovery_attempted:
                    unreadable_state_recovery_attempted = True
                    restart_uiautomator = getattr(ops, "_restart_uiautomator_server", None)
                    restarted = False
                    if callable(restart_uiautomator):
                        try:
                            restarted = bool(restart_uiautomator())
                        except Exception as exc:
                            self._log(
                                "warn",
                                f"全流程v3: 切第{target}集时自动化服务恢复异常: {exc}",
                            )
                    self._log(
                        "info" if restarted else "warn",
                        f"全流程v3: 切第{target}集时页面状态完全不可读，重启自动化服务={restarted}",
                    )
                    if restarted:
                        time.sleep(2)
                        continue
                now = time.time()
                if now - last_log_at >= 10:
                    self._log("warn", f"全流程v3: 切第{target}集时页面状态暂不可读，继续重试")
                    last_log_at = now
                time.sleep(2)
                continue
            if not self._has_playback_context(state):
                if self._restore_foreground_if_needed(ops, target):
                    time.sleep(2)
                    continue
                shot = self._take_diagnostic_screenshot(ops, f"seek_ep{target}_playback_context_failed")
                raise RuntimeError(
                    f"切第{target}集失败: {self._playback_state_summary(state)}，截图={shot or '失败'}"
                )
            # LiveLite is an app activity, not a skippable in-player ad. Handle
            # it immediately even when visual ad detection is also positive.
            if state.get("ad_visible") and app.get("activity") != LIVE_LITE_ACTIVITY:
                if getattr(ops, "_ad_swipe_pending", False) is True:
                    now = time.time()
                    if now - last_log_at >= 30:
                        self._log(
                            "info",
                            f"全流程v3: 切第{target}集时广告仍在展示，已执行单次上滑，继续等待",
                        )
                        last_log_at = now
                    time.sleep(3)
                    continue
                shot = ops.take_screenshot(f"seek_ep{target}_ad", self.screenshot_dir)
                skipped = ops.skip_ad_if_present()
                deadline = max(deadline, time.time() + 45)
                self._log(
                    "info" if skipped else "warn",
                    f"全流程v3: 切第{target}集时遇到广告，已截图 {shot}，跳过广告={skipped}",
                )
                last_log_at = time.time()
                if not skipped:
                    ad_state = self._page_state(ops, task)
                    ad_current = int(ad_state.get("current_episode") or 0)
                    ad_total = int(ad_state.get("total_episodes") or 0)
                    if self._total_mismatch_is_fatal(
                        ops,
                        task,
                        ad_state,
                        expected_total,
                        ad_total,
                        current=ad_current,
                        target=target,
                    ):
                        self._log(
                            "warn",
                            f"全流程v3: 切第{target}集时广告跳过失败且总集数不匹配，期望 {expected_total}，实际 {ad_total}，尝试重新进入目标短剧",
                        )
                        if allow_reopen and self._recover_to_verified_episode(
                            ops,
                            task,
                            target,
                            expected_total,
                            f"切集广告跳过失败后总集数不匹配，实际{ad_total}",
                            allow_reopen=True,
                        ):
                            return True
                time.sleep(3)
                continue
            if app.get("activity") and app.get("activity") != "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity":
                activity = app.get("activity") or "-"
                self._log("warn", f"全流程v3: 切第{target}集时离开播放页，当前 activity={activity}，尝试恢复")
                if self._recover_to_verified_episode(ops, task, target, expected_total, f"切集确认离开播放页 {activity}", allow_reopen=allow_reopen):
                    return True
                if not allow_reopen:
                    time.sleep(2)
                    continue
                raise RuntimeError(f"切集时未停留在短剧播放页，当前 activity={activity}")
            total = int(state.get("total_episodes") or 0)
            if self._total_mismatch_is_fatal(ops, task, state, expected_total, total, current=current, target=target):
                shot = ops.take_screenshot(f"seek_ep{target}_total_mismatch", self.screenshot_dir)
                self._log(
                    "warn",
                    f"全流程v3: 切第{target}集时总集数不匹配，期望 {expected_total}，实际 {total}，截图 {shot}",
                )
                if allow_reopen and self._recover_to_verified_episode(
                    ops,
                    task,
                    target,
                    expected_total,
                    f"切集总集数不匹配，实际{total}",
                    allow_reopen=True,
                ):
                    return True
                raise RuntimeError(f"切集时短剧总集数不匹配: 期望 {expected_total}，实际 {total}")
            if current == target:
                if self._pause_pending_action_episode(ops, task, target, state):
                    return True
                stable_target_confirmations += 1
                if stable_target_confirmations >= 2:
                    return True
                time.sleep(2)
                continue
            stable_target_confirmations = 0
            if current > target and not self._pending_comment_episodes_between(task, target, current):
                self._log(
                    "info",
                    f"全流程v3: 确认第{target}集时已自然播放到第{current}集，区间无待评论任务，顺延观察",
                )
                return True
            if current > target and reseek_attempts < max_reseek_attempts:
                reseek_attempts += 1
                replayed = ops.play_episode(target)
                if replayed and self._pause_pending_action_episode(ops, task, target):
                    return True
                deadline = max(deadline, time.time() + 45)
                self._log(
                    "warn",
                    f"全流程v3: 确认第{target}集时已自动播放到第{current}集，"
                    f"重新切回目标集，尝试{reseek_attempts}/{max_reseek_attempts}，切集={replayed}",
                )
                time.sleep(3)
                continue
            safe_playback: Optional[bool] = None
            if target == 1 and not current:
                safe_playback = self._safe_resume_playback(ops, target, "首集Surface确认中")
            if (
                target == 1
                and not current
                and app.get("activity") == "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity"
                and bool(state.get("playback_visible") or safe_playback)
                and not state.get("ad_visible")
                and (not expected_total or not total or total == expected_total)
            ):
                self._log(
                    "info",
                    "全流程v3: Surface播放页确认正常，按显式切集结果确认第1集",
                )
                return True
            now = time.time()
            if now - last_log_at >= 10:
                self._log("info", f"全流程v3: 正在确认第{target}集，当前识别第{current or 0}集")
                last_log_at = now
            if safe_playback is None:
                self._safe_resume_playback(ops, current or target, "切集确认中")
            time.sleep(2)
        return False

    def _wait_for_next_episode_verified(
        self,
        ops: HongguoOperations,
        task: Dict[str, Any],
        episode: int,
        target: int,
        expected_total: int,
    ) -> bool:
        deadline = time.time() + max(900, int(task.get("comment_interval_sec") or 30) + 600)
        last_log_at = 0.0
        same_episode_since = 0.0
        forced_target = False
        stale_recovered = False
        stale_observe_path = ""
        stale_observe_at = 0.0
        freeze_recovery_attempted = False
        post_comment_play_nudged = False
        unreadable_since = 0.0
        last_episode_probe_at = 0.0
        while time.time() < deadline:
            self._check_pause_stop()
            state = self._page_state(ops, task)
            app = state.get("app") or {}
            current = int(state.get("current_episode") or 0)

            if not self._has_playback_context(state):
                if self._restore_foreground_if_needed(ops, episode):
                    time.sleep(2)
                    restored_state = self._page_state(ops, task)
                    restored_app = restored_state.get("app") or {}
                    restored_current = int(restored_state.get("current_episode") or 0)
                    restored_total = int(restored_state.get("total_episodes") or 0)
                    restored_wrong_collection = bool(
                        restored_app.get("activity") == SHORT_SERIES_ACTIVITY
                        and self._has_playback_context(restored_state)
                        and self._total_mismatch_is_fatal(
                            ops,
                            task,
                            restored_state,
                            expected_total,
                            restored_total,
                            current=restored_current,
                            target=target,
                        )
                    )
                    if restored_wrong_collection:
                        self._log(
                            "warn",
                            f"全流程v3: 拉回前台后检测到错误合集，总集数={restored_total}，直接重新搜索目标短剧",
                        )
                        if self._reopen_target_episode(ops, task, target, expected_total):
                            return True
                        continue
                    restored_playback = (
                        restored_app.get("activity") == SHORT_SERIES_ACTIVITY
                        and self._has_playback_context(restored_state)
                        and not restored_wrong_collection
                    )
                    if restored_playback and restored_current == target:
                        self._pause_pending_action_episode(ops, task, target, restored_state)
                        self._log("info", f"全流程v3: 拉回红果前台后已进入第{target}集")
                        return True
                    if restored_playback and restored_current in (0, episode):
                        advanced = bool(ops.play_episode(target))
                        self._log(
                            "info" if advanced else "warn",
                            f"全流程v3: 拉回红果前台后直接切换第{target}集={advanced}",
                        )
                        if advanced:
                            self._pause_pending_action_episode(ops, task, target)
                            return True
                    if (
                        restored_playback
                        and restored_current > target
                        and not self._pending_comment_episodes_between(task, target, restored_current)
                    ):
                        self._log(
                            "info",
                            f"全流程v3: 拉回红果前台后已播放到第{restored_current}集，"
                            f"第{target}-{restored_current - 1}集无待评论任务，顺延观察",
                        )
                        return True
                    if self._recover_to_verified_episode(
                        ops,
                        task,
                        target,
                        expected_total,
                        f"第{episode}集后红果不在前台，当前 package={app.get('package') or '-'}",
                    ):
                        return True
                    continue
                if self._recover_to_verified_episode(
                    ops,
                    task,
                    target,
                    expected_total,
                    f"第{episode}集后红果不在前台，当前 package={app.get('package') or '-'}",
                ):
                    return True
                raise RuntimeError(f"第{episode}集后红果不在前台，当前 package={app.get('package') or '-'}")
            if state.get("ad_visible") and app.get("activity") != LIVE_LITE_ACTIVITY:
                if getattr(ops, "_ad_swipe_pending", False) is True:
                    now = time.time()
                    if now - last_log_at >= 30:
                        self._log(
                            "info",
                            f"全流程v3: 第{episode}集后广告仍在展示，已执行单次上滑，继续等待",
                        )
                        last_log_at = now
                    time.sleep(3)
                    continue
                shot = ops.take_screenshot(f"ep{episode}_ad", self.screenshot_dir)
                skipped = ops.skip_ad_if_present()
                self._log(
                    "info" if skipped else "warn",
                    f"全流程v3: 第{episode}集后出现广告，已截图 {shot}，跳过广告={skipped}",
                )
                last_log_at = time.time()
                time.sleep(3)
                continue
            if app.get("activity") and app.get("activity") != SHORT_SERIES_ACTIVITY:
                activity = str(app.get("activity") or "")
                if activity == LIVE_LITE_ACTIVITY:
                    self._log(
                        "warn",
                        f"全流程v3: 第{episode}集后检测到红果内部直播页，先关闭直播页再确认第{target}集",
                    )
                    close_live_lite = getattr(ops, "_close_live_lite_page", None)
                    closed = bool(close_live_lite()) if callable(close_live_lite) else False
                    self._log(
                        "info" if closed else "warn",
                        f"全流程v3: 第{episode}集后关闭红果内部直播页={closed}",
                    )
                    if closed:
                        time.sleep(1)
                        restored_state = self._page_state(ops, task)
                        restored_app = restored_state.get("app") or {}
                        restored_activity = str(restored_app.get("activity") or "")
                        restored_current = int(restored_state.get("current_episode") or 0)
                        if restored_activity == SHORT_SERIES_ACTIVITY and self._has_playback_context(restored_state):
                            if restored_current == target:
                                self._pause_pending_action_episode(ops, task, target, restored_state)
                                self._log("info", f"全流程v3: 关闭红果内部直播页后已进入第{target}集")
                                return True
                            if restored_current in (0, episode):
                                advanced = bool(ops.play_episode(target))
                                self._log(
                                    "info" if advanced else "warn",
                                    f"全流程v3: 关闭红果内部直播页后回到第{restored_current or episode}集，"
                                    f"主动切换第{target}集={advanced}",
                                )
                                if not advanced:
                                    resume = getattr(ops, "resume_playback_safely", None)
                                    resumed = bool(resume()) if callable(resume) else False
                                    self._log(
                                        "info" if resumed else "warn",
                                        f"全流程v3: 直播页关闭后目标集直切未确认，先恢复上一集播放={resumed}，"
                                        f"再次尝试第{target}集",
                                    )
                                    time.sleep(1)
                                    advanced = bool(ops.play_episode(target))
                                    self._log(
                                        "info" if advanced else "warn",
                                        f"全流程v3: 直播页关闭后第二次主动切换第{target}集={advanced}",
                                    )
                                if advanced:
                                    self._pause_pending_action_episode(ops, task, target)
                                    return True
                                if self._recover_to_verified_episode(
                                    ops,
                                    task,
                                    target,
                                    expected_total,
                                    f"第{episode}集后直播页反复拦截自动连播",
                                ):
                                    return True
                                raise RuntimeError(
                                    f"第{episode}集后关闭红果内部直播页，但无法切换到第{target}集"
                                )
                            if restored_current > target and not self._pending_comment_episodes_between(
                                task,
                                target,
                                restored_current,
                            ):
                                self._log(
                                    "info",
                                    f"全流程v3: 关闭红果内部直播页后已播放到第{restored_current}集，"
                                    f"第{target}-{restored_current - 1}集无待评论任务，顺延观察",
                                )
                                return True
                            self._log(
                                "warn",
                                f"全流程v3: 关闭红果内部直播页后识别为第{restored_current or 0}集，"
                                f"需要恢复目标第{target}集",
                            )
                        else:
                            self._log(
                                "warn",
                                f"全流程v3: 关闭红果内部直播页后未回到短剧播放页，"
                                f"当前 activity={restored_activity or '-'}",
                            )
                total = int(state.get("total_episodes") or 0)
                if self._recover_to_verified_episode(
                    ops,
                    task,
                    target,
                    expected_total,
                    (
                        f"第{episode}集后红果内部直播页未能恢复目标播放"
                        if activity == LIVE_LITE_ACTIVITY
                        else f"第{episode}集后离开播放页，当前 activity={activity or '-'}"
                    ),
                ):
                    return True
                raise RuntimeError(
                    f"第{episode}集后已离开目标短剧播放页，当前 activity={app.get('activity') or '-'}，识别总集数={total or 0}"
                )
            total = int(state.get("total_episodes") or 0)
            if current == 0 and total == 0:
                if not state.get("playback_visible"):
                    if self._recover_to_verified_episode(
                        ops,
                        task,
                        target,
                        expected_total,
                        f"第{episode}集后集数不可见且播放页不可见，当前 activity={app.get('activity') or '-'}",
                    ):
                        return True
                    self._log(
                        "warn",
                        f"全流程v3: 第{episode}集后未识别到播放页或集数，等待前台恢复，不执行上滑",
                    )
                    time.sleep(3)
                    continue
                now = time.time()
                if unreadable_since <= 0:
                    unreadable_since = now
                if now - unreadable_since >= 45 and now - last_episode_probe_at >= 45:
                    confirmed = self._confirm_current_episode(ops, target)
                    last_episode_probe_at = now
                    if confirmed > 0:
                        current = confirmed
                        total = expected_total
                        state["current_episode"] = confirmed
                        state["total_episodes"] = expected_total
                        self._update_task(current_episode=confirmed, updated_at=datetime.now())
                        self._log(
                            "warn",
                            f"全流程v3: 第{episode}集后集数长时间不可见，强确认实际为第{confirmed}集，已纠正执行进度",
                        )
                    else:
                        self._log(
                            "warn",
                            f"全流程v3: 第{episode}集后集数长时间不可见，强制显示控件后仍无法读取，继续观察",
                        )
                if current > 0:
                    pass
                else:
                    paused = bool(state.get("playback_paused"))
                    if paused:
                        self._safe_resume_playback(ops, episode, "播放页集数暂不可见，检测到暂停")
                    elif time.time() - last_log_at >= 20:
                        self._log("info", f"全流程v3: 第{episode}集播放页集数暂不可见，继续观察，不执行上滑")
                        last_log_at = time.time()
                    time.sleep(2)
                    continue
            else:
                unreadable_since = 0.0
            if self._total_mismatch_is_fatal(ops, task, state, expected_total, total, current=current, target=target):
                self._log(
                    "warn",
                    f"全流程v3: 第{episode}集后疑似跳到其他短剧，期望总集数{expected_total}，"
                    f"实际{total}，尝试恢复目标第{target}集",
                )
                if self._recover_to_verified_episode(
                    ops,
                    task,
                    target,
                    expected_total,
                    f"第{episode}集后总集数变为{total}",
                ):
                    return True
                raise RuntimeError(f"第{episode}集后跳到其他短剧: 期望总集数 {expected_total}，实际 {total}")

            if current == target:
                self._pause_pending_action_episode(ops, task, target, state)
                self._log("info", f"全流程v3: 已自动进入第{target}集")
                return True
            if current == episode:
                now = time.time()
                if same_episode_since <= 0:
                    same_episode_since = now
                comment_recovered_at = self._comment_recovered_at.get(int(episode), 0.0)
                after_comment = bool(comment_recovered_at and now - comment_recovered_at < 420)
                log_interval = 30
                soft_recover_after = 30
                observe_after = 60 if after_comment else 180
                paused = bool(state.get("playback_paused"))
                normal_playing = bool(state.get("playback_visible")) and not paused and not state.get("ad_visible")
                if (
                    after_comment
                    and not post_comment_play_nudged
                    and now - same_episode_since >= soft_recover_after
                ):
                    resumed = bool(ops.resume_playback_safely())
                    post_comment_play_nudged = True
                    self._log(
                        "info",
                        f"全流程v3: 第{episode}集评论后停留超过{soft_recover_after}秒，"
                        f"主动发送播放命令={resumed}",
                    )
                if now - last_log_at >= log_interval:
                    if paused or not normal_playing:
                        self._log("info", f"全流程v3: 仍在第{episode}集，等待自动播放第{target}集")
                        self._safe_resume_playback(ops, episode, "仍停留当前集，检查是否暂停")
                    else:
                        self._log("info", f"全流程v3: 第{episode}集仍在正常播放，继续等待自然进入第{target}集")
                    last_log_at = now
                if after_comment and not stale_recovered and now - same_episode_since >= soft_recover_after and not normal_playing:
                    shot = ops.take_screenshot(f"ep{episode}_after_comment_stale_observe", self.screenshot_dir)
                    recovered = self._safe_resume_playback(ops, episode, "评论后仍停留当前集，继续等待自然播放")
                    self._log(
                        "info",
                        f"全流程v3: 第{episode}集评论后停留超过{soft_recover_after}秒，已截图 {shot}，恢复播放={recovered}，继续等待第{target}集",
                    )
                    stale_recovered = True
                    last_log_at = now
                if not stale_recovered and now - same_episode_since >= observe_after:
                    shot = ops.take_screenshot(f"ep{episode}_stale_observe", self.screenshot_dir)
                    stale_observe_path = shot
                    stale_observe_at = now
                    if normal_playing:
                        self._log(
                            "info",
                            f"全流程v3: 第{episode}集已正常播放超过{observe_after}秒，已截图 {shot}，继续等待自然进入第{target}集",
                        )
                    else:
                        recovered = self._safe_resume_playback(ops, episode, "停留当前集超过观察阈值，尝试恢复播放")
                        self._log(
                            "warn",
                            f"全流程v3: 第{episode}集停留超过{observe_after}秒，已截图 {shot}，恢复播放={recovered}，继续等待第{target}集",
                        )
                    stale_recovered = True
                    last_log_at = now
                if (
                    bool(state.get("playback_visible"))
                    and not state.get("ad_visible")
                    and stale_observe_path
                    and not freeze_recovery_attempted
                    and now - stale_observe_at >= (30 if after_comment else 90)
                ):
                    freeze_confirm_after = 30 if after_comment else 90
                    confirm_shot = ops.take_screenshot(f"ep{episode}_stale_confirm", self.screenshot_dir)
                    if self._video_frames_are_static(stale_observe_path, confirm_shot):
                        freeze_recovery_attempted = True
                        recovered = bool(ops.play_episode(target))
                        if not recovered:
                            recovered = self._recover_to_verified_episode(
                                ops,
                                task,
                                target,
                                expected_total,
                                f"第{episode}集视频画面持续静止",
                            )
                        self._log(
                            "warn",
                            f"全流程v3: 第{episode}集视频区域连续{freeze_confirm_after}秒静止，截图 {confirm_shot}，"
                            f"恢复目标第{target}集={recovered}",
                        )
                        if recovered:
                            return True
                    else:
                        stale_observe_path = confirm_shot
                        stale_observe_at = now
            elif current == 0:
                now = time.time()
                same_episode_since = 0.0
                stale_recovered = False
                stale_observe_path = ""
                stale_observe_at = 0.0
                freeze_recovery_attempted = False
                post_comment_play_nudged = False
                if getattr(ops, "_episode_list_panel_open", lambda: False)():
                    closed = getattr(ops, "_close_episode_list_panel", lambda _episode=0: False)(target)
                    self._log(
                        "info" if closed else "warn",
                        f"全流程v3: 第{episode}集后停留在选集页，尝试收回并确认第{target}集={closed}",
                    )
                    if closed:
                        time.sleep(2)
                        continue
                if now - last_log_at >= 20:
                    self._log("warn", f"全流程v3: 第{episode}集后暂未识别到集数，继续观察播放页")
                    self._safe_resume_playback(ops, episode, "集数暂未识别，检查是否暂停")
                    last_log_at = now
            else:
                same_episode_since = 0.0
                stale_recovered = False
                stale_observe_path = ""
                stale_observe_at = 0.0
                freeze_recovery_attempted = False
                post_comment_play_nudged = False
            if current > target:
                pending_comments = self._pending_comment_episodes_between(task, target, current)
                if not pending_comments:
                    self._log(
                        "info",
                        f"全流程v3: 已自动跨到第{current}集，第{target}-{current - 1}集无待评论任务，顺延观察",
                    )
                    return True
                self._log(
                    "warn",
                    f"全流程v3: 已跳过目标第{target}集，当前第{current}集，"
                    f"区间内待评论集数={pending_comments}，尝试切回目标集",
                )
                if self._recover_to_verified_episode(ops, task, target, expected_total, f"自动跳过目标集，当前第{current}集"):
                    return True
                raise RuntimeError(f"跳过目标集: 目标第{target}集，当前第{current}集")
            if current and current < episode:
                raise RuntimeError(f"回退异常: 上一集第{episode}集，当前第{current}集")
            time.sleep(2)
        # The episode marker can update immediately after the deadline. Confirm
        # once more before turning a successful transition into a task failure.
        time.sleep(2)
        final_state = self._page_state(ops, task)
        final_current = int(final_state.get("current_episode") or 0)
        if final_current <= 0 and final_state.get("playback_visible"):
            final_current = self._confirm_current_episode(ops, target)
            if final_current > 0:
                final_state["current_episode"] = final_current
                final_state["total_episodes"] = expected_total
                self._update_task(current_episode=final_current, updated_at=datetime.now())
                self._log(
                    "warn",
                    f"全流程v3: 第{episode}集后超时前强确认实际为第{final_current}集，已纠正执行进度",
                )
        final_total = int(final_state.get("total_episodes") or 0)
        if final_current == target and not self._total_mismatch_is_fatal(
            ops,
            task,
            final_state,
            expected_total,
            final_total,
            current=final_current,
            target=target,
        ):
            self._log("info", f"全流程v3: 超时后二次确认已进入第{target}集")
            return True
        if final_current > target:
            pending_comments = self._pending_comment_episodes_between(task, target, final_current)
            if not pending_comments:
                self._log(
                    "info",
                    f"全流程v3: 超时前强确认已播放到第{final_current}集，"
                    f"第{target}-{final_current - 1}集无待评论任务，顺延观察",
                )
                return True
            self._log(
                "warn",
                f"全流程v3: 超时前强确认已播放到第{final_current}集，"
                f"区间待评论集数={pending_comments}，恢复第{target}集",
            )
            return self._recover_to_verified_episode(
                ops,
                task,
                target,
                expected_total,
                f"超时前发现实际已到第{final_current}集",
            )
        return False

    @staticmethod
    def _confirm_current_episode(ops: HongguoOperations, expected_episode: int = 0) -> int:
        probe = getattr(ops, "confirm_current_episode", None)
        if callable(probe):
            try:
                current = probe(expected_episode=expected_episode)
                if isinstance(current, (int, float, str)) and str(current).isdigit():
                    return int(current)
            except Exception:
                pass
        try:
            current = ops.get_current_episode()
            if isinstance(current, (int, float, str)) and str(current).isdigit():
                return int(current)
        except Exception:
            pass
        return 0

    def _pending_comment_episodes_between(
        self,
        task: Dict[str, Any],
        start_episode: int,
        end_episode: int,
    ) -> List[int]:
        try:
            plan = json.loads(task.get("execution_plan_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            plan = {}
        planned_comments = {
            int(value)
            for value in plan.get("comment_episodes") or []
            if str(value).isdigit()
        }
        planned_engagements: set[int] = set()
        for action, key in (("like", "like_episodes"), ("favorite", "favorite_episodes")):
            planned_engagements.update(
                int(value)
                for value in plan.get(key) or []
                if str(value).isdigit()
                and int(value) not in self._completed_engagement_episodes[action]
            )
        planned = sorted(
            {
                *planned_engagements,
                *(
                    episode
                    for episode in planned_comments
                    if not self._comment_already_verified(episode)
                ),
            }
        )
        return [
            episode
            for episode in planned
            if start_episode <= episode < end_episode
        ]

    def _pause_pending_action_episode(
        self,
        ops: HongguoOperations,
        task: Dict[str, Any],
        episode: int,
        state: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not self._pending_comment_episodes_between(task, episode, episode + 1):
            return False
        if state and state.get("playback_paused"):
            return True
        pause = getattr(ops, "pause_playback_quickly", None)
        paused = bool(pause()) if callable(pause) else False
        self._log(
            "info" if paused else "warn",
            f"全流程v3: 第{episode}集命中待执行评论或互动，立即暂停={paused}",
        )
        return paused

    def _recover_to_verified_episode(
        self,
        ops: HongguoOperations,
        task: Dict[str, Any],
        target: int,
        expected_total: int,
        reason: str,
        allow_reopen: bool = True,
    ) -> bool:
        self._log("warn", f"全流程v3: 恢复目标第{target}集，原因={reason}")
        regular_deadline = time.monotonic() + REGULAR_RECOVERY_BUDGET_SECONDS
        for attempt in range(2):
            self._check_pause_stop()
            if time.monotonic() >= regular_deadline:
                self._log("warn", f"全流程v3: 常规恢复第{target}集已用尽90秒总预算，转为重新搜索")
                break
            if self._skip_ad_if_present(ops):
                self._log("info", f"全流程v3: 恢复第{target}集前检测到广告，已上滑继续观看")
                time.sleep(2)
            try:
                if ops.ensure_playback_page(target):
                    remaining = regular_deadline - time.monotonic()
                    if remaining < 20:
                        self._log("warn", f"全流程v3: 常规恢复第{target}集剩余预算不足20秒，转为重新搜索")
                        break
                    if self._wait_for_episode_verified(
                        ops,
                        task,
                        target,
                        expected_total,
                        timeout=min(45, int(remaining)),
                        allow_reopen=False,
                    ):
                        confirmed = self._confirm_current_episode(ops, target)
                        if confirmed == target:
                            self._log("info", f"全流程v3: 已恢复到第{target}集")
                            return True
                        self._log(
                            "warn",
                            f"全流程v3: 第{target}集恢复校验曾成功，但强确认当前集={confirmed or 0}，继续恢复",
                        )
            except RuntimeError as exc:
                self._log("warn", f"全流程v3: 常规恢复第{target}集失败: {exc}")
                if any(marker in str(exc) for marker in ("总集数不匹配", "非目标合集")):
                    self._log(
                        "info",
                        f"全流程v3: 第{target}集已确认是错误合集，跳过重复常规恢复并重新搜索",
                    )
                    break
            if attempt == 0:
                if regular_deadline - time.monotonic() <= 2:
                    self._log("warn", f"全流程v3: 常规恢复第{target}集总预算即将耗尽，转为重新搜索")
                    break
                time.sleep(2)

        if not allow_reopen:
            self._log("warn", f"全流程v3: 常规恢复第{target}集失败，当前上下文禁止重新搜索")
            return False

        for reopen_attempt in range(3):
            prefer_exact_title = reopen_attempt != 1
            reopened = self._reopen_target_episode(
                ops,
                task,
                target,
                expected_total,
                prefer_exact_title=prefer_exact_title,
            )
            if reopened:
                confirmed = self._confirm_current_episode(ops, target)
                if confirmed == target:
                    self._log(
                        "info",
                        f"全流程v3: 第{reopen_attempt + 1}轮重新进入短剧后已恢复到第{target}集",
                    )
                    return True
                self._log(
                    "warn",
                    f"全流程v3: 第{reopen_attempt + 1}轮重新进入短剧后强确认当前集={confirmed or 0}，拒绝误判成功",
                )
            if reopen_attempt >= 2:
                break
            self._log(
                "warn",
                f"全流程v3: 第{reopen_attempt + 1}轮重新进入目标短剧未通过稳定校验，下一轮将冷重置后重试",
            )
            time.sleep(2)
        return False

    def _reopen_target_episode(
        self,
        ops: HongguoOperations,
        task: Dict[str, Any],
        target: int,
        expected_total: int,
        prefer_exact_title: bool = True,
    ) -> bool:
        keyword = str(task.get("drama_name") or "").strip()
        if not keyword:
            return False
        try:
            self._log("warn", f"全流程v3: 准备重新搜索目标短剧并切到第{target}集")
            live_lite_active = getattr(ops, "_live_lite_activity_active", None)
            if callable(live_lite_active) and live_lite_active() is True:
                close_live_lite = getattr(ops, "_close_live_lite_page", None)
                closed = bool(close_live_lite()) if callable(close_live_lite) else False
                self._log(
                    "info" if closed else "warn",
                    f"全流程v3: 重新搜索前检测到红果内部直播页，关闭直播页={closed}",
                )
                if not closed:
                    open_main = getattr(ops, "_open_main_activity", None)
                    opened_main = bool(open_main()) if callable(open_main) else False
                    self._log(
                        "info" if opened_main else "warn",
                        f"全流程v3: 直播页关闭失败，强制打开红果主页面={opened_main}",
                    )
                    if not opened_main:
                        return False
                time.sleep(1)
            is_foreground = getattr(ops, "_is_app_foreground", None)
            if callable(is_foreground) and not is_foreground():
                bring_to_foreground = getattr(ops, "bring_to_foreground", None)
                launch_app = getattr(ops, "launch_app", None)
                foreground = bool(bring_to_foreground() if callable(bring_to_foreground) else False)
                if not foreground and callable(launch_app):
                    foreground = bool(launch_app())
                self._log("info" if foreground else "warn", f"全流程v3: 重新搜索前拉回红果前台={foreground}")
                if not foreground:
                    return False
            if not self._reset_search_context(ops, f"恢复第{target}集"):
                return False
            opened = ops.open_search_page(keyword)
            self._log("info" if opened.get("success") else "warn", opened.get("message") or "重新进入搜索框")
            if not opened.get("success"):
                open_main = getattr(ops, "_open_main_activity", None)
                opened_main = bool(open_main()) if callable(open_main) else False
                self._log(
                    "info" if opened_main else "warn",
                    f"全流程v3: 恢复搜索入口未加载，强制打开红果主页面={opened_main}",
                )
                if not opened_main:
                    return False
                time.sleep(1)
                opened = ops.open_search_page(keyword)
                self._log(
                    "info" if opened.get("success") else "warn",
                    opened.get("message") or "强制回主页面后重新进入搜索框",
                )
                if not opened.get("success"):
                    return False
            input_result = ops.input_search_keyword(keyword)
            if not input_result.get("success"):
                self._log("warn", input_result.get("message") or "重新填入关键词失败")
                return False
            self._log("info", input_result.get("message") or f"全流程v3: 恢复时已填入搜索词 {keyword}")
            search: Dict[str, Any] = {}
            for submit_attempt in range(3):
                search = ops.submit_search(keyword)
                submit = search.get("submit") or {}
                self._log(
                    "info" if search.get("success") else "warn",
                    f"{search.get('message') or '重新搜索完成'}，提交尝试={submit_attempt + 1}/3，"
                    f"提交动作={submit.get('action') or search.get('action') or '-'}，"
                    f"结果页={bool(submit.get('tabs_visible') or search.get('tabs_visible'))}，"
                    f"候选={bool(submit.get('candidate_visible') or search.get('candidate_visible'))}",
                )
                if search.get("success"):
                    break
                time.sleep(2)
                ops.input_search_keyword(keyword)
            if not search.get("success"):
                return False
            titles = ops._extract_drama_titles()
            selected_title = ops._choose_title(keyword, titles)
            self._log("info", f"全流程v3: 恢复搜索结果={titles[:5]}，命中={selected_title or '-'}")
            if not selected_title:
                self._log("warn", "全流程v3: 恢复搜索未找到可读文字标题命中，尝试无文字海报兜底校验")
            selected = ops.select_drama(
                selected_title,
                keyword=keyword,
                prefer_exact_title=prefer_exact_title,
                prefer_result_card=not prefer_exact_title,
                expected_total=expected_total,
            )
            if not selected.get("success"):
                self._log("warn", selected.get("message") or "重新进入目标短剧失败")
                if self._retry_reopen_target_from_main(ops, keyword, target, expected_total, task):
                    return True
                return False
            playback_speed = str(task.get("playback_speed") or "1.0x")
            if playback_speed != "1.0x":
                speed_set = ops.set_playback_speed(playback_speed)
                self._log("info" if speed_set else "warn", f"全流程v3: 恢复后倍速设置 {playback_speed} = {speed_set}")
            if not ops.play_episode(target):
                self._log("warn", f"全流程v3: 恢复后第{target}集播放触发未确认")
            return self._wait_for_episode_verified(
                ops,
                task,
                target,
                expected_total,
                timeout=90,
                allow_reopen=False,
            )
        except Exception as exc:
            self._log("warn", f"全流程v3: 重新进入目标短剧失败: {exc}")
            return False

    def _retry_reopen_target_from_main(
        self,
        ops: HongguoOperations,
        keyword: str,
        target: int,
        expected_total: int,
        task: Dict[str, Any],
    ) -> bool:
        self._log("warn", f"全流程v3: 恢复选剧失败，强制回主页面后重试第{target}集")
        if not self._reset_search_context(ops, f"恢复重试第{target}集"):
            return False
        opened = ops.open_search_page(keyword)
        self._log("info" if opened.get("success") else "warn", opened.get("message") or "恢复重试进入搜索框")
        if not opened.get("success"):
            return False
        input_result = ops.input_search_keyword(keyword)
        if not input_result.get("success"):
            self._log("warn", input_result.get("message") or "恢复重试填入关键词失败")
            return False
        search = ops.submit_search(keyword)
        submit = search.get("submit") or {}
        self._log(
            "info" if search.get("success") else "warn",
            f"{search.get('message') or '恢复重试搜索完成'}，提交动作={submit.get('action') or '-'}，"
            f"结果页={bool(submit.get('tabs_visible') or search.get('tabs_visible'))}",
        )
        if not search.get("success"):
            return False
        titles = ops._extract_drama_titles()
        selected_title = ops._choose_title(keyword, titles)
        self._log("info", f"全流程v3: 恢复重试搜索结果={titles[:5]}，命中={selected_title or '-'}")
        selected = ops.select_drama(
            selected_title,
            keyword=keyword,
            prefer_exact_title=True,
            expected_total=expected_total,
        )
        if not selected.get("success"):
            self._log("warn", selected.get("message") or "恢复重试进入目标短剧失败")
            return False
        playback_speed = str(task.get("playback_speed") or "1.0x")
        if playback_speed != "1.0x":
            speed_set = ops.set_playback_speed(playback_speed)
            self._log("info" if speed_set else "warn", f"全流程v3: 恢复重试倍速设置 {playback_speed} = {speed_set}")
        if not ops.play_episode(target):
            self._log("warn", f"全流程v3: 恢复重试第{target}集播放触发未确认")
        verified = self._wait_for_episode_verified(
            ops,
            task,
            target,
            expected_total,
            timeout=90,
            allow_reopen=False,
        )
        if not verified:
            return False
        state = self._page_state_with_empty_retry(ops, task)
        try:
            self._assert_target_playback(ops, task, state, expected_total)
        except RuntimeError as exc:
            self._log("warn", f"全流程v3: 精确标题重搜后仍未通过目标合集校验: {exc}")
            return False
        return True

    def _reset_search_context(self, ops: HongguoOperations, reason: str) -> bool:
        stop_app = getattr(ops, "_stop_app", None)
        open_main = getattr(ops, "_open_main_activity", None)
        if not callable(open_main):
            self._log("warn", f"全流程v3: {reason}前无法调用红果主页面重置")
            return False
        try:
            if callable(stop_app):
                stop_app()
                time.sleep(1)
            opened_main = bool(open_main())
        except Exception as exc:
            self._log("warn", f"全流程v3: {reason}前重置红果主页面异常: {exc}")
            return False
        self._log(
            "info" if opened_main else "warn",
            f"全流程v3: {reason}前冷重置红果主页面={opened_main}",
        )
        return opened_main

    def _page_state(self, ops: HongguoOperations, task: Dict[str, Any]) -> Dict[str, Any]:
        keyword = str(task.get("drama_name") or "").strip()
        xml = ops._xml()
        app = ops._safe_app_current()
        app_foreground = ops._is_app_foreground_from_state(app, xml)
        short_series_active = (
            app.get("package") == "com.phoenix.read"
            and app.get("activity") == "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity"
        )
        if not self._device_info_cache:
            self._device_info_cache = ops.get_device_info()
        return {
            "device": dict(self._device_info_cache),
            "app": app,
            "app_foreground": app_foreground,
            "launcher_visible": ops._launcher_visible(xml),
            "first_visible_package": ops._first_visible_package(xml),
            "hongguo_visible_area_ratio": ops._hongguo_visible_area_ratio(xml),
            "current_episode": ops.get_current_episode(xml, assume_foreground=app_foreground),
            "total_episodes": ops.get_total_episodes(xml, assume_foreground=app_foreground),
            "playback_visible": ops._playback_visible(xml, short_series_active=short_series_active),
            "playback_paused": ops.is_playback_paused(xml, short_series_active=short_series_active),
            "ad_visible": ops._ad_continue_visible(xml),
            "detail_title": ops._extract_detail_title(keyword, xml),
            "playing_title": ops._current_playing_title(xml),
            "collection_title": ops._current_collection_title(xml),
        }

    def _page_state_with_empty_retry(
        self,
        ops: HongguoOperations,
        task: Dict[str, Any],
        attempts: int = 3,
    ) -> Dict[str, Any]:
        state: Dict[str, Any] = {}
        for attempt in range(max(1, attempts)):
            state = self._page_state(ops, task)
            app = state.get("app") or {}
            if not (
                not app.get("package")
                and not state.get("first_visible_package")
                and not state.get("launcher_visible")
                and not state.get("playback_visible")
            ):
                return state
            if attempt + 1 < attempts:
                self._log("warn", "全流程v3: 页面状态暂不可读，重新采集")
                time.sleep(2)
        return state

    def _take_diagnostic_screenshot(self, ops: HongguoOperations, name: str) -> str:
        try:
            return str(ops.take_screenshot(name, self.screenshot_dir) or "")
        except Exception as exc:
            self._log("warn", f"诊断截图失败: {exc}")
            return ""

    @staticmethod
    def _video_frames_are_static(first_path: str, second_path: str, threshold: float = 1.5) -> bool:
        try:
            from PIL import Image, ImageChops, ImageStat

            first_file = Path(first_path)
            second_file = Path(second_path)
            if not first_file.exists() or not second_file.exists():
                return False
            with Image.open(first_file) as first_image, Image.open(second_file) as second_image:
                first = first_image.convert("L")
                second = second_image.convert("L")
                if first.size != second.size:
                    return False
                width, height = first.size
                video_box = (
                    int(width * 0.04),
                    int(height * 0.31),
                    int(width * 0.88),
                    int(height * 0.61),
                )
                first = first.crop(video_box).resize((84, 48))
                second = second.crop(video_box).resize((84, 48))
                difference = ImageChops.difference(first, second)
                return float(ImageStat.Stat(difference).mean[0]) <= float(threshold)
        except Exception:
            return False

    @staticmethod
    def _playback_state_summary(state: Dict[str, Any]) -> str:
        app = state.get("app") or {}
        device = state.get("device") or {}
        return (
            f"设备={device.get('serial') or '-'}, "
            f"package={app.get('package') or '-'}, activity={app.get('activity') or '-'}, "
            f"红果前台={bool(state.get('app_foreground'))}, 桌面可见={bool(state.get('launcher_visible'))}, "
            f"首个可见包={state.get('first_visible_package') or '-'}, 播放页={bool(state.get('playback_visible'))}, "
            f"当前集={int(state.get('current_episode') or 0)}, 总集数={int(state.get('total_episodes') or 0)}, "
            f"暂停={bool(state.get('playback_paused'))}, 广告={bool(state.get('ad_visible'))}"
        )

    @staticmethod
    def _has_playback_context(state: Dict[str, Any]) -> bool:
        """Treat a transient empty app_current result as inconclusive.

        uiautomator2 intermittently returns an empty package while the visible
        Hongguo player remains active. The launcher signal remains decisive.
        """
        app = state.get("app") or {}
        if state.get("ad_visible"):
            return True
        if state.get("launcher_visible") and float(state.get("hongguo_visible_area_ratio") or 0) < 0.18:
            return False
        if app.get("package") == "com.phoenix.read":
            return True
        return bool(state.get("app_foreground") and state.get("playback_visible"))

    def _check_login(self, ops: HongguoOperations) -> Dict[str, Any]:
        result = ops.check_login()
        account = ops.get_account_info()
        if not account.get("logged_in") and result.get("logged_in"):
            for _ in range(2):
                time.sleep(2)
                retry_result = ops.check_login()
                retry_account = ops.get_account_info()
                if retry_result.get("logged_in"):
                    result = retry_result
                if retry_account.get("logged_in"):
                    account = retry_account
                    break
        if account.get("logged_in"):
            result = {
                **result,
                "logged_in": True,
                "status": "logged_in",
                "message": account.get("message") or "已登录",
            }
        else:
            result = {
                **result,
                "logged_in": False,
                "status": "not_logged_in",
                "message": account.get("message") or "请先在当前红果实例登录账号",
            }
        return {**result, "account": account}

    def _assert_target_playback(
        self,
        ops: HongguoOperations,
        task: Dict[str, Any],
        state: Dict[str, Any],
        expected_total: int,
        *,
        allow_unreadable_first_episode: bool = False,
    ) -> None:
        app = state.get("app") or {}
        if not self._has_playback_context(state):
            raise RuntimeError(f"未停留在红果APP，当前 package={app.get('package') or '-'}")
        if app.get("activity") and app.get("activity") != "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity":
            raise RuntimeError(f"未停留在目标短剧播放页，当前 activity={app.get('activity') or '-'}")
        total = int(state.get("total_episodes") or 0)
        current = int(state.get("current_episode") or 0)
        if self._total_mismatch_is_fatal(ops, task, state, expected_total, total, current=current):
            raise RuntimeError(f"检测到短剧总集数不匹配: 期望 {expected_total}，实际 {total}")
        keyword = str(task.get("drama_name") or "").strip()
        collection_title = str(state.get("collection_title") or "").strip()
        if keyword and collection_title and not self._strict_title_matches(keyword, collection_title):
            raise RuntimeError(f"检测到非目标合集: 期望 {keyword}，实际 {collection_title}")
        playing_title = str(state.get("playing_title") or "").strip()
        detail_title = str(state.get("detail_title") or "").strip()
        if keyword and playing_title and not self._strict_title_matches(keyword, playing_title):
            raise RuntimeError(f"检测到短剧标题不匹配: 期望 {keyword}，实际 {playing_title}")
        title_signals = [playing_title]
        if not state.get("playback_visible"):
            title_signals.append(detail_title)
        reliable_titles = [title for title in title_signals if self._reliable_title_signal(keyword, title)]
        if keyword and reliable_titles and not any(self._strict_title_matches(keyword, title) for title in reliable_titles):
            raise RuntimeError(f"检测到短剧标题不匹配: 期望 {keyword}，实际 {reliable_titles[0]}")
        if (
            keyword
            and state.get("playback_visible")
            and detail_title
            and self._reliable_title_signal(keyword, detail_title)
            and not self._strict_title_matches(keyword, detail_title)
        ):
            self._log("warn", f"全流程v3: 忽略播放页相关推荐标题 {detail_title}")
        if not current and bool(state.get("playback_visible") or ops._playback_visible()):
            try:
                shot = ops.take_screenshot("playback_episode_unreadable", self.screenshot_dir)
            except Exception:
                shot = "截图失败"
            self._log("warn", f"全流程v3: 播放页可见但当前集数不可读，继续观察，{shot}")
            return
        if (
            not current
            and allow_unreadable_first_episode
            and expected_total > 0
            and total == expected_total
            and app.get("package") == "com.phoenix.read"
            and app.get("activity") == "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity"
            and not state.get("launcher_visible")
            and not state.get("ad_visible")
        ):
            self._log("info", "全流程v3: 首集已确认，播放控件暂时隐藏，按第1集继续")
            return
        if not current:
            raise RuntimeError("未识别到当前集数")
        if not ops._playback_visible():
            if app.get("activity") == "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity":
                self._log("info", "全流程v3: 短剧播放页控件暂时隐藏，继续观察")
                return
            raise RuntimeError("未检测到播放控件")

    def _total_mismatch_is_fatal(
        self,
        ops: HongguoOperations,
        task: Dict[str, Any],
        state: Dict[str, Any],
        expected_total: int,
        total: int,
        current: int = 0,
        target: int = 0,
    ) -> bool:
        if not expected_total or not total or total == expected_total:
            return False

        keyword = str(task.get("drama_name") or "").strip()
        detail_title = str(state.get("detail_title") or "").strip()
        title_matches = bool(detail_title and keyword and ops._title_matches(keyword, detail_title))
        if title_matches and total < expected_total:
            observed_floor = max(current, target)
            if observed_floor and total >= observed_floor:
                return False
            if expected_total - total <= 1:
                return False
        return True

    def _resume_if_paused(self, ops: HongguoOperations, episode: int) -> bool:
        if not ops.is_playback_paused():
            return False
        resumed = ops.resume_playback_safely()
        still_paused = ops.is_playback_paused()
        if still_paused:
            resumed = ops.resume_playback_if_paused(allow_center_fallback=True) or resumed
            time.sleep(0.8)
            still_paused = ops.is_playback_paused()
        ok = not still_paused
        self._log("info" if ok else "warn", f"全流程v3: 第{episode}集检测到暂停，恢复播放={resumed}，仍暂停={still_paused}")
        return ok

    def _restore_playback_after_comment(
        self,
        ops: HongguoOperations,
        task: Dict[str, Any],
        episode: int,
        expected_total: int,
    ) -> bool:
        back_to_playback = ops.ensure_playback_page(episode)
        if not back_to_playback:
            self._log("warn", f"全流程v3: 第{episode}集评论后未直接确认回到播放页，继续读取页面状态")
        time.sleep(1)

        state = self._page_state(ops, task)
        if not self._has_playback_context(state):
            foreground = bool(ops.bring_to_foreground())
            self._log(
                "info" if foreground else "warn",
                f"全流程v3: 第{episode}集评论后检测到离开红果，尝试拉回前台={foreground}",
            )
            if foreground:
                time.sleep(2)
                if not ops.ensure_playback_page(episode):
                    self._recover_to_verified_episode(
                        ops,
                        task,
                        episode,
                        expected_total,
                        "评论后从桌面恢复播放页",
                        allow_reopen=True,
                    )
                state = self._page_state(ops, task)
        if state.get("ad_visible"):
            shot = ops.take_screenshot(f"ep{episode}_after_comment_ad", self.screenshot_dir)
            skipped = ops.skip_ad_if_present()
            self._log(
                "info" if skipped else "warn",
                f"全流程v3: 第{episode}集评论后遇到广告，已截图 {shot}，跳过广告={skipped}",
            )
            time.sleep(3)
            state = self._page_state(ops, task)

        app = state.get("app") or {}
        if app.get("activity") and app.get("activity") != "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity":
            recovered = self._recover_to_verified_episode(
                ops,
                task,
                episode,
                expected_total,
                f"评论后停留在非播放页 {app.get('activity')}",
            )
            self._log(
                "info" if recovered else "warn",
                f"全流程v3: 第{episode}集评论后非播放页恢复={recovered}",
            )
            if recovered:
                state = self._page_state(ops, task)

        try:
            self._assert_target_playback(ops, task, state, expected_total)
        except RuntimeError as exc:
            recovered = self._recover_to_verified_episode(
                ops,
                task,
                episode,
                expected_total,
                f"评论后播放上下文异常: {exc}",
                allow_reopen=True,
            )
            self._log(
                "info" if recovered else "warn",
                f"全流程v3: 第{episode}集评论后目标短剧恢复={recovered}",
            )
            if not recovered:
                raise
            state = self._page_state(ops, task)
            self._assert_target_playback(ops, task, state, expected_total)
        was_paused = bool(state.get("playback_paused") or ops.is_playback_paused())
        resumed = ops.resume_playback_safely()
        time.sleep(1)
        still_paused = ops.is_playback_paused()
        if still_paused:
            resumed = ops.resume_playback_if_paused(allow_center_fallback=True) or resumed
            time.sleep(1)
            still_paused = ops.is_playback_paused()
        if not still_paused:
            time.sleep(2)
            still_paused = ops.is_playback_paused()
            if still_paused:
                resumed = ops.resume_playback_if_paused(allow_center_fallback=True) or resumed
                time.sleep(1)
                still_paused = ops.is_playback_paused()
        ok = not still_paused
        if ok:
            self._comment_recovered_at[int(episode)] = time.time()
        self._log(
            "info" if ok else "warn",
            f"全流程v3: 第{episode}集评论后恢复播放，回播放页={back_to_playback}，原暂停={was_paused}，恢复={resumed}，仍暂停={still_paused}",
        )
        return ok

    def _safe_resume_playback(self, ops: HongguoOperations, episode: int, reason: str) -> bool:
        resumed = ops.resume_playback_safely()
        still_paused = ops.is_playback_paused()
        if still_paused:
            resumed = ops.resume_playback_if_paused(allow_center_fallback=True) or resumed
            time.sleep(0.8)
            still_paused = ops.is_playback_paused()
        if still_paused:
            time.sleep(1.5)
            still_paused = ops.is_playback_paused()
        ok = not still_paused
        self._log("info" if ok else "warn", f"全流程v3: 第{episode}集{reason}，安全播放={resumed}，仍暂停={still_paused}")
        return ok

    def _comment_already_verified(self, episode: int) -> bool:
        task = self._load_task()
        started_at = task.get("started_at") if task else None
        run_filter = "AND created_at >= %s" if started_at else ""
        params: List[Any] = [self.task_id, episode]
        if started_at:
            params.append(started_at)
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id
                    FROM hongguo_comment_records
                    WHERE task_id=%s AND episode_number=%s AND status='success' {run_filter}
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    params,
                )
                return cur.fetchone() is not None

    def _missing_verified_comment_episodes(self, comment_episodes: Iterable[int]) -> List[int]:
        return [episode for episode in sorted(set(comment_episodes)) if not self._comment_already_verified(episode)]

    def _duration_seconds(self, completed_at: datetime) -> Optional[int]:
        task = self._load_task()
        started_at = task.get("started_at") if task else None
        if not started_at:
            return None
        try:
            return max(0, int((completed_at - started_at).total_seconds()))
        except Exception:
            return None

    def _run(self) -> None:
        self._run_verified_flow()
        return
        Path(self.screenshot_dir).mkdir(parents=True, exist_ok=True)
        try:
            os.environ.pop("PYTHONPATH", None)
            self._update_task(
                status="running",
                started_at=datetime.now(),
                completed_at=None,
                error_message=None,
                comments_sent=0,
                comments_verified=0,
            )
            self._log("info", "正在连接模拟器")
            if not check_connection(self.device_addr):
                message = f"device {self.device_addr} not online"
                self._update_task(status="failed", error_message=message, completed_at=datetime.now())
                self._log("error", message)
                return
            device = connect(self.device_addr)
            self._log("info", f"已连接设备: {getattr(device, 'serial', self.device_addr)}")
            ops = HongguoOperations(device)

            task = self._load_task()
            if not task:
                raise RuntimeError("任务不存在")
            self._log("info", f"任务配置已加载: {task.get('drama_name')}")

            self._check_pause_stop()
            self._log("info", "启动红果短剧")
            if not ops.launch_app():
                raise RuntimeError("红果短剧启动失败")
            ops.take_screenshot("launch", self.screenshot_dir)

            login = ops.check_login()
            self._log("info", f"登录检测: {login.get('message')}")
            if not login.get("logged_in") and login.get("status") == "unknown":
                self._log("warn", "登录状态暂时无法确认，继续通过搜索和播放流程验证")
                self._update_task(error_message=None)
            elif not login.get("logged_in"):
                self._update_task(status="waiting_login", error_message=login.get("message"))
                while not self._stop_event.is_set():
                    self._check_pause_stop()
                    time.sleep(5)
                    login = ops.check_login()
                    self._log("info", f"等待登录检测: {login.get('message')}")
                    if login.get("logged_in"):
                        self._update_task(status="running", error_message=None)
                        break
                self._check_pause_stop()

            self._check_pause_stop()
            self._log("info", f"搜索关键词: {task['drama_name']}")
            found = ops.find_drama(task["drama_name"])
            search = found.get("search") or {}
            self._log("info", search.get("message", found.get("message", "搜索完成")))
            if search.get("input_text") is not None:
                self._log("info", f"搜索框实际输入: {search.get('input_text')}")
            ops.take_screenshot("search_results", self.screenshot_dir)

            titles = found.get("titles") or search.get("titles") or []
            self._log("info", f"搜索结果标题: {titles[:5]}")
            if not found.get("success"):
                raise RuntimeError(found.get("message") or f"未找到匹配短剧: {task['drama_name']}")
            drama_title = found.get("drama_title") or found.get("selected_title") or task["drama_name"]
            self._log("info", f"已选择短剧: {drama_title}")
            ops.take_screenshot("drama_detail", self.screenshot_dir)

            rule_start_episode = max(1, int(task.get("start_episode") or 1))
            watch_start_episode = 1
            total = ops.get_total_episodes()
            if total <= 0:
                ops.play_episode(watch_start_episode)
                time.sleep(2)
                ops.exit_fullscreen()
                total = ops.get_total_episodes() or watch_start_episode
            self._update_task(total_episodes=total)
            self._log("info", f"检测到总集数: {total}")

            watch_start_episode = min(watch_start_episode, max(1, total))
            rule_start_episode = min(rule_start_episode, max(1, total))
            watch_episodes = self._watch_episode_plan(total, watch_start_episode)
            comment_episodes = set(self._comment_episode_plan(task, total))
            done_episodes = self._completed_comment_episodes()
            if done_episodes:
                comment_episodes -= done_episodes
            self._update_task(
                execution_plan_json=json.dumps(
                    {
                        "watch_episodes": watch_episodes,
                        "comment_episodes": sorted(comment_episodes),
                        "skipped_comment_episodes": sorted(done_episodes),
                        "rule": self._task_rule_snapshot(task),
                    },
                    ensure_ascii=False,
                )
            )
            self._log("info", f"刷剧计划: 第{watch_start_episode}集到第{total}集")
            self._log("info", f"评论集数计划: {sorted(comment_episodes)}")
            if rule_start_episode != watch_start_episode:
                self._log("info", f"评论规则起始集: 第{rule_start_episode}集，刷剧仍从第{watch_start_episode}集开始")
            if done_episodes:
                self._log("info", f"已完成评论集数将跳过: {sorted(done_episodes)}")
            desired_speed = str(task.get("playback_speed") or "1.0x")
            if desired_speed != "1.0x":
                self._log("info", f"准备设置倍速: {desired_speed}")
                if ops.set_playback_speed(desired_speed):
                    self._log("info", f"倍速已设置: {desired_speed}")
                else:
                    self._log("warn", f"倍速设置失败，继续使用当前倍速: {desired_speed}")
            current_episode = ops.get_current_episode()
            if current_episode > 0 and current_episode != watch_start_episode:
                self._log("info", f"检测到当前停留在第{current_episode}集，准备切到第{watch_start_episode}集")
            if not ops.play_episode(watch_start_episode):
                self._log("warn", f"第{watch_start_episode}集播放未确认，准备重试切换")
                time.sleep(2)
                if not ops.play_episode(watch_start_episode):
                    failure_shot = ops.take_screenshot(f"ep{watch_start_episode}_play_failed", self.screenshot_dir)
                    self._save_record(watch_start_episode, "", "ai", "failed", screenshot_input=failure_shot, error_message=f"第{watch_start_episode}集播放失败")
                    raise RuntimeError(f"第{watch_start_episode}集播放失败")
            self._log("info", f"第{watch_start_episode}集播放已触发，开始确认当前播放状态")
            if not self._wait_for_episode(ops, watch_start_episode, task):
                self._log("warn", f"第{watch_start_episode}集播放状态确认不足，将继续观察自动跳集")

            for episode in watch_episodes:
                self._check_pause_stop()
                self._update_task(current_episode=episode)
                self._log("info", f"正在刷第{episode}集")
                if not self._wait_for_episode(ops, episode, task) and not self._recover_episode_position(ops, episode, task):
                    failure_shot = ops.take_screenshot(f"ep{episode}_play_failed", self.screenshot_dir)
                    self._save_record(episode, "", "ai", "failed", screenshot_input=failure_shot, error_message="等待当前集播放失败")
                    self._log("error", f"第{episode}集播放状态未能确认")
                    current = ops.get_current_episode()
                    state = f"当前识别到第{current}集" if current else "当前集数无法识别"
                    raise RuntimeError(f"第{episode}集播放状态未能确认，{state}，已停止以避免继续跳错")

                if episode not in comment_episodes:
                    if episode < total and not self._wait_for_next_episode(ops, episode, task):
                        target_episode = episode + 1
                        failure_shot = ops.take_screenshot(f"ep{episode}_next_failed", self.screenshot_dir)
                        self._save_record(
                            episode,
                            "",
                            "ai",
                            "failed",
                            screenshot_input=failure_shot,
                            error_message=f"等待第{target_episode}集失败",
                        )
                        self._log("error", f"第{episode}集未能自动跳到第{target_episode}集")
                        if self._recover_episode_position(ops, target_episode, task):
                            self._log("info", f"已恢复到第{target_episode}集，继续按顺序执行")
                        else:
                            current = ops.get_current_episode()
                            state = f"当前识别到第{current}集" if current else "当前集数无法识别"
                            raise RuntimeError(
                                f"第{episode}集后无法确认第{target_episode}集，{state}，已停止以避免跳错短剧"
                            )
                    else:
                        self._log("info", f"第{episode}集未命中评论规则，继续下一集")
                    continue

                self._log("info", f"第{episode}集命中评论规则，准备生成评论")
                generator = CommentGenerator(self._current_ai_config())
                content, source, usage = generator.generate_with_usage(
                    drama_title,
                    task.get("content_source", "ai"),
                    self._templates(task),
                )
                if usage:
                    record_usage(usage, context=f"task:{self.task_id}:episode:{episode}")
                self._log("info", f"评论内容已生成: {source}")
                if not self._wait_safe_comment_window(ops, episode, task):
                    failure_shot = ops.take_screenshot(f"ep{episode}_comment_window_missed", self.screenshot_dir)
                    self._save_record(
                        episode,
                        content,
                        source,
                        "failed",
                        screenshot_input=failure_shot,
                        error_message="评论前已跳出目标集，取消发布",
                    )
                    self._log("warn", f"第{episode}集评论窗口已错过，取消发布以避免发到错误集")
                    target_episode = episode + 1
                    if not self._recover_episode_position(ops, target_episode, task):
                        current = ops.get_current_episode()
                        state = f"当前识别到第{current}集" if current else "当前集数无法识别"
                        raise RuntimeError(
                            f"第{episode}集评论窗口错过后无法确认第{target_episode}集，{state}，已停止以避免跳错短剧"
                        )
                    continue
                input_path = ops.take_screenshot(f"ep{episode}_before_comment", self.screenshot_dir)
                post = ops.post_comment(content, episode)
                if not post.get("success"):
                    verify_path = ops.take_screenshot(f"ep{episode}_post_failed", self.screenshot_dir)
                    self._save_record(
                        episode,
                        content,
                        source,
                        "failed",
                        input_path,
                        verify_path,
                        post.get("message"),
                    )
                    self._log("error", f"评论发送失败: {post.get('message')}")
                    self._recover_episode_position(ops, episode, task)
                    continue

                self._increment_counter("sent")
                verify = ops.verify_comment(content, episode, self.screenshot_dir)
                verify_path = verify.get("screenshot_path") or ops.take_screenshot(
                    f"ep{episode}_{'verified' if verify.get('verified') else 'not_found'}",
                    self.screenshot_dir,
                )
                status = "success" if verify.get("verified") else "failed"
                error = None if verify.get("verified") else verify.get("message", "评论验证失败")
                self._save_record(episode, content, source, status, input_path, verify_path, error)
                if status == "success":
                    self._increment_counter("verified")
                level = "info" if status == "success" else "error"
                message = "评论验证成功" if status == "success" else "评论验证失败"
                self._log(level, message)
                ops.ensure_playback_page(episode)

                if episode < total and not self._wait_for_next_episode(ops, episode, task):
                    target_episode = episode + 1
                    if self._recover_episode_position(ops, target_episode, task):
                        self._log("warn", f"第{episode}集评论后未能自动跳到下一集，已恢复到第{target_episode}集")
                    else:
                        current = ops.get_current_episode()
                        state = f"当前识别到第{current}集" if current else "当前集数无法识别"
                        raise RuntimeError(
                            f"第{episode}集评论后无法确认第{target_episode}集，{state}，已停止以避免跳错短剧"
                        )

            if self._stop_event.is_set():
                self._update_task(status="stopped", completed_at=datetime.now())
                self._log("info", "任务已停止")
            else:
                self._update_task(status="completed", completed_at=datetime.now())
                self._log("info", "任务执行完成")
        except StopRequested:
            self._update_task(status="stopped", completed_at=datetime.now())
            self._log("info", "任务已停止")
        except Exception as exc:
            self._update_task(status="failed", error_message=str(exc), completed_at=datetime.now())
            self._log("error", f"任务失败: {exc}")

    def _check_pause_stop(self) -> None:
        if self._stop_event.is_set():
            raise StopRequested()
        while self._pause_event.is_set():
            if self._stop_event.is_set():
                raise StopRequested()
            time.sleep(0.5)

    def _wait_comment_interval(self, task: Dict[str, Any]) -> None:
        if task.get("comment_mode") == "random":
            min_delay = int(task.get("random_min_interval") or 0)
            max_delay = int(task.get("random_max_interval") or min_delay)
            if max_delay < min_delay:
                min_delay, max_delay = max_delay, min_delay
            delay = random.randint(min_delay, max_delay)
        else:
            delay = int(task.get("comment_interval_sec") or 0)
        if delay > 0:
            self._log("info", f"等待{delay}秒后发布评论")
        end = time.time() + max(0, delay)
        while time.time() < end:
            self._check_pause_stop()
            self._sleep_until(end)

    def _wait_safe_comment_window(self, ops: HongguoOperations, episode: int, task: Dict[str, Any]) -> bool:
        if task.get("comment_mode") == "random":
            min_delay = int(task.get("random_min_interval") or 0)
            max_delay = int(task.get("random_max_interval") or min_delay)
            if max_delay < min_delay:
                min_delay, max_delay = max_delay, min_delay
            configured_delay = random.randint(min_delay, max_delay)
        else:
            configured_delay = int(task.get("comment_interval_sec") or 0)

        speed = self._playback_speed_factor(task)
        # Keep the human-like delay, but cap it for short episodes and high playback speed.
        safe_cap = max(3, int(12 / max(1.0, speed)))
        delay = min(max(0, configured_delay), safe_cap)
        if configured_delay != delay:
            self._log("info", f"智能调整评论等待: 原{configured_delay}秒 -> {delay}秒")
        elif delay > 0:
            self._log("info", f"等待{delay}秒后发布评论")

        end = time.time() + delay
        while time.time() < end:
            self._check_pause_stop()
            current = ops.get_current_episode()
            if current and current != episode:
                self._log("warn", f"等待发布时已从第{episode}集跳到第{current}集")
                return False
            self._sleep_until(end)

        current = ops.get_current_episode()
        if current and current != episode:
            self._log("warn", f"发布前已从第{episode}集跳到第{current}集")
            return False
        return ops.ensure_playback_page(episode)

    def _sleep_until(self, deadline: float, max_step: float = 1.0) -> None:
        remaining = deadline - time.time()
        if remaining > 0:
            time.sleep(min(max_step, remaining))

    def _playback_speed_factor(self, task: Dict[str, Any]) -> float:
        value = str(task.get("playback_speed") or "1.0x").strip().lower().replace("x", "")
        try:
            return max(0.5, float(value))
        except (TypeError, ValueError):
            return 1.0

    def _watch_episode_plan(self, total: int, start_episode: int = 1) -> List[int]:
        total = max(1, int(total or 1))
        start_episode = min(max(1, int(start_episode or 1)), total)
        return list(range(start_episode, total + 1))

    def _wait_for_episode(self, ops: HongguoOperations, episode: int, task: Dict[str, Any]) -> bool:
        deadline = time.time() + max(40, int(task.get("comment_interval_sec") or 30) + 90)
        while time.time() < deadline:
            self._check_pause_stop()
            if self._restore_foreground_if_needed(ops, episode):
                time.sleep(2)
                continue
            if self._skip_ad_if_present(ops):
                self._log("info", "检测到广告页，已上滑继续观看")
                time.sleep(2)
                continue
            self._resume_playback_if_needed(ops)
            current = ops.get_current_episode()
            if current == episode:
                return True
            if current and current > episode:
                return False
            time.sleep(2)
        return False

    def _wait_for_next_episode(self, ops: HongguoOperations, episode: int, task: Dict[str, Any]) -> bool:
        timeout = int(task.get("comment_interval_sec") or 30)
        deadline = time.time() + max(30, timeout + 90)
        target = episode + 1
        last_seen: Optional[int] = None
        while time.time() < deadline:
            self._check_pause_stop()
            if self._restore_foreground_if_needed(ops, episode):
                time.sleep(2)
                continue
            if self._skip_ad_if_present(ops):
                self._log("info", f"第{episode}集后检测到广告页，已上滑继续观看")
                time.sleep(3)
                current_after_ad = ops.get_current_episode()
                if current_after_ad == target:
                    self._log("info", f"广告后已进入第{target}集")
                    return True
                if current_after_ad:
                    last_seen = current_after_ad
                    self._log("info", f"广告后当前识别为第{current_after_ad}集，目标第{target}集")
                    if current_after_ad > target:
                        self._log("warn", f"广告后检测到已跳到第{current_after_ad}集，目标下一集是第{target}集")
                        return False
                    if current_after_ad < episode:
                        self._log("warn", f"广告后检测到回退到第{current_after_ad}集，当前应为第{episode}集")
                        return False
                else:
                    self._log("warn", f"第{episode}集广告上滑后暂时无法识别当前集数")
                continue
            self._resume_playback_if_needed(ops)
            current = ops.get_current_episode()
            if current != last_seen:
                last_seen = current
                if current:
                    self._log("info", f"等待第{target}集，当前识别为第{current}集")
                else:
                    self._log("warn", f"等待第{target}集时暂时无法识别当前集数")
            if current == target:
                return True
            if current and current > target:
                self._log("warn", f"检测到已跳到第{current}集，目标下一集是第{target}集")
                return False
            if current and current < episode:
                return False
            if current == episode and ops._playback_visible():
                time.sleep(2)
                continue
            time.sleep(2)
        state = f"最后识别到第{last_seen}集" if last_seen else "始终未识别到当前集数"
        self._log("error", f"等待第{target}集超时，{state}")
        return False

    def _restore_foreground_if_needed(self, ops: HongguoOperations, episode: int) -> bool:
        is_foreground = getattr(ops, "_is_app_foreground", None)
        if not callable(is_foreground):
            return False
        safe_app_current = getattr(ops, "_safe_app_current", None)
        xml_getter = getattr(ops, "_xml", None)
        first_visible_package = getattr(ops, "_first_visible_package", None)
        launcher_visible = getattr(ops, "_launcher_visible", None)
        large_hongguo_window = getattr(ops, "_has_large_hongguo_window", None)
        xml = xml_getter() if callable(xml_getter) else ""
        launcher_detected = bool(launcher_visible(xml)) if callable(launcher_visible) else False
        hongguo_window_visible = bool(large_hongguo_window(xml)) if callable(large_hongguo_window) else False
        desktop_visible = launcher_detected and not hongguo_window_visible
        if not desktop_visible and is_foreground():
            return False
        app = safe_app_current() if callable(safe_app_current) else {}
        if (
            app.get("package") == "com.phoenix.read"
            and app.get("activity") == "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity"
        ):
            return False
        first_package = first_visible_package(xml) if callable(first_visible_package) else ""
        self._log("warn", f"第{episode}集观察时红果不在前台，当前={app.get('package') or '-'}，可见={first_package or '-'}，尝试拉回")
        bring_to_foreground = getattr(ops, "bring_to_foreground", None)
        launch_app = getattr(ops, "launch_app", None)
        resume = getattr(ops, "resume_playback_if_paused", None)
        foreground = bring_to_foreground() if callable(bring_to_foreground) else False
        if not foreground and callable(launch_app):
            foreground = launch_app()
        resumed = resume(allow_center_fallback=True) if callable(resume) else False
        self._log("info", f"红果前台恢复={foreground}，继续播放={resumed}")
        return True

    def _resume_playback_if_needed(self, ops: HongguoOperations) -> None:
        if not self._resume_playback_check:
            return
        self._resume_playback_check = False
        if ops.resume_playback_if_paused(allow_center_fallback=True):
            self._log("info", "恢复后已尝试继续播放")

    def _skip_ad_if_present(self, ops: HongguoOperations) -> bool:
        try:
            return bool(ops.skip_ad_if_present())
        except Exception:
            return False

    def _recover_episode_position(self, ops: HongguoOperations, episode: int, task: Dict[str, Any]) -> bool:
        self._log("warn", f"尝试恢复到第{episode}集")
        for _ in range(2):
            self._check_pause_stop()
            if self._skip_ad_if_present(ops):
                self._log("info", "恢复前检测到广告页，已上滑继续观看")
                time.sleep(2)
            if ops.ensure_playback_page(episode):
                if self._wait_for_episode(ops, episode, task):
                    self._log("info", f"已恢复到第{episode}集")
                    return True
            time.sleep(2)
        self._log("error", f"恢复到第{episode}集失败")
        return False

    def _comment_episode_plan(self, task: Dict[str, Any], total: int) -> List[int]:
        total = max(1, int(total or 1))
        if task.get("comment_mode") == "random":
            count = min(int(task.get("random_comment_count") or 1), total)
            return sorted(random.sample(range(1, total + 1), count))
        start = max(1, int(task.get("start_episode") or 1))
        interval = max(1, int(task.get("episode_interval") or 1))
        return list(range(start, total + 1, interval))

    @staticmethod
    def _engagement_episode_plan(
        task: Dict[str, Any],
        total: int,
        field: str,
        default: int,
    ) -> List[int]:
        total = max(1, int(total or 1))
        raw_count = task.get(field)
        count = max(0, int(default if raw_count is None else raw_count))
        count = min(count, total)
        if field == "random_favorite_count":
            count = min(count, 1)
        return sorted(random.sample(range(1, total + 1), count)) if count else []

    def _task_rule_snapshot(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "comment_mode": task.get("comment_mode"),
            "start_episode": task.get("start_episode"),
            "episode_interval": task.get("episode_interval"),
            "comment_interval_sec": task.get("comment_interval_sec"),
            "random_comment_count": task.get("random_comment_count"),
            "random_min_interval": task.get("random_min_interval"),
            "random_max_interval": task.get("random_max_interval"),
            "random_like_count": task.get("random_like_count"),
            "random_favorite_count": task.get("random_favorite_count"),
            "content_source": task.get("content_source"),
            "playback_speed": task.get("playback_speed"),
        }

    def _choose_title(self, keyword: str, titles: Iterable[str]) -> str:
        titles = [title for title in titles if not self._looks_like_preview_title(title)]
        matches = [title for title in titles if self._title_matches(keyword, title)]
        if not matches:
            return ""
        keyword_key = self._normalize_title_key(keyword)
        keyword_has_variant = bool(self._season_marker(keyword_key) or self._has_variant_marker(keyword_key))
        exact = [title for title in matches if self._normalize_title_key(title) == keyword_key]
        if keyword_has_variant:
            canonical = [
                title
                for title in matches
                if re.search(r"第[一二三四五六七八九十\d]+季", self._normalize_title_key(title))
                and self._season_marker(self._normalize_title_key(title)) == self._season_marker(keyword_key)
                and self._title_stem(self._normalize_title_key(title)) == self._title_stem(keyword_key)
            ]
            if canonical:
                return min(canonical, key=lambda value: len(self._normalize_title_key(value)))
            extended = [
                title
                for title in matches
                if self._normalize_title_key(title).startswith(keyword_key)
                and self._normalize_title_key(title) != keyword_key
            ]
            if extended:
                return max(extended, key=lambda value: len(self._normalize_title_key(value)))
            return exact[0] if exact else matches[0]
        if exact:
            return exact[0]
        ranked: List[tuple[tuple[int, int, int], str]] = []
        for index, title in enumerate(matches):
            title_key = self._normalize_title_key(title)
            if not title_key.startswith(keyword_key):
                continue
            suffix = title_key[len(keyword_key) :]
            numeric_installment = re.match(r"(\d+)", suffix)
            if numeric_installment:
                if int(numeric_installment.group(1)) != 1:
                    continue
                ranked.append(((1, index, -len(title_key)), title))
                continue
            season = self._season_marker(title_key)
            has_variant = self._has_variant_marker(title_key)
            if season and season != "1":
                continue
            rank = 1 if season == "1" else 3 if has_variant else 2
            ranked.append(((rank, index, -len(title_key)), title))
        if ranked:
            ranked.sort(key=lambda item: item[0])
            return ranked[0][1]
        return matches[0]

    @staticmethod
    def _looks_like_preview_title(title: str) -> bool:
        value = str(title or "").strip()
        if any(marker in value for marker in ("即将上线", "预告", "预约")):
            return True
        if "《" in value and "》" in value:
            before, remainder = value.split("《", 1)
            _, after = remainder.split("》", 1)
            return bool(before.strip() or after.strip())
        return False

    def _title_matches(self, keyword: str, title: str) -> bool:
        keyword_key = self._normalize_title_key(keyword)
        title_key = self._normalize_title_key(title)
        if not keyword_key or not title_key:
            return False
        if keyword_key in title_key:
            return True
        season = self._season_marker(keyword_key)
        if season:
            if self._season_marker(title_key) != season:
                return False
            return self._season_stem_matches(keyword_key, title_key)
        return title_key in keyword_key and len(title_key) >= 4

    def _strict_title_matches(self, keyword: str, title: str) -> bool:
        keyword_key = self._normalize_title_key(keyword)
        title_key = self._normalize_title_key(title)
        if not keyword_key or not title_key:
            return False
        if self._season_marker(keyword_key):
            return self._title_matches(keyword, title)
        if self._has_variant_marker(keyword_key):
            if title_key == keyword_key:
                return True
            if title_key.startswith(keyword_key):
                if keyword_key[-1:].isdigit() and title_key[len(keyword_key) : len(keyword_key) + 1].isdigit():
                    return False
                return True
            return False
        title_season = self._season_marker(title_key)
        if title_season:
            return title_season == "1" and title_key.startswith(keyword_key)
        if title_key.startswith(keyword_key) and len(title_key) > len(keyword_key):
            suffix = title_key[len(keyword_key) :]
            if suffix[:1].isdigit():
                return suffix[:1] == "1" and not suffix[1:2].isdigit()
        if self._has_variant_marker(title_key):
            return False
        return self._title_matches(keyword, title)

    def _reliable_title_signal(self, keyword: str, title: str) -> bool:
        keyword_key = self._normalize_title_key(keyword)
        title_key = self._normalize_title_key(title)
        if not keyword_key or not title_key:
            return False
        if self._strict_title_matches(keyword, title):
            return True
        if self._season_marker(title_key):
            return True
        if self._has_variant_marker(title_key):
            return True
        keyword_stem = self._title_stem(keyword_key)
        return bool(keyword_stem and keyword_stem in title_key)

    def _normalize_title_key(self, value: str) -> str:
        text = unicodedata.normalize("NFKC", str(value or "")).replace("⻣", "骨")
        return re.sub(r"[\s《》<>:：·,，。.!！?？\-_/\\]+", "", text.lower())

    def _season_marker(self, value: str) -> str:
        match = re.search(r"第([一二三四五六七八九十\d]+)季", value)
        if match:
            return self._canonical_season_number(match.group(1))
        shorthand = re.search(r"(.+?)([1-9])$", value)
        return shorthand.group(2) if shorthand else ""

    def _season_stem_matches(self, keyword_key: str, title_key: str) -> bool:
        keyword_stem = self._title_stem(keyword_key)
        title_stem = self._title_stem(title_key)
        if not keyword_stem or not title_stem:
            return False
        return keyword_stem in title_stem or title_stem in keyword_stem

    def _title_stem(self, value: str) -> str:
        stem = re.sub(r"第[一二三四五六七八九十\d]+季", "", value)
        return re.sub(r"([^\d])([1-9])$", r"\1", stem)

    def _canonical_season_number(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if text.isdigit():
            return str(int(text))
        digits = {
            "零": 0,
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
        }
        if text == "十":
            return "10"
        if text.startswith("十") and len(text) == 2:
            return str(10 + digits.get(text[1], 0))
        if text.endswith("十") and len(text) == 2:
            return str(digits.get(text[0], 0) * 10)
        if "十" in text and len(text) == 3:
            return str(digits.get(text[0], 0) * 10 + digits.get(text[2], 0))
        if len(text) == 1 and text in digits:
            return str(digits[text])
        return text

    def _has_variant_marker(self, value: str) -> bool:
        return bool(re.search(r"\d+|第?[一二三四五六七八九十\d]+[季部篇]|[上下续前后]篇", value))

    def _templates(self, task: Dict[str, Any]) -> List[str]:
        value = task.get("templates_json")
        if isinstance(value, list):
            return value
        if not value:
            return []
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (TypeError, json.JSONDecodeError):
            return []

    def _completed_comment_episodes(self) -> set[int]:
        episodes: set[int] = set()
        task = self._load_task()
        started_at = task.get("started_at") if task else None
        run_filter = "AND created_at >= %s" if started_at else ""
        params: List[Any] = [self.task_id]
        if started_at:
            params.append(started_at)
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT episode_number
                    FROM hongguo_comment_records
                    WHERE task_id=%s AND status='success' {run_filter}
                    """,
                    params,
                )
                for row in cur.fetchall():
                    episode = row.get("episode_number")
                    if isinstance(episode, int) and episode > 0:
                        episodes.add(episode)
        return episodes

    def _load_task(self) -> Optional[Dict[str, Any]]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM hongguo_comment_tasks WHERE id=%s", (self.task_id,))
                return cur.fetchone()

    def _current_ai_config(self) -> Dict[str, Any]:
        manager = TaskEngineManager.get_instance()
        return dict(manager.ai_config or self.ai_config or {})

    @staticmethod
    def _structured_log_context(message: str) -> tuple[Optional[int], Optional[str]]:
        text = str(message or "")
        episode_match = re.search(r"第\s*(\d+)\s*集", text)
        screenshot_match = re.search(r"(?:已截图|截图)\s+([^，,\s]+)", text)
        episode = int(episode_match.group(1)) if episode_match else None
        screenshot_path = screenshot_match.group(1).rstrip("。.;；") if screenshot_match else None
        return episode, screenshot_path

    def _log(self, level: str, message: str) -> None:
        episode_number, screenshot_path = self._structured_log_context(message)
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO hongguo_execution_logs (
                            task_id, level, message, episode_number, screenshot_path, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            self.task_id,
                            level,
                            message,
                            episode_number,
                            screenshot_path,
                            datetime.now(),
                        ),
                    )
        except Exception:
            pass

    def _save_record(
        self,
        episode: int,
        content: str,
        source: str,
        status: str,
        screenshot_input: str = "",
        screenshot_verified: str = "",
        error_message: Optional[str] = None,
        screenshot_sent: str = "",
        sent_at: Optional[datetime] = None,
        verified_at: Optional[datetime] = None,
    ) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO hongguo_comment_records (
                        task_id, episode_number, comment_text, generated_by,
                        status, sent_at, verified_at, screenshot_input, screenshot_sent,
                        screenshot_verified, error_message, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        self.task_id,
                        episode,
                        content,
                        source,
                        status,
                        sent_at,
                        verified_at,
                        screenshot_input or None,
                        screenshot_sent or None,
                        screenshot_verified or None,
                        error_message,
                        datetime.now(),
                    ),
                )

    def _increment_counter(self, counter: str) -> None:
        if counter not in {"sent", "verified"}:
            return
        column = "comments_verified" if counter == "verified" else "comments_sent"
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE hongguo_comment_tasks SET {column}={column}+1 WHERE id=%s",
                    (self.task_id,),
                )

    def _increment_engagement_counter(self, action: str) -> None:
        columns = {"like": "likes_completed", "favorite": "favorites_completed"}
        column = columns.get(action)
        if not column:
            return
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE hongguo_comment_tasks SET {column}={column}+1 WHERE id=%s",
                    (self.task_id,),
                )

    def _update_task(self, **kwargs: Any) -> None:
        if not kwargs:
            return
        if self._lease_heartbeat and time.monotonic() - self._last_lease_heartbeat >= 300:
            try:
                self._lease_heartbeat(self.task_id)
                self._last_lease_heartbeat = time.monotonic()
            except Exception:
                pass
        assignments = []
        values = []
        for key, value in kwargs.items():
            assignments.append(f"{key}=%s")
            values.append(value)
        values.append(self.task_id)
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE hongguo_comment_tasks SET {', '.join(assignments)} WHERE id=%s",
                    values,
                )

    @contextmanager
    def _connection(self):
        conn = pymysql.connect(**self.db_config)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


class TaskEngineManager:
    """Singleton registry for Hongguo task engines."""

    _instance: Optional["TaskEngineManager"] = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        db_config: Optional[Dict[str, Any]] = None,
        screenshot_root: str = DEFAULT_SCREENSHOT_ROOT,
        ai_config: Optional[Dict[str, Any]] = None,
        device_addr: str = DEFAULT_ADDR,
    ):
        self.db_config = db_config or {}
        self.screenshot_root = screenshot_root
        self.ai_config = ai_config or {}
        self.device_addr = device_addr or DEFAULT_ADDR
        self._engines: Dict[int, TaskEngine] = {}
        self._lock = threading.Lock()

    def _lease_store(self) -> DeviceLeaseStore:
        return DeviceLeaseStore(self._normalized_db_config())

    @classmethod
    def get_instance(
        cls,
        db_config: Optional[Dict[str, Any]] = None,
        screenshot_root: str = DEFAULT_SCREENSHOT_ROOT,
        ai_config: Optional[Dict[str, Any]] = None,
        device_addr: Optional[str] = None,
    ) -> "TaskEngineManager":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(db_config, screenshot_root, ai_config, device_addr or DEFAULT_ADDR)
            elif db_config:
                cls._instance.db_config = db_config
                cls._instance.screenshot_root = screenshot_root
                cls._instance.ai_config = ai_config or {}
            if device_addr:
                cls._instance.device_addr = device_addr
            return cls._instance

    def _prune_finished_locked(self) -> None:
        finished = [task_id for task_id, engine in self._engines.items() if not engine.is_alive]
        for task_id in finished:
            self._engines.pop(task_id, None)
            self._lease_store().release(task_id)

    def _device_busy_locked(self, device_addr: str, task_id: int) -> bool:
        for running_task_id, running_engine in self._engines.items():
            if int(running_task_id) == int(task_id):
                continue
            if running_engine.is_alive and running_engine.device_addr == device_addr:
                return True
        return False

    def start_task(self, task_id: int, device_addr: Optional[str] = None, wait_timeout: float = 20) -> bool:
        effective_device_addr = device_addr or self.device_addr
        deadline = time.time() + max(0, float(wait_timeout))
        while True:
            with self._lock:
                self._prune_finished_locked()
                engine = self._engines.get(int(task_id))
                if engine and engine.is_alive:
                    return False
                if not self._device_busy_locked(effective_device_addr, int(task_id)):
                    lease_store = self._lease_store()
                    if not lease_store.acquire(int(task_id), effective_device_addr):
                        return False
                    engine = TaskEngine(
                        task_id=task_id,
                        db_config=self._normalized_db_config(),
                        screenshot_dir=self._task_screenshot_dir(task_id),
                        ai_config=dict(self.ai_config or {}),
                        device_addr=effective_device_addr,
                        lease_heartbeat=lease_store.renew,
                    )
                    self._engines[int(task_id)] = engine
                    started = engine.start()
                    if not started:
                        self._engines.pop(int(task_id), None)
                        self._lease_store().release(int(task_id))
                    return started
            if time.time() >= deadline:
                return False
            time.sleep(0.5)

    def pause_task(self, task_id: int) -> bool:
        engine = self._engines.get(int(task_id))
        return engine.pause() if engine and engine.is_alive else False

    def resume_task(self, task_id: int) -> bool:
        engine = self._engines.get(int(task_id))
        return engine.resume() if engine and engine.is_alive else False

    def stop_task(self, task_id: int) -> bool:
        engine = self._engines.get(int(task_id))
        if not engine:
            self._lease_store().release(int(task_id))
            return False
        stopped = engine.stop()
        engine.wait_stopped(5)
        with self._lock:
            self._prune_finished_locked()
        return stopped

    def is_running(self, task_id: int) -> bool:
        engine = self._engines.get(int(task_id))
        return bool(engine and engine.is_alive)

    def _task_screenshot_dir(self, task_id: int) -> str:
        return str((Path(self.screenshot_root) / str(task_id)).as_posix())

    def _normalized_db_config(self) -> Dict[str, Any]:
        cfg = dict(self.db_config)
        cfg.setdefault("cursorclass", DictCursor)
        cfg.setdefault("charset", "utf8mb4")
        cfg.setdefault("autocommit", False)
        return cfg


class StopRequested(Exception):
    """Raised internally when the task is stopped."""
