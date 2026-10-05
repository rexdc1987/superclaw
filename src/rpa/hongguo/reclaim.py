"""Which outside writer reaped a task row, and how to tell them apart.

Why this module exists
----------------------
``hongguo_comment_tasks`` is a **shared** table.  Every node in the fleet writes
to it, and so do two writers that live outside this repository.  Three very
different stories therefore look identical in the database - a row parked on
``stopped`` with an ``error_message`` - and they call for opposite reactions:

``this machine's own restart``
    ``reconcile_runtime_state`` stopped the row because the process driving it
    went away.  The row is right and the thread is gone, so the run really is
    over and the queue may start the drama again immediately.
``an old-version node's startup reconcile``
    A node still running a pre-3790522 build sweeps *every* running task in the
    shared database whenever it starts.  The row is wrong and the thread is
    alive, so acting on it throws away a run that still holds a device.
``the fleet watchdog``
    ``执行线程已失联`` reaps by the age of ``updated_at``.  While MySQL is
    unreachable a healthy thread cannot refresh that column, so an outage
    longer than the threshold reads as "this thread went quiet" when the truth
    is "this thread could not write".

The engine already draws this distinction once per episode
(``TaskEngine._check_external_reclaim``).  The queue dispatcher needs exactly
the same reading when it judges a finished batch, and the two must never
disagree: a batch replayed because one side read a foreign sweep as a real
failure costs the whole run again (2026-09-30, seq4 《胭脂如梦如雨如尘2》: batch 1
finished 4/4 at 48/48, a foreign reconcile reaped one row mid-flight, the queue
called the batch failed, and a second full pass was dispatched - eight
device-hours - whose tail then collided with the still-running device and left
the item ``failed`` despite the drama having been watched to the end).

Both callers therefore use the rules below rather than their own copies.  A
duplicated string match is exactly how the two drift apart.
"""

from __future__ import annotations

from typing import Optional

__all__ = [
    "RECONCILE_SNIPPET",
    "SELF_RECONCILE_OWNER_MARK",
    "WATCHDOG_HEARTBEAT_SNIPPET",
    "WATCHDOG_SNIPPET",
    "classify",
    "is_foreign_fleet_reconcile",
    "is_foreign_sweep",
    "is_watchdog_reap",
]

#: Since 3790522 (2026-09-11) ``reconcile_runtime_state`` names the machine it
#: is stopping tasks for - ``执行电脑 <worker_id> 的服务进程已重启…``.  The old
#: build wrote the very same sentence with no owner at all, and *that* is what
#: makes "somebody else's startup" distinguishable from our own.  The prefix is
#: the whole discriminator, so it is spelled out once, here.
SELF_RECONCILE_OWNER_MARK = "执行电脑"

#: Half of the reconcile sentence, stable across both builds.
RECONCILE_SNIPPET = "服务进程已重启，原执行线程不存在"

#: The watchdog's message, matched by shape rather than by call site because it
#: is written from outside this repo.  Tasks 420-423 were reaped on 2026-09-17
#: at episode 47/48 with ``执行线程已失联（113 分钟无心跳，节点
#: DESKTOP-S8K66QQ），任务已自动回收，如仍需执行请重新启动任务`` while the threads
#: were merely locked out of MySQL.
WATCHDOG_SNIPPET = "执行线程已失联"
WATCHDOG_HEARTBEAT_SNIPPET = "无心跳"


def is_foreign_fleet_reconcile(message: str) -> bool:
    """True only for the pre-3790522 message, which named no machine."""
    if RECONCILE_SNIPPET not in message:
        return False
    return SELF_RECONCILE_OWNER_MARK not in message


def is_watchdog_reap(message: str) -> bool:
    """True for the fleet watchdog's "this thread went silent" reap."""
    return WATCHDOG_SNIPPET in message and WATCHDOG_HEARTBEAT_SNIPPET in message


def is_foreign_sweep(message: str) -> bool:
    """True when the message names an outside sweeper rather than this run.

    A message from this machine's *own* reconcile returns False on purpose: it
    carries ``执行电脑 <worker> 的``, because that restart really did kill the
    thread and the failure is honest.
    """
    return is_foreign_fleet_reconcile(message) or is_watchdog_reap(message)


def classify(message: str) -> Optional[str]:
    """Name the outside sweeper behind ``message``, or None when there is none.

    Callers use this for their log line, so the operator can tell a fleet-wide
    reconcile apart from a watchdog false reaping without reading the message.
    """
    if is_foreign_fleet_reconcile(message):
        return "其它节点旧版本的全库 reconcile 误标"
    if is_watchdog_reap(message):
        return "其它节点的看门狗误判失联"
    return None
