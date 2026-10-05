"""机器归属档案：读统计、查缺口、纠错绑定。

分层的唯一理由是「让路由不写 SQL」：router 只解析入参和格式化响应，
SQL 与业务判断都在这里和 `rpa.hongguo.attribution` 里。

连接复用 `rpa.dashboard.routes_hongguo._connection()` —— 它带着
`_ensure_task_schema()` 的惰性建表/补列，走这条路才能保证归属列一定存在
（`HongguoWorker` 也是这么拿连接的）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from rpa.dashboard.routes_hongguo import _connection
from rpa.hongguo.attribution import (
    bind_machine_account,
    infer_machine_owners,
    machine_attribution_report,
)


class AttributionError(Exception):
    """归属操作失败：给路由一个统一的 4xx 出口。"""


def overview() -> Dict[str, Any]:
    """机器档案 + 按账号/机器的产出统计 + 归属缺口（只读）。"""
    with _connection() as conn:
        return machine_attribution_report(conn)


def inference() -> Dict[str, Any]:
    """从历史任务反推机器归属，只给建议，不改数据。"""
    with _connection() as conn:
        proposals = infer_machine_owners(conn)
    return {
        "proposals": proposals,
        "ambiguous_count": sum(1 for p in proposals if p["ambiguous"]),
        "note": "ambiguous=True 表示这台机上出现过多个账号，需要人工判断后再手工绑定。",
    }


def _resolve_user(conn, username: str) -> Dict[str, Any]:
    username = str(username or "").strip()
    if not username:
        raise AttributionError("username 不能为空")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, username, role, status FROM users WHERE username=%s",
            (username,),
        )
        row = cur.fetchone()
    if not row:
        raise AttributionError("账号不存在: %s" % username)
    if int(row.get("id") or 0) <= 0:
        raise AttributionError("账号 %s 的 id 非法，不能作为归属" % username)
    return dict(row)


def bind_machine(
    worker_id: str,
    username: str,
    force: bool = False,
    backfill: bool = False,
) -> Dict[str, Any]:
    """把一台机器归属给某个账号；`backfill=True` 时顺带认领它的无主任务。"""
    worker_id = str(worker_id or "").strip()
    if not worker_id:
        raise AttributionError("worker_id 不能为空")

    with _connection() as conn:
        user = _resolve_user(conn, username)
        uid = int(user["id"])
        name = str(user["username"])

        result = bind_machine_account(conn, worker_id, uid, name, force=force)
        if not result.get("bound"):
            raise AttributionError(
                "机器 %s 当前归属 %s，未被 %s 覆盖。确认要改就带 force=true。"
                % (
                    worker_id,
                    result.get("owner_username") or result.get("owner_user_id"),
                    name,
                )
            )

        claimed_tasks = 0
        if backfill:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE hongguo_comment_tasks
                    SET owner_user_id=%s
                    WHERE worker_id=%s AND owner_user_id=0
                    """,
                    (uid, worker_id),
                )
                claimed_tasks = int(cur.rowcount or 0)

    return {
        "worker_id": worker_id,
        "owner_user_id": uid,
        "owner_username": name,
        "forced": bool(result.get("forced")),
        "previous_owner": result.get("previous_owner") or "",
        "tasks_backfilled": claimed_tasks,
        "bound_at": datetime.now().isoformat(timespec="seconds"),
    }


def audit_gaps() -> Dict[str, Any]:
    """归属缺口清单：无主任务、无机器任务、冲突机器。"""
    with _connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT owner_user_id, COUNT(*) AS n,
                       SUM(worker_id IS NULL OR worker_id='') AS no_machine
                FROM hongguo_comment_tasks
                WHERE owner_user_id=0
                GROUP BY owner_user_id
                """
            )
            ownerless = dict(cur.fetchone() or {})
            cur.execute(
                """
                SELECT worker_id, COUNT(*) AS n, MIN(id) AS min_id, MAX(id) AS max_id,
                       MIN(created_at) AS first_at, MAX(created_at) AS last_at
                FROM hongguo_comment_tasks
                WHERE worker_id IS NULL OR worker_id=''
                GROUP BY worker_id
                """
            )
            rows = [dict(r) for r in (cur.fetchall() or [])]
    return {
        "tasks_without_owner": int(ownerless.get("n") or 0),
        "tasks_without_machine": sum(int(r["n"]) for r in rows),
        "orphan_buckets": rows,
        "note": (
            "无机器（worker_id 为空）的任务是 2026-07-20 之前写入的，"
            "当时任务表还没有这一列，事后无法从数据库反推是哪台机器。"
        ),
    }
