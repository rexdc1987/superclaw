"""机器归属档案：把「执行机器 worker_id」与「登录账号」绑定起来。

为什么需要它
------------
任务表本身已经有 `owner_user_id`（哪个账号）和 `worker_id`（哪台机器），
但**机器自己从来没有账号档案**：

- `api` 模式的执行节点注册时只报 `platform` / `python`
  （`rpa/hongguo/worker.py::_upsert_worker`），没有账号信息；
- `embedded` 模式（安装包默认值）**根本不注册**。

结果是 `hongguo_workers` 长期是空的，"这台机器是谁的、产出了多少"无从回答，
只能反着从任务表里猜。

做法
----
在 `hongguo_workers` 上增加归属列，并在**任务落库时自动认领**：
谁在这台机器上执行任务，这台机器就归属谁。首次认领生效；之后换别的账号
再来认领**不覆盖**，只记一条冲突 —— 冲突本身就是要被看见的信号
（同一台机被两个账号用，统计口径就已经分裂了）。

约定（改之前先读）
------------------
1. 只认 `user_id > 0` 的账号。`user_id=0` 是"本地/未登录"虚拟主体
   （`api/security.py::LOCAL_PRINCIPAL`，username 叫 `local`），**不构成归属**。
2. **绝不触碰 `status` / `last_seen_at`**：那两个字段是心跳语义，
   `hongguo_runtime_health()` 用 `status='online' AND last_seen_at >= 90s 前`
   算在线节点数，进而决定 `task_execution_ready`。认领时建档用
   `status='registered'` 并且只动归属列，控制端才不会把一个不轮询的机器
   误判成"有执行节点在线"。
3. 认领走**条件 UPDATE**（`WHERE worker_id=%s AND owner_user_id=%s`），
   不用 `SELECT ... FOR UPDATE`：给不存在的行加排他读会拿间隙锁，没必要。
   插入用 `INSERT IGNORE`，插入失败（并发抢建）就回读一次再走正常分支。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

MACHINE_OWNER_COLUMNS: tuple[tuple[str, str], ...] = (
    ("owner_user_id", "BIGINT NOT NULL DEFAULT 0"),
    ("owner_username", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ("owner_bound_at", "DATETIME DEFAULT NULL"),
    ("owner_conflict", "VARCHAR(255) NOT NULL DEFAULT ''"),
)

_OWNER_INDEX = "idx_hongguo_worker_owner"

# 建档来源写进 hongguo_workers.metadata_json，便于区分是谁把这台机带进来的。
_CLAIM_SOURCE = "task_claim"


def ensure_machine_columns(cur, db_name: str) -> None:
    """给已有的 hongguo_workers 补上归属列（幂等，可在每次建连时调用）。"""
    names = [name for name, _ in MACHINE_OWNER_COLUMNS]
    placeholders = ", ".join(["%s"] * len(names))
    cur.execute(
        f"""
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=%s
          AND TABLE_NAME='hongguo_workers'
          AND COLUMN_NAME IN ({placeholders})
        """,
        (db_name, *names),
    )
    existing = {str(row.get("COLUMN_NAME")) for row in (cur.fetchall() or [])}
    for name, ddl in MACHINE_OWNER_COLUMNS:
        if name in existing:
            continue
        cur.execute(f"ALTER TABLE hongguo_workers ADD COLUMN {name} {ddl}")

    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA=%s
          AND TABLE_NAME='hongguo_workers'
          AND INDEX_NAME=%s
        """,
        (db_name, _OWNER_INDEX),
    )
    if int((cur.fetchone() or {}).get("count") or 0) == 0:
        cur.execute(
            "ALTER TABLE hongguo_workers ADD INDEX %s (owner_user_id)" % _OWNER_INDEX
        )


def _read_machine(cur, worker_id: str) -> Optional[Dict[str, Any]]:
    cur.execute(
        """
        SELECT worker_id, owner_user_id, owner_username, owner_conflict
        FROM hongguo_workers
        WHERE worker_id=%s
        """,
        (worker_id,),
    )
    return cur.fetchone()


def bind_machine_account(
    conn,
    worker_id: str,
    user_id: int,
    username: str,
    host: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """把一台机器认领给某个账号。返回认领结果，供调用方记日志。

    - 机器首次出现       → 建档并归属该账号
    - 已被同一账号认领   → 幂等刷新
    - 已有归属但不是他   → **不覆盖**，记一条冲突

    `force=True` 是给管理员纠错用的：覆盖归属，并把原归属写进
    `owner_conflict` 留痕（谁改的、从谁手上改的，事后查得到）。
    """
    worker_id = str(worker_id or "").strip()
    username = str(username or "").strip()
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0

    if not worker_id:
        return {"bound": False, "reason": "no_worker_id"}
    if uid <= 0:
        # 未登录 / 本地虚拟主体：不是归属，别写脏数据
        return {"bound": False, "reason": "no_principal"}

    now = datetime.now()
    local_host = str(host or "").strip() or worker_id

    with conn.cursor() as cur:
        row = _read_machine(cur, worker_id)
        if not row:
            cur.execute(
                """
                INSERT IGNORE INTO hongguo_workers (
                    worker_id, name, host, status, metadata_json,
                    owner_user_id, owner_username, owner_bound_at, owner_conflict,
                    last_seen_at, created_at, updated_at
                ) VALUES (%s, %s, %s, 'registered', %s, %s, %s, %s, '', %s, %s, %s)
                """,
                (
                    worker_id,
                    worker_id,
                    local_host,
                    json.dumps({"source": _CLAIM_SOURCE}, ensure_ascii=True),
                    uid,
                    username,
                    now,
                    now,
                    now,
                    now,
                ),
            )
            if int(cur.rowcount or 0) > 0:
                return {
                    "bound": True,
                    "claimed": True,
                    "owner_user_id": uid,
                    "owner_username": username,
                }
            # 并发抢建：别人刚插进去，回读后按正常分支处理
            row = _read_machine(cur, worker_id) or {}

        current_owner = int(row.get("owner_user_id") or 0)

        if current_owner == uid:
            cur.execute(
                """
                UPDATE hongguo_workers
                SET owner_username=%s, updated_at=%s
                WHERE worker_id=%s AND owner_user_id=%s
                """,
                (username, now, worker_id, uid),
            )
            return {
                "bound": True,
                "claimed": False,
                "owner_user_id": uid,
                "owner_username": username,
            }

        if current_owner == 0:
            cur.execute(
                """
                UPDATE hongguo_workers
                SET owner_user_id=%s, owner_username=%s, owner_bound_at=%s, updated_at=%s
                WHERE worker_id=%s AND owner_user_id=0
                """,
                (uid, username, now, now, worker_id),
            )
            if int(cur.rowcount or 0) > 0:
                return {
                    "bound": True,
                    "claimed": True,
                    "owner_user_id": uid,
                    "owner_username": username,
                }
            return {"bound": False, "reason": "race_lost"}

        # 冲突：这台机已经属于别的账号
        seen: List[str] = [x for x in str(row.get("owner_conflict") or "").split(",") if x]
        if username and username not in seen:
            seen.append(username)
        conflict = ",".join(seen)[:255]

        if force:
            previous = str(row.get("owner_username") or "") or str(current_owner)
            trail = [x for x in seen if x != username]
            if previous and previous not in trail:
                trail.append(previous)
            cur.execute(
                """
                UPDATE hongguo_workers
                SET owner_user_id=%s, owner_username=%s, owner_bound_at=%s,
                    owner_conflict=%s, updated_at=%s
                WHERE worker_id=%s
                """,
                (uid, username, now, ",".join(trail)[:255], now, worker_id),
            )
            return {
                "bound": True,
                "claimed": True,
                "forced": True,
                "owner_user_id": uid,
                "owner_username": username,
                "previous_owner": previous,
            }

        cur.execute(
            """
            UPDATE hongguo_workers
            SET owner_conflict=%s, updated_at=%s
            WHERE worker_id=%s AND owner_user_id<>%s
            """,
            (conflict, now, worker_id, uid),
        )
        return {
            "bound": False,
            "conflict": True,
            "owner_user_id": current_owner,
            "owner_username": str(row.get("owner_username") or ""),
            "attempted_user_id": uid,
            "attempted_username": username,
        }


_MACHINE_SQL = """
    SELECT worker_id, name, host, status, last_seen_at,
           owner_user_id, owner_username, owner_bound_at, owner_conflict
    FROM hongguo_workers
"""

_AGGREGATE_SQL = """
    SELECT worker_id,
           COUNT(*) AS total,
           SUM(status='running') AS running,
           SUM(status='completed') AS completed,
           SUM(status='failed') AS failed,
           SUM(status='stopped') AS stopped,
           SUM(COALESCE(comments_sent, 0)) AS comments_sent,
           SUM(COALESCE(comments_verified, 0)) AS comments_verified,
           SUM(COALESCE(likes_completed, 0)) AS likes_completed,
           SUM(COALESCE(favorites_completed, 0)) AS favorites_completed,
           SUM(COALESCE(duration_seconds, 0)) AS duration_seconds,
           MIN(created_at) AS first_task_at,
           MAX(created_at) AS last_task_at
    FROM hongguo_comment_tasks
    WHERE worker_id IS NOT NULL AND worker_id <> ''
    GROUP BY worker_id
"""


_EFFECTIVE_OWNER_SQL = """
    SELECT COALESCE(NULLIF(t.owner_user_id, 0), w.owner_user_id, 0) AS owner_user_id,
           SUM(NULLIF(t.owner_user_id, 0) IS NOT NULL) AS direct,
           SUM(NULLIF(t.owner_user_id, 0) IS NULL
               AND COALESCE(w.owner_user_id, 0) > 0) AS via_machine,
           SUM(NULLIF(t.owner_user_id, 0) IS NULL
               AND COALESCE(w.owner_user_id, 0) = 0) AS unknown,
           COUNT(*) AS total,
           SUM(t.status='running') AS running,
           SUM(t.status='completed') AS completed,
           SUM(t.status='failed') AS failed,
           SUM(COALESCE(t.comments_sent, 0)) AS comments_sent,
           SUM(COALESCE(t.comments_verified, 0)) AS comments_verified,
           SUM(COALESCE(t.likes_completed, 0)) AS likes_completed,
           SUM(COALESCE(t.favorites_completed, 0)) AS favorites_completed,
           MIN(t.created_at) AS first_task_at,
           MAX(t.created_at) AS last_task_at
    FROM hongguo_comment_tasks t
    -- 显式 COLLATE：hongguo_workers 及其兄弟表建表时写了 CHARSET=utf8mb4 却没写
    -- COLLATE，MySQL 8 于是采用字符集默认的 utf8mb4_0900_ai_ci，而任务表是库默认的
    -- utf8mb4_general_ci。不指定就会报 1267 Illegal mix of collations。
    -- 库已经对齐过排序规则，这一句是防御：换个没迁移过的库也能跑。
    LEFT JOIN hongguo_workers w
        ON w.worker_id = t.worker_id COLLATE utf8mb4_general_ci
    GROUP BY owner_user_id
    ORDER BY total DESC
"""


def machine_attribution_report(conn) -> Dict[str, Any]:
    """机器档案 + 产出统计 + 归属缺口，一次查全（只读）。

    给两个口径：

    - `by_owner`：按任务自带的 `owner_user_id` 聚合。**历史任务会掉进 0**
      （2026-07 之前的任务落库时登录未强制，写的是默认值 0）。
    - `by_owner_effective`：按 `COALESCE(任务归属, 机器归属)` 聚合。机器档案建立后，
      无主任务只要还留着 `worker_id`，就能顺着机器找回账号 —— 这才是"能统计"的口径。
      两者差值就是"靠机器档案救回来的任务数"。
    """
    with conn.cursor() as cur:
        cur.execute(_MACHINE_SQL)
        registry = {str(r["worker_id"]): dict(r) for r in (cur.fetchall() or [])}

        cur.execute(_AGGREGATE_SQL)
        aggregates = {str(r["worker_id"]): dict(r) for r in (cur.fetchall() or [])}

        cur.execute(
            """
            SELECT owner_user_id, COUNT(*) AS total,
                   SUM(worker_id IS NULL OR worker_id='') AS missing_worker,
                   SUM(status='running') AS running,
                   SUM(status='completed') AS completed,
                   SUM(status='failed') AS failed,
                   MIN(created_at) AS first_task_at,
                   MAX(created_at) AS last_task_at
            FROM hongguo_comment_tasks
            GROUP BY owner_user_id
            ORDER BY total DESC
            """
        )
        by_owner = [dict(r) for r in (cur.fetchall() or [])]

        cur.execute(_EFFECTIVE_OWNER_SQL)
        by_owner_effective = [dict(r) for r in (cur.fetchall() or [])]

        cur.execute(
            """
            SELECT
                SUM(owner_user_id=0) AS no_owner,
                SUM(worker_id IS NULL OR worker_id='') AS no_machine,
                COUNT(*) AS total
            FROM hongguo_comment_tasks
            """
        )
        gaps = dict(cur.fetchone() or {})

        cur.execute("SELECT id, username FROM users")
        usernames = {int(r["id"]): str(r["username"]) for r in (cur.fetchall() or [])}

    machines: List[Dict[str, Any]] = []
    for worker_id in sorted(set(registry) | set(aggregates)):
        reg = registry.get(worker_id) or {}
        agg = aggregates.get(worker_id) or {}
        owner_id = int(reg.get("owner_user_id") or 0)
        machines.append(
            {
                "worker_id": worker_id,
                "host": reg.get("host") or "",
                "name": reg.get("name") or "",
                "registry_status": reg.get("status") or "unregistered",
                "last_seen_at": reg.get("last_seen_at"),
                "registered": bool(reg),
                "owner_user_id": owner_id,
                "owner_username": reg.get("owner_username")
                or usernames.get(owner_id, ""),
                "owner_bound_at": reg.get("owner_bound_at"),
                "owner_conflict": [
                    x for x in str(reg.get("owner_conflict") or "").split(",") if x
                ],
                "task_total": int(agg.get("total") or 0),
                "task_running": int(agg.get("running") or 0),
                "task_completed": int(agg.get("completed") or 0),
                "task_failed": int(agg.get("failed") or 0),
                "comments_sent": int(agg.get("comments_sent") or 0),
                "comments_verified": int(agg.get("comments_verified") or 0),
                "likes_completed": int(agg.get("likes_completed") or 0),
                "favorites_completed": int(agg.get("favorites_completed") or 0),
                "duration_seconds": int(agg.get("duration_seconds") or 0),
                "first_task_at": agg.get("first_task_at"),
                "last_task_at": agg.get("last_task_at"),
            }
        )

    for row in by_owner:
        uid = int(row.get("owner_user_id") or 0)
        row["username"] = usernames.get(uid, "")
        row["unattributed"] = uid == 0

    for row in by_owner_effective:
        uid = int(row.get("owner_user_id") or 0)
        row["username"] = usernames.get(uid, "")
        row["unattributed"] = uid == 0

    saved = sum(int(r.get("via_machine") or 0) for r in by_owner_effective)
    return {
        "machines": machines,
        "by_owner": by_owner,
        "by_owner_effective": by_owner_effective,
        "summary": {
            "machine_count": len(machines),
            "registered_count": sum(1 for m in machines if m["registered"]),
            "owned_count": sum(1 for m in machines if int(m["owner_user_id"]) > 0),
            "conflict_count": sum(1 for m in machines if m["owner_conflict"]),
            "unowned_machine_count": sum(
                1 for m in machines if int(m["owner_user_id"]) <= 0
            ),
            "task_total": int(gaps.get("total") or 0),
            "task_without_owner": int(gaps.get("no_owner") or 0),
            "task_without_machine": int(gaps.get("no_machine") or 0),
            "task_recovered_by_machine": saved,
            "task_still_unattributed": int(gaps.get("no_owner") or 0) - saved,
        },
    }


def infer_machine_owners(conn, limit: int = 200) -> List[Dict[str, Any]]:
    """从历史任务反推机器归属（只读，不改数据）。

    规则：某台机器上出现过的**非 0** 账号里，任务数最多的那个作为建议归属；
    出现多个不同账号则标 `ambiguous`，交给人判断。
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.worker_id, t.owner_user_id, u.username, COUNT(*) AS n
            FROM hongguo_comment_tasks t
            LEFT JOIN users u ON u.id = t.owner_user_id
            WHERE t.worker_id IS NOT NULL AND t.worker_id <> ''
            GROUP BY t.worker_id, t.owner_user_id, u.username
            ORDER BY t.worker_id, n DESC
            """
        )
        rows = cur.fetchall() or []

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["worker_id"]), []).append(dict(row))

    proposals: List[Dict[str, Any]] = []
    for worker_id, items in grouped.items():
        named = sorted(
            [i for i in items if int(i["owner_user_id"] or 0) > 0],
            key=lambda i: int(i["n"]),
            reverse=True,
        )
        anonymous = [i for i in items if int(i["owner_user_id"] or 0) == 0]
        top = named[0] if named else None
        proposals.append(
            {
                "worker_id": worker_id,
                "proposed_owner_user_id": int(top["owner_user_id"]) if top else 0,
                "proposed_owner_username": str(top["username"] or "") if top else "",
                "confidence": int(top["n"]) if top else 0,
                "distinct_accounts": [
                    {
                        "owner_user_id": int(i["owner_user_id"]),
                        "username": str(i["username"] or ""),
                        "tasks": int(i["n"]),
                    }
                    for i in named
                ],
                "ambiguous": len(named) > 1,
                "tasks_without_owner": sum(int(i["n"]) for i in anonymous),
                "tasks_total": sum(int(i["n"]) for i in items),
            }
        )
    proposals.sort(key=lambda p: p["tasks_total"], reverse=True)
    return proposals[:limit]
