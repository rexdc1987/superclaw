"""Threaded task engine for Hongguo comment automation."""

from __future__ import annotations

import json
import os
import random
import re
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pymysql
from pymysql.cursors import DictCursor

from .ai_usage import record_usage
from .comment_gen import CommentGenerator
from .device import DEFAULT_ADDR, check_connection, connect
from .operations import HongguoOperations


DEFAULT_SCREENSHOT_ROOT = "E:/Projects/SuperClaw/screenshots/hongguo"


class TaskEngine:
    """Runs one Hongguo task in a daemon thread."""

    def __init__(
        self,
        task_id: int,
        db_config: Dict[str, Any],
        screenshot_dir: str,
        ai_config: Optional[Dict[str, Any]] = None,
        device_addr: str = DEFAULT_ADDR,
    ):
        self.task_id = int(task_id)
        self.db_config = dict(db_config)
        self.screenshot_dir = str(Path(screenshot_dir).as_posix())
        self.ai_config = dict(ai_config or {})
        self.device_addr = device_addr
        self._pause_event = threading.Event()
        self._stop_event = threading.Event()
        self._resume_playback_check = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._generator = CommentGenerator(self.ai_config)

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

    def _run_verified_flow(self) -> None:
        Path(self.screenshot_dir).mkdir(parents=True, exist_ok=True)
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
            completed_episodes = self._completed_comment_episodes()
            if completed_episodes:
                comment_episodes -= completed_episodes

            self._update_task(
                current_episode=1,
                total_episodes=total,
                execution_plan_json=json.dumps(
                    {
                        "watch_episodes": list(range(1, total + 1)),
                        "comment_episodes": sorted(comment_episodes),
                        "skipped_comment_episodes": sorted(completed_episodes),
                        "rule": self._task_rule_snapshot(task),
                        "flow": "verified_v3_full",
                    },
                    ensure_ascii=False,
                ),
                updated_at=datetime.now(),
            )
            self._log("info", f"全流程v3: 准备完成，短剧={drama_title}，总集数={total}，评论集数={sorted(comment_episodes)}")
            self._resume_if_paused(ops, 1)

            for episode in range(1, total + 1):
                self._check_pause_stop()
                state = self._page_state(ops, task)
                self._assert_target_playback(ops, task, state, total)
                current = int(state.get("current_episode") or 0)
                if current and current != episode:
                    raise RuntimeError(f"全流程v3跳集异常: 期望第{episode}集，当前第{current}集")

                self._update_task(current_episode=episode, updated_at=datetime.now())
                self._log("info", f"全流程v3: 正在观察第{episode}集")
                self._resume_if_paused(ops, episode)

                if episode in comment_episodes:
                    if self._comment_already_verified(episode):
                        self._log("info", f"全流程v3: 第{episode}集已有成功评论记录，跳过重复评论")
                    else:
                        self._handle_verified_comment(ops, task, drama_title, episode, total)

                if episode >= total:
                    break
                target = episode + 1
                if not self._wait_for_next_episode_verified(ops, task, episode, target, total):
                    shot = ops.take_screenshot(f"ep{episode}_next_timeout", self.screenshot_dir)
                    raise RuntimeError(f"全流程v3: 第{episode}集后未自动进入第{target}集，已截图 {shot}")

            completed_at = datetime.now()
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
        self._log("info", search.get("message") or "全流程v3: 搜索完成")
        if not search.get("success"):
            raise RuntimeError(search.get("message") or "提交搜索失败")

        titles = ops._extract_drama_titles()
        selected_title = ops._choose_title(keyword, titles)
        self._log("info", f"全流程v3: 搜索结果={titles[:5]}，命中={selected_title or '-'}")
        if not selected_title:
            raise RuntimeError("没有匹配任务短剧名称的搜索结果")

        selected = ops.select_drama(selected_title, keyword=keyword)
        drama_title = selected.get("drama_title") or selected_title
        self._log("info", selected.get("message") or f"全流程v3: 已进入目标剧集 {drama_title}")
        if not selected.get("success"):
            raise RuntimeError(selected.get("message") or "进入目标剧集失败")

        playback_speed = str(task.get("playback_speed") or "1.0x")
        if playback_speed != "1.0x":
            speed_set = ops.set_playback_speed(playback_speed)
            self._log("info" if speed_set else "warn", f"全流程v3: 倍速设置 {playback_speed} = {speed_set}")
            if not speed_set:
                raise RuntimeError(f"倍速设置失败: {playback_speed}")

        task_total = int(task.get("total_episodes") or 0)
        total_before = int(ops.get_total_episodes() or task_total or 0)
        self._log("info", f"全流程v3: 切换到第1集，当前识别总集数={total_before or 0}")
        if not ops.play_episode(1):
            self._log("warn", "全流程v3: 第1集播放触发未确认，继续等待页面识别")
        if not self._wait_for_episode_verified(ops, task, 1, max(total_before, 1), timeout=90):
            shot = ops.take_screenshot("ep1_play_failed", self.screenshot_dir)
            raise RuntimeError(f"首集播放失败，已截图 {shot}")

        state = self._page_state(ops, task)
        total = int(state.get("total_episodes") or total_before or task_total or 0)
        self._assert_target_playback(ops, task, state, max(total, 1))
        return {
            "drama_title": drama_title,
            "total_episodes": total,
            "current_episode": int(state.get("current_episode") or 1),
        }

    def _handle_verified_comment(
        self,
        ops: HongguoOperations,
        task: Dict[str, Any],
        drama_title: str,
        episode: int,
        expected_total: int,
    ) -> None:
        generator = CommentGenerator(self._current_ai_config())
        content, source, usage = generator.generate_with_usage(
            drama_title,
            task.get("content_source", "ai"),
            self._templates(task),
        )
        if usage:
            record_usage(usage, context=f"task:{self.task_id}:episode:{episode}")

        paused = ops.pause_playback_if_playing()
        self._log("info", f"全流程v3: 第{episode}集命中评论规则，暂停播放={paused}，准备评论")
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
        self._log(
            "info" if status == "success" else "error",
            f"全流程v3: 第{episode}集评论{'验证成功' if status == 'success' else '验证失败'}，截图 {verify_path}",
        )

        self._restore_playback_after_comment(ops, task, episode, expected_total)

    def _wait_for_episode_verified(
        self,
        ops: HongguoOperations,
        task: Dict[str, Any],
        target: int,
        expected_total: int,
        timeout: int = 60,
    ) -> bool:
        deadline = time.time() + max(20, timeout)
        last_log_at = 0.0
        while time.time() < deadline:
            self._check_pause_stop()
            state = self._page_state(ops, task)
            app = state.get("app") or {}
            current = int(state.get("current_episode") or 0)
            if app.get("package") != "com.phoenix.read":
                raise RuntimeError(f"切集时红果不在前台，当前 package={app.get('package') or '-'}")
            if state.get("ad_visible"):
                shot = ops.take_screenshot(f"seek_ep{target}_ad", self.screenshot_dir)
                skipped = ops.skip_ad_if_present(attempts=3)
                if not skipped:
                    ops._swipe_up_continue_ad()
                self._log("warn", f"全流程v3: 切第{target}集时遇到广告，已截图 {shot}，上滑继续观看")
                time.sleep(3)
                continue
            if app.get("activity") != "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity":
                raise RuntimeError(f"切集时未停留在短剧播放页，当前 activity={app.get('activity') or '-'}")
            total = int(state.get("total_episodes") or 0)
            if self._total_mismatch_is_fatal(ops, task, state, expected_total, total, current=current, target=target):
                raise RuntimeError(f"切集时短剧总集数不匹配: 期望 {expected_total}，实际 {total}")
            if current == target:
                return True
            now = time.time()
            if now - last_log_at >= 10:
                self._log("info", f"全流程v3: 正在确认第{target}集，当前识别第{current or 0}集")
                last_log_at = now
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
        deadline = time.time() + max(300, int(task.get("comment_interval_sec") or 30) + 240)
        last_log_at = 0.0
        same_episode_since = 0.0
        forced_target = False
        while time.time() < deadline:
            self._check_pause_stop()
            state = self._page_state(ops, task)
            app = state.get("app") or {}
            current = int(state.get("current_episode") or 0)

            if app.get("package") != "com.phoenix.read":
                raise RuntimeError(f"第{episode}集后红果不在前台，当前 package={app.get('package') or '-'}")
            if state.get("ad_visible"):
                shot = ops.take_screenshot(f"ep{episode}_ad", self.screenshot_dir)
                skipped = ops.skip_ad_if_present(attempts=3)
                if not skipped:
                    ops._swipe_up_continue_ad()
                    self._log("warn", f"全流程v3: 第{episode}集后出现广告，常规跳过未确认成功，已截图 {shot}，执行兜底上滑")
                else:
                    self._log("info", f"全流程v3: 第{episode}集后出现广告，已截图 {shot}，上滑继续观看")
                time.sleep(3)
                continue
            if app.get("activity") != "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity":
                total = int(state.get("total_episodes") or 0)
                raise RuntimeError(
                    f"第{episode}集后已离开目标短剧播放页，当前 activity={app.get('activity') or '-'}，识别总集数={total or 0}"
                )
            total = int(state.get("total_episodes") or 0)
            if current == 0 and total == 0:
                shot = ops.take_screenshot(f"ep{episode}_unknown_ad_overlay", self.screenshot_dir)
                self._log("warn", f"全流程v3: 第{episode}集后播放页集数不可见，按广告/遮罩页处理，已截图 {shot}，上滑继续观看")
                ops._swipe_up_continue_ad()
                time.sleep(3)
                continue
            if self._total_mismatch_is_fatal(ops, task, state, expected_total, total, current=current, target=target):
                raise RuntimeError(f"第{episode}集后跳到其他短剧: 期望总集数 {expected_total}，实际 {total}")

            if current == target:
                self._log("info", f"全流程v3: 已自动进入第{target}集")
                return True
            if current == episode:
                now = time.time()
                if same_episode_since <= 0:
                    same_episode_since = now
                if now - last_log_at >= 30:
                    self._log("info", f"全流程v3: 仍在第{episode}集，等待自动播放第{target}集")
                    self._safe_resume_playback(ops, episode, "仍停留当前集，检查是否暂停")
                    last_log_at = now
                if not forced_target and now - same_episode_since >= 150:
                    shot = ops.take_screenshot(f"ep{episode}_stale_force_target", self.screenshot_dir)
                    forced_target = ops.play_episode(target)
                    self._log("warn", f"全流程v3: 第{episode}集停留超过150秒，已截图 {shot}，强制切第{target}集={forced_target}")
                    time.sleep(3)
            elif current == 0:
                now = time.time()
                same_episode_since = 0.0
                if now - last_log_at >= 20:
                    self._log("warn", f"全流程v3: 第{episode}集后暂未识别到集数，继续观察播放页")
                    self._safe_resume_playback(ops, episode, "集数暂未识别，检查是否暂停")
                    last_log_at = now
            else:
                same_episode_since = 0.0
            if current > target:
                raise RuntimeError(f"跳过目标集: 目标第{target}集，当前第{current}集")
            if current < episode:
                raise RuntimeError(f"回退异常: 上一集第{episode}集，当前第{current}集")
            time.sleep(2)
        return False

    def _page_state(self, ops: HongguoOperations, task: Dict[str, Any]) -> Dict[str, Any]:
        keyword = str(task.get("drama_name") or "").strip()
        xml = ops._xml()
        return {
            "device": ops.get_device_info(),
            "app": ops._safe_app_current(),
            "app_foreground": ops._is_app_foreground(),
            "launcher_visible": ops._launcher_visible(xml),
            "first_visible_package": ops._first_visible_package(xml),
            "hongguo_visible_area_ratio": ops._hongguo_visible_area_ratio(xml),
            "current_episode": ops.get_current_episode(),
            "total_episodes": ops.get_total_episodes(),
            "playback_visible": ops._playback_visible(xml),
            "playback_paused": ops.is_playback_paused(),
            "ad_visible": ops._ad_continue_visible(xml),
            "detail_title": ops._extract_detail_title(keyword),
            "playing_title": ops._current_playing_title(),
        }

    def _check_login(self, ops: HongguoOperations) -> Dict[str, Any]:
        result = ops.check_login()
        account = ops.get_account_info()
        if account.get("logged_in") and not result.get("logged_in"):
            result = {
                **result,
                "logged_in": True,
                "status": "logged_in",
                "message": account.get("message") or "已登录",
            }
        if result.get("logged_in") and not account.get("logged_in"):
            account = {**account, "logged_in": True}
        return {**result, "account": account}

    def _assert_target_playback(
        self,
        ops: HongguoOperations,
        task: Dict[str, Any],
        state: Dict[str, Any],
        expected_total: int,
    ) -> None:
        app = state.get("app") or {}
        if app.get("package") != "com.phoenix.read":
            raise RuntimeError(f"未停留在红果APP，当前 package={app.get('package') or '-'}")
        if app.get("activity") != "com.dragon.read.component.shortvideo.impl.ShortSeriesActivity":
            raise RuntimeError(f"未停留在目标短剧播放页，当前 activity={app.get('activity') or '-'}")
        total = int(state.get("total_episodes") or 0)
        current = int(state.get("current_episode") or 0)
        if self._total_mismatch_is_fatal(ops, task, state, expected_total, total, current=current):
            raise RuntimeError(f"检测到短剧总集数不匹配: 期望 {expected_total}，实际 {total}")
        keyword = str(task.get("drama_name") or "").strip()
        title_signals = [
            str(state.get("playing_title") or "").strip(),
            str(state.get("detail_title") or "").strip(),
        ]
        reliable_titles = [title for title in title_signals if self._reliable_title_signal(keyword, title)]
        if keyword and reliable_titles and not any(self._strict_title_matches(keyword, title) for title in reliable_titles):
            raise RuntimeError(f"检测到短剧标题不匹配: 期望 {keyword}，实际 {reliable_titles[0]}")
        if not current:
            raise RuntimeError("未识别到当前集数")
        if not ops._playback_visible():
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
        resumed = ops.resume_playback_if_paused(allow_center_fallback=True)
        still_paused = ops.is_playback_paused()
        ok = bool(resumed and not still_paused)
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
        if state.get("ad_visible"):
            shot = ops.take_screenshot(f"ep{episode}_after_comment_ad", self.screenshot_dir)
            skipped = ops.skip_ad_if_present(attempts=3)
            if not skipped:
                ops._swipe_up_continue_ad()
            self._log(
                "info" if skipped else "warn",
                f"全流程v3: 第{episode}集评论后遇到广告，已截图 {shot}，跳过广告={skipped}",
            )
            time.sleep(3)
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
        ok = bool(resumed and not still_paused)
        self._log(
            "info" if ok else "warn",
            f"全流程v3: 第{episode}集评论后恢复播放，回播放页={back_to_playback}，原暂停={was_paused}，恢复={resumed}，仍暂停={still_paused}",
        )
        return ok

    def _safe_resume_playback(self, ops: HongguoOperations, episode: int, reason: str) -> bool:
        resumed = ops.resume_playback_safely()
        still_paused = ops.is_playback_paused()
        ok = bool(resumed and not still_paused)
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
        if ops._is_app_foreground():
            return False
        app = ops._safe_app_current()
        first_package = ops._first_visible_package(ops._xml())
        self._log("warn", f"第{episode}集观察时红果不在前台，当前={app.get('package') or '-'}，可见={first_package or '-'}，尝试拉回")
        foreground = ops.bring_to_foreground()
        resumed = ops.resume_playback_if_paused(allow_center_fallback=True)
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

    def _task_rule_snapshot(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "comment_mode": task.get("comment_mode"),
            "start_episode": task.get("start_episode"),
            "episode_interval": task.get("episode_interval"),
            "comment_interval_sec": task.get("comment_interval_sec"),
            "random_comment_count": task.get("random_comment_count"),
            "random_min_interval": task.get("random_min_interval"),
            "random_max_interval": task.get("random_max_interval"),
            "content_source": task.get("content_source"),
            "playback_speed": task.get("playback_speed"),
        }

    def _choose_title(self, keyword: str, titles: Iterable[str]) -> str:
        titles = list(titles)
        for title in titles:
            if self._title_matches(keyword, title):
                return title
        return ""

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
        return re.sub(r"[\s《》<>:：·,，。.!！?？\-_/\\]+", "", str(value or "").lower())

    def _season_marker(self, value: str) -> str:
        match = re.search(r"第([一二三四五六七八九十\d]+)季", value)
        return self._canonical_season_number(match.group(1)) if match else ""

    def _season_stem_matches(self, keyword_key: str, title_key: str) -> bool:
        keyword_stem = self._title_stem(keyword_key)
        title_stem = self._title_stem(title_key)
        if not keyword_stem or not title_stem:
            return False
        return keyword_stem in title_stem or title_stem in keyword_stem

    def _title_stem(self, value: str) -> str:
        return re.sub(r"第[一二三四五六七八九十\d]+季", "", value)

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

    def _log(self, level: str, message: str) -> None:
        try:
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO hongguo_execution_logs (task_id, level, message, created_at)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (self.task_id, level, message, datetime.now()),
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
    ) -> None:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO hongguo_comment_records (
                        task_id, episode_number, comment_text, generated_by,
                        status, screenshot_input, screenshot_verified, error_message, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        self.task_id,
                        episode,
                        content,
                        source,
                        status,
                        screenshot_input or None,
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

    def _update_task(self, **kwargs: Any) -> None:
        if not kwargs:
            return
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

    def start_task(self, task_id: int) -> bool:
        with self._lock:
            engine = self._engines.get(int(task_id))
            if engine and engine.is_alive:
                return False
            engine = TaskEngine(
                task_id=task_id,
                db_config=self._normalized_db_config(),
                screenshot_dir=self._task_screenshot_dir(task_id),
                ai_config=dict(self.ai_config or {}),
                device_addr=self.device_addr,
            )
            self._engines[int(task_id)] = engine
            return engine.start()

    def pause_task(self, task_id: int) -> bool:
        engine = self._engines.get(int(task_id))
        return engine.pause() if engine and engine.is_alive else False

    def resume_task(self, task_id: int) -> bool:
        engine = self._engines.get(int(task_id))
        return engine.resume() if engine and engine.is_alive else False

    def stop_task(self, task_id: int) -> bool:
        engine = self._engines.get(int(task_id))
        return engine.stop() if engine else False

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
