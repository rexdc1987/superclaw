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
from difflib import SequenceMatcher
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
        self._account_info: Dict[str, Any] = {}
        self._comment_persona: Dict[str, Any] = {}
        self._ops: Optional[HongguoOperations] = None
        self._externally_stopped = False

    @property
    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> bool:
        with self._lock:
            if self.is_alive:
                return False
            self._pause_event.clear()
            self._stop_event.clear()
            self._externally_stopped = False
            self._thread = threading.Thread(
                target=self._run,
                name=f"hongguo-task-{self.task_id}",
                daemon=True,
            )
            self._thread.start()
            return True

    def pause(self) -> bool:
        self._pause_event.set()
        if self._ops:
            try:
                if self._ops.pause_playback_if_playing():
                    self._log("info", "红果播放已暂停")
                else:
                    self._log("warn", "任务已暂停，但未确认红果播放器暂停")
            except Exception as exc:
                self._log("warn", f"任务已暂停，但暂停红果播放失败: {exc}")
        self._update_task(status="paused")
        self._log("info", "任务已暂停")
        return True

    def resume(self) -> bool:
        self._pause_event.clear()
        self._resume_playback_check = bool(self._ops)
        self._update_task(status="running")
        self._log("info", "任务已恢复")
        return True

    def stop(self) -> bool:
        self._externally_stopped = True
        self._stop_event.set()
        self._pause_event.clear()
        self._finish_task(status="stopped")
        self._log("info", "任务已停止")
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5)
        return True

    def _run(self) -> None:
        Path(self.screenshot_dir).mkdir(parents=True, exist_ok=True)
        try:
            os.environ.pop("PYTHONPATH", None)
            self._update_task(
                status="running",
                started_at=datetime.now(),
                completed_at=None,
                duration_seconds=None,
                error_message=None,
                current_episode=0,
                total_episodes=0,
                comments_sent=0,
                comments_verified=0,
                execution_plan_json=None,
            )
            self._log("info", "正在连接模拟器")
            if not check_connection(self.device_addr):
                message = f"device {self.device_addr} not online"
                self._finish_task(status="failed", error_message=message)
                self._log("error", message)
                return
            device = connect(self.device_addr)
            self._log("info", f"已连接设备: {getattr(device, 'serial', self.device_addr)}")
            ops = HongguoOperations(device)
            self._ops = ops

            task = self._load_task()
            if not task:
                raise RuntimeError("任务不存在")
            self._log("info", f"任务配置已加载: {task.get('drama_name')}")

            self._check_pause_stop()
            self._log("info", "重启红果短剧")
            if not ops.launch_app(force_restart=True):
                failure_path = ops.take_screenshot("launch_failed", self.screenshot_dir)
                try:
                    current = ops.d.app_current()
                    texts = ops._extract_xml_texts(ops._xml())[:8]
                    self._log(
                        "error",
                        f"红果启动失败详情: package={current.get('package')}, "
                        f"activity={current.get('activity')}, visible_texts={texts}, screenshot={failure_path}",
                    )
                except Exception as detail_exc:
                    self._log("error", f"红果启动失败详情采集失败: {detail_exc}, screenshot={failure_path}")
                raise RuntimeError("红果短剧启动失败")
            ops.take_screenshot("launch", self.screenshot_dir)

            login = self._confirm_login(ops)
            self._log("info", f"登录检测: {login.get('message')}")
            if not login.get("logged_in") and login.get("status") in {"unknown", "playback_only"}:
                self._log("warn", "登录状态暂时无法确认，继续通过搜索和播放流程验证")
                self._update_task(error_message=None)
            elif self._login_requires_wait(login):
                self._update_task(status="waiting_login", error_message=login.get("message"))
                while not self._stop_event.is_set():
                    self._check_pause_stop()
                    time.sleep(5)
                    login = self._confirm_login(ops)
                    self._log("info", f"等待登录检测: {login.get('message')}")
                    if login.get("logged_in"):
                        self._update_task(status="running", error_message=None)
                        break
                self._check_pause_stop()

            self._check_pause_stop()
            self._log("info", f"搜索关键词: {task['drama_name']}")
            try:
                self._account_info = HongguoOperations.normalize_account_info(login.get("account") or ops.get_account_info() or {})
                self._comment_persona = self._resolve_comment_persona(self._account_info)
                nickname = self._account_info.get("nickname") or ("已确认登录账号" if self._account_info.get("logged_in") else "未知账号")
                hongguo_id = self._account_info.get("hongguo_id") or ""
                style = self._comment_persona.get("style") or self._current_ai_config().get("comment_style") or "grounded"
                suffix = f"({hongguo_id})" if hongguo_id else ""
                self._log("info", f"评论账号: {nickname}{suffix}，评论风格: {style}")
            except Exception as exc:
                self._account_info = {}
                self._comment_persona = {}
                self._log("warn", f"评论账号信息读取失败，使用默认人设: {exc}")

            search = ops.search_drama(task["drama_name"], screenshot_dir=self.screenshot_dir)
            if search.get("input_text") is not None:
                self._log("info", f"搜索框实际输入: {search.get('input_text') or '<空>'}")
            if search.get("input_method"):
                self._log("info", f"搜索框输入方式: {search.get('input_method')}")
            if search.get("screenshot_path"):
                self._log("warn", f"搜索输入失败截图: {search.get('screenshot_path')}")
            self._log("info", search.get("message", "搜索完成"))
            if not search.get("success"):
                raise RuntimeError(search.get("message") or "搜索短剧失败")
            ops.take_screenshot("search_results", self.screenshot_dir)

            titles = search.get("titles") or []
            self._log("info", f"搜索结果标题: {titles[:20]}")
            selected_title = self._choose_title(task["drama_name"], titles)
            if not selected_title:
                keyword_key = self._normalize_title_key(task["drama_name"])
                diagnostics = [
                    (title, self._normalize_title_key(title), self._season_marker(self._normalize_title_key(title), keyword_key))
                    for title in titles[:20]
                ]
                self._log("warn", f"标题匹配诊断: keyword_key={keyword_key}, candidates={diagnostics}")
                for title in titles:
                    try:
                        if ops._loose_title_match(task["drama_name"], title):
                            selected_title = title
                            self._log("warn", f"标题主匹配为空，使用播放端兜底匹配: {selected_title}")
                            break
                    except Exception:
                        continue
            if not selected_title:
                raise RuntimeError(f"未找到匹配短剧: {task['drama_name']}")
            self._log("info", f"已匹配搜索标题: {selected_title}")
            if self._season_marker(self._normalize_title_key(task["drama_name"])) and not self._season_marker(
                self._normalize_title_key(selected_title)
            ):
                self._log("warn", f"搜索结果未标注季数，按主标题匹配继续: {selected_title}")
            selected = ops.select_drama(selected_title)
            if not selected.get("success"):
                raise RuntimeError(selected.get("message") or "选择短剧失败")
            if not selected.get("playable"):
                clicked_title = selected.get("clicked_title") or selected_title
                message = selected.get("message") or "短剧不可播放"
                self._log("error", f"短剧不可播放: 目标 {selected_title}，点击 {clicked_title}，原因 {message}")
                raise RuntimeError(f"短剧不可播放: {message}")
            drama_title = selected.get("drama_title") or selected_title or task["drama_name"]
            self._log("info", f"已选择短剧: {drama_title}")
            ops.take_screenshot("drama_detail", self.screenshot_dir)

            total = ops.get_total_episodes()
            if total <= 0:
                ops.play_episode(1)
                time.sleep(2)
                ops.exit_fullscreen()
                total = ops.get_total_episodes() or 1
            self._update_task(total_episodes=total)
            self._log("info", f"检测到总集数: {total}")

            watch_episodes = self._watch_episode_plan(total)
            comment_episodes, skipped_comment_episodes = self._pending_comment_plan(task, total)
            self._update_task(
                execution_plan_json=json.dumps(
                    {
                        "watch_episodes": watch_episodes,
                        "comment_episodes": sorted(comment_episodes),
                        "skipped_comment_episodes": skipped_comment_episodes,
                        "rule": self._task_rule_snapshot(task),
                    },
                    ensure_ascii=False,
                )
            )
            self._log("info", f"刷剧计划: 第1集到第{total}集")
            if skipped_comment_episodes:
                self._log("info", f"已跳过历史成功评论集数: {skipped_comment_episodes}")
            self._log("info", f"评论集数计划: {sorted(comment_episodes)}")
            abort_reason = ""
            missed_comment_episodes: set[int] = set()
            failed_verify_episodes: set[int] = set()
            comment_cache: Dict[int, tuple[str, str, Dict[str, Any]]] = {}
            comment_cache_lock = threading.Lock()
            used_comments = self._used_comment_keys()
            self._start_comment_prewarm(comment_cache, comment_cache_lock, sorted(comment_episodes), drama_title, task)
            current_episode = ops.get_current_episode()
            if current_episode > 1:
                self._log("info", f"检测到当前停留在第{current_episode}集，准备切回第1集")
            if not ops.play_episode(1):
                self._log("warn", "首集播放未确认，准备重试切换第1集")
                time.sleep(2)
                if not ops.play_episode(1):
                    failure_shot = ops.take_screenshot("ep1_play_failed", self.screenshot_dir)
                    self._save_record(1, "", "ai", "failed", screenshot_input=failure_shot, error_message="首集播放失败")
                    raise RuntimeError("首集播放失败")
            desired_speed = str(task.get("playback_speed") or "1.0x")
            if desired_speed != "1.0x":
                self._log("info", f"准备设置倍速: {desired_speed}")
                if ops.set_playback_speed(desired_speed):
                    self._log("info", f"倍速已设置: {desired_speed}")
                else:
                    self._log("warn", f"倍速设置失败，继续使用当前倍速: {desired_speed}")
            self._log("info", "首集播放已触发，开始确认当前播放状态")
            if not self._wait_for_episode(ops, 1, task):
                self._log("warn", "首集播放状态确认不足，将继续观察自动跳集")

            for episode in watch_episodes:
                self._check_pause_stop()
                current_before_wait = ops.get_current_episode()
                if current_before_wait and current_before_wait > episode:
                    if self._large_jump_crosses_comment_plan(episode, current_before_wait, comment_episodes):
                        self._log(
                            "warn",
                            f"检测到集数从第{episode}集异常跳到第{current_before_wait}集，先尝试恢复到第{episode}集",
                        )
                        if not self._recover_episode_position(ops, episode, task):
                            failure_shot = ops.take_screenshot(f"ep{episode}_jump_recover_failed", self.screenshot_dir)
                            self._save_record(
                                episode,
                                "",
                                "ai",
                                "failed",
                                screenshot_input=failure_shot,
                                error_message=f"异常跳集到第{current_before_wait}集，恢复第{episode}集失败",
                            )
                            self._log("error", f"异常跳集到第{current_before_wait}集，恢复第{episode}集失败")
                            continue
                        current_before_wait = ops.get_current_episode()
                        if not current_before_wait or current_before_wait <= episode:
                            self._log("info", f"已从异常跳集恢复到第{episode}集附近")
                        else:
                            continue
                    if episode in comment_episodes and episode not in missed_comment_episodes:
                        missed_comment_episodes.add(episode)
                        failure_shot = ops.take_screenshot(f"ep{episode}_auto_skipped", self.screenshot_dir)
                        self._save_record(
                            episode,
                            "",
                            "ai",
                            "failed",
                            screenshot_input=failure_shot,
                            error_message=f"已自动跳到第{current_before_wait}集，错过第{episode}集评论窗口",
                        )
                        self._log("warn", f"已自动跳到第{current_before_wait}集，错过第{episode}集评论窗口")
                    continue
                self._log("info", f"准备确认第{episode}集播放状态")
                if not self._wait_for_episode(ops, episode, task) and not self._recover_episode_position(ops, episode, task):
                    current_after_wait = ops.get_current_episode()
                    if current_after_wait and current_after_wait > episode:
                        if episode in comment_episodes and episode not in missed_comment_episodes:
                            missed_comment_episodes.add(episode)
                            failure_shot = ops.take_screenshot(f"ep{episode}_auto_skipped", self.screenshot_dir)
                            self._save_record(
                                episode,
                                "",
                                "ai",
                                "failed",
                                screenshot_input=failure_shot,
                                error_message=f"已自动跳到第{current_after_wait}集，错过第{episode}集评论窗口",
                            )
                            self._log("warn", f"已自动跳到第{current_after_wait}集，错过第{episode}集评论窗口")
                        continue
                    failure_shot = ops.take_screenshot(f"ep{episode}_play_failed", self.screenshot_dir)
                    self._save_record(episode, "", "ai", "failed", screenshot_input=failure_shot, error_message="等待当前集播放失败")
                    self._log("error", f"第{episode}集播放状态未能确认")
                    continue
                confirmed = ops.get_current_episode()
                if confirmed != episode:
                    failure_shot = ops.take_screenshot(f"ep{episode}_confirm_mismatch", self.screenshot_dir)
                    self._save_record(
                        episode,
                        "",
                        "ai",
                        "failed",
                        screenshot_input=failure_shot,
                        error_message=f"集数确认不一致: 目标第{episode}集，实际第{confirmed or 0}集",
                    )
                    self._log("error", f"集数确认不一致: 目标第{episode}集，实际第{confirmed or 0}集")
                    continue
                self._update_task(current_episode=episode)
                self._log("info", f"正在刷第{episode}集")

                if episode not in comment_episodes:
                    if episode < total and not self._wait_for_next_episode(ops, episode, task):
                        current_after_next = ops.get_current_episode()
                        if current_after_next and current_after_next > episode:
                            if self._large_jump_crosses_comment_plan(episode, current_after_next, comment_episodes):
                                self._log(
                                    "warn",
                                    f"第{episode}集后检测到异常跳到第{current_after_next}集，准备恢复到第{episode + 1}集",
                                )
                                if self._recover_episode_position(ops, episode + 1, task):
                                    self._log("info", f"已从异常跳集恢复到第{episode + 1}集")
                                    continue
                                failure_shot = ops.take_screenshot(f"ep{episode}_large_jump_recover_failed", self.screenshot_dir)
                                self._save_record(
                                    episode,
                                    "",
                                    "ai",
                                    "failed",
                                    screenshot_input=failure_shot,
                                    error_message=f"第{episode}集后异常跳到第{current_after_next}集，恢复第{episode + 1}集失败",
                                )
                                abort_reason = f"异常跳集到第{current_after_next}集且恢复失败，停止继续刷剧"
                                self._log("error", abort_reason)
                                break
                            skipped_planned = [
                                item
                                for item in sorted(comment_episodes)
                                if episode < item < current_after_next and item not in missed_comment_episodes
                            ]
                            for missed_episode in skipped_planned:
                                missed_comment_episodes.add(missed_episode)
                                failure_shot = ops.take_screenshot(
                                    f"ep{missed_episode}_auto_skipped",
                                    self.screenshot_dir,
                                )
                                self._save_record(
                                    missed_episode,
                                    "",
                                    "ai",
                                    "failed",
                                    screenshot_input=failure_shot,
                                    error_message=(
                                        f"第{episode}集后已自动跳到第{current_after_next}集，"
                                        f"错过第{missed_episode}集评论窗口"
                                    ),
                                )
                                self._log(
                                    "warn",
                                    f"第{episode}集后已自动跳到第{current_after_next}集，错过第{missed_episode}集评论窗口",
                                )
                            self._log("warn", f"第{episode}集后已自动跳到第{current_after_next}集，继续追踪当前进度")
                            continue
                        self._log("warn", f"第{episode}集未能自动跳到下一集，准备恢复到第{episode + 1}集")
                        if not self._recover_episode_position(ops, episode + 1, task):
                            failure_shot = ops.take_screenshot(f"ep{episode}_next_failed", self.screenshot_dir)
                            self._save_record(episode, "", "ai", "failed", screenshot_input=failure_shot, error_message="等待下一集失败")
                            abort_reason = f"未能恢复到第{episode + 1}集，停止继续刷剧"
                            self._log("error", abort_reason)
                            break
                    else:
                        self._log("info", f"第{episode}集未命中评论规则，继续下一集")
                    continue

                self._log("info", f"第{episode}集命中评论规则，准备生成评论")
                content, source, usage = self._comment_for_episode(
                    comment_cache,
                    comment_cache_lock,
                    episode,
                    drama_title,
                    task,
                )
                content, source = self._safe_comment_content(content, source, drama_title)
                content, source = self._dedupe_comment(content, source, used_comments, drama_title)
                if usage:
                    record_usage(usage, context=f"task:{self.task_id}:episode:{episode}")
                self._log("info", f"评论内容已生成: {source}")
                if not self._wait_safe_comment_window(ops, episode, task):
                    missed_comment_episodes.add(episode)
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
                    self._recover_episode_position(ops, episode + 1, task)
                    continue
                input_path = ops.take_screenshot(f"ep{episode}_before_comment", self.screenshot_dir)
                post = ops.post_comment(content, episode, self.screenshot_dir)
                if not post.get("success"):
                    missed_comment_episodes.add(episode)
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
                sent_path = post.get("screenshot_path") or ops.take_screenshot(f"ep{episode}_after_comment", self.screenshot_dir)
                verify = ops.verify_comment(content, episode, self.screenshot_dir)
                verify_path = verify.get("screenshot_path") or ops.take_screenshot(
                    f"ep{episode}_{'verified' if verify.get('verified') else 'not_found'}",
                    self.screenshot_dir,
                )
                status = "success" if verify.get("verified") else "failed"
                error = None if verify.get("verified") else verify.get("message", "评论验证失败")
                self._save_record(episode, content, source, status, input_path, verify_path, error, sent_path)
                if status == "success":
                    self._increment_counter("verified")
                else:
                    failed_verify_episodes.add(episode)
                level = "info" if status == "success" else "error"
                message = "评论验证成功" if status == "success" else "评论验证失败"
                self._log(level, message)
                current_after_comment = ops.get_current_episode()
                if not current_after_comment or current_after_comment <= episode:
                    ops.ensure_playback_page(episode)

                if episode < total and not self._wait_for_next_episode(ops, episode, task):
                    self._recover_episode_position(ops, episode + 1, task)
                    self._log("warn", f"第{episode}集评论后未能自动跳到下一集")

            if self._stop_event.is_set():
                self._finish_task(status="stopped")
                self._log("info", "任务已停止")
            elif abort_reason:
                self._finish_task(status="failed", error_message=abort_reason)
                self._log("error", f"任务失败: {abort_reason}")
            elif missed_comment_episodes:
                missed = sorted(missed_comment_episodes)
                message = f"计划评论集数漏发: {missed}"
                self._finish_task(status="failed", error_message=message)
                self._log("error", f"任务失败: {message}")
            elif failed_verify_episodes:
                failed = sorted(failed_verify_episodes)
                message = f"计划评论集数验证失败: {failed}"
                self._finish_task(status="failed", error_message=message)
                self._log("error", f"任务失败: {message}")
            else:
                self._finish_task(status="completed")
                self._log("info", "任务执行完成")
        except StopRequested:
            if not self._externally_stopped:
                self._finish_task(status="stopped")
                self._log("info", "任务已停止")
        except Exception as exc:
            self._finish_task(status="failed", error_message=str(exc))
            self._log("error", f"任务失败: {exc}")
        finally:
            self._ops = None

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

    def _comment_for_episode(
        self,
        cache: Dict[int, tuple[str, str, Dict[str, Any]]],
        cache_lock: threading.Lock,
        episode: int,
        drama_title: str,
        task: Dict[str, Any],
    ) -> tuple[str, str, Dict[str, Any]]:
        with cache_lock:
            cached = cache.get(episode)
        if cached:
            return cached
        generator = CommentGenerator(self._current_ai_config())
        templates = self._templates(task)
        source = str(task.get("content_source") or "ai")
        if templates and source in {"template", "mixed"}:
            result = (generator.pick_template(templates, drama_title), "template", {})
        else:
            result = (generator._generate_local_comment(drama_title), "local", {})
        with cache_lock:
            cache[episode] = result
        return result

    def _normalize_comment_key(self, content: str) -> str:
        return re.sub(r"[\s，,。.!！?？~～、；;：:\"'“”‘’《》<>（）()]+", "", content or "").lower()

    def _comment_is_duplicate(self, comment_key: str, used_comments: set[str]) -> bool:
        if not comment_key:
            return True
        if comment_key in used_comments:
            return True
        for used in used_comments:
            if not used:
                continue
            shorter = min(len(comment_key), len(used))
            if shorter >= 10 and (comment_key in used or used in comment_key):
                return True
            if shorter >= 14 and SequenceMatcher(None, comment_key, used).ratio() >= 0.86:
                return True
        return False

    def _dedupe_comment(self, content: str, source: str, used_comments: set[str], drama_title: str) -> tuple[str, str]:
        normalized = self._normalize_comment_key(content)
        if not self._comment_is_duplicate(normalized, used_comments):
            used_comments.add(normalized)
            return content, source
        generator = CommentGenerator(self._current_ai_config())
        for _ in range(5):
            candidate = generator._generate_local_comment(drama_title)
            candidate_key = self._normalize_comment_key(candidate)
            if not self._comment_is_duplicate(candidate_key, used_comments):
                used_comments.add(candidate_key)
                return candidate, "local"
        suffixes = ["这集也很稳", "继续追下去", "越看越上头", "剧情很带感"]
        for suffix in suffixes:
            candidate = f"{(content or '').rstrip('。！!~～')}{suffix}"
            candidate_key = self._normalize_comment_key(candidate)
            if not self._comment_is_duplicate(candidate_key, used_comments):
                used_comments.add(candidate_key)
                return candidate, "local"
        if normalized:
            used_comments.add(normalized)
        return content, source

    def _safe_comment_content(self, content: str, source: str, drama_title: str) -> tuple[str, str]:
        generator = CommentGenerator(self._current_ai_config())
        try:
            return generator._clean_comment(content, title=drama_title), source
        except Exception as exc:
            self._log("warn", f"评论内容安全校验失败，已回退本地评论: {exc}")
            return generator._generate_local_comment(drama_title), "local"

    def _start_comment_prewarm(
        self,
        cache: Dict[int, tuple[str, str, Dict[str, Any]]],
        cache_lock: threading.Lock,
        episodes: List[int],
        drama_title: str,
        task: Dict[str, Any],
    ) -> None:
        if not episodes:
            return

        def worker() -> None:
            for episode in episodes:
                if self._stop_event.is_set():
                    return
                with cache_lock:
                    if episode in cache:
                        continue
                try:
                    generator = CommentGenerator(self._current_ai_config())
                    result = generator.generate_with_usage(
                        drama_title,
                        task.get("content_source", "ai"),
                        self._templates(task),
                    )
                    with cache_lock:
                        cache.setdefault(episode, result)
                except Exception as exc:
                    self._log("warn", f"预生成第{episode}集评论失败，将在发布前重试: {exc}")

        threading.Thread(
            target=worker,
            name=f"hongguo-comment-prewarm-{self.task_id}",
            daemon=True,
        ).start()

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
        # Comment episodes can be very short at 2x/3x speed; publish near the
        # beginning of the target episode so the comment cannot drift to next one.
        safe_cap = max(1, int(5 / max(1.0, speed)))
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

    def _watch_episode_plan(self, total: int) -> List[int]:
        total = max(1, int(total or 1))
        return list(range(1, total + 1))

    def _current_playing_title(self, ops: HongguoOperations) -> str:
        getter = getattr(ops, "_current_playing_title", None)
        if not callable(getter):
            return ""
        try:
            return str(getter() or "").strip()
        except Exception:
            return ""

    def _wait_for_episode(self, ops: HongguoOperations, episode: int, task: Dict[str, Any]) -> bool:
        deadline = time.time() + max(40, int(task.get("comment_interval_sec") or 30) + 90)
        while time.time() < deadline:
            self._check_pause_stop()
            self._resume_playback_if_needed(ops)
            if self._restore_app_surface_if_needed(ops):
                time.sleep(1)
                continue
            if self._skip_feed_ad_if_visible(ops):
                self._log("warn", "检测到追剧广告，已尝试上滑继续观看短剧")
                time.sleep(1)
                continue
            current_title = self._current_playing_title(ops)
            if self._off_target_title(ops, task, current_title):
                self._log("warn", f"当前播放已偏离目标短剧: {current_title}")
                return False
            current = ops.get_current_episode()
            if current == episode:
                return self._confirm_episode_on_target(ops, episode, task)
            if current and current > episode:
                return False
            time.sleep(2)
        return False

    def _wait_for_next_episode(self, ops: HongguoOperations, episode: int, task: Dict[str, Any]) -> bool:
        timeout = int(task.get("comment_interval_sec") or 30)
        wait_seconds = max(90, timeout + 90)
        deadline = time.time() + wait_seconds
        target = episode + 1
        same_episode_since: Optional[float] = None
        resume_attempted = False
        target_attempted = False
        resume_after = max(45, int(wait_seconds * 0.45))
        target_after = max(resume_after + 20, int(wait_seconds * 0.75))
        allow_force_next = bool(task.get("force_next_on_stuck", False))
        while time.time() < deadline:
            self._check_pause_stop()
            self._resume_playback_if_needed(ops)
            if self._restore_app_surface_if_needed(ops):
                time.sleep(1)
                continue
            if self._skip_feed_ad_if_visible(ops):
                self._log("warn", "检测到追剧广告，已尝试上滑继续观看短剧")
                time.sleep(1)
                continue
            current_title = self._current_playing_title(ops)
            if self._off_target_title(ops, task, current_title):
                self._log("warn", f"等待下一集时偏离目标短剧: {current_title}")
                return False
            current = ops.get_current_episode()
            if current >= target:
                return self._confirm_episode_on_target(ops, current, task)
            if current and current < episode:
                return False
            if current == episode and ops._playback_visible():
                if same_episode_since is None:
                    same_episode_since = time.time()
                elif not resume_attempted and time.time() - same_episode_since >= resume_after:
                    if ops.resume_playback_if_paused(allow_center_fallback=False):
                        self._log("warn", f"第{episode}集长时间未跳转，已尝试继续播放")
                    resume_attempted = True
                elif not target_attempted and allow_force_next and time.time() - same_episode_since >= target_after:
                    self._log("warn", f"第{episode}集仍未跳转，按配置兜底切到第{target}集")
                    if ops.play_episode(target):
                        return self._wait_for_episode(ops, target, task)
                    target_attempted = True
                elif not target_attempted and not allow_force_next and time.time() - same_episode_since >= target_after:
                    self._log("warn", f"第{episode}集仍未自动跳转，继续等待自然播放完成")
                    target_attempted = True
                time.sleep(2)
                continue
            time.sleep(2)
        return False

    def _confirm_episode_on_target(self, ops: HongguoOperations, episode: int, task: Dict[str, Any]) -> bool:
        if not str(task.get("drama_name") or "").strip():
            return True
        for attempt in range(3):
            title = self._current_playing_title(ops)
            if self._off_target_title(ops, task, title):
                self._log("warn", f"第{episode}集标题确认偏离目标短剧: {title}")
                return False
            if title:
                return True
            if attempt < 2:
                time.sleep(1)
        return True

    def _large_jump_crosses_comment_plan(self, episode: int, current: int, comment_episodes: Iterable[int]) -> bool:
        if current <= episode + 1:
            return False
        crossed = [item for item in comment_episodes if episode < int(item) < current]
        return len(crossed) >= 2

    def _resume_playback_if_needed(self, ops: HongguoOperations) -> None:
        if not self._resume_playback_check:
            return
        self._resume_playback_check = False
        if ops.resume_playback_if_paused(allow_center_fallback=False):
            self._log("info", "恢复后已尝试继续播放")

    def _skip_feed_ad_if_visible(self, ops: HongguoOperations) -> bool:
        skipper = getattr(ops, "skip_feed_ad_if_visible", None)
        if not callable(skipper):
            return False
        try:
            return bool(skipper())
        except Exception:
            return False

    def _restore_app_surface_if_needed(self, ops: HongguoOperations) -> bool:
        checker = getattr(ops, "_known_not_foreground", None)
        if not callable(checker):
            return False
        try:
            off_surface = bool(checker())
        except Exception:
            return False
        if not off_surface:
            return False
        restarter = getattr(ops, "ensure_app_ready", None)
        if not callable(restarter):
            return False
        try:
            restored = bool(restarter(restart=True, timeout=12))
        except Exception:
            restored = False
        if restored:
            self._log("warn", "检测到红果已离开播放页，已重新拉起红果")
            return True
        self._log("warn", "检测到红果已离开播放页，重新拉起失败")
        return False

    def _recover_episode_position(self, ops: HongguoOperations, episode: int, task: Dict[str, Any]) -> bool:
        self._log("warn", f"尝试恢复到第{episode}集")
        target_researched = False
        for _ in range(2):
            self._check_pause_stop()
            if self._restore_app_surface_if_needed(ops):
                time.sleep(1)
                continue
            current_title = self._current_playing_title(ops)
            if self._off_target_title(ops, task, current_title):
                self._log("warn", f"当前在非目标短剧《{current_title}》，准备重新搜索目标短剧")
                target_researched = True
                if self._recover_target_drama(ops, episode, task):
                    self._log("info", f"已重新回到目标短剧第{episode}集")
                    return True
            if ops.ensure_playback_page(episode):
                if self._wait_for_episode(ops, episode, task):
                    self._log("info", f"已恢复到第{episode}集")
                    return True
            current_title = self._current_playing_title(ops)
            if self._off_target_title(ops, task, current_title):
                self._log("warn", f"恢复第{episode}集后仍在非目标短剧《{current_title}》，重新搜索目标短剧")
                target_researched = True
                if self._recover_target_drama(ops, episode, task):
                    self._log("info", f"已重新回到目标短剧第{episode}集")
                    return True
            time.sleep(2)
        if not target_researched:
            self._log("warn", f"常规恢复第{episode}集失败，改用重新搜索目标短剧恢复")
            self._restore_app_surface_if_needed(ops)
            if self._recover_target_drama(ops, episode, task):
                self._log("info", f"已重新回到目标短剧第{episode}集")
                return True
        self._log("error", f"恢复到第{episode}集失败")
        return False

    def _off_target_title(self, ops: HongguoOperations, task: Dict[str, Any], current_title: str) -> bool:
        if not current_title:
            return False
        expected = str(task.get("drama_name") or "").strip()
        return bool(expected and not ops._loose_title_match(expected, current_title))

    def _recover_target_drama(self, ops: HongguoOperations, episode: int, task: Dict[str, Any]) -> bool:
        keyword = str(task.get("drama_name") or "").strip()
        if not keyword:
            return False
        self._check_pause_stop()
        self._restore_app_surface_if_needed(ops)
        try:
            search = ops.search_drama(keyword, force_reset=True, screenshot_dir=self.screenshot_dir)
        except TypeError:
            search = ops.search_drama(keyword, force_reset=True)
        if not search.get("success") and "搜索入口" in str(search.get("message") or ""):
            self._log("warn", "重新搜索未找到入口，尝试重新拉起红果后再搜索")
            self._restore_app_surface_if_needed(ops)
            try:
                search = ops.search_drama(keyword, force_reset=True, screenshot_dir=self.screenshot_dir)
            except TypeError:
                search = ops.search_drama(keyword, force_reset=True)
        self._check_pause_stop()
        if not search.get("success"):
            if search.get("screenshot_path"):
                self._log("warn", f"重新搜索输入失败截图: {search.get('screenshot_path')}")
            self._log("warn", f"重新搜索目标短剧失败: {search.get('message') or '搜索失败'}")
            return False
        titles = search.get("titles") or []
        selected_title = self._choose_title(keyword, titles) or (titles[0] if titles else keyword)
        selected = ops.select_drama(selected_title)
        self._check_pause_stop()
        if not selected.get("success") or not selected.get("playable"):
            self._log("warn", f"重新选择目标短剧失败: {selected.get('message') or selected_title}")
            return False
        if not ops.play_episode(episode):
            return False
        self._check_pause_stop()
        if not self._wait_for_episode(ops, episode, task):
            return False
        return self._verify_recovered_target(ops, episode, task)

    def _verify_recovered_target(self, ops: HongguoOperations, episode: int, task: Dict[str, Any]) -> bool:
        for attempt in range(3):
            self._check_pause_stop()
            current = ops.get_current_episode()
            title = self._current_playing_title(ops)
            if self._off_target_title(ops, task, title):
                self._log("warn", f"恢复第{episode}集稳定校验失败，当前短剧: {title}")
                return False
            if current == episode and (title or attempt >= 1):
                return True
            time.sleep(1)
        return False

    def _comment_episode_plan(self, task: Dict[str, Any], total: int) -> List[int]:
        total = max(1, int(total or 1))
        if task.get("comment_mode") == "random":
            count = min(int(task.get("random_comment_count") or 1), total)
            return sorted(random.sample(range(1, total + 1), count))
        start = max(1, int(task.get("start_episode") or 1))
        interval = max(1, int(task.get("episode_interval") or 1))
        return list(range(start, total + 1, interval))

    def _pending_comment_plan(self, task: Dict[str, Any], total: int) -> tuple[set[int], List[int]]:
        raw_comment_episodes = set(self._comment_episode_plan(task, total))
        completed_comment_episodes = self._completed_comment_episodes()
        skipped_comment_episodes = sorted(raw_comment_episodes & completed_comment_episodes)
        return raw_comment_episodes - completed_comment_episodes, skipped_comment_episodes

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
        keyword_key = self._normalize_title_key(keyword)
        for title in titles:
            if self._normalize_title_key(title) == keyword_key:
                return title
        expected_season = self._season_marker(keyword_key)
        if not expected_season:
            for title in titles:
                title_key = self._normalize_title_key(title)
                if title_key.startswith(keyword_key) and self._season_equivalent("", self._season_marker(title_key, keyword_key)):
                    return title
        else:
            for title in titles:
                title_key = self._normalize_title_key(title)
                if self._strip_season_marker(title_key).startswith(self._strip_season_marker(keyword_key)):
                    if self._season_equivalent(
                        expected_season,
                        self._season_marker(title_key, self._strip_season_marker(keyword_key)),
                    ):
                        return title
        for title in titles:
            if self._title_matches(keyword, title):
                return title
        return ""

    def _title_matches(self, keyword: str, title: str) -> bool:
        keyword_key = self._normalize_title_key(keyword)
        title_key = self._normalize_title_key(title)
        if not keyword_key or not title_key:
            return False
        season = self._season_marker(keyword_key)
        keyword_base = self._strip_season_marker(keyword_key)
        title_season = self._season_marker(title_key, keyword_base)
        if title_season and not self._season_equivalent(season, title_season):
            return False
        if keyword_key in title_key:
            return True
        title_base = self._strip_season_marker(title_key)
        if len(keyword_base) >= 4 and keyword_base in title_key:
            return True
        if any(part in title_key for part in self._title_core_parts(keyword_base)):
            return True
        return title_base in keyword_key and len(title_base) >= 4

    def _normalize_title_key(self, value: str) -> str:
        cleaned = re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", str(value or ""))
        return re.sub(r"[\s《》<>:：·,，。.!！?？\-_/\\]+", "", cleaned.lower())

    def _season_marker(self, value: str, base: str = "") -> str:
        match = re.search(r"第([一二三四五六七八九十\d]+)季", value)
        if match:
            return match.group(1)
        if base:
            suffix = re.match(rf"{re.escape(base)}(\d+)(?:$|[\u4e00-\u9fff])", value or "")
            if suffix:
                return suffix.group(1)
        suffix = re.match(r"[\u4e00-\u9fff]{2,}(\d+)$", value or "")
        if suffix:
            return suffix.group(1)
        return ""

    def _season_equivalent(self, expected: str, actual: str) -> bool:
        expected_value = self._normalize_season_value(expected)
        actual_value = self._normalize_season_value(actual)
        if not expected_value and actual_value == "1":
            return True
        if expected_value == "1" and not actual_value:
            return True
        return expected_value == actual_value

    def _strip_season_marker(self, value: str) -> str:
        text = re.sub(r"第[一二三四五六七八九十\d]+季", "", value or "")
        return re.sub(r"(?<=[\u4e00-\u9fff])\d+$", "", text)

    def _normalize_season_value(self, value: str) -> str:
        text = str(value or "").strip().lower()
        numerals = {
            "一": "1",
            "二": "2",
            "两": "2",
            "三": "3",
            "四": "4",
            "五": "5",
            "六": "6",
            "七": "7",
            "八": "8",
            "九": "9",
            "十": "10",
        }
        return numerals.get(text, text)

    def _title_core_parts(self, value: str) -> List[str]:
        parts: List[str] = []
        text = self._strip_season_marker(value)
        if len(text) >= 4:
            parts.append(text)
        for size in range(min(6, len(text)), 3, -1):
            for idx in range(0, len(text) - size + 1):
                part = text[idx : idx + size]
                if part not in parts:
                    parts.append(part)
        return parts[:8]

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
        rule_updated_at = self._rule_updated_at(task)
        where = "task_id=%s AND status='success'"
        params: List[Any] = [self.task_id]
        if rule_updated_at:
            where += " AND created_at >= %s"
            params.append(rule_updated_at)
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT episode_number
                    FROM hongguo_comment_records
                    WHERE {where}
                    """,
                    params,
                )
                for row in cur.fetchall():
                    episode = row.get("episode_number")
                    if isinstance(episode, int) and episode > 0:
                        episodes.add(episode)
        return episodes

    def _used_comment_keys(self) -> set[str]:
        comments: set[str] = set()
        try:
            task = self._load_task()
            rule_updated_at = self._rule_updated_at(task)
            where = "task_id=%s AND status='success' AND comment_text IS NOT NULL"
            params: List[Any] = [self.task_id]
            if rule_updated_at:
                where += " AND created_at >= %s"
                params.append(rule_updated_at)
            with self._connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT comment_text
                        FROM hongguo_comment_records
                        WHERE {where}
                        """,
                        params,
                    )
                    for row in cur.fetchall():
                        key = self._normalize_comment_key(row.get("comment_text") or "")
                        if key:
                            comments.add(key)
        except Exception:
            return comments
        return comments

    def _rule_updated_at(self, task: Optional[Dict[str, Any]]) -> Any:
        if not task:
            return None
        return task.get("rule_updated_at") or task.get("updated_at") or task.get("created_at")

    def _load_task(self) -> Optional[Dict[str, Any]]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM hongguo_comment_tasks WHERE id=%s", (self.task_id,))
                return cur.fetchone()

    def _confirm_login(self, ops: HongguoOperations) -> Dict[str, Any]:
        login = ops.check_login() or {}
        account: Dict[str, Any] = {}
        if login.get("logged_in") or login.get("status") in {"playback_only", "unknown"}:
            account = HongguoOperations.normalize_account_info(ops.get_account_info() or {})
            if account.get("logged_in"):
                return {
                    **login,
                    "logged_in": True,
                    "status": "logged_in",
                    "message": account.get("message") or "已登录",
                    "account": account,
                }
            if login.get("logged_in"):
                return {
                    **login,
                    "logged_in": False,
                    "status": "not_logged_in",
                    "message": account.get("message") or "未确认红果账号登录",
                    "account": account,
                }
        if account:
            login = {**login, "account": account}
        return login

    def _login_requires_wait(self, login: Dict[str, Any]) -> bool:
        if login.get("logged_in"):
            return False
        return login.get("status") not in {"unknown", "playback_only"}

    def _base_ai_config(self) -> Dict[str, Any]:
        manager = TaskEngineManager.get_instance()
        return dict(manager.ai_config or self.ai_config or {})

    def _resolve_comment_persona(self, account: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self._base_ai_config()
        result = {
            "persona": str(cfg.get("default_persona") or "").strip(),
            "style": str(cfg.get("comment_style") or "grounded").strip(),
            "matched": False,
        }
        account_id = str(account.get("hongguo_id") or "").strip()
        nickname = str(account.get("nickname") or "").strip()
        personas = cfg.get("account_personas") or []
        if not isinstance(personas, list):
            return result
        for item in personas:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("hongguo_id") or "").strip()
            item_name = str(item.get("nickname") or "").strip()
            if (item_id and account_id and item_id == account_id) or (item_name and nickname and item_name == nickname):
                persona = str(item.get("persona") or "").strip()
                style = str(item.get("style") or "").strip()
                if persona:
                    result["persona"] = persona
                if style:
                    result["style"] = style
                result["matched"] = True
                break
        return result

    def _current_ai_config(self) -> Dict[str, Any]:
        cfg = self._base_ai_config()
        if self._account_info:
            cfg["account_info"] = dict(self._account_info)
        if self._comment_persona:
            cfg["comment_persona"] = dict(self._comment_persona)
        return cfg

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
        screenshot_sent: str = "",
    ) -> None:
        now = datetime.now()
        sent_at = now if screenshot_sent and content else None
        verified_at = now if status == "success" else None
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
                        now,
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

    def _finish_task(self, status: str, error_message: Optional[str] = None) -> None:
        completed_at = datetime.now()
        started_at = None
        try:
            task = self._load_task()
            started_at = task.get("started_at") if task else None
        except Exception:
            started_at = None
        duration_seconds = None
        if started_at:
            duration_seconds = max(0, int((completed_at - started_at).total_seconds()))
        updates: Dict[str, Any] = {
            "status": status,
            "completed_at": completed_at,
            "duration_seconds": duration_seconds,
        }
        if error_message is not None:
            updates["error_message"] = error_message
        self._update_task(**updates)
        try:
            self._log("info", f"执行总时长: {self._format_duration(duration_seconds)}，状态: {self._status_label(status)}")
        except Exception:
            pass

    @staticmethod
    def _format_duration(seconds: Optional[int]) -> str:
        if seconds is None:
            return "-"
        seconds = max(0, int(seconds))
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours}小时{minutes}分{secs}秒"
        if minutes:
            return f"{minutes}分{secs}秒"
        return f"{secs}秒"

    @staticmethod
    def _status_label(status: str) -> str:
        return {
            "completed": "已完成",
            "failed": "失败",
            "stopped": "已停止",
            "paused": "已暂停",
            "running": "执行中",
        }.get(status, status)

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
