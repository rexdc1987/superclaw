"""Resilience tests for the Hongguo engine's database access.

These pin the three defects that turned one twenty minute outage on 2026-09-16
into a lost four-device batch (tasks 409-412):

* a transient ``OperationalError`` killed the task thread outright - 411 died
  with ``(2003, "Can't connect to MySQL server ... (timed out)")`` and its own
  ``except Exception`` handler then tried to write ``status='failed'`` over the
  same broken link;
* ``_log`` swallowed every exception, so 409/410/412 left no trace at all and
  only an outside watchdog's message explained what happened;
* nothing retried, so the link coming back at 20:51 could never let a task
  resume.

The retry sleep is injected through ``engine._db_sleep`` so none of this takes
real time.
"""

import re
import sys
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pymysql

from rpa.hongguo import dbresilience
from rpa.hongguo import engine as engine_module
from rpa.hongguo import leases as leases_module
from rpa.hongguo.engine import ExternalReclaimDetected, TaskEngine
from rpa.hongguo.dbresilience import (
    DbHealth,
    DbUnavailable,
    LogSpool,
    call_with_retry,
    flush_spooled_logs,
    is_transient_error,
)

CANNOT_CONNECT = pymysql.err.OperationalError(
    2003, "Can't connect to MySQL server on '43.154.184.208' (timed out)"
)
LOST_CONNECTION = pymysql.err.OperationalError(2013, "Lost connection to MySQL server during query")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def make_connection_context():
    cursor = MagicMock()
    cursor_context = MagicMock()
    cursor_context.__enter__.return_value = cursor
    connection = MagicMock()
    connection.cursor.return_value = cursor_context
    context = MagicMock()
    context.__enter__.return_value = connection
    return context, connection, cursor


def make_engine(task_id=409, **kwargs):
    engine = TaskEngine(task_id=task_id, db_config={}, screenshot_dir="C:/tmp", **kwargs)
    engine._db_sleep = lambda seconds: None  # never really wait in a test
    return engine


# ---------------------------------------------------------------------------
# error classification
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "exc",
    [
        pymysql.err.OperationalError(2003, "can't connect"),
        pymysql.err.OperationalError(2006, "server has gone away"),
        pymysql.err.OperationalError(2013, "lost connection"),
        pymysql.err.OperationalError(1205, "lock wait timeout"),
        pymysql.err.InterfaceError(0, ""),
        pymysql.err.InternalError("Packet sequence number wrong - got 1 expected 2"),
        ConnectionResetError("reset by peer"),
        TimeoutError("timed out"),
    ],
)
def test_transient_failures_are_retryable(exc):
    assert is_transient_error(exc) is True


def test_the_packet_desync_error_from_the_20260930_incident_is_retryable():
    """09-30 00:00~00:30：远程库抖动，6 个任务被这条原文写进 error_message 判死。

    ``InternalError`` 继承 ``DatabaseError``，不是 ``OperationalError``，所以按
    errno 的分类完全看不到它；而 pymysql 抛它之前已经 ``_force_close()`` 了
    socket —— 换新连接重试正是唯一正确的处理方式。
    """
    exc = pymysql.err.InternalError("Packet sequence number wrong - got 1 expected 2")
    assert is_transient_error(exc) is True


def test_a_plain_internal_error_is_still_not_retryable():
    """只有包序号错乱这一种 InternalError 是瞬态，别的不能被顺手吞掉。"""
    assert is_transient_error(pymysql.err.InternalError("corrupt result set")) is False


@pytest.mark.parametrize(
    "exc",
    [
        pymysql.err.OperationalError(1045, "Access denied for user"),
        pymysql.err.OperationalError(1049, "Unknown database"),
        pymysql.err.ProgrammingError(1064, "syntax error"),
        pymysql.err.IntegrityError(1062, "Duplicate entry"),
        pymysql.err.InternalError("corrupt result set"),
        KeyError("db_config"),
        ValueError("nope"),
    ],
)
def test_real_mistakes_are_not_retryable(exc):
    """A wrong password or a bad statement must fail loudly, not slowly."""
    assert is_transient_error(exc) is False


# ---------------------------------------------------------------------------
# call_with_retry
# ---------------------------------------------------------------------------
def test_retry_recovers_the_call_without_the_caller_noticing():
    attempts = {"n": 0}

    def work():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise CANNOT_CONNECT
        return "committed"

    assert (
        call_with_retry(work, label="counter", budget=30, sleep=lambda seconds: None)
        == "committed"
    )
    assert attempts["n"] == 3


def test_a_zero_budget_reraises_the_original_error():
    """Misconfiguration must read exactly as loudly as it did before."""
    with pytest.raises(pymysql.err.OperationalError) as excinfo:
        call_with_retry(
            lambda: (_ for _ in ()).throw(CANNOT_CONNECT),
            label="task_update",
            budget=0,
            sleep=lambda seconds: None,
        )
    assert excinfo.value.args[0] == 2003


def test_spending_the_budget_reports_db_unavailable():
    with pytest.raises(DbUnavailable) as excinfo:
        call_with_retry(
            lambda: (_ for _ in ()).throw(CANNOT_CONNECT),
            label="task_update",
            budget=0.2,
            sleep=lambda seconds: None,
        )
    assert excinfo.value.label == "task_update"
    assert excinfo.value.attempts >= 2


def test_a_programming_error_is_never_retried():
    attempts = {"n": 0}

    def work():
        attempts["n"] += 1
        raise pymysql.err.ProgrammingError(1064, "syntax error")

    with pytest.raises(pymysql.err.ProgrammingError):
        call_with_retry(work, label="x", budget=30, sleep=lambda seconds: None)
    assert attempts["n"] == 1


def test_retry_gives_up_as_soon_as_the_task_is_stopped():
    with pytest.raises(pymysql.err.OperationalError):
        call_with_retry(
            lambda: (_ for _ in ()).throw(CANNOT_CONNECT),
            label="x",
            budget=30,
            should_abort=lambda: True,
            sleep=lambda seconds: None,
        )


# ---------------------------------------------------------------------------
# DbHealth
# ---------------------------------------------------------------------------
def test_one_outage_is_counted_once_however_many_attempts_fail():
    health = DbHealth(probe_interval=5.0)
    for _ in range(50):
        health.mark_down(CANNOT_CONNECT)
    assert health.failure_count == 1
    assert health.snapshot()["last_error"].startswith("(2003")


def test_probe_window_expiry_lets_a_call_through_without_faking_a_recovery():
    health = DbHealth(probe_interval=0.0)
    health.mark_down(CANNOT_CONNECT)
    assert health.is_down() is False
    assert health.recovery_count == 0  # nothing has succeeded yet

    health.mark_up()
    assert health.recovery_count == 1
    assert health.ever_connected is True

    health.mark_down(CANNOT_CONNECT)
    assert health.failure_count == 2  # a genuinely separate outage


def test_ever_connected_stays_false_until_something_succeeds():
    health = DbHealth(probe_interval=0.0)
    assert health.ever_connected is False
    health.mark_down(CANNOT_CONNECT)
    assert health.ever_connected is False


# ---------------------------------------------------------------------------
# socket timeouts
# ---------------------------------------------------------------------------
def test_apply_timeouts_fills_in_missing_socket_timeouts():
    config = dbresilience.apply_timeouts({"host": "db", "user": "u"})
    assert config["connect_timeout"] == dbresilience.CONNECT_TIMEOUT_SECONDS
    assert config["read_timeout"] == dbresilience.READ_TIMEOUT_SECONDS
    assert config["write_timeout"] == dbresilience.WRITE_TIMEOUT_SECONDS


def test_apply_timeouts_respects_an_explicit_value():
    config = dbresilience.apply_timeouts({"connect_timeout": 1})
    assert config["connect_timeout"] == 1


def test_a_transient_connect_failure_opens_the_breaker(monkeypatch):
    dbresilience.DB_HEALTH.reset()
    monkeypatch.setattr(
        dbresilience.pymysql, "connect", MagicMock(side_effect=CANNOT_CONNECT)
    )
    with pytest.raises(pymysql.err.OperationalError):
        dbresilience.resilient_connect({"host": "db"})
    assert dbresilience.DB_HEALTH.is_down() is True
    assert dbresilience.DB_HEALTH.ever_connected is False


# ---------------------------------------------------------------------------
# LogSpool
# ---------------------------------------------------------------------------
def test_spool_round_trips_datetimes_and_nulls(tmp_path):
    spool = LogSpool(tmp_path / "spool")
    stamp = datetime(2026, 9, 16, 20, 30, 29, 123456)
    assert spool.append(
        {
            "task_id": 409,
            "level": "info",
            "message": "第12集 观察完成",
            "episode_number": 12,
            "screenshot_path": None,
            "created_at": stamp,
        }
    )

    rows = spool.pending()
    assert len(rows) == 1
    assert rows[0]["created_at"] == stamp  # original timestamp, not the replay time
    assert rows[0]["episode_number"] == 12
    assert rows[0]["screenshot_path"] is None
    assert rows[0]["message"] == "第12集 观察完成"


def test_spool_survives_an_unusable_path(tmp_path):
    spool = LogSpool("\x00not-a-path")
    assert spool.append({"task_id": 1}) is False
    assert spool.dropped_count == 1
    assert spool.pending_count() == 0


def test_spool_drops_a_row_it_cannot_serialise(tmp_path):
    spool = LogSpool(tmp_path / "spool")
    assert spool.append({"task_id": 1, "created_at": object()}) is False
    assert spool.dropped_count == 1


def test_spool_rewrite_keeps_only_the_undelivered_rows(tmp_path):
    spool = LogSpool(tmp_path / "spool")
    spool.append({"task_id": 1, "message": "a", "created_at": datetime.now()})
    spool.append({"task_id": 1, "message": "b", "created_at": datetime.now()})
    spool.rewrite(spool.pending()[1:])
    assert [row["message"] for row in spool.pending()] == ["b"]
    spool.clear()
    assert spool.pending_count() == 0
    # Emptying truncates in place instead of unlinking.  A refused unlink
    # (antivirus, a sandbox, an open handle) would leave already-delivered rows
    # on disk and the next probe would replay them - which is how the three rows
    # from 2026-09-17 17:37 reached hongguo_execution_logs three times over.
    assert not spool.path.exists() or spool.path.read_text(encoding="utf-8") == ""


# ---------------------------------------------------------------------------
# flush_spooled_logs
# ---------------------------------------------------------------------------
def test_replay_removes_the_rows_it_delivered(tmp_path):
    spool = LogSpool(tmp_path / "spool")
    spool.append({"task_id": 409, "message": "a", "created_at": datetime.now()})
    spool.append({"task_id": 409, "message": "b", "created_at": datetime.now()})
    context, connection, cursor = make_connection_context()
    delivered_rows = []

    with patch.object(dbresilience, "resilient_connect", return_value=connection):
        delivered = flush_spooled_logs(
            lambda cur, row: delivered_rows.append(row), spool, {}
        )

    assert delivered == 2
    assert [row["message"] for row in delivered_rows] == ["a", "b"]
    assert connection.commit.called
    assert spool.pending_count() == 0


def test_replay_keeps_every_row_when_the_transaction_rolls_back(tmp_path):
    """A half delivered batch would silently lose the rest of the timeline."""
    spool = LogSpool(tmp_path / "spool")
    for message in ("a", "b", "c"):
        spool.append({"task_id": 409, "message": message, "created_at": datetime.now()})
    context, connection, cursor = make_connection_context()
    seen = []

    def failing_insert(cur, row):
        seen.append(row["message"])
        if len(seen) == 2:
            raise LOST_CONNECTION

    with patch.object(dbresilience, "resilient_connect", return_value=connection):
        delivered = flush_spooled_logs(failing_insert, spool, {})

    assert delivered == 0
    assert connection.rollback.called
    assert spool.pending_count() == 3


def test_replay_does_nothing_when_the_spool_is_empty(tmp_path):
    spool = LogSpool(tmp_path / "spool")
    with patch.object(dbresilience, "resilient_connect") as connect:
        assert flush_spooled_logs(lambda cur, row: None, spool, {}) == 0
    assert connect.called is False


# ---------------------------------------------------------------------------
# engine: logging must never be lost and never be fatal
# ---------------------------------------------------------------------------
def test_log_spools_without_touching_mysql_while_the_link_is_down(tmp_path):
    engine = make_engine()
    engine._connection = MagicMock()
    dbresilience.DB_HEALTH.mark_down(CANNOT_CONNECT)

    engine._log("info", "第12集 观看完成 已截图 C:/tmp/12.png")  # must not raise

    engine._connection.assert_not_called()
    rows = engine._spool.pending()
    assert len(rows) == 1
    assert rows[0]["episode_number"] == 12
    assert rows[0]["screenshot_path"] == "C:/tmp/12.png"


def test_log_spools_when_the_write_fails_transiently(tmp_path):
    """This is what 409/410/412 should have done instead of going silent."""
    engine = make_engine()
    engine._connection = MagicMock(side_effect=CANNOT_CONNECT)

    engine._log("info", "第12集 观看完成")  # must not raise

    rows = engine._spool.pending()
    assert len(rows) == 1
    assert rows[0]["level"] == "info"
    assert rows[0]["message"] == "第12集 观看完成"


def test_log_does_not_retry_forever_on_an_outage(tmp_path):
    """A log line is not worth stalling the device flow for."""
    engine = make_engine()
    engine._connection = MagicMock(side_effect=CANNOT_CONNECT)

    engine._log("info", "x")

    assert engine._connection.call_count <= 3
    assert engine._spool.pending_count() == 1


def test_a_successful_log_replays_what_was_spooled_before(tmp_path):
    engine = make_engine()
    engine._spool.append(
        {"task_id": 409, "level": "warn", "message": "断网期间的日志", "created_at": datetime.now()}
    )
    context, connection, cursor = make_connection_context()
    engine._connection = MagicMock(return_value=context)
    dbresilience.DB_HEALTH.mark_up()

    with patch.object(dbresilience, "resilient_connect", return_value=connection):
        engine._log("info", "网络恢复后的第一条")

    assert engine._spool.pending_count() == 0


# ---------------------------------------------------------------------------
# engine: the failure that killed task 411
# ---------------------------------------------------------------------------
def test_task_411_no_longer_dies_on_a_2003_outage():
    """Exactly 411's failure: a transient connect error on `_update_task`."""
    engine = make_engine(task_id=411)
    dbresilience.DB_HEALTH.mark_up()  # this process has talked to MySQL before

    attempts = {"n": 0}
    context, connection, cursor = make_connection_context()

    def flaky():
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise CANNOT_CONNECT
        return context

    engine._connection = MagicMock(side_effect=flaky)

    engine._update_task(status="running", current_episode=13)  # must not raise

    assert attempts["n"] == 3
    assert engine._db_outage_seen is True
    assert engine._db_retry_count == 1


def test_a_critical_write_that_really_cannot_land_is_reported_not_swallowed():
    engine = make_engine(task_id=411, db_outage_budget=0.2)
    dbresilience.DB_HEALTH.mark_up()
    engine._connection = MagicMock(side_effect=CANNOT_CONNECT)

    with pytest.raises(DbUnavailable):
        engine._update_task(status="failed", error_message="x")


def test_a_broken_config_fails_fast_instead_of_waiting_out_a_budget():
    """A process that never reached MySQL is misconfigured, not unlucky."""
    engine = make_engine(task_id=411, db_outage_budget=1800)
    assert dbresilience.DB_HEALTH.ever_connected is False
    engine._connection = MagicMock(side_effect=CANNOT_CONNECT)

    with pytest.raises(pymysql.err.OperationalError):
        engine._update_task(status="running")


def test_the_engine_never_opens_a_connection_without_socket_timeouts():
    engine = make_engine()
    captured = {}

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    with patch.object(dbresilience.pymysql, "connect", side_effect=fake_connect):
        with engine._connection():
            pass

    assert captured["connect_timeout"] == dbresilience.CONNECT_TIMEOUT_SECONDS
    assert captured["read_timeout"] == dbresilience.READ_TIMEOUT_SECONDS
    assert captured["write_timeout"] == dbresilience.WRITE_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# engine: an outside watchdog reaping a row we are still running
# ---------------------------------------------------------------------------
def test_a_reclaimed_row_is_reported_once_the_link_is_back():
    engine = make_engine()
    engine._db_outage_seen = True
    dbresilience.DB_HEALTH.mark_up()
    engine._load_task = MagicMock(
        return_value={
            "status": "stopped",
            "error_message": "执行线程已失联（21 分钟无心跳，节点 DESKTOP-S8K66QQ），任务已自动回收",
        }
    )

    with pytest.raises(ExternalReclaimDetected) as excinfo:
        engine._check_external_reclaim()
    assert "执行线程已失联" in str(excinfo.value)


def test_reclaim_detection_is_skipped_when_this_thread_stopped_the_task():
    """A user pressing stop also writes `stopped`; that is not a reclaim."""
    engine = make_engine()
    engine._db_outage_seen = True
    engine._stop_event.set()
    engine._load_task = MagicMock(return_value={"status": "stopped"})

    engine._check_external_reclaim()  # must not raise
    engine._load_task.assert_not_called()


def test_the_reclaim_check_runs_every_episode_not_only_after_an_outage():
    """A sweep can arrive over a perfectly healthy link.

    Task 418 was reaped at 14:42 on 2026-09-17 with no outage anywhere on this
    machine, so gating the check behind ``_db_outage_seen`` would have left the
    thread driving a device no row was tracking.
    """
    engine = make_engine()
    engine._load_task = MagicMock(return_value={"status": "stopped", "error_message": ""})

    with pytest.raises(ExternalReclaimDetected):
        engine._check_external_reclaim()
    engine._load_task.assert_called_once()


def test_a_running_row_is_left_alone():
    engine = make_engine()
    engine._db_outage_seen = True
    dbresilience.DB_HEALTH.mark_up()
    engine._load_task = MagicMock(return_value={"status": "running"})

    engine._check_external_reclaim()
    # Left alone *and* un-armed again, so a stop landing on a later episode is
    # still noticed.
    assert engine._external_reclaim_checked is False
    assert engine._foreign_reclaim_repairs == 0


def test_a_row_without_a_readable_status_is_not_a_verdict():
    """A blank status is missing information, not "somebody stopped us".

    Because the check now runs on every episode, treating an unreadable row as a
    reclaim would abort any run whose row came back empty.  That is not
    hypothetical: ``test_main_loop_processes_pending_favorite_immediately_after_skip_recovery``
    mocks ``_load_task`` as ``{"drama_name": ...}`` - no status field at all -
    and the run was killed on its first episode instead of reaching the
    favourite at episode 11.
    """
    engine = make_engine()
    for row in ({}, {"status": None}, {"status": ""}, {"status": "   "}, {"status": "pending"}):
        engine._load_task = MagicMock(return_value=row)
        engine._external_reclaim_checked = False
        engine._check_external_reclaim()  # must not raise
        assert engine._external_reclaim_checked is False
        assert engine._foreign_reclaim_repairs == 0


# ---------------------------------------------------------------------------
# engine: an OLD-VERSION node's fleet-wide reconcile  (2026-09-17)
#
# Before commit 3790522 (2026-09-11) reconcile_runtime_state had no worker
# filter: starting any node running that build stopped *every* running task in
# the shared database and deleted *every* device lease.  Tasks 373, 377,
# 380-383, 394-398, 399-401 and 418 all died that way, and on 2026-09-16 a human
# repaired 394-398 by hand with exactly the note this code now writes itself.
# ---------------------------------------------------------------------------
FOREIGN_SWEEP_MESSAGE = "服务进程已重启，原执行线程不存在，请手动重新启动任务"
OWN_RECONCILE_MESSAGE = (
    "执行电脑 DESKTOP-S8K66QQ 的服务进程已重启，原执行线程不存在，请手动重新启动任务"
)


@pytest.mark.parametrize(
    "message,expected",
    [
        (FOREIGN_SWEEP_MESSAGE, True),
        (OWN_RECONCILE_MESSAGE, False),
        ("执行电脑 SOME-OTHER-NODE 的服务进程已重启，原执行线程不存在，请手动重新启动任务", False),
        ("执行线程已失联（21 分钟无心跳，节点 DESKTOP-S8K66QQ），任务已自动回收", False),
        ("", False),
    ],
)
def test_only_the_ownerless_reconcile_message_counts_as_a_foreign_sweep(message, expected):
    assert TaskEngine._is_foreign_fleet_reconcile(message) is expected


def _recording_connection(rowcount=1):
    """A stand-in for ``engine._connection()`` that records executed SQL."""
    cursor = MagicMock()
    cursor.rowcount = rowcount
    cursor_cm = MagicMock()
    cursor_cm.__enter__.return_value = cursor
    connection = MagicMock()
    connection.cursor.return_value = cursor_cm
    context = MagicMock()
    context.__enter__.return_value = connection
    return context, connection, cursor


def test_an_ownerless_fleet_sweep_is_repaired_not_obeyed():
    engine = make_engine(task_id=418)
    engine._load_task = MagicMock(
        return_value={"status": "stopped", "error_message": FOREIGN_SWEEP_MESSAGE}
    )
    context, connection, cursor = _recording_connection()
    engine._connection = MagicMock(return_value=context)
    dbresilience.DB_HEALTH.mark_up()

    engine._check_external_reclaim()  # the thread is alive: must not raise

    assert engine._foreign_reclaim_repairs == 1
    sql = " ".join(str(call.args[0]) for call in cursor.execute.call_args_list)
    assert "status='running'" in sql
    assert "error_message=NULL" in sql
    assert "hongguo_execution_logs" in sql
    # One transaction: the status repair and its audit line land together.
    engine._connection.assert_called_once()
    context.__enter__.assert_called_once()


def test_our_own_reconcile_message_still_ends_the_run():
    """The prefixed form means this machine really did restart: obey it."""
    engine = make_engine(task_id=418)
    engine._load_task = MagicMock(
        return_value={"status": "stopped", "error_message": OWN_RECONCILE_MESSAGE}
    )
    engine._connection = MagicMock(side_effect=AssertionError("must not write"))

    with pytest.raises(ExternalReclaimDetected):
        engine._check_external_reclaim()
    assert engine._foreign_reclaim_repairs == 0


def test_a_repair_that_cannot_reach_mysql_does_not_take_the_run_down():
    engine = make_engine(task_id=418)
    engine._load_task = MagicMock(
        return_value={"status": "stopped", "error_message": FOREIGN_SWEEP_MESSAGE}
    )
    engine._connection = MagicMock(side_effect=CANNOT_CONNECT)
    dbresilience.DB_HEALTH.mark_up()

    engine._check_external_reclaim()  # must not raise
    assert engine._foreign_reclaim_repairs == 1  # counted, retried next episode


def test_a_repair_is_rate_limited():
    """A node restarting in a loop must not turn this into a write storm."""
    engine = make_engine(task_id=418)
    engine._load_task = MagicMock(
        return_value={"status": "stopped", "error_message": FOREIGN_SWEEP_MESSAGE}
    )
    engine._connection = MagicMock(side_effect=AssertionError("must not write"))
    engine._last_foreign_repair_at = time.monotonic()

    engine._check_external_reclaim()  # must not raise, must not write
    assert engine._foreign_reclaim_repairs == 0


def test_verified_flow_reports_a_reclaim_instead_of_overwriting_the_row():
    engine = make_engine()
    engine._update_task = MagicMock()
    engine._log = MagicMock()
    engine._load_task = MagicMock(return_value={"drama_name": "胭脂如梦如雨如尘"})
    engine._prepare_verified_playback = MagicMock(
        side_effect=ExternalReclaimDetected("任务行已被外部置为 stopped")
    )

    with patch.object(engine_module, "check_connection", return_value=True), patch.object(
        engine_module, "connect", return_value=MagicMock()
    ), patch.object(engine_module, "HongguoOperations", return_value=MagicMock()):
        engine._run_verified_flow()  # must not raise

    statuses = [call.kwargs.get("status") for call in engine._update_task.call_args_list]
    assert "failed" not in statuses
    assert "stopped" not in statuses
    assert any(
        "外部置为" in call.args[1] for call in engine._log.call_args_list if len(call.args) > 1
    )


# ---------------------------------------------------------------------------
# the four read helpers that used to bypass _run_db  (task 418, 2026-09-17)
#
# 418 died on a bare 2003 while its three siblings rode the same blip out and
# finished all 40 episodes.  These helpers opened `self._connection()` straight
# - socket timeout, no retry - and two of them had no exception guard, so the
# highest-frequency read of the run (`_comment_already_verified`, called from
# `_pending_comment_episodes_between` inside the per-episode loop) was also the
# only unprotected one.
# ---------------------------------------------------------------------------
def test_the_per_episode_verified_check_rides_out_a_blip():
    engine = make_engine(task_id=418)
    dbresilience.DB_HEALTH.mark_up()
    engine._load_task = MagicMock(return_value={"started_at": datetime(2026, 9, 17, 12, 22)})
    attempts = {"n": 0}
    context, connection, cursor = make_connection_context()
    cursor.fetchone.return_value = {"id": 7}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise CANNOT_CONNECT
        return context

    engine._connection = MagicMock(side_effect=flaky)

    assert engine._comment_already_verified(28) is True
    assert attempts["n"] == 3
    assert engine._db_outage_seen is True


def test_the_per_episode_verified_check_still_reports_a_real_outage():
    """Retrying must not turn a genuine outage into a silent "not verified"."""
    engine = make_engine(task_id=418, db_outage_budget=0.2)
    dbresilience.DB_HEALTH.mark_up()
    engine._load_task = MagicMock(return_value={"started_at": None})
    engine._connection = MagicMock(side_effect=CANNOT_CONNECT)

    with pytest.raises(DbUnavailable):
        engine._comment_already_verified(28)


def test_completed_comment_episodes_rides_out_a_blip():
    engine = make_engine(task_id=418)
    dbresilience.DB_HEALTH.mark_up()
    engine._load_task = MagicMock(return_value={"started_at": None})
    attempts = {"n": 0}
    context, connection, cursor = make_connection_context()
    cursor.fetchall.return_value = [
        {"episode_number": 3},
        {"episode_number": 7},
        {"episode_number": None},
    ]

    def flaky():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise CANNOT_CONNECT
        return context

    engine._connection = MagicMock(side_effect=flaky)

    assert engine._completed_comment_episodes() == {3, 7}
    assert attempts["n"] == 2


def test_the_dedup_reader_rides_out_a_blip_before_degrading():
    """A short blip must not silently read as "no comment used yet"."""
    engine = make_engine(task_id=418)
    dbresilience.DB_HEALTH.mark_up()
    attempts = {"n": 0}
    context, connection, cursor = make_connection_context()
    cursor.fetchall.return_value = [{"comment_text": "  好剧  "}, {"comment_text": ""}]

    def flaky():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise CANNOT_CONNECT
        return context

    engine._connection = MagicMock(side_effect=flaky)

    assert engine._comment_contents_for_episode(28) == {"好剧"}
    assert attempts["n"] == 2


def test_dedup_readers_keep_their_empty_set_contract_on_a_real_outage():
    engine = make_engine(task_id=418, db_outage_budget=0.2)
    dbresilience.DB_HEALTH.mark_up()
    engine._load_task = MagicMock(return_value={"multi_run_id": "multi-x"})
    engine._connection = MagicMock(side_effect=CANNOT_CONNECT)

    assert engine._comment_contents_for_episode(28) == set()
    assert engine._comment_contents_for_batch() == set()


@pytest.mark.parametrize(
    "call",
    [
        lambda engine: engine._comment_already_verified(3),
        lambda engine: engine._completed_comment_episodes(),
        lambda engine: engine._comment_contents_for_episode(3),
        lambda engine: engine._comment_contents_for_batch(),
    ],
)
def test_no_read_helper_leaks_a_raw_transient_error(call):
    """Whatever a helper decides to do, a transient 2003 must never reach the
    caller untouched - leaking it is exactly what killed 418."""
    engine = make_engine(task_id=418, db_outage_budget=0.2)
    dbresilience.DB_HEALTH.mark_up()
    engine._load_task = MagicMock(return_value={"started_at": None, "multi_run_id": "multi-x"})
    engine._connection = MagicMock(side_effect=CANNOT_CONNECT)

    try:
        call(engine)
    except DbUnavailable:
        pass  # retried until a real budget was spent: honest, and the caller knows
    except Exception as exc:  # noqa: BLE001 - the point is to catch every leak
        pytest.fail("raw error leaked to the caller: {0!r}".format(exc))


def test_no_engine_helper_opens_a_connection_outside_the_resilience_layer():
    """Static guard: every helper that opens a connection must hand its work to
    ``_run_db`` (directly, or as a callable it passes in)."""
    # `_write_log_row` IS the callable `_log` hands to `_run_db`, so its own
    # body never has to mention the retry layer.
    allowed = {"_write_log_row"}
    source = Path(engine_module.__file__).read_text(encoding="utf-8")
    current = None
    offenders = set()
    for line in source.split("\n"):
        header = re.match(r"^    def (\w+)", line)
        if header:
            current = header.group(1)
        if current and "self._connection()" in line and current not in allowed:
            offenders.add(current)

    assert offenders, "nothing to check - did the connection helper get renamed?"
    for name in sorted(offenders):
        start = source.index("    def {0}(".format(name))
        end = source.find("\n    def ", start + 1)
        body = source[start:] if end == -1 else source[start:end]
        assert "_run_db(" in body, (
            "{0}() opens a connection but never routes the work through _run_db".format(name)
        )


# ---------------------------------------------------------------------------
# device leases: the same "connect() outside the try" shape  (2026-09-17)
#
# `acquire` / `release` / `renew` / `release_inactive` all opened their
# connection on a line that sat BEFORE the try block, so a blip raised straight
# out of them.  `renew` is worse than the rest: the engine calls it
# synchronously from its heartbeat, and without socket timeouts a stalled link
# would block the task thread for the OS default TCP timeout.
# ---------------------------------------------------------------------------
def test_a_lease_acquire_that_cannot_reach_mysql_reports_false():
    store = leases_module.DeviceLeaseStore({})
    with patch("rpa.hongguo.leases.pymysql.connect", side_effect=CANNOT_CONNECT):
        assert store.acquire(418, "127.0.0.1:16480") is False


def test_a_lease_renew_that_cannot_reach_mysql_does_not_raise():
    store = leases_module.DeviceLeaseStore({})
    with patch("rpa.hongguo.leases.pymysql.connect", side_effect=CANNOT_CONNECT):
        store.renew(418)  # must not raise: called inline from the heartbeat


def test_a_lease_release_that_cannot_reach_mysql_does_not_raise():
    store = leases_module.DeviceLeaseStore({})
    with patch("rpa.hongguo.leases.pymysql.connect", side_effect=CANNOT_CONNECT):
        store.release(418)


def test_release_inactive_survives_an_unreachable_database():
    store = leases_module.DeviceLeaseStore({})
    with patch("rpa.hongguo.leases.pymysql.connect", side_effect=CANNOT_CONNECT):
        assert store.release_inactive() == 0


def test_a_lease_rollback_or_close_failure_cannot_escape():
    """`rollback()`/`close()` themselves can raise on a dead socket."""
    store = leases_module.DeviceLeaseStore({})
    dying = MagicMock()
    dying.cursor.side_effect = CANNOT_CONNECT
    dying.rollback.side_effect = pymysql.err.InterfaceError(0, "")
    dying.close.side_effect = pymysql.err.InterfaceError(0, "")

    with patch("rpa.hongguo.leases.pymysql.connect", return_value=dying):
        store.release(418)  # must not raise


def test_lease_connections_carry_socket_timeouts():
    store = leases_module.DeviceLeaseStore({})
    captured = {}

    def fake_connect(**kwargs):
        captured.update(kwargs)
        raise CANNOT_CONNECT

    with patch("rpa.hongguo.leases.pymysql.connect", side_effect=fake_connect):
        store.release(418)

    assert captured["connect_timeout"] == dbresilience.CONNECT_TIMEOUT_SECONDS
    assert captured["read_timeout"] == dbresilience.READ_TIMEOUT_SECONDS
    assert captured["write_timeout"] == dbresilience.WRITE_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# engine: a watchdog reaping a thread that was only BLIND  (2026-09-17)
#
# Tasks 420-423 worked from 16:07 up to episode 47/48, lost MySQL at 17:38:43
# and were reaped at 19:31:35 with "执行线程已失联（113 分钟无心跳…）" - 113
# minutes against a 30 minute retry budget.  The threads were alive the whole
# time; they simply could not write, and updated_at is exactly what a watchdog
# ages.  So the row is wrong and the live thread takes it back - but only when
# it can prove it was blind rather than stuck, otherwise the watchdog could no
# longer free a device from a run that really did go quiet.
# ---------------------------------------------------------------------------
WATCHDOG_REAP_MESSAGE = (
    "执行线程已失联（113 分钟无心跳，节点 DESKTOP-S8K66QQ），"
    "任务已自动回收，如仍需执行请重新启动任务"
)


@pytest.mark.parametrize(
    "message,expected",
    [
        (WATCHDOG_REAP_MESSAGE, True),
        ("执行线程已失联（21 分钟无心跳，节点 DESKTOP-S8K66QQ），任务已自动回收", True),
        (FOREIGN_SWEEP_MESSAGE, False),
        (OWN_RECONCILE_MESSAGE, False),
        ("执行线程已失联，任务已自动回收", False),  # heartbeat wording is required
        ("", False),
    ],
)
def test_only_the_watchdog_wording_counts_as_a_false_reap(message, expected):
    assert TaskEngine._is_watchdog_false_reap(message) is expected


def test_a_watchdog_reap_is_repaired_when_we_just_came_back_from_an_outage():
    engine = make_engine(task_id=420)
    engine._load_task = MagicMock(
        return_value={"status": "stopped", "error_message": WATCHDOG_REAP_MESSAGE}
    )
    engine._db_recovered_at = time.monotonic()  # we were blind seconds ago
    context, connection, cursor = _recording_connection()
    engine._connection = MagicMock(return_value=context)
    dbresilience.DB_HEALTH.mark_up()

    engine._check_external_reclaim()  # the thread is alive: must not raise

    assert engine._foreign_reclaim_repairs == 1
    sql = " ".join(str(call.args[0]) for call in cursor.execute.call_args_list)
    assert "status='running'" in sql
    assert "error_message=NULL" in sql
    # The audit note travels as a bound parameter, not as literal SQL.
    params = " ".join(
        str(arg) for call in cursor.execute.call_args_list for arg in call.args[1:]
    )
    assert "断线期间其它节点的看门狗误判本机任务失联" in params
    # The repair and its audit line are one transaction.
    engine._connection.assert_called_once()


def test_a_watchdog_reap_is_obeyed_when_the_link_was_healthy():
    """No outage to excuse it: this thread really did go quiet, so stay reaped."""
    engine = make_engine(task_id=420)
    engine._load_task = MagicMock(
        return_value={"status": "stopped", "error_message": WATCHDOG_REAP_MESSAGE}
    )
    engine._db_recovered_at = 0.0
    engine._connection = MagicMock(side_effect=AssertionError("must not write"))

    with pytest.raises(ExternalReclaimDetected):
        engine._check_external_reclaim()
    assert engine._foreign_reclaim_repairs == 0


def test_the_false_reap_window_expires():
    """An old outage must not license repairs forever."""
    engine = make_engine(task_id=420)
    engine._db_recovered_at = (
        time.monotonic() - (TaskEngine._FALSE_REAP_WINDOW_SECONDS + 1)
    )
    assert engine._blinded_by_recent_outage() is False

    engine._db_recovered_at = time.monotonic()
    assert engine._blinded_by_recent_outage() is True


def test_every_outage_is_datable_not_just_the_first_one():
    """420-423 were reaped on a later outage; the first one must not mask it."""
    engine = make_engine(task_id=420)
    engine._note_db_retry(1, 0.5, CANNOT_CONNECT)
    assert engine._db_down_since is not None
    engine._db_down_since = None  # a success landed: the link came back
    engine._note_db_retry(1, 0.5, CANNOT_CONNECT)
    assert engine._db_down_since is not None
    # …while the noisy warning is still written only once per thread.
    assert engine._db_retry_count == 1


def test_a_successful_call_after_an_outage_stamps_the_recovery():
    engine = make_engine(task_id=420)
    dbresilience.DB_HEALTH.mark_up()
    engine._note_db_retry(1, 0.5, CANNOT_CONNECT)

    engine._run_db(lambda: True, label="probe", critical=True)

    assert engine._db_down_since is None
    assert time.monotonic() - engine._db_recovered_at < 5.0


def test_the_default_outage_budget_outlives_the_observed_outages():
    """113 minutes killed 420-423 at episode 47/48; the default must clear that."""
    assert dbresilience.OUTAGE_BUDGET_SECONDS >= 113 * 60 * 1.5
    assert make_engine()._db_outage_budget == dbresilience.OUTAGE_BUDGET_SECONDS
