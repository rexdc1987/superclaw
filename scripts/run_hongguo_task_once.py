"""Run one Hongguo task synchronously with the current source tree."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pymysql

from rpa.dashboard.routes_hongguo import _ai_config, _db_config
from rpa.hongguo.engine import DEFAULT_SCREENSHOT_ROOT, TaskEngine


def run_task(task_id: int) -> None:
    db_config = _db_config()
    with pymysql.connect(**db_config) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT device_addr FROM hongguo_comment_tasks WHERE id=%s LIMIT 1",
                (task_id,),
            )
            task = cur.fetchone()
    if not task:
        raise SystemExit(f"Hongguo task {task_id} does not exist")

    engine = TaskEngine(
        task_id=task_id,
        db_config=db_config,
        screenshot_dir=str((Path(DEFAULT_SCREENSHOT_ROOT) / str(task_id)).as_posix()),
        ai_config=_ai_config(),
        device_addr=str(task.get("device_addr") or "").strip(),
    )
    engine._run_verified_flow()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id", type=int)
    args = parser.parse_args()
    run_task(args.task_id)


if __name__ == "__main__":
    main()
