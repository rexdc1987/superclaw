"""Fail-safe audit logging for mutating API requests."""

from __future__ import annotations

import os
import threading
from datetime import datetime

import pymysql
from pymysql.cursors import DictCursor

from api.security import Principal
from services.ai_config_service import app_config


_schema_lock = threading.Lock()
_schema_ready = False


def _db_config() -> dict:
    database = app_config().get("database", {})
    return {
        "host": os.environ.get("SUPERCLAW_DB_HOST") or database.get("host", "localhost"),
        "port": int(os.environ.get("SUPERCLAW_DB_PORT") or database.get("port", 3308)),
        "database": os.environ.get("SUPERCLAW_DB_NAME") or database.get("name", "superclaw"),
        "user": os.environ.get("SUPERCLAW_DB_USER") or database.get("user", "superclaw"),
        "password": os.environ.get("SUPERCLAW_DB_PASSWORD") or database.get("password", ""),
        "charset": "utf8mb4",
        "cursorclass": DictCursor,
        "autocommit": False,
    }


def _ensure_schema(conn) -> None:
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS superclaw_api_audit_logs (
                    id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    request_id VARCHAR(40) NOT NULL,
                    user_id BIGINT NOT NULL DEFAULT 0,
                    username VARCHAR(64) NOT NULL,
                    method VARCHAR(10) NOT NULL,
                    path VARCHAR(500) NOT NULL,
                    status_code INT NOT NULL,
                    client_ip VARCHAR(80) DEFAULT NULL,
                    created_at DATETIME NOT NULL,
                    INDEX idx_audit_created (created_at),
                    INDEX idx_audit_user (user_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        conn.commit()
        _schema_ready = True


def record_api_action(
    principal: Principal,
    method: str,
    path: str,
    status_code: int,
    client_ip: str,
    request_id: str,
) -> None:
    if method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    try:
        conn = pymysql.connect(**_db_config())
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO superclaw_api_audit_logs (
                        request_id, user_id, username, method, path,
                        status_code, client_ip, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        request_id,
                        int(principal.user_id),
                        principal.username,
                        method.upper(),
                        path[:500],
                        int(status_code),
                        client_ip[:80],
                        datetime.now(),
                    ),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        return
