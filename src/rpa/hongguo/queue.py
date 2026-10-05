"""Serial batch queue and the daily drama playlist.

Why this module exists
----------------------
A "batch" has always meant one drama across N devices, created and started by
hand. An operator holding a list of five dramas had to repeat that ten times,
and "run something every day" had nowhere to live in the product at all.

This module supplies the missing middle:

``playlist``
    A standing list of dramas. Enqueue from it, or from a pasted list.
``queue``
    Rows sharing a ``queue_id``. One drama runs at a time across every
    selected device, and the next one starts by itself when the first
    finishes - a failed drama is recorded and skipped rather than stalling
    the rest of the list.
``daily timer``
    Once a day, at the configured time, the whole playlist is enqueued in
    random order. If the previous queue is still running, firing is deferred
    until it drains, so a slow day simply pushes into the next one.

Only one queue is active at a time. Starting two would put two dramas on the
same devices and the device leases would refuse the second one anyway.

Ownership note: the dispatcher runs on a background thread with no request
context, so it restores the principal recorded on the queue item before it
creates tasks. Otherwise queued work would be attributed to the virtual
``user_id=0`` principal.
"""

from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from datetime import date, datetime, time as clock_time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from rpa.dashboard.routes_hongguo import (
    HTTPException,
    TaskBase,
    _connection,
    _fetch_multi_run_tasks,
    _insert_log,
    _insert_task_record,
    _local_worker_id,
    _start_task_on_device,
)
from rpa.hongguo.reclaim import classify, is_foreign_sweep

logger = logging.getLogger(__name__)

QUEUE_ITEM_STATUSES = ("pending", "running", "done", "failed", "skipped", "cancelled")
UNFINISHED_ITEM_STATUSES = ("pending", "running")
BUSY_TASK_STATUSES = ("running", "paused")
TERMINAL_TASK_STATUSES = ("completed", "failed", "stopped")

DEFAULT_DAILY_TIME = "09:00"
DAILY_MODES = ("all_random", "random_one")
MAX_START_ATTEMPTS = 2

#: A batch that was created but never launched is an infrastructure failure, not
#: a bad drama, so it is retried on this budget instead of ``MAX_START_ATTEMPTS``
#: and does not spend a real start attempt. Bounded, because every retry inserts
#: a fresh task row per device and an endless loop during a long outage would
#: litter the task table. 2026-09-30: seq2/seq4 were dropped by two blips of the
#: shared MySQL, without ever playing an episode.
MAX_INFRA_RETRIES = 8

#: A batch whose task rows were created but never started is not "busy", it is
#: wedged: the tick that inserted them can die before ``_start_task_on_device``
#: runs, and the follow-up "mark the item failed" write then hits the same
#: outage. Give an ``api``-mode dispatch (rows park on ``pending`` until a worker
#: claims them) this long to be picked up before the batch is declared dead.
STALLED_START_GRACE_SECONDS = 900

#: A batch whose only "failure" evidence is an outside writer's reap - an
#: old-version node's fleet-wide reconcile, or the watchdog - is not failed, it
#: is mislabelled, and the engine is about to put the row back (see
#: ``untrusted_failure_reason``). Give that repair a chance before the drama is
#: replayed from episode 1: on 2026-09-30 a finished 4/4 pass of seq4
#: 《胭脂如梦如雨如尘2》 was re-dispatched for eight device-hours this way, and the
#: second pass collided with the device still running, so the item ended up
#: ``failed`` even though the drama had been watched to the end. It is measured
#: from the sweep's own ``updated_at``, so it can only ever delay a genuine
#: verdict, never wedge the queue behind one.
FOREIGN_SWEEP_GRACE_SECONDS = 900

#: How many distinct dramas a single "import from history" pulls in.  Ordered by
#: most recent batch, so the cap only ever drops names nobody has touched in ages.
HISTORY_IMPORT_LIMIT = 200

# A tick that finds devices but nothing to do should stay quiet; one that
# cannot fire because no device is configured would otherwise log every 20s.
_no_device_warned_at = 0.0
_db_down_warned_at = 0.0
_foreign_sweep_warned_at = 0.0


# ---------------------------------------------------------------- pure helpers


def parse_daily_time(value: Optional[str]) -> clock_time:
    """Read ``HH:MM``; anything unusable falls back to 09:00."""
    text = str(value or "").strip()
    for fmt in ("%H:%M", "%H:%M:%S", "%H%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return datetime.strptime(DEFAULT_DAILY_TIME, "%H:%M").time()


def daily_due(daily_time: Optional[str], now: datetime) -> bool:
    return now.time() >= parse_daily_time(daily_time)


def daily_should_fire(
    *,
    daily_enabled: bool,
    last_fired_date: Optional[date],
    now: datetime,
    daily_time: Optional[str],
    unfinished_queue: Optional[str],
) -> bool:
    """Decide whether this tick is the one that enqueues today's playlist.

    Deferring while a queue is unfinished is deliberate: the timer represents
    "one full pass through the playlist per day", not "a second pass on top of
    the one still running".
    """
    if not daily_enabled:
        return False
    if last_fired_date == now.date():
        return False
    if unfinished_queue:
        return False
    return daily_due(daily_time, now)


def verdict_from_task_rows(rows: Sequence[Dict[str, Any]]) -> Optional[Tuple[str, Optional[str]]]:
    """Judge a finished run.

    ``None`` means "still busy, ask again later" - the same distinction the
    engine draws, because an unreadable row must never be mistaken for a
    finished one.
    """
    if not rows:
        return ("failed", "批次里没有任何任务")
    statuses = [str(row.get("status") or "") for row in rows]
    if not statuses or all(status not in TERMINAL_TASK_STATUSES for status in statuses):
        return None
    if any(status in BUSY_TASK_STATUSES for status in statuses):
        return None
    if any(status not in TERMINAL_TASK_STATUSES for status in statuses):
        return None
    if all(status == "completed" for status in statuses):
        return ("done", None)
    problems = []
    for row in rows:
        status = str(row.get("status") or "")
        if status == "completed":
            continue
        reason = str(row.get("error_message") or status)
        device = row.get("device_addr") or "?"
        problems.append("%s %s: %s" % (device, status, reason[:120]))
    return ("failed", "；".join(problems[:4]) or "有设备未完成")


def failed_device_addrs(rows: Sequence[Dict[str, Any]]) -> List[str]:
    """Devices that did not finish the run, in a stable order.

    Every device watches the whole drama by itself, so a retry only has to
    cover the devices that actually failed; replaying the ones that already
    finished buys nothing and costs a full drama each. On 2026-10-01 seq3
    《丧尸狂潮》two devices died five minutes in and all four were replayed
    (~6.7 device-hours). An empty list means "no usable per-device information"
    and the caller falls back to the whole device list.
    """
    addrs: List[str] = []
    for row in rows:
        if str(row.get("status") or "") == "completed":
            continue
        addr = str(row.get("device_addr") or "").strip()
        if addr and addr not in addrs:
            addrs.append(addr)
    return addrs


def _as_datetime(value: Any) -> Optional[datetime]:
    """Best-effort datetime for a row column, which pymysql may hand back either way."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(value[:19], fmt)
            except ValueError:
                continue
    return None


def stalled_start_reason(
    rows: Sequence[Dict[str, Any]],
    now: datetime,
    grace_seconds: int = STALLED_START_GRACE_SECONDS,
) -> Optional[str]:
    """Explain a batch that was created but never started, or None when it is fine.

    ``verdict_from_task_rows`` counts ``pending`` as neither terminal nor busy, so
    it answers "still busy" forever for rows that will never move: the tick that
    inserted them can die before it reaches ``_start_task_on_device`` (a
    remote-MySQL blip is enough), and the follow-up "mark the item failed" write
    then hits the same outage and is swallowed by the dispatcher loop. The item is
    left on ``running`` and the whole queue stops behind it.

    Any row still ``pending`` with no ``started_at`` qualifies, as long as no row
    is live (``running``/``paused``) - a batch with even one live device is left
    alone. That covers both "nothing ever launched" and the nastier "one device
    was reaped by the 20-minute watchdog while the rest never launched" (09-30
    00:50, 胭脂如梦如雨如尘2: the item sat on ``running`` for 14.5 hours and every
    drama behind it was blocked). The grace window keeps a legitimate
    ``api``-mode dispatch, whose rows wait on ``pending`` until a worker claims
    them, from being reaped mid-flight.
    """
    if not rows:
        return None
    # A live device means the batch is still doing useful work - never reap it.
    if any(str(row.get("status") or "") in BUSY_TASK_STATUSES for row in rows):
        return None
    # ``pending`` without ``started_at`` is the only state that can never move on
    # its own. Rows that already finished (``completed``/``failed``/``stopped``)
    # are ignored: a batch where the first device was stopped by the watchdog and
    # the rest never launched has no live row either, and used to stall the whole
    # queue behind it (09-30 00:50, 胭脂如梦如雨如尘2, stuck for 14.5h).
    unstarted = [
        row
        for row in rows
        if str(row.get("status") or "") == "pending" and not row.get("started_at")
    ]
    if not unstarted:
        return None
    stamps = [stamp for stamp in (_as_datetime(row.get("created_at")) for row in unstarted) if stamp]
    if not stamps:
        return None
    if (now - min(stamps)).total_seconds() < grace_seconds:
        return None
    if len(unstarted) == len(rows):
        return "批次创建后一直没能启动（调度中断），已按失败处理"
    return "批次有 %d 台设备创建后一直没能启动（调度中断），已按失败处理" % len(unstarted)


def untrusted_failure_reason(
    rows: Sequence[Dict[str, Any]],
    now: datetime,
    grace_seconds: int = FOREIGN_SWEEP_GRACE_SECONDS,
) -> Optional[str]:
    """Explain why a "failed" batch verdict is not yet trustworthy, or None.

    ``verdict_from_task_rows`` reads the rows literally, and for a run that is
    still holding a device that reading can be wrong: an old-version node's
    startup reconcile sweeps *every* running task in the shared database, so a
    live batch briefly shows a ``stopped`` row naming no machine (the fingerprint
    lives in :mod:`rpa.hongguo.reclaim`). Acting on that replays the whole batch
    - 2026-09-30, seq4 《胭脂如梦如雨如尘2》: a finished 4/4 pass was dispatched a
    second time for eight device-hours, and the second pass collided with the
    device that was still running, leaving the item ``failed`` even though the
    drama had been watched to the end.

    The engine repairs such a row back to ``running`` within an episode or two
    (``TaskEngine._check_external_reclaim``), so the honest answer for this tick
    is "not yet a verdict". Deferring is bounded twice over: the window is
    measured from the sweep's own ``updated_at`` - which the sweeper stamps - so
    a stale mislabel is accepted at once, and a fresh one can hold the queue for
    only ``grace_seconds``. Any row whose failure is *not* a sweep message makes
    this return None, so a genuine crash still fails the batch immediately, and a
    mixed batch (one device really failed, another was swept) is still judged
    failed at once.
    """
    if not rows:
        return None
    unfinished = [row for row in rows if str(row.get("status") or "") != "completed"]
    if not unfinished:
        return None
    if not all(
        is_foreign_sweep(str(row.get("error_message") or "")) for row in unfinished
    ):
        return None
    stamps = [
        stamp
        for stamp in (
            _as_datetime(row.get("updated_at")) or _as_datetime(row.get("completed_at"))
            for row in unfinished
        )
        if stamp
    ]
    if not stamps:
        # No clock to measure against. Accept the verdict rather than defer
        # blind, because "wait forever" is the failure this module exists to
        # avoid - the 14.5 hour stall of 2026-09-30 was exactly that shape.
        return None
    remaining = grace_seconds - (now - max(stamps)).total_seconds()
    if remaining <= 0:
        return None
    labels: List[str] = []
    for row in unfinished:
        label = classify(str(row.get("error_message") or ""))
        if label and label not in labels:
            labels.append(label)
    return "批次被%s，正在等其自愈（约 %.0f 秒后仍无恢复才按失败处理）" % (
        "、".join(labels) or "外部写入方",
        remaining,
    )


def _warn_foreign_sweep(item: Dict[str, Any], reason: str) -> None:
    """Say that an outside sweep is holding a batch back, at most once a tick-window.

    The dispatcher runs every 20 seconds, so without this limiter one mislabel
    would write a line every 20 seconds for the whole grace window.
    """
    global _foreign_sweep_warned_at
    now = time.monotonic()
    if now - _foreign_sweep_warned_at < 300:
        return
    _foreign_sweep_warned_at = now
    logger.warning("队列：《%s》%s", item.get("drama_name"), reason)


def retry_allowed(item: Dict[str, Any], *, infra_failure: bool) -> bool:
    """Whether a failed item gets another go instead of being dropped.

    A drama that really ran and failed is the drama's problem: it gets
    ``MAX_START_ATTEMPTS`` goes and is then left out of the list. A batch that
    was created but never launched (``stalled_start_reason``) is a failure of
    the infrastructure instead, so it does not spend a real attempt - it burns
    ``infra_retries`` against ``MAX_INFRA_RETRIES``. Without that split a MySQL
    outage costs the drama one of its two lives each time, and two blips later a
    drama nobody ever watched is marked ``failed`` for good (2026-09-30,
    seq2 《80年代之我的嫂子》 and seq4 《胭脂如梦如雨如尘2》).
    """
    if infra_failure:
        return int(item.get("infra_retries") or 0) < MAX_INFRA_RETRIES
    return int(item.get("attempt") or 0) < MAX_START_ATTEMPTS


def pick_next_item(items: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The next drama to start, or None when the queue is done for now."""
    pending = [item for item in items if str(item.get("status")) == "pending"]
    if not pending:
        return None
    return sorted(pending, key=lambda item: (int(item.get("seq") or 0), int(item.get("id") or 0)))[0]


def summarize_items(items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    counts = {status: 0 for status in QUEUE_ITEM_STATUSES}
    for item in items:
        status = str(item.get("status") or "pending")
        counts[status] = counts.get(status, 0) + 1
    total = len(items)
    finished = counts.get("done", 0) + counts.get("failed", 0) + counts.get("skipped", 0) + counts.get("cancelled", 0)
    current = None
    for item in sorted(items, key=lambda row: int(row.get("seq") or 0)):
        if str(item.get("status")) in UNFINISHED_ITEM_STATUSES:
            current = item
            break
    return {
        "total": total,
        "finished": finished,
        "counts": counts,
        "current_seq": int(current.get("seq") or 0) if current else None,
        "current_drama": current.get("drama_name") if current else None,
    }


def normalize_names(names: Iterable[str]) -> List[str]:
    """Split pasted text into drama names, newest input order preserved."""
    result: List[str] = []
    seen = set()
    for raw in names:
        for piece in str(raw or "").replace("\r", "\n").replace("\uff0c", ",").split("\n"):
            for token in piece.split(","):
                name = token.strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                result.append(name[:200])
    return result


# ------------------------------------------------------------------ db helpers


#: Whether this process already made sure ``hongguo_queue_item`` carries the
#: columns the tick writes. ``ensure_base_schema`` cannot add a column to a table
#: that already exists, and the dispatcher thread never goes through the API's
#: column migration, so without this a stale database would make the retry
#: UPDATE fail - and the dispatcher swallows that error, leaving the item on
#: ``running`` with the whole queue wedged behind it.
_queue_columns_ready = False


def _ensure_queue_columns(conn) -> None:
    """Idempotently add the columns ``hongguo_queue_item`` gained over time."""
    global _queue_columns_ready
    if _queue_columns_ready:
        return
    from rpa.hongguo.schema import ensure_queue_item_columns

    try:
        with conn.cursor() as cur:
            added = ensure_queue_item_columns(cur)
    except Exception as exc:  # pragma: no cover - defensive
        # DDL commits implicitly, so a failure leaves the table as it was. Stay
        # on the old shape rather than wedging the whole tick on it.
        logger.error("队列：补列失败，改用旧结构继续：%s", exc)
        return
    _queue_columns_ready = True
    if added:
        logger.warning("hongguo_queue_item 补上列：%s", ", ".join(added))


def _ensure_config(conn) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT IGNORE INTO hongguo_queue_config
                (id, daily_enabled, daily_time, daily_mode, devices_json, template_json)
            VALUES (1, 0, %s, 'all_random', '[]', '{}')
            """,
            (DEFAULT_DAILY_TIME,),
        )
        cur.execute("SELECT * FROM hongguo_queue_config WHERE id=1")
        return cur.fetchone() or {}


def _unfinished_queue_id(conn) -> Optional[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT queue_id FROM hongguo_queue_item
            WHERE status IN ('pending', 'running')
            GROUP BY queue_id
            ORDER BY MIN(created_at)
            LIMIT 1
            """
        )
        row = cur.fetchone()
    return str(row["queue_id"]) if row and row.get("queue_id") else None


def _queue_items(conn, queue_id: str) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM hongguo_queue_item WHERE queue_id=%s ORDER BY seq, id",
            (queue_id,),
        )
        return list(cur.fetchall() or [])


def _json_column(row: Dict[str, Any], key: str, default):
    value = row.get(key)
    if isinstance(value, (list, dict)):
        return value
    if not value:
        return default
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return default
    return parsed


def _devices_from(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    devices = _json_column(row, "devices_json", [])
    if not isinstance(devices, list):
        return []
    cleaned = []
    for item in devices:
        if not isinstance(item, dict):
            continue
        addr = str(item.get("addr") or item.get("serial") or "").strip()
        if not addr:
            continue
        cleaned.append(
            {
                "addr": addr,
                "label": str(item.get("label") or addr),
                "worker_id": item.get("worker_id") or None,
            }
        )
    return cleaned


def _template_from(row: Dict[str, Any]) -> Dict[str, Any]:
    template = _json_column(row, "template_json", {})
    return template if isinstance(template, dict) else {}


def template_field_names() -> set:
    fields = getattr(TaskBase, "model_fields", None)
    if fields is None:
        fields = getattr(TaskBase, "__fields__", {})
    return set(fields or {})


def build_task_payload(drama_name: str, template: Optional[Dict[str, Any]]) -> TaskBase:
    """Turn stored execution rules plus one drama into a task payload.

    Unknown keys are dropped rather than passed on: the stored template is
    whatever the form posted, and pydantic would reject a stale or invented
    field name instead of simply ignoring it.
    """
    allowed = template_field_names() - {"drama_name"}
    kwargs = {key: value for key, value in (template or {}).items() if key in allowed}
    kwargs["drama_name"] = drama_name
    return TaskBase(**kwargs)


def _principal_for_owner(conn, user_id: Any):
    """Rebuild the creating account so queued tasks keep their attribution."""
    from api.security import LOCAL_PRINCIPAL, Principal

    try:
        owner = int(user_id or 0)
    except (TypeError, ValueError):
        owner = 0
    if owner <= 0:
        return LOCAL_PRINCIPAL, None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, username, role FROM users WHERE id=%s", (owner,))
            row = cur.fetchone()
        if not row:
            return LOCAL_PRINCIPAL, None
        principal = Principal(
            user_id=int(row["id"]),
            username=str(row.get("username") or "queue"),
            role=str(row.get("role") or "user"),
        )
        return principal, principal
    except Exception as exc:  # pragma: no cover - attribution is never fatal
        logger.warning("队列任务归属恢复失败 user_id=%s: %s", owner, exc)
        return LOCAL_PRINCIPAL, None


# ------------------------------------------------------------------- playlist


def list_playlist(conn) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, drama_name, enabled, sort_order, run_count, last_run_at, created_at
            FROM hongguo_drama_playlist
            ORDER BY sort_order, id
            """
        )
        return list(cur.fetchall() or [])


def add_playlist_names(conn, names: Sequence[str], owner_user_id: int = 0) -> List[Dict[str, Any]]:
    """Append dramas that are not in the 剧单 yet; already-known names are a no-op.

    ``ON DUPLICATE KEY UPDATE`` alone is not enough: this table was created by
    SQLAlchemy before ``schema.py`` carried the DDL, so the UNIQUE key on
    ``drama_name`` is missing on databases built that way and the statement
    happily inserts a twin. Filtering against the table first keeps the result
    correct on both shapes, and stops the sort_order counter from drifting.
    """
    names = normalize_names(names)
    if not names:
        return []
    with conn.cursor() as cur:
        cur.execute("SELECT drama_name FROM hongguo_drama_playlist")
        known = {str(row.get("drama_name")) for row in (cur.fetchall() or [])}
        fresh = [name for name in names if name not in known]
        if not fresh:
            return list_playlist(conn)
        # The alias matters: without it pymysql keys the row by the literal
        # expression text, which is both unreadable and easy to mistype in tests.
        cur.execute("SELECT COALESCE(MAX(sort_order), 0) AS max_order FROM hongguo_drama_playlist")
        start = int((cur.fetchone() or {}).get("max_order") or 0)
        for offset, name in enumerate(fresh, start=1):
            cur.execute(
                """
                INSERT INTO hongguo_drama_playlist (drama_name, enabled, sort_order, owner_user_id)
                VALUES (%s, 1, %s, %s)
                ON DUPLICATE KEY UPDATE enabled=1
                """,
                (name, start + offset, owner_user_id),
            )
    return list_playlist(conn)


def update_playlist_entry(conn, entry_id: int, *, enabled: Optional[bool], drama_name: Optional[str]) -> bool:
    sets: List[str] = []
    params: List[Any] = []
    if enabled is not None:
        sets.append("enabled=%s")
        params.append(1 if enabled else 0)
    if drama_name is not None and str(drama_name).strip():
        sets.append("drama_name=%s")
        params.append(str(drama_name).strip()[:200])
    if not sets:
        return False
    params.append(int(entry_id))
    with conn.cursor() as cur:
        cur.execute("UPDATE hongguo_drama_playlist SET %s WHERE id=%%s" % ", ".join(sets), tuple(params))
        return cur.rowcount > 0


def delete_playlist_entry(conn, entry_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM hongguo_drama_playlist WHERE id=%s", (int(entry_id),))
        return cur.rowcount > 0


def enabled_playlist_names(conn) -> List[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT drama_name FROM hongguo_drama_playlist WHERE enabled=1 ORDER BY sort_order, id"
        )
        return [str(row["drama_name"]) for row in (cur.fetchall() or [])]


def history_drama_names(conn, limit: int = HISTORY_IMPORT_LIMIT) -> List[str]:
    """Distinct 剧名 already used, most recently batched first.

    ``MAX(id)`` rather than ``MAX(created_at)``: the auto-increment id is the one
    column that cannot tie or drift, and it is what "latest" means here.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT drama_name, MAX(id) AS last_id
            FROM hongguo_comment_tasks
            WHERE drama_name IS NOT NULL AND drama_name <> ''
            GROUP BY drama_name
            ORDER BY last_id DESC
            LIMIT %s
            """,
            (max(1, int(limit)),),
        )
        return normalize_names([row.get("drama_name") for row in (cur.fetchall() or [])])


def import_history_names(
    conn, owner_user_id: int = 0, limit: int = HISTORY_IMPORT_LIMIT
) -> Dict[str, Any]:
    """Add every previously-run 剧名 that is not in the 剧单 yet.

    Existing rows are left completely alone: their ``enabled`` flag, run counter
    and sort position are the operator's, and re-importing must not reset them.
    """
    scanned = history_drama_names(conn, limit)
    existing = {str(row.get("drama_name")) for row in list_playlist(conn)}
    fresh = [name for name in scanned if name not in existing]
    items = add_playlist_names(conn, fresh, owner_user_id) if fresh else list_playlist(conn)
    return {"added": fresh, "items": items, "scanned": len(scanned)}


# --------------------------------------------------------------- config (timer)


def save_config(
    conn,
    *,
    daily_enabled: Optional[bool] = None,
    daily_time: Optional[str] = None,
    daily_mode: Optional[str] = None,
    devices: Optional[Sequence[Dict[str, Any]]] = None,
    template: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Patch the single config row; ``None`` means "leave this field alone"."""
    _ensure_config(conn)
    sets: List[str] = []
    params: List[Any] = []
    if daily_enabled is not None:
        sets.append("daily_enabled=%s")
        params.append(1 if daily_enabled else 0)
    if daily_time is not None:
        sets.append("daily_time=%s")
        params.append(parse_daily_time(daily_time).strftime("%H:%M"))
    if daily_mode is not None:
        sets.append("daily_mode=%s")
        params.append(daily_mode if daily_mode in DAILY_MODES else "all_random")
    if devices is not None:
        sets.append("devices_json=%s")
        params.append(json.dumps(list(devices), ensure_ascii=False))
    if template is not None:
        sets.append("template_json=%s")
        params.append(json.dumps(template or {}, ensure_ascii=False))
    if sets:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE hongguo_queue_config SET %s WHERE id=1" % ", ".join(sets),
                tuple(params),
            )
    return _ensure_config(conn)


# ---------------------------------------------------------------------- queue


def create_queue(
    conn,
    names: Sequence[str],
    devices: Sequence[Dict[str, Any]],
    template: Optional[Dict[str, Any]],
    *,
    source: str = "manual",
    trigger_date: Optional[date] = None,
    owner_user_id: int = 0,
) -> Optional[str]:
    names = normalize_names(names)
    if not names:
        return None
    devices_json = json.dumps(list(devices or []), ensure_ascii=False)
    template_json = json.dumps(template or {}, ensure_ascii=False)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    prefix = "daily" if source == "daily" else "queue"
    queue_id = "%s-%s-%04d" % (prefix, stamp, random.randint(0, 9999))
    with conn.cursor() as cur:
        for seq, name in enumerate(names, start=1):
            cur.execute(
                """
                INSERT INTO hongguo_queue_item
                    (queue_id, seq, drama_name, status, source, trigger_date,
                     devices_json, template_json, owner_user_id)
                VALUES (%s, %s, %s, 'pending', %s, %s, %s, %s, %s)
                """,
                (queue_id, seq, name, source, trigger_date, devices_json, template_json, owner_user_id),
            )
    return queue_id


def cancel_pending(conn, queue_id: Optional[str]) -> int:
    """Drop everything still waiting in a queue. A running drama is left alone."""
    with conn.cursor() as cur:
        if queue_id:
            cur.execute(
                """
                UPDATE hongguo_queue_item
                SET status='cancelled', finished_at=%s, updated_at=%s
                WHERE queue_id=%s AND status='pending'
                """,
                (datetime.now(), datetime.now(), queue_id),
            )
        else:
            cur.execute(
                """
                UPDATE hongguo_queue_item
                SET status='cancelled', finished_at=%s, updated_at=%s
                WHERE status='pending'
                """,
                (datetime.now(), datetime.now()),
            )
        return cur.rowcount


def active_queue_snapshot(conn) -> Dict[str, Any]:
    queue_id = _unfinished_queue_id(conn)
    if not queue_id:
        return {"queue_id": None, "items": [], "summary": summarize_items([])}
    items = _queue_items(conn, queue_id)
    return {"queue_id": queue_id, "items": items, "summary": summarize_items(items)}


def _finish_item(conn, item: Dict[str, Any], status: str, message: Optional[str]) -> None:
    now = datetime.now()
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE hongguo_queue_item
            SET status=%s, error_message=%s, finished_at=%s, updated_at=%s
            WHERE id=%s
            """,
            (status, message, now, now, int(item["id"])),
        )
        if status == "done":
            cur.execute(
                """
                UPDATE hongguo_drama_playlist
                SET run_count=run_count+1, last_run_at=%s
                WHERE drama_name=%s
                """,
                (now, item.get("drama_name")),
            )


def _start_item(
    conn,
    item: Dict[str, Any],
    devices: Sequence[Dict[str, Any]],
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Create and start the run for one queue item.

    The task rows are committed before ``_start_task_on_device`` is called,
    because that helper opens its own connection and would not see uncommitted
    inserts.

    The creating account is put back into the context first: this runs on the
    dispatcher thread, which has no request context, and without it every
    queued task would be filed under the virtual ``user_id=0`` principal.
    """
    from api.security import current_principal, set_current_principal

    now = now or datetime.now()
    previous = current_principal()
    principal, _ = _principal_for_owner(conn, item.get("owner_user_id"))
    set_current_principal(principal)

    try:
        payload = build_task_payload(str(item.get("drama_name") or ""), _template_from(item))
        run_id = "multi-%s-%05d" % (now.strftime("%Y%m%d%H%M%S"), random.randint(0, 99999))
        attempts = int(item.get("attempt") or 0) + 1
        total = int(item.get("_queue_total") or 0)
        seq = int(item.get("seq") or 0)
        # Claim the item before touching the devices. Two ticks can overlap - the
        # 20s dispatcher racing a manual "立即推进一次", or two API instances that
        # share the same worker id - and both would otherwise start the same drama
        # on the same emulators. The conditional UPDATE makes exactly one win; the
        # loser sees rowcount 0 and leaves the queue alone.
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE hongguo_queue_item
                SET status='running', multi_run_id=%s, attempt=%s, started_at=%s, updated_at=%s
                WHERE id=%s AND status='pending'
                """,
                (run_id, attempts, now, now, int(item["id"])),
            )
            if cur.rowcount != 1:
                return {"run_id": None, "task_ids": [], "devices": [], "claimed": False}
        conn.commit()
        task_ids: List[int] = []
        for device in devices:
            addr = str(device.get("addr") or "")
            task_id = _insert_task_record(
                conn,
                payload,
                device_addr=addr,
                device_label=str(device.get("label") or addr),
                multi_run_id=run_id,
                worker_id=device.get("worker_id") or _local_worker_id(),
            )
            _insert_log(
                conn,
                task_id,
                "队列任务已创建：第 %d/%d 部《%s》，批次=%s，设备=%s"
                % (seq, total or seq, item.get("drama_name"), run_id, addr),
            )
            task_ids.append(task_id)
        conn.commit()
    finally:
        set_current_principal(previous)
    return {"run_id": run_id, "task_ids": task_ids, "devices": [dict(device) for device in devices]}


def _start_tasks(task_ids: Sequence[int], devices: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    for task_id, device in zip(task_ids, devices):
        addr = str(device.get("addr") or "")
        try:
            _start_task_on_device(task_id, device_addr=addr)
        except HTTPException as exc:
            failures.append({"task_id": task_id, "device_addr": addr, "message": str(exc.detail)})
        except Exception as exc:  # pragma: no cover - defensive
            failures.append({"task_id": task_id, "device_addr": addr, "message": str(exc)})
    return failures


# ------------------------------------------------------------------ dispatcher


def _tick_plan(now: datetime) -> Dict[str, Any]:
    """Do the database half of a tick and say what should be started next."""
    plan: Dict[str, Any] = {
        "now": now,
        "daily_fired": None,
        "finalized": [],
        "start": None,
        "waiting": False,
        "queue_id": None,
        "summary": summarize_items([]),
        "notes": [],
    }
    with _connection() as conn:
        _ensure_queue_columns(conn)
        config = _ensure_config(conn)

        unfinished = _unfinished_queue_id(conn)
        if daily_should_fire(
            daily_enabled=bool(config.get("daily_enabled")),
            last_fired_date=config.get("last_fired_date"),
            now=now,
            daily_time=config.get("daily_time"),
            unfinished_queue=unfinished,
        ):
            names = enabled_playlist_names(conn)
            devices = _devices_from(config)
            if not names:
                plan["notes"].append("每日定时已到，但剧单是空的")
            elif not devices:
                _warn_no_devices()
                plan["notes"].append("每日定时已到，但没有配置设备，暂时不触发")
            else:
                mode = str(config.get("daily_mode") or "all_random")
                if mode not in DAILY_MODES:
                    mode = "all_random"
                picked = names[:]
                random.shuffle(picked)
                if mode == "random_one":
                    picked = picked[:1]
                queue_id = create_queue(
                    conn,
                    picked,
                    devices,
                    _template_from(config),
                    source="daily",
                    trigger_date=now.date(),
                    owner_user_id=0,
                )
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE hongguo_queue_config SET last_fired_date=%s WHERE id=1",
                        (now.date(),),
                    )
                plan["daily_fired"] = {"queue_id": queue_id, "names": picked, "mode": mode}

        queue_id = _unfinished_queue_id(conn)
        plan["queue_id"] = queue_id
        if not queue_id:
            return plan

        items = _queue_items(conn, queue_id)
        total = len(items)
        for item in items:
            if str(item.get("status")) != "running":
                continue
            run_id = item.get("multi_run_id")
            if not run_id:
                _finish_item(conn, item, "failed", "队列条目没有关联批次，已跳过")
                plan["finalized"].append({"drama": item.get("drama_name"), "status": "failed"})
                continue
            rows = _fetch_multi_run_tasks(conn, str(run_id))
            stalled = None
            verdict = verdict_from_task_rows(rows)
            if verdict is not None and verdict[0] == "failed":
                # A foreign sweep is a statement about the row, not about the
                # drama. While it is fresh, wait for the engine to repair the
                # row - replaying here costs the whole batch (09-30, seq4).
                swept = untrusted_failure_reason(rows, now)
                if swept:
                    _warn_foreign_sweep(item, swept)
                    plan["notes"].append(swept)
                    plan["waiting"] = True
                    continue
            if verdict is None:
                # A batch that was created but never started would otherwise keep
                # this item on ``running`` forever (``pending`` is neither
                # terminal nor busy), stalling every drama behind it.
                stalled = stalled_start_reason(rows, now)
                if stalled:
                    verdict = ("failed", stalled)
            if verdict is None:
                plan["waiting"] = True
                continue
            status, message = verdict
            if status == "failed" and retry_allowed(item, infra_failure=bool(stalled)):
                # Give a run that died on a device hiccup one more go before
                # the drama is dropped from the list. A batch that never
                # launched is blamed on the infrastructure: it refunds the
                # attempt ``_start_item`` already spent and counts against
                # ``infra_retries`` instead.
                #
                # A real task failure also remembers *which* devices failed, so
                # the replay only covers those. Every device watches the whole
                # drama on its own, so replaying the ones that already finished
                # is pure waste (2026-10-01 seq3: 2 died, 4 were replayed).
                retry_addrs = [] if stalled else failed_device_addrs(rows)
                retry_json = json.dumps(retry_addrs, ensure_ascii=False) if retry_addrs else None
                with conn.cursor() as cur:
                    if stalled:
                        cur.execute(
                            """
                            UPDATE hongguo_queue_item
                            SET status='pending',
                                attempt=GREATEST(attempt-1, 0),
                                infra_retries=COALESCE(infra_retries, 0)+1,
                                retry_devices_json=NULL,
                                updated_at=%s
                            WHERE id=%s
                            """,
                            (now, int(item["id"])),
                        )
                    else:
                        cur.execute(
                            "UPDATE hongguo_queue_item "
                            "SET status='pending', retry_devices_json=%s, updated_at=%s "
                            "WHERE id=%s",
                            (retry_json, now, int(item["id"])),
                        )
                if retry_addrs and len(retry_addrs) < len(rows):
                    plan["notes"].append(
                        "《%s》重跑只覆盖 %d/%d 台未完成的设备"
                        % (item.get("drama_name"), len(retry_addrs), len(rows))
                    )
                plan["finalized"].append({"drama": item.get("drama_name"), "status": "retry", "message": message})
                continue
            _finish_item(conn, item, status, message)
            plan["finalized"].append(
                {"drama": item.get("drama_name"), "status": status, "message": message}
            )

        items = _queue_items(conn, queue_id)
        plan["summary"] = summarize_items(items)
        if any(str(item.get("status")) == "running" for item in items):
            plan["waiting"] = True
            return plan

        nxt = pick_next_item(items)
        if not nxt:
            return plan
        nxt = dict(nxt)
        nxt["_queue_total"] = total
        devices = _devices_from(nxt) or _devices_from(config)
        retry_raw = _json_column(nxt, "retry_devices_json", [])
        retry_addrs = (
            [str(addr).strip() for addr in retry_raw if str(addr or "").strip()]
            if isinstance(retry_raw, list)
            else []
        )
        if retry_addrs:
            wanted = set(retry_addrs)
            narrowed = [device for device in devices if str(device.get("addr") or "") in wanted]
            if narrowed and len(narrowed) < len(devices):
                plan["notes"].append(
                    "《%s》上次有 %d 台设备没跑完，本次只重跑这几台"
                    % (nxt.get("drama_name"), len(narrowed))
                )
                devices = narrowed
        if not devices:
            _finish_item(conn, nxt, "failed", "没有可用设备，无法启动")
            plan["finalized"].append({"drama": nxt.get("drama_name"), "status": "failed", "message": "没有可用设备"})
            plan["summary"] = summarize_items(_queue_items(conn, queue_id))
            return plan
        started = _start_item(conn, nxt, devices, now)
        if started.get("claimed") is False:
            # Another tick got there first; it owns this drama now.
            plan["notes"].append("另一路调度抢先启动了《%s》，本轮跳过" % nxt.get("drama_name"))
            plan["waiting"] = True
            plan["summary"] = summarize_items(_queue_items(conn, queue_id))
            return plan
        plan["start"] = {
            "item_id": int(nxt["id"]),
            "drama_name": nxt.get("drama_name"),
            "seq": int(nxt.get("seq") or 0),
            "total": total,
            "owner_user_id": nxt.get("owner_user_id"),
            **started,
        }
        plan["summary"] = summarize_items(_queue_items(conn, queue_id))
        return plan


def _warn_no_devices() -> None:
    global _no_device_warned_at
    now = time.monotonic()
    if now - _no_device_warned_at < 600:
        return
    _no_device_warned_at = now
    logger.warning("队列定时已到但没有配置设备，先不触发；请在队列设置里选好实例")


def run_queue_tick(now: Optional[datetime] = None) -> Dict[str, Any]:
    """One dispatch step. Cheap and safe to call from a thread or by hand."""
    now = now or datetime.now()
    plan = _tick_plan(now)
    failures = _start_tasks((plan["start"] or {}).get("task_ids") or [], (plan["start"] or {}).get("devices") or [])
    if failures and plan.get("start"):
        started_count = len((plan["start"].get("task_ids") or [])) - len(failures)
        if started_count <= 0:
            with _connection() as conn:
                rows = _queue_items(conn, plan["queue_id"]) if plan.get("queue_id") else []
                target = next((row for row in rows if int(row["id"]) == plan["start"]["item_id"]), None)
                if target:
                    _finish_item(
                        conn,
                        target,
                        "failed",
                        "所有设备都没能启动：" + "; ".join(item["message"] for item in failures[:3]),
                    )
            plan["finalized"].append({"drama": plan["start"]["drama_name"], "status": "failed"})
            plan["start"] = None
        else:
            # Partial dispatch: the devices that launched keep the item on
            # ``running``, so the ones that never launched sit on ``pending`` and
            # cannot be reaped until the grace window passes. Say it out loud -
            # silently absorbing this is how 09-30 lost three of four devices.
            logger.warning(
                "队列：第 %s 部《%s》有 %d/%d 台设备没能启动：%s",
                plan["start"].get("seq"),
                plan["start"].get("drama_name"),
                len(failures),
                len(plan["start"].get("devices") or []),
                "; ".join(str(item.get("message"))[:80] for item in failures[:3]),
            )
            plan["notes"].append(
                "《%s》有 %d 台设备没能启动（设备忙或启动失败）"
                % (plan["start"].get("drama_name"), len(failures))
            )
    plan["failures"] = failures
    return plan


# ------------------------------------------------------------- background loop

_dispatcher_thread: Optional[threading.Thread] = None
_dispatcher_stop = threading.Event()


def dispatcher_enabled() -> bool:
    value = os.environ.get("SUPERCLAW_QUEUE_DISPATCHER", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _warn_db_down_once() -> None:
    """A multi-hour outage must not bury the real errors under one line per tick."""
    global _db_down_warned_at
    now = time.monotonic()
    if now - _db_down_warned_at < 600:
        return
    _db_down_warned_at = now
    logger.warning("队列调度：数据库暂时不可用，本轮跳过（会一直重试）")


def _dispatcher_loop(interval: float) -> None:
    from rpa.hongguo.dbresilience import DbUnavailable

    logger.info("队列调度器已启动，每 %.0f 秒检查一次", interval)
    while not _dispatcher_stop.wait(interval):
        try:
            result = run_queue_tick()
        except DbUnavailable:
            continue  # the resilience layer is already riding it out
        except HTTPException as exc:
            # ``_connection()`` turns a transient connect failure into a 503 and
            # logs nothing itself, so it lands here on every tick of an outage.
            # Swallow that one; anything else is a real bug and gets a traceback.
            if exc.status_code == 503:
                _warn_db_down_once()
                continue
            logger.warning("队列调度出错：%s", exc, exc_info=True)
            continue
        except Exception as exc:  # pragma: no cover - the loop must never die
            logger.warning("队列调度出错：%s", exc, exc_info=True)
            continue
        notes = []
        if result.get("daily_fired"):
            notes.append("按时入队 %s" % result["daily_fired"]["names"])
        for done in result.get("finalized") or []:
            notes.append("%s -> %s" % (done.get("drama"), done.get("status")))
        if result.get("start"):
            notes.append(
                "启动第 %s/%s 部《%s》" % (result["start"]["seq"], result["start"]["total"], result["start"]["drama_name"])
            )
        if notes:
            logger.info("队列调度：%s", "；".join(notes))


def start_dispatcher() -> Optional[threading.Thread]:
    global _dispatcher_thread
    if not dispatcher_enabled():
        logger.info("队列调度器已按环境变量关闭（SUPERCLAW_QUEUE_DISPATCHER=0）")
        return None
    if _dispatcher_thread is not None and _dispatcher_thread.is_alive():
        return _dispatcher_thread
    try:
        interval = float(os.environ.get("SUPERCLAW_QUEUE_TICK_SECONDS", "20"))
    except ValueError:
        interval = 20.0
    interval = max(5.0, interval)
    _dispatcher_stop.clear()
    thread = threading.Thread(
        target=_dispatcher_loop,
        args=(interval,),
        name="hongguo-queue-dispatcher",
        daemon=True,
    )
    _dispatcher_thread = thread
    thread.start()
    return thread


def stop_dispatcher() -> None:
    _dispatcher_stop.set()
