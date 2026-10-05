"""Continue an existing Hongguo task without resetting verified comments."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pymysql

from rpa.dashboard.routes_hongguo import _ai_config, _db_config
from rpa.hongguo.device import connect
from rpa.hongguo.engine import DEFAULT_SCREENSHOT_ROOT, TaskEngine
from rpa.hongguo.operations import HongguoOperations


def load_task(task_id: int, db_config: dict) -> dict:
    with pymysql.connect(**db_config) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM hongguo_comment_tasks WHERE id=%s LIMIT 1", (task_id,))
            task = cur.fetchone()
    if not task:
        raise RuntimeError(f"Hongguo task {task_id} does not exist")
    return dict(task)


def continue_task(task_id: int, start_episode: int) -> None:
    db_config = _db_config()
    task = load_task(task_id, db_config)
    total = int(task.get("total_episodes") or 0)
    if total <= 0:
        raise RuntimeError("Task total episode count is unavailable")

    engine = TaskEngine(
        task_id=task_id,
        db_config=db_config,
        screenshot_dir=str((Path(DEFAULT_SCREENSHOT_ROOT) / str(task_id)).as_posix()),
        ai_config=_ai_config(),
        device_addr=str(task.get("device_addr") or "").strip(),
    )
    plan = json.loads(task.get("execution_plan_json") or "{}")
    planned_comments = set(int(value) for value in plan.get("comment_episodes") or [])
    completed_comments = engine._completed_comment_episodes()
    pending_comments = planned_comments - completed_comments
    drama_title = str(task.get("drama_name") or "")
    start_episode = min(max(1, int(start_episode)), total)

    now = datetime.now()
    engine._update_task(
        status="running",
        current_episode=start_episode,
        completed_at=None,
        error_message=None,
        updated_at=now,
    )
    engine._log(
        "info",
        f"全流程v3续跑: 从第{start_episode}集继续，待验证评论集数={sorted(pending_comments)}",
    )

    try:
        ops = HongguoOperations(connect(engine.device_addr))
        if not engine._recover_to_verified_episode(
            ops,
            task,
            start_episode,
            total,
            "续跑入口恢复目标剧集",
        ):
            raise RuntimeError(f"续跑无法恢复到第{start_episode}集")

        desired_speed = str(task.get("playback_speed") or "1.0x")
        if desired_speed != "1.0x":
            speed_set = ops.set_playback_speed(desired_speed)
            engine._log(
                "info" if speed_set else "warn",
                f"全流程v3续跑: 倍速设置 {desired_speed} = {speed_set}",
            )

        for episode in range(start_episode, total + 1):
            engine._check_pause_stop()
            state = engine._page_state(ops, task)
            current = int(state.get("current_episode") or 0)
            if current != episode:
                if current > episode:
                    skipped_pending = [
                        value
                        for value in sorted(pending_comments)
                        if episode <= value < current and not engine._comment_already_verified(value)
                    ]
                    if not skipped_pending:
                        engine._log(
                            "info",
                            f"全流程v3续跑: 当前已到第{current}集，第{episode}-{current - 1}集无待评论任务，顺延",
                        )
                        continue
                if not engine._recover_to_verified_episode(
                    ops,
                    task,
                    episode,
                    total,
                    f"续跑期望第{episode}集，实际第{current or 0}集",
                ):
                    raise RuntimeError(f"续跑无法恢复到第{episode}集，当前第{current or 0}集")
                state = engine._page_state(ops, task)
            engine._assert_target_playback(ops, task, state, total)
            engine._update_task(current_episode=episode, updated_at=datetime.now())
            engine._log("info", f"全流程v3续跑: 正在观察第{episode}集")
            engine._resume_if_paused(ops, episode)

            if episode in pending_comments and not engine._comment_already_verified(episode):
                engine._handle_verified_comment(ops, task, drama_title, episode, total)

            if episode >= total:
                break
            if not engine._wait_for_next_episode_verified(ops, task, episode, episode + 1, total):
                shot = ops.take_screenshot(f"ep{episode}_continue_next_timeout", engine.screenshot_dir)
                raise RuntimeError(f"续跑第{episode}集后未进入第{episode + 1}集，截图 {shot}")

        completed_at = datetime.now()
        missing = engine._missing_verified_comment_episodes(planned_comments)
        if missing:
            raise RuntimeError(f"续跑结束但评论验证未达标: {missing}")
        engine._update_task(
            status="completed",
            current_episode=total,
            completed_at=completed_at,
            duration_seconds=engine._duration_seconds(completed_at),
            error_message=None,
            updated_at=completed_at,
        )
        engine._log("info", "全流程v3续跑: 任务执行完成")
    except Exception as exc:
        completed_at = datetime.now()
        engine._update_task(
            status="failed",
            error_message=str(exc),
            completed_at=completed_at,
            duration_seconds=engine._duration_seconds(completed_at),
            updated_at=completed_at,
        )
        engine._log("error", f"全流程v3续跑失败: {exc}")
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id", type=int)
    parser.add_argument("start_episode", type=int)
    args = parser.parse_args()
    continue_task(args.task_id, args.start_episode)


if __name__ == "__main__":
    main()
