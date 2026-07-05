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

    def _run(self) -> None:
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
        if season and self._season_marker(title_key) != season:
            return False
        return title_key in keyword_key and len(title_key) >= 4

    def _normalize_title_key(self, value: str) -> str:
        return re.sub(r"[\s《》<>:：·,，。.!！?？\-_/\\]+", "", str(value or "").lower())

    def _season_marker(self, value: str) -> str:
        match = re.search(r"第([一二三四五六七八九十\d]+)季", value)
        return match.group(1) if match else ""

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
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT episode_number
                    FROM hongguo_comment_records
                    WHERE task_id=%s AND status='success'
                    """,
                    (self.task_id,),
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
