"""Windows execution worker for centrally dispatched Hongguo tasks."""

from __future__ import annotations

import json
import os
import platform
import socket
import threading
import time
from datetime import datetime
from typing import Any, Dict, List

from rpa.dashboard.routes_hongguo import (
    _connection,
    _db_config,
    _insert_log,
    _safe_check_login_for_device,
    _screenshot_root,
)
from rpa.hongguo.device import discover_mumu_instances
from rpa.hongguo.engine import TaskEngineManager
from services.ai_config_service import ai_config, hongguo_config


class HongguoWorker:
    def __init__(self):
        self.worker_id = os.environ.get("SUPERCLAW_WORKER_ID", socket.gethostname()).strip()
        self.worker_name = os.environ.get("SUPERCLAW_WORKER_NAME", self.worker_id).strip()
        self.poll_interval = max(1, int(os.environ.get("SUPERCLAW_WORKER_POLL_SECONDS", "2")))
        self.scan_interval = max(30, int(os.environ.get("SUPERCLAW_DEVICE_SCAN_SECONDS", "60")))
        self._stop = threading.Event()
        self._manager = TaskEngineManager.get_instance(
            _db_config(),
            str(_screenshot_root().as_posix()),
            ai_config(),
            device_addr=hongguo_config().get("device_addr"),
        )

    def run(self) -> None:
        self._ensure_schema_and_reconcile()
        heartbeat = threading.Thread(target=self._heartbeat_loop, name="hongguo-worker-heartbeat", daemon=True)
        scanner = threading.Thread(target=self._device_scan_loop, name="hongguo-worker-devices", daemon=True)
        heartbeat.start()
        scanner.start()
        try:
            while not self._stop.wait(self.poll_interval):
                self._process_commands()
        finally:
            self._mark_offline()

    def stop(self) -> None:
        self._stop.set()

    def _ensure_schema_and_reconcile(self) -> None:
        now = datetime.now()
        message = "执行节点已重启，原任务线程不存在，请重新启动任务"
        with _connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id FROM hongguo_comment_tasks
                    WHERE worker_id=%s AND status IN ('running', 'paused')
                    """,
                    (self.worker_id,),
                )
                task_ids = [int(row["id"]) for row in (cur.fetchall() or [])]
                if task_ids:
                    placeholders = ", ".join(["%s"] * len(task_ids))
                    cur.execute(
                        f"""
                        UPDATE hongguo_comment_tasks
                        SET status='stopped', control_command=NULL, error_message=%s,
                            completed_at=%s, updated_at=%s
                        WHERE id IN ({placeholders})
                        """,
                        (message, now, now, *task_ids),
                    )
                    cur.executemany(
                        """
                        INSERT INTO hongguo_execution_logs (task_id, level, message, created_at)
                        VALUES (%s, 'warn', %s, %s)
                        """,
                        [(task_id, message, now) for task_id in task_ids],
                    )
                cur.execute("DELETE FROM hongguo_device_leases WHERE worker_id=%s", (self.worker_id,))

    def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            self._upsert_worker("online")
            self._stop.wait(10)

    def _upsert_worker(self, status: str) -> None:
        now = datetime.now()
        metadata = json.dumps(
            {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "execution_mode": "worker",
            },
            ensure_ascii=True,
        )
        with _connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO hongguo_workers (
                        worker_id, name, host, status, metadata_json,
                        last_seen_at, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        name=VALUES(name), host=VALUES(host), status=VALUES(status),
                        metadata_json=VALUES(metadata_json), last_seen_at=VALUES(last_seen_at),
                        updated_at=VALUES(updated_at)
                    """,
                    (
                        self.worker_id,
                        self.worker_name,
                        socket.gethostname(),
                        status,
                        metadata,
                        now,
                        now,
                        now,
                    ),
                )

    def _device_scan_loop(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self._scan_devices()
            except Exception:
                pass
            remaining = max(1, self.scan_interval - int(time.monotonic() - started))
            self._stop.wait(remaining)

    def _scan_devices(self) -> None:
        instances = discover_mumu_instances(connect_adb=True)
        devices: List[Dict[str, Any]] = []
        for instance in instances:
            addr = str(instance.get("addr") or "").strip()
            if not addr:
                continue
            result = _safe_check_login_for_device(addr, mumu=instance, timeout=60)
            result["worker_id"] = self.worker_id
            devices.append(result)
        now = datetime.now()
        with _connection() as conn:
            with conn.cursor() as cur:
                for item in devices:
                    addr = str(item.get("addr") or item.get("serial") or "")
                    cur.execute(
                        """
                        INSERT INTO hongguo_worker_devices (
                            worker_id, device_addr, label, online, logged_in, payload_json, last_seen_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            label=VALUES(label), online=VALUES(online), logged_in=VALUES(logged_in),
                            payload_json=VALUES(payload_json), last_seen_at=VALUES(last_seen_at)
                        """,
                        (
                            self.worker_id,
                            addr,
                            item.get("label") or addr,
                            int(bool(item.get("online"))),
                            int(bool(item.get("logged_in"))),
                            json.dumps(item, ensure_ascii=False, default=str),
                            now,
                        ),
                    )

    def _process_commands(self) -> None:
        with _connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, device_addr, control_command, status
                    FROM hongguo_comment_tasks
                    WHERE worker_id=%s AND control_command IS NOT NULL
                    ORDER BY dispatch_requested_at ASC, id ASC
                    LIMIT 20
                    """,
                    (self.worker_id,),
                )
                commands = list(cur.fetchall() or [])
        for task in commands:
            self._execute_command(task)

    def _execute_command(self, task: Dict[str, Any]) -> None:
        task_id = int(task["id"])
        command = str(task.get("control_command") or "")
        device_addr = str(task.get("device_addr") or "")
        success = False
        if command == "start":
            success = self._manager.start_task(task_id, device_addr=device_addr)
        elif command == "pause":
            success = self._manager.pause_task(task_id)
        elif command == "resume":
            success = self._manager.resume_task(task_id)
        elif command == "stop":
            success = self._manager.stop_task(task_id)
            if not success:
                success = True
        with _connection() as conn:
            with conn.cursor() as cur:
                if success:
                    if command == "stop":
                        cur.execute(
                            """
                            UPDATE hongguo_comment_tasks
                            SET status='stopped', control_command=NULL, completed_at=%s, updated_at=%s
                            WHERE id=%s AND control_command=%s
                            """,
                            (datetime.now(), datetime.now(), task_id, command),
                        )
                    else:
                        cur.execute(
                            """
                            UPDATE hongguo_comment_tasks
                            SET control_command=NULL, updated_at=%s
                            WHERE id=%s AND control_command=%s
                            """,
                            (datetime.now(), task_id, command),
                        )
                    _insert_log(conn, task_id, f"执行节点 {self.worker_id} 已执行命令: {command}")
                else:
                    cur.execute(
                        """
                        UPDATE hongguo_comment_tasks
                        SET status='failed', control_command=NULL, error_message=%s,
                            completed_at=%s, updated_at=%s
                        WHERE id=%s AND control_command=%s
                        """,
                        (
                            f"执行节点 {self.worker_id} 无法执行命令: {command}",
                            datetime.now(),
                            datetime.now(),
                            task_id,
                            command,
                        ),
                    )
                    _insert_log(conn, task_id, f"执行节点命令失败: {command}", "error")

    def _mark_offline(self) -> None:
        try:
            self._upsert_worker("offline")
        except Exception:
            pass
