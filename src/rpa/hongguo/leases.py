"""Database-backed device leases shared by API and worker processes."""

from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta
from typing import Any, Dict

import pymysql
from pymysql.cursors import DictCursor

from .dbresilience import apply_timeouts


class DeviceLeaseStore:
    """One row per ``worker_id|device_addr``, refreshed while a task runs.

    Every helper here is best-effort: a lease that cannot be read or written is
    reported as a plain ``False``/``0`` rather than raised, because a database
    blip in this bookkeeping must never take a running task down.

    Connections go through :func:`apply_timeouts` so a dead link fails in
    seconds.  That matters most for :meth:`renew`, which the engine calls
    synchronously from its heartbeat: without a socket timeout a stalled link
    would block the task thread on the OS default TCP timeout instead.
    """

    def __init__(self, db_config: Dict[str, Any]):
        self.db_config = dict(db_config)
        self.db_config.setdefault("cursorclass", DictCursor)
        self.db_config.setdefault("charset", "utf8mb4")
        self.db_config.setdefault("autocommit", False)
        self.worker_id = os.environ.get(
            "SUPERCLAW_WORKER_ID",
            socket.gethostname(),
        )
        self.lease_hours = max(1, int(os.environ.get("SUPERCLAW_DEVICE_LEASE_HOURS", "24")))

    def _connect(self):
        """Open one connection with socket timeouts already applied."""
        return pymysql.connect(**apply_timeouts(self.db_config))

    @staticmethod
    def _safe_rollback(conn: Any) -> None:
        if conn is None:
            return
        try:
            conn.rollback()
        except Exception:
            pass

    @staticmethod
    def _safe_close(conn: Any) -> None:
        if conn is None:
            return
        try:
            conn.close()
        except Exception:
            pass

    def acquire(self, task_id: int, device_addr: str) -> bool:
        now = datetime.now()
        expires_at = now + timedelta(hours=self.lease_hours)
        lease_key = f"{self.worker_id}|{device_addr}"
        conn = None
        try:
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute("DELETE FROM hongguo_device_leases WHERE expires_at <= %s", (now,))
                cur.execute(
                    "SELECT owner_user_id FROM hongguo_comment_tasks WHERE id=%s FOR UPDATE",
                    (int(task_id),),
                )
                task = cur.fetchone()
                if not task:
                    conn.rollback()
                    return False
                cur.execute(
                    "SELECT task_id FROM hongguo_device_leases WHERE lease_key=%s FOR UPDATE",
                    (lease_key,),
                )
                current = cur.fetchone()
                if current and int(current.get("task_id") or 0) != int(task_id):
                    conn.rollback()
                    return False
                if current:
                    cur.execute(
                        """
                        UPDATE hongguo_device_leases
                        SET owner_user_id=%s, worker_id=%s, acquired_at=%s, expires_at=%s
                        WHERE lease_key=%s AND task_id=%s
                        """,
                        (
                            int(task.get("owner_user_id") or 0),
                            self.worker_id,
                            now,
                            expires_at,
                            lease_key,
                            int(task_id),
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO hongguo_device_leases (
                            lease_key, device_addr, owner_user_id, task_id, worker_id, acquired_at, expires_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            lease_key,
                            device_addr,
                            int(task.get("owner_user_id") or 0),
                            int(task_id),
                            self.worker_id,
                            now,
                            expires_at,
                        ),
                    )
            conn.commit()
            return True
        except Exception:
            self._safe_rollback(conn)
            return False
        finally:
            self._safe_close(conn)

    def release(self, task_id: int) -> None:
        conn = None
        try:
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute("DELETE FROM hongguo_device_leases WHERE task_id=%s", (int(task_id),))
            conn.commit()
        except Exception:
            self._safe_rollback(conn)
        finally:
            self._safe_close(conn)

    def renew(self, task_id: int) -> None:
        expires_at = datetime.now() + timedelta(hours=self.lease_hours)
        conn = None
        try:
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE hongguo_device_leases
                    SET expires_at=%s
                    WHERE task_id=%s AND worker_id=%s
                    """,
                    (expires_at, int(task_id), self.worker_id),
                )
            conn.commit()
        except Exception:
            self._safe_rollback(conn)
        finally:
            self._safe_close(conn)

    def release_inactive(self) -> int:
        conn = None
        try:
            conn = self._connect()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE lease
                    FROM hongguo_device_leases AS lease
                    LEFT JOIN hongguo_comment_tasks AS task ON task.id=lease.task_id
                    WHERE lease.expires_at <= %s
                       OR task.id IS NULL
                       OR task.status NOT IN ('running', 'paused')
                    """,
                    (datetime.now(),),
                )
                count = int(cur.rowcount or 0)
            conn.commit()
            return count
        except Exception:
            self._safe_rollback(conn)
            return 0
        finally:
            self._safe_close(conn)
