"""Tests for the serial batch queue and the daily timer.

Only the decision logic is covered here: which drama runs next, whether the
daily timer should fire, and how a finished run is judged. The parts that talk
to MySQL and to emulators are exercised by running a real queue.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from rpa.hongguo import queue as q
from rpa.hongguo import schema


# ------------------------------------------------------------------ daily timer


def test_daily_time_parsing_accepts_the_formats_the_form_can_send():
    assert q.parse_daily_time("09:00").hour == 9
    assert q.parse_daily_time("9:00").minute == 0
    assert q.parse_daily_time("09:00:00").hour == 9
    assert q.parse_daily_time("2130").hour == 21


def test_daily_time_parsing_falls_back_instead_of_raising():
    """A typo in the settings must not stop the timer from ever firing."""
    for broken in ("", None, "晚上九点", "25:00"):
        assert q.parse_daily_time(broken) == q.parse_daily_time(q.DEFAULT_DAILY_TIME)


def test_daily_fires_once_a_day_at_or_after_the_configured_time():
    now = datetime(2026, 9, 25, 9, 30)
    assert q.daily_should_fire(
        daily_enabled=True,
        last_fired_date=date(2026, 9, 24),
        now=now,
        daily_time="09:00",
        unfinished_queue=None,
    )
    assert not q.daily_should_fire(
        daily_enabled=True,
        last_fired_date=date(2026, 9, 24),
        now=datetime(2026, 9, 25, 8, 59),
        daily_time="09:00",
        unfinished_queue=None,
    )


def test_daily_does_not_fire_twice_on_the_same_day():
    assert not q.daily_should_fire(
        daily_enabled=True,
        last_fired_date=date(2026, 9, 25),
        now=datetime(2026, 9, 25, 23, 0),
        daily_time="09:00",
        unfinished_queue=None,
    )


def test_daily_defers_instead_of_stacking_on_an_unfinished_queue():
    """Yesterday's slow run must not be buried under today's batch."""
    assert not q.daily_should_fire(
        daily_enabled=True,
        last_fired_date=date(2026, 9, 24),
        now=datetime(2026, 9, 25, 10, 0),
        daily_time="09:00",
        unfinished_queue="daily-20260924-101010-0001",
    )


def test_daily_is_off_unless_enabled():
    assert not q.daily_should_fire(
        daily_enabled=False,
        last_fired_date=None,
        now=datetime(2026, 9, 25, 23, 0),
        daily_time="09:00",
        unfinished_queue=None,
    )


# ------------------------------------------------------------------ run verdict


def test_a_run_still_running_is_not_a_verdict():
    rows = [{"status": "completed", "device_addr": "a"}, {"status": "running", "device_addr": "b"}]
    assert q.verdict_from_task_rows(rows) is None


def test_a_run_whose_rows_are_unreadable_is_not_a_verdict():
    assert q.verdict_from_task_rows([{"status": ""}]) is None
    assert q.verdict_from_task_rows([{"status": None}]) is None


def test_a_run_of_completed_tasks_is_done():
    rows = [{"status": "completed"}, {"status": "completed"}]
    assert q.verdict_from_task_rows(rows) == ("done", None)


def test_a_run_with_a_failed_device_reports_why():
    rows = [
        {"status": "completed", "device_addr": "a"},
        {"status": "failed", "device_addr": "b", "error_message": "互动未达标: 点赞=1/2"},
    ]
    status, message = q.verdict_from_task_rows(rows)
    assert status == "failed"
    assert "b" in message and "互动未达标" in message


def test_a_stopped_task_counts_as_failed_not_completed():
    status, _ = q.verdict_from_task_rows([{"status": "completed"}, {"status": "stopped"}])
    assert status == "failed"


def test_an_empty_run_is_failed_rather_than_done():
    assert q.verdict_from_task_rows([])[0] == "failed"


# ------------------------------------------------ batches that never started

#: 2026-09-29 真事故：tick 先把 476~479 造出来并把队列条目标成 running，紧接着
#: 启动设备时撞上远程库抖动（2013 断连），回头「标记失败」的那次写入又被同一个
#: 抖动吞掉 ⇒ 任务烂在 pending、条目烂在 running。而 ``pending`` 既不是终态也不
#: 是忙态，``verdict_from_task_rows`` 只会一直回答「还在忙」，整个队列就死在那
#: 一部短剧前面。下面这组断言钉住「造出来但从没启动」必须能被识别出来。

_CREATED_AT = datetime(2026, 9, 29, 17, 26, 35)


def _never_started_rows(*, statuses=("pending", "pending"), started_at=None):
    return [
        {"status": status, "started_at": started_at, "created_at": _CREATED_AT}
        for status in statuses
    ]


def test_a_batch_created_but_never_started_is_reaped():
    now = _CREATED_AT + timedelta(minutes=30)
    reason = q.stalled_start_reason(_never_started_rows(), now)
    assert reason, "创建后一直没启动的批次必须被判死，否则队列永远卡在 running"
    assert "启动" in reason


def test_the_grace_window_protects_a_dispatch_that_is_still_being_claimed():
    """api 模式下任务本来就停在 pending 等执行节点领取，不能立刻判死。"""
    now = _CREATED_AT + timedelta(seconds=q.STALLED_START_GRACE_SECONDS - 1)
    assert q.stalled_start_reason(_never_started_rows(), now) is None


def test_a_batch_with_any_started_row_is_left_alone():
    rows = _never_started_rows(started_at=_CREATED_AT)
    now = _CREATED_AT + timedelta(hours=3)
    assert q.stalled_start_reason(rows, now) is None


def test_a_batch_with_one_live_device_is_left_alone():
    now = _CREATED_AT + timedelta(hours=3)
    rows = _never_started_rows(statuses=("pending", "running"))
    assert q.stalled_start_reason(rows, now) is None


def test_a_finished_batch_is_left_to_the_normal_verdict():
    now = _CREATED_AT + timedelta(hours=3)
    rows = _never_started_rows(statuses=("completed", "failed"))
    assert q.stalled_start_reason(rows, now) is None


def test_a_batch_without_rows_or_timestamps_is_not_reaped():
    now = _CREATED_AT + timedelta(hours=3)
    assert q.stalled_start_reason([], now) is None
    assert q.stalled_start_reason([{"status": "pending"}], now) is None
    assert q.stalled_start_reason(
        [{"status": "pending", "started_at": None, "created_at": None}], now
    ) is None


def test_a_string_timestamp_from_the_driver_still_counts():
    """pymysql 有时把 DATETIME 当字符串给回来，别因此漏判。"""
    now = _CREATED_AT + timedelta(hours=3)
    rows = [{"status": "pending", "started_at": None, "created_at": "2026-09-29T17:26:35"}]
    assert q.stalled_start_reason(rows, now)


def test_a_partially_started_batch_is_reaped_too():
    """09-30 真事故：495 被 20 分钟看门狗判失联，496~498 从没启动。

    三台没启动的行永远停在 ``pending``，而 495 已经是 ``stopped`` ⇒ 没有任何一行
    是「忙」，但 ``verdict_from_task_rows`` 因为 ``pending`` 既非终态也非忙态只会
    一直回 None。上一版自愈要求「全部 pending」，正好漏掉这种混合批次，于是队列
    又卡了 14.5 小时（00:30 → 15:20），后面每一部短剧全部陪葬。
    """
    now = _CREATED_AT + timedelta(hours=3)
    rows = [
        {"status": "stopped", "started_at": _CREATED_AT, "created_at": _CREATED_AT},
        {"status": "pending", "started_at": None, "created_at": _CREATED_AT},
        {"status": "pending", "started_at": None, "created_at": _CREATED_AT},
        {"status": "pending", "started_at": None, "created_at": _CREATED_AT},
    ]
    reason = q.stalled_start_reason(rows, now)
    assert reason, "一台被回收 + 其余从没启动的批次必须能被判死"
    assert "启动" in reason
    assert "3" in reason, "文案要说清有几台没启动，便于事后认领"


def test_a_partially_started_batch_still_honours_the_grace_window():
    """混合批次也不能一建立就判死：api 模式下 pending 行可能还在等执行节点。"""
    now = _CREATED_AT + timedelta(seconds=q.STALLED_START_GRACE_SECONDS - 1)
    rows = [
        {"status": "stopped", "started_at": _CREATED_AT, "created_at": _CREATED_AT},
        {"status": "pending", "started_at": None, "created_at": _CREATED_AT},
    ]
    assert q.stalled_start_reason(rows, now) is None


def test_a_batch_whose_rows_all_started_is_left_to_the_normal_verdict():
    """每台都启动过（哪怕慢、哪怕已失败）就不是「没启动」，交给常规判决。"""
    now = _CREATED_AT + timedelta(hours=3)
    rows = [
        {"status": "completed", "started_at": _CREATED_AT, "created_at": _CREATED_AT},
        {"status": "failed", "started_at": _CREATED_AT, "created_at": _CREATED_AT},
    ]
    assert q.stalled_start_reason(rows, now) is None


def test_the_tick_actually_consults_the_stall_guard():
    """接线契约：自愈函数写好了但没人调用等于没有（09-30 的代价）。"""
    source = (Path(q.__file__)).read_text(encoding="utf-8")
    # 切片要覆盖整个「判决解析」段：从读行到 verdict 被解包为止。别拿
    # ``plan["waiting"] = True`` 当终点 —— 10-01 加的宽限分支也设这个标记，
    # 会把它提前截断（切片边界比断言本身还脆，是这类契约测试的常见坑）。
    verdict_branch = source.split("verdict = verdict_from_task_rows(", 1)[1].split("status, message = verdict", 1)[0]
    assert "stalled_start_reason(" in verdict_branch, (
        "tick 的 verdict is None 分支必须调用 stalled_start_reason，"
        "否则整批从没启动时队列会永远卡在 running"
    )


# ------------------------------------------------- infrastructure retry budget
#
# 09-30：共享 MySQL 抖动让 seq4 的批次从没启动，条目被判 failed 时 attempt 已经
# 是 2（两次机会全花在「压根没跑起来」上），《胭脂如梦如雨如尘2》于是被永久丢弃，
# 而它一集都没播过。基建故障不是剧本的问题，得有自己的重试预算。


def test_retry_allowed_keeps_a_drama_that_really_ran_on_its_two_attempts():
    assert q.retry_allowed({"attempt": 0}, infra_failure=False) is True
    assert q.retry_allowed({"attempt": 1}, infra_failure=False) is True
    assert q.retry_allowed({"attempt": 2}, infra_failure=False) is False


def test_retry_allowed_does_not_spend_an_attempt_on_a_batch_that_never_launched():
    """关键：attempt 已经用满也必须还能重试 —— 那两次压根没启动过。"""
    item = {"attempt": q.MAX_START_ATTEMPTS, "infra_retries": 0}
    assert q.retry_allowed(item, infra_failure=True) is True


def test_retry_allowed_bounds_the_infrastructure_budget():
    """每次重试都会给每台设备插一条新任务行，不能无限循环。"""
    assert q.retry_allowed({"infra_retries": q.MAX_INFRA_RETRIES - 1}, infra_failure=True) is True
    assert q.retry_allowed({"infra_retries": q.MAX_INFRA_RETRIES}, infra_failure=True) is False


def test_retry_allowed_treats_a_missing_budget_column_as_zero():
    """旧库还没补列时不能因此拒绝重试，读不到就当 0。"""
    assert q.retry_allowed({}, infra_failure=True) is True
    assert q.retry_allowed({}, infra_failure=False) is True


def _tick_statements(monkeypatch, *, item, rows, now):
    """Run one ``_tick_plan`` against recording stubs and return the SQL it ran."""
    statements = []

    class _Cur:
        rowcount = 1

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def execute(self, sql, params=None):
            statements.append((" ".join(str(sql).split()), params))

        def fetchone(self):
            return None

        def fetchall(self):
            return []

    class _Conn:
        def cursor(self):
            return _Cur()

        def commit(self):
            pass

    class _Ctx:
        def __enter__(self):
            return _Conn()

        def __exit__(self, *exc_info):
            return False

    monkeypatch.setattr(q, "_connection", lambda: _Ctx())
    monkeypatch.setattr(q, "_ensure_queue_columns", lambda conn: None)
    monkeypatch.setattr(q, "_ensure_config", lambda conn: {})
    monkeypatch.setattr(q, "daily_should_fire", lambda **kwargs: False)
    monkeypatch.setattr(q, "_unfinished_queue_id", lambda conn: "queue-1")
    monkeypatch.setattr(q, "_queue_items", lambda conn, queue_id: [dict(item)])
    monkeypatch.setattr(q, "_fetch_multi_run_tasks", lambda conn, run_id: list(rows))
    return q._tick_plan(now), statements


def _retry_updates(statements):
    return [
        sql for sql, _ in statements
        if "UPDATE hongguo_queue_item" in sql and "status='pending'" in sql
    ]


def _stalled_item(**overrides):
    item = {
        "id": 4,
        "queue_id": "queue-1",
        "seq": 4,
        "drama_name": "胭脂如梦如雨如尘2",
        "status": "running",
        "attempt": 2,
        "infra_retries": 0,
        "multi_run_id": "multi-1",
    }
    item.update(overrides)
    return item


#: 09-30 的形状：第一台被 20 分钟看门狗判失联，其余从没启动。
_STALLED_ROWS = [
    {"status": "stopped", "started_at": _CREATED_AT, "created_at": _CREATED_AT},
    {"status": "pending", "started_at": None, "created_at": _CREATED_AT},
]


def test_an_infrastructure_failure_refunds_the_attempt_and_counts_its_own(monkeypatch):
    now = _CREATED_AT + timedelta(hours=1)
    plan, statements = _tick_statements(
        monkeypatch, item=_stalled_item(), rows=_STALLED_ROWS, now=now
    )

    retries = _retry_updates(statements)
    assert len(retries) == 1, "从没启动的批次必须退回 pending 重试：%s" % (statements,)
    assert "attempt=GREATEST(attempt-1, 0)" in retries[0], (
        "基建故障要退还 _start_item 已经花掉的那次 attempt，否则两次抖动就丢一部剧"
    )
    assert "infra_retries=COALESCE(infra_retries, 0)+1" in retries[0], "基建重试要单独计数"
    assert any(entry.get("status") == "retry" for entry in plan["finalized"])


def test_a_real_failure_still_spends_an_attempt(monkeypatch):
    """真跑过又失败的剧本走原路：花掉一次 attempt，不碰基建预算。"""
    now = _CREATED_AT + timedelta(hours=1)
    rows = [
        {
            "status": "failed",
            "error_message": "设备炸了",
            "started_at": _CREATED_AT,
            "created_at": _CREATED_AT,
        }
    ]
    _, statements = _tick_statements(
        monkeypatch, item=_stalled_item(attempt=1), rows=rows, now=now
    )

    retries = _retry_updates(statements)
    assert len(retries) == 1
    assert "GREATEST" not in retries[0]
    assert "infra_retries" not in retries[0]


def test_an_infrastructure_failure_past_its_budget_drops_the_drama(monkeypatch):
    now = _CREATED_AT + timedelta(hours=1)
    _, statements = _tick_statements(
        monkeypatch,
        item=_stalled_item(infra_retries=q.MAX_INFRA_RETRIES),
        rows=_STALLED_ROWS,
        now=now,
    )

    assert _retry_updates(statements) == [], "预算用尽后不能再退"
    assert any("finished_at=%s" in sql for sql, _ in statements), "预算用尽要真正收尾为 failed"


# ----------------------------------------------------------------- queue order


def test_the_lowest_sequence_number_runs_next():
    items = [
        {"id": 3, "seq": 3, "status": "pending"},
        {"id": 1, "seq": 1, "status": "done"},
        {"id": 2, "seq": 2, "status": "pending"},
    ]
    assert q.pick_next_item(items)["id"] == 2


def test_nothing_is_picked_when_every_drama_is_finished():
    items = [{"id": 1, "seq": 1, "status": "done"}, {"id": 2, "seq": 2, "status": "failed"}]
    assert q.pick_next_item(items) is None


def test_summary_points_at_the_drama_being_worked_on():
    items = [
        {"id": 1, "seq": 1, "status": "done", "drama_name": "甲"},
        {"id": 2, "seq": 2, "status": "running", "drama_name": "乙"},
        {"id": 3, "seq": 3, "status": "pending", "drama_name": "丙"},
    ]
    summary = q.summarize_items(items)
    assert summary["total"] == 3
    assert summary["finished"] == 1
    assert summary["current_seq"] == 2
    assert summary["current_drama"] == "乙"


# -------------------------------------------------------------------- names


def test_pasted_names_split_on_newlines_and_commas():
    names = q.normalize_names(["一品布衣2\n万妖图录,三清观里的挽劫小道士", "\n\n丧失狂潮"])
    assert names == ["一品布衣2", "万妖图录", "三清观里的挽劫小道士", "丧失狂潮"]


def test_pasted_names_drop_duplicates_and_blank_lines():
    assert q.normalize_names(["甲\n甲\n\n  \n乙"]) == ["甲", "乙"]


# ---------------------------------------------------------------- task payload


def test_a_stored_template_only_contributes_fields_the_task_model_knows():
    payload = q.build_task_payload(
        "甲",
        {
            "random_like_count": 2,
            "episode_interval": 3,
            "a_field_that_never_existed": "boom",
            "devices": [{"addr": "127.0.0.1:16416"}],
        },
    )
    assert payload.drama_name == "甲"
    assert payload.random_like_count == 2
    assert payload.episode_interval == 3
    assert not hasattr(payload, "a_field_that_never_existed")


def test_the_drama_of_the_queue_item_wins_over_a_name_left_in_the_template():
    payload = q.build_task_payload("当前这一部", {"drama_name": "上一部", "random_like_count": 1})
    assert payload.drama_name == "当前这一部"


def test_a_stored_template_that_is_not_a_dict_is_ignored():
    payload = q.build_task_payload("甲", None)
    assert payload.drama_name == "甲"


# --------------------------------------------------------------- start an item
#
# ``_start_item`` is the seam where an abstract "queue item" becomes real
# ``hongguo_comment_tasks`` rows, so it is worth pinning: it is only ever
# reached from the background dispatcher, where an unhandled NameError would
# surface as a silently stalled queue rather than a failing request.


class _RecordingCursor:
    def __init__(self, sink, rowcount=1):
        self.sink = sink
        self.rowcount = rowcount

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=None):
        self.sink.append((str(sql), params))


class _RecordingConn:
    """Just enough of a connection for the queue helpers to run."""

    def __init__(self, rowcount=1):
        self.statements = []
        self.commits = 0
        self.rowcount = rowcount

    def cursor(self):
        return _RecordingCursor(self.statements, self.rowcount)

    def commit(self):
        self.commits += 1


def _item(**overrides):
    item = {
        "id": 7,
        "seq": 2,
        "drama_name": "万妖图录",
        "status": "pending",
        "owner_user_id": 9,
        "attempt": 0,
        "template_json": '{"random_like_count": 3, "playback_speed": "2.0x"}',
        "devices_json": '[{"addr": "127.0.0.1:16416", "label": "实例1"}]',
    }
    item.update(overrides)
    return item


def _stub_inserts(monkeypatch, created, logged):
    monkeypatch.setattr(
        q, "_insert_task_record",
        lambda conn, payload, **kwargs: created.append((payload, kwargs)) or len(created),
    )
    monkeypatch.setattr(
        q, "_insert_log",
        lambda conn, task_id, message, level="info": logged.append(message),
    )


def test_starting_an_item_creates_one_task_per_device_under_a_single_run(monkeypatch):
    from api.security import Principal

    conn = _RecordingConn()
    created = []
    logged = []
    _stub_inserts(monkeypatch, created, logged)
    monkeypatch.setattr(
        q, "_principal_for_owner",
        lambda conn, owner: (Principal(user_id=int(owner), username="admin001", role="user"), None),
    )

    item = _item()
    item["_queue_total"] = 5
    started = q._start_item(
        conn,
        item,
        [{"addr": "127.0.0.1:16416", "label": "实例1", "worker_id": "w1"}],
        datetime(2026, 9, 25, 10, 30, 0),
    )

    assert started["run_id"].startswith("multi-20260925103000-")
    assert started["task_ids"] == [1]
    payload, kwargs = created[0]
    assert payload.drama_name == "万妖图录"
    assert payload.random_like_count == 3
    assert payload.playback_speed == "2.0x"
    assert kwargs["device_addr"] == "127.0.0.1:16416"
    assert kwargs["device_label"] == "实例1"
    assert kwargs["multi_run_id"] == started["run_id"]
    assert kwargs["worker_id"] == "w1"
    assert "2/5" in logged[0]
    assert conn.commits == 2
    updates = [sql for sql, _ in conn.statements if "hongguo_queue_item" in sql]
    assert updates and "status='running'" in updates[0]
    assert "AND status='pending'" in updates[0]


def test_an_item_another_tick_already_claimed_is_left_untouched(monkeypatch):
    """Two overlapping ticks must not put the same drama on the same devices."""
    from api.security import Principal

    created = []
    _stub_inserts(monkeypatch, created, [])
    monkeypatch.setattr(q, "_principal_for_owner", lambda conn, owner: (Principal(9, "admin001", "user"), None))
    conn = _RecordingConn(rowcount=0)

    result = q._start_item(conn, _item(), [{"addr": "a"}], datetime(2026, 9, 25, 10, 0, 0))

    assert result == {"run_id": None, "task_ids": [], "devices": [], "claimed": False}
    assert created == []
    assert conn.commits == 0


def test_a_retry_of_the_same_item_is_counted_in_the_attempt_column(monkeypatch):
    _stub_inserts(monkeypatch, [], [])
    conn = _RecordingConn()
    q._start_item(conn, _item(attempt=1), [{"addr": "a"}], datetime(2026, 9, 25, 10, 0, 0))
    _, params = [row for row in conn.statements if "hongguo_queue_item" in row[0]][0]
    assert params[1] == 2


def test_starting_an_item_files_the_task_under_its_owner_then_restores_the_caller(monkeypatch):
    """The dispatcher has no request context; attribution must survive it."""
    from api import security
    from api.security import Principal

    monkeypatch.setattr(
        q, "_principal_for_owner",
        lambda conn, owner: (Principal(user_id=int(owner), username="admin001", role="user"), None),
    )
    monkeypatch.setattr(q, "_insert_log", lambda conn, task_id, message, level="info": None)
    seen = {}

    def fake_insert(conn, payload, **kwargs):
        seen["during"] = security.current_principal().user_id
        return 1

    monkeypatch.setattr(q, "_insert_task_record", fake_insert)

    previous = security.current_principal()
    security.set_current_principal(Principal(user_id=1, username="admin", role="admin"))
    try:
        q._start_item(_RecordingConn(), _item(), [{"addr": "a"}], datetime(2026, 9, 25, 10, 0, 0))
        assert seen["during"] == 9
        assert security.current_principal().user_id == 1
    finally:
        security.set_current_principal(previous)


# --------------------------------------------------------- import from history
#
# 剧名 has always been typed by hand into 执行规则, so ``hongguo_comment_tasks``
# already holds the list the operator would otherwise retype.  The import must add
# what is missing and leave every existing row alone: ``enabled``, ``run_count``
# and the ordering are the operator's, not the importer's.


class _RowsCursor:
    """A cursor whose ``fetchall`` replays prepared rows per statement."""

    def __init__(self, script, sink):
        self._script = list(script)
        self._sink = sink
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=None):
        flat = " ".join(str(sql).split())
        self._sink.append((flat, params))
        for needle, rows in self._script:
            if needle in flat:
                self._rows = rows
                return
        self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    @property
    def rowcount(self):
        return len(self._rows)


class _RowsConn:
    def __init__(self, script):
        self._script = script
        self.statements = []
        self.commits = 0

    def cursor(self):
        return _RowsCursor(self._script, self.statements)

    def commit(self):
        self.commits += 1


def _inserted(conn):
    return [params[0] for sql, params in conn.statements if sql.startswith("INSERT INTO hongguo_drama_playlist")]


def test_history_import_adds_only_the_dramas_that_are_missing():
    conn = _RowsConn(
        [
            ("FROM hongguo_comment_tasks", [{"drama_name": "新剧"}, {"drama_name": "旧剧"}, {"drama_name": "新剧"}]),
            ("COALESCE(MAX(sort_order)", [{"max_order": 3}]),
            ("FROM hongguo_drama_playlist", [{"id": 1, "drama_name": "旧剧", "enabled": 1, "sort_order": 1}]),
        ]
    )

    result = q.import_history_names(conn, owner_user_id=11)

    # Duplicates in the task table must not turn into two rows.
    assert _inserted(conn) == ["新剧"]
    assert result["scanned"] == 2
    assert result["added"] == ["新剧"]


def test_history_import_keeps_the_owners_own_settings():
    """Re-importing must never touch a row that is already there."""
    conn = _RowsConn(
        [
            ("FROM hongguo_comment_tasks", [{"drama_name": "旧剧"}]),
            ("COALESCE(MAX(sort_order)", [{"max_order": 1}]),
            ("FROM hongguo_drama_playlist", [{"id": 1, "drama_name": "旧剧", "enabled": 0, "sort_order": 1, "run_count": 7}]),
        ]
    )

    result = q.import_history_names(conn)

    assert result["added"] == []
    assert _inserted(conn) == []
    # The one existing row keeps enabled=0 / run_count=7 - nothing wrote to it.
    assert not [sql for sql, _ in conn.statements if sql.startswith("UPDATE")]


def test_history_names_are_ranked_by_the_newest_batch_and_capped():
    conn = _RowsConn([("FROM hongguo_comment_tasks", [{"drama_name": "甲", "last_id": 9}])])

    names = q.history_drama_names(conn, limit=5)

    assert names == ["甲"]
    sql, params = conn.statements[-1]
    assert "MAX(id) AS last_id" in sql
    assert "GROUP BY drama_name" in sql
    assert params == (5,)


def test_history_import_ignores_blank_names():
    conn = _RowsConn(
        [
            ("FROM hongguo_comment_tasks", [{"drama_name": "  "}, {"drama_name": ""}, {"drama_name": "好剧"}]),
            ("COALESCE(MAX(sort_order)", [{"max_order": 0}]),
            ("FROM hongguo_drama_playlist", []),
        ]
    )

    result = q.import_history_names(conn)

    assert result["added"] == ["好剧"]
    assert result["scanned"] == 1


# ------------------------------------------------------- playlist uniqueness


def test_adding_a_drama_that_is_already_listed_inserts_nothing():
    """The playlist must not grow a twin row for a drama it already has.

    ``ON DUPLICATE KEY UPDATE`` only works when the UNIQUE key exists, and on
    databases built by ``create_all`` it does not - so the guard has to live in
    Python too. A duplicate means the daily timer promotes the same drama twice.
    """
    conn = _RowsConn(
        [
            (
                "FROM hongguo_drama_playlist",
                [{"id": 98, "drama_name": "貂蝉", "enabled": 1, "sort_order": 41}],
            ),
        ]
    )

    items = q.add_playlist_names(conn, ["貂蝉"], owner_user_id=18)

    assert _inserted(conn) == []
    assert [item["drama_name"] for item in items] == ["貂蝉"]


def test_adding_a_mixed_batch_only_inserts_the_new_names():
    conn = _RowsConn(
        [
            # Order matters: _RowsCursor returns on the first substring match, and
            # the MAX(sort_order) query also contains "FROM hongguo_drama_playlist".
            ("COALESCE(MAX(sort_order)", [{"max_order": 1}]),
            (
                "FROM hongguo_drama_playlist",
                [{"id": 1, "drama_name": "旧剧", "enabled": 1, "sort_order": 1}],
            ),
        ]
    )

    q.add_playlist_names(conn, ["旧剧", "新剧", "新剧"], owner_user_id=18)

    assert _inserted(conn) == ["新剧"]
    rows = [
        params
        for sql, params in conn.statements
        if sql.startswith("INSERT INTO hongguo_drama_playlist")
    ]
    # sort_order continues after the existing rows rather than restarting at 1.
    assert rows == [("新剧", 2, 18)]
    # And the statement must alias the aggregate: the stub above keys its row the
    # way pymysql does, so an unaliased column silently reads back as 0.
    order_sql = [sql for sql, _ in conn.statements if "COALESCE(MAX" in sql]
    assert order_sql and "AS max_order" in order_sql[0]


def test_playlist_model_carries_the_unique_key_so_create_all_gets_it_right():
    """A fresh database is built from the models, not from BASE_DDL."""
    from models.hongguo_queue import HongguoDramaPlaylist

    unique = [
        constraint
        for constraint in HongguoDramaPlaylist.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    ]
    assert [c.name for c in unique] == ["uq_hongguo_playlist_name"]
    assert [tuple(col.name for col in c.columns) for c in unique] == [("drama_name",)]


class _SchemaCursor:
    """Answers the three probes ``ensure_queue_schema`` makes."""

    def __init__(self, *, has_index, has_table=True, duplicates=0):
        self.has_index = has_index
        self.has_table = has_table
        self.duplicates = duplicates
        self.log = []
        self.rowcount = 0
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=None):
        flat = " ".join(str(sql).split())
        self.log.append((flat, params))
        self.rowcount = 0
        if flat.startswith("SELECT DATABASE()"):
            self._rows = [{"DATABASE()": "superclaw"}]
        elif "FROM information_schema.STATISTICS" in flat:
            self._rows = [{"n": 1 if self.has_index else 0}]
        elif "FROM information_schema.TABLES" in flat:
            self._rows = [{"n": 1 if self.has_table else 0}]
        elif flat.startswith("DELETE dup"):
            self.rowcount = self.duplicates
            self._rows = []
        else:
            self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _SchemaConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1


def _statements(cursor, needle):
    return [sql for sql, _ in cursor.log if needle in sql]


def test_queue_schema_repairs_a_playlist_created_by_create_all():
    cursor = _SchemaCursor(has_index=False, has_table=True, duplicates=2)
    conn = _SchemaConn(cursor)

    schema.ensure_queue_schema(conn)

    assert len(_statements(cursor, "DELETE dup")) == 1
    alter = _statements(cursor, "ALTER TABLE hongguo_drama_playlist")
    assert len(alter) == 1
    assert "ADD UNIQUE KEY uq_hongguo_playlist_name" in alter[0]
    assert conn.commits == 1


def test_queue_schema_is_a_noop_once_the_key_exists():
    cursor = _SchemaCursor(has_index=True)
    conn = _SchemaConn(cursor)

    schema.ensure_queue_schema(conn)

    assert _statements(cursor, "DELETE") == []
    assert _statements(cursor, "ALTER TABLE") == []
    assert conn.commits == 0


def test_queue_schema_leaves_a_brand_new_database_to_the_ddl():
    """No table yet means BASE_DDL/create_all will build it with the key."""
    cursor = _SchemaCursor(has_index=False, has_table=False)
    conn = _SchemaConn(cursor)

    schema.ensure_queue_schema(conn)

    assert _statements(cursor, "DELETE") == []
    assert _statements(cursor, "ALTER TABLE") == []
    assert conn.commits == 0


class _ColumnCursor:
    """Answers ``ensure_queue_item_columns``'s two probes."""

    def __init__(self, existing=()):
        self.existing = list(existing)
        self.log = []

    def execute(self, sql, params=None):
        self.log.append(" ".join(str(sql).split()))

    def fetchone(self):
        return {"DATABASE()": "superclaw"}

    def fetchall(self):
        return [{"COLUMN_NAME": name} for name in self.existing]


def test_queue_item_columns_are_added_when_the_table_predates_them():
    """生产库的表早就存在，``CREATE TABLE IF NOT EXISTS`` 补不上新列。"""
    cursor = _ColumnCursor()

    assert schema.ensure_queue_item_columns(cursor) == [
        "infra_retries",
        "retry_devices_json",
    ]
    alters = [sql for sql in cursor.log if sql.startswith("ALTER TABLE hongguo_queue_item")]
    assert len(alters) == 2
    assert "infra_retries INT NOT NULL DEFAULT 0" in alters[0]
    assert "retry_devices_json TEXT DEFAULT NULL" in alters[1]


def test_queue_item_columns_are_not_added_twice():
    cursor = _ColumnCursor(existing=["infra_retries", "retry_devices_json"])

    assert schema.ensure_queue_item_columns(cursor) == []
    assert [sql for sql in cursor.log if sql.startswith("ALTER TABLE")] == []


# -------------------------------------------------- foreign sweeps are not verdicts
#
# 09-30 的 seq4《胭脂如梦如雨如尘2》：批次 1（507-510）已经 4/4 跑完 48/48，但跑动中
# 被某个旧版节点的「全库 reconcile」扫了一次 —— 508 短暂变成 stopped，且
# error_message 不带「执行电脑」前缀。engine 把这行纠正回 running 并一路跑到 20:16；
# 可队列 tick 在纠正之前的窗口里看到了 stopped，判批次 failed ⇒ 20:03 又起了整整
# 一轮（8 个设备小时），第二轮尾巴还撞上仍在跑的 508（Task is already running ⇒
# 512 failed），条目最终反而被倒扣成 failed。
#
# 判据放在 rpa/hongguo/reclaim.py，engine 与 queue 共用同一份 —— 两边各抄一份字符串
# 就是漂移的开始，而漂移的代价是整批重跑。

_FOREIGN_RECONCILE = "服务进程已重启，原执行线程不存在，请手动重新启动任务"
_OWN_RECONCILE = (
    "执行电脑 DESKTOP-S8K66QQ 的服务进程已重启，原执行线程不存在，请手动重新启动任务"
)
_WATCHDOG_REAP = (
    "执行线程已失联（113 分钟无心跳，节点 DESKTOP-S8K66QQ），"
    "任务已自动回收，如仍需执行请重新启动任务"
)
_REAL_FAILURE = "本集未完成：期望 30，实际 12"


def _swept_rows(message, *, swept_at, finished=3):
    """09-30 的形状：N 台跑完，一台被外部写手扫成 stopped。"""
    rows = [
        {"status": "completed", "updated_at": swept_at, "created_at": _CREATED_AT}
        for _ in range(finished)
    ]
    rows.append(
        {
            "status": "stopped",
            "error_message": message,
            "updated_at": swept_at,
            "completed_at": swept_at,
            "created_at": _CREATED_AT,
        }
    )
    return rows


def _item_finish_calls(statements):
    """``_finish_item`` 是唯一写 ``finished_at`` 的地方，参数第 0 位是终态。"""
    return [
        (sql, params)
        for sql, params in statements
        if "UPDATE hongguo_queue_item" in sql and "finished_at=" in sql
    ]


def test_a_fresh_foreign_reconcile_does_not_fail_the_batch(monkeypatch):
    """关键：外部全库 reconcile 误标是对「行」的说法，不是对「剧本」的判决。"""
    swept_at = _CREATED_AT + timedelta(hours=1)
    plan, statements = _tick_statements(
        monkeypatch,
        item=_stalled_item(),
        rows=_swept_rows(_FOREIGN_RECONCILE, swept_at=swept_at),
        now=swept_at + timedelta(seconds=60),
    )

    assert plan["waiting"] is True
    assert _retry_updates(statements) == [], "宽限内绝不能重置条目重跑整批"
    assert _item_finish_calls(statements) == []
    assert plan["finalized"] == []


def test_a_fresh_watchdog_reap_is_held_back_too(monkeypatch):
    """看门狗按 updated_at 判失联，断线期间它会误杀健康线程（09-17 的 420-423）。"""
    swept_at = _CREATED_AT + timedelta(hours=1)
    plan, statements = _tick_statements(
        monkeypatch,
        item=_stalled_item(),
        rows=_swept_rows(_WATCHDOG_REAP, swept_at=swept_at),
        now=swept_at + timedelta(seconds=60),
    )

    assert plan["waiting"] is True
    assert _retry_updates(statements) == []
    assert _item_finish_calls(statements) == []


def test_a_stale_foreign_reconcile_is_accepted_at_last(monkeypatch):
    """宽限不是免死金牌：过窗仍无自愈就照常处理，否则队列被一部剧永久卡住。"""
    swept_at = _CREATED_AT + timedelta(hours=1)
    _, statements = _tick_statements(
        monkeypatch,
        item=_stalled_item(attempt=0),
        rows=_swept_rows(_FOREIGN_RECONCILE, swept_at=swept_at),
        now=swept_at + timedelta(seconds=q.FOREIGN_SWEEP_GRACE_SECONDS + 1),
    )

    retries = _retry_updates(statements)
    assert len(retries) == 1, "过窗后要按普通失败走重试：%s" % (statements,)
    assert "GREATEST" not in retries[0], "外部误标不是「从没启动」，不动基建预算"
    assert "infra_retries" not in retries[0]


def test_a_real_failure_is_still_a_verdict_at_once(monkeypatch):
    """真失败（集数不够）必须保持即时判死，否则等于把 bug 从一头搬到另一头。"""
    swept_at = _CREATED_AT + timedelta(hours=1)
    _, statements = _tick_statements(
        monkeypatch,
        item=_stalled_item(attempt=0),
        rows=_swept_rows(_REAL_FAILURE, swept_at=swept_at),
        now=swept_at + timedelta(seconds=5),
    )

    assert len(_retry_updates(statements)) == 1


def test_our_own_restart_is_not_an_outside_sweep(monkeypatch):
    """带「执行电脑 X 的」前缀的是本机 reconcile：线程真没了，必须照常重跑。"""
    swept_at = _CREATED_AT + timedelta(hours=1)
    _, statements = _tick_statements(
        monkeypatch,
        item=_stalled_item(attempt=0),
        rows=_swept_rows(_OWN_RECONCILE, swept_at=swept_at),
        now=swept_at + timedelta(seconds=5),
    )

    assert len(_retry_updates(statements)) == 1, "自己重启杀掉的任务要正常重试"


def test_one_real_failure_beside_a_sweep_still_fails_the_batch(monkeypatch):
    """混批：只要有一台真失败，批次就是真失败，不能因为另一台被误标而整体免责。"""
    swept_at = _CREATED_AT + timedelta(hours=1)
    rows = _swept_rows(_FOREIGN_RECONCILE, swept_at=swept_at)
    rows.append(
        {
            "status": "failed",
            "error_message": _REAL_FAILURE,
            "updated_at": swept_at,
            "created_at": _CREATED_AT,
        }
    )
    _, statements = _tick_statements(
        monkeypatch,
        item=_stalled_item(attempt=0),
        rows=rows,
        now=swept_at + timedelta(seconds=5),
    )

    assert len(_retry_updates(statements)) == 1


def test_the_grace_boundary_is_half_open():
    swept_at = _CREATED_AT + timedelta(hours=1)
    rows = _swept_rows(_FOREIGN_RECONCILE, swept_at=swept_at)

    inside = swept_at + timedelta(seconds=q.FOREIGN_SWEEP_GRACE_SECONDS - 1)
    outside = swept_at + timedelta(seconds=q.FOREIGN_SWEEP_GRACE_SECONDS)

    assert q.untrusted_failure_reason(rows, inside)
    assert q.untrusted_failure_reason(rows, outside) is None


def test_the_newest_sweep_stamp_sets_the_clock():
    """反复被扫时以最近一次为准，否则一次旧误标会把新的那次宽限一起抹掉。"""
    early = _CREATED_AT + timedelta(hours=1)
    late = early + timedelta(minutes=30)
    rows = _swept_rows(_FOREIGN_RECONCILE, swept_at=early)
    rows[-1]["updated_at"] = late

    assert q.untrusted_failure_reason(rows, late + timedelta(seconds=10))
    assert q.untrusted_failure_reason(rows, late + timedelta(seconds=q.FOREIGN_SWEEP_GRACE_SECONDS)) is None


def test_a_swept_row_without_a_clock_is_not_deferred():
    """读不到时间戳就不拿宽限当挡箭牌 —— 「永久等待」正是这个模块要消灭的失败。"""
    rows = [{"status": "stopped", "error_message": _FOREIGN_RECONCILE}]

    assert q.untrusted_failure_reason(rows, _CREATED_AT) is None


def test_a_finished_batch_is_not_a_sweep_case():
    rows = [{"status": "completed", "updated_at": _CREATED_AT, "created_at": _CREATED_AT}]

    assert q.untrusted_failure_reason(rows, _CREATED_AT) is None


def test_no_rows_is_not_a_sweep_case():
    assert q.untrusted_failure_reason([], _CREATED_AT) is None


def test_the_deferral_says_which_sweeper_did_it():
    swept_at = _CREATED_AT + timedelta(hours=1)
    reason = q.untrusted_failure_reason(
        _swept_rows(_FOREIGN_RECONCILE, swept_at=swept_at), swept_at + timedelta(seconds=1)
    )

    assert reason and "reconcile" in reason, "日志要能一眼看出是哪一路外部写手：%r" % (reason,)


def test_the_tick_actually_consults_the_foreign_sweep_guard():
    """接线契约：判据写好了但没人调用等于没有（09-30 就是这么白跑一轮的）。"""
    source = Path(q.__file__).read_text(encoding="utf-8")
    branch = source.split("verdict = verdict_from_task_rows(", 1)[1].split("status, message = verdict", 1)[0]

    assert "untrusted_failure_reason(" in branch, (
        "tick 必须在拿到 failed 判决后先问一次「这是不是外部误标」，"
        "否则整批会被外部 reconcile 重跑一遍"
    )


def test_engine_and_queue_read_the_same_fingerprint():
    """engine 与 queue 必须共用一份指纹 —— 各抄一份字符串就是漂移的开始。"""
    from rpa.hongguo import reclaim
    from rpa.hongguo.engine import TaskEngine

    for message in (_FOREIGN_RECONCILE, _OWN_RECONCILE, _WATCHDOG_REAP, _REAL_FAILURE, ""):
        assert TaskEngine._is_foreign_fleet_reconcile(message) is reclaim.is_foreign_fleet_reconcile(message)
        assert TaskEngine._is_watchdog_false_reap(message) is reclaim.is_watchdog_reap(message)


def test_the_fingerprint_splits_the_three_writers():
    from rpa.hongguo import reclaim

    assert reclaim.is_foreign_fleet_reconcile(_FOREIGN_RECONCILE) is True
    assert reclaim.is_foreign_fleet_reconcile(_OWN_RECONCILE) is False
    assert reclaim.is_watchdog_reap(_WATCHDOG_REAP) is True
    assert reclaim.is_foreign_sweep(_REAL_FAILURE) is False
    assert reclaim.classify(_FOREIGN_RECONCILE) == "其它节点旧版本的全库 reconcile 误标"
    assert reclaim.classify(_WATCHDOG_REAP) == "其它节点的看门狗误判失联"
    assert reclaim.classify(_OWN_RECONCILE) is None


# ------------------------------------------- 重跑只覆盖失败的设备（2026-10-01）
#
# 每台设备都是自己把整部剧跑一遍，所以条目重跑时已经跑完的那几台没必要陪跑。
# 10-01 seq3《丧尸狂潮》两台跑了 5 分钟就挂，队列却把 4 台一起从第 1 集重跑，
# 首轮 1 小时 40 分 × 4 台全部作废（≈6.7 设备·小时），而其中 537/538 本来就已经
# 跑成功了。


def test_failed_device_addrs_lists_only_the_unfinished_ones():
    rows = [
        {"status": "completed", "device_addr": "127.0.0.1:16416"},
        {"status": "completed", "device_addr": "127.0.0.1:16448"},
        {"status": "failed", "device_addr": "127.0.0.1:16480"},
        {"status": "stopped", "device_addr": "127.0.0.1:16512"},
        {"status": "failed", "device_addr": "127.0.0.1:16480"},
    ]

    assert q.failed_device_addrs(rows) == ["127.0.0.1:16480", "127.0.0.1:16512"]


def test_failed_device_addrs_is_empty_when_every_device_finished():
    assert q.failed_device_addrs([{"status": "completed", "device_addr": "a"}]) == []


def test_failed_device_addrs_ignores_rows_without_an_address():
    """读不到地址就只有"没有可用信息"这一种解释，交给调用方退回全量。"""
    assert q.failed_device_addrs([{"status": "failed", "device_addr": None}]) == []


def test_a_real_failure_records_which_devices_failed(monkeypatch):
    """重跑清单必须落库，否则下一个 tick 又按全量设备起一遍。"""
    now = _CREATED_AT + timedelta(hours=1)
    rows = [
        {"status": "completed", "device_addr": "127.0.0.1:16416",
         "started_at": _CREATED_AT, "created_at": _CREATED_AT},
        {"status": "completed", "device_addr": "127.0.0.1:16448",
         "started_at": _CREATED_AT, "created_at": _CREATED_AT},
        {"status": "failed", "device_addr": "127.0.0.1:16480", "error_message": "集数不符",
         "started_at": _CREATED_AT, "created_at": _CREATED_AT},
        {"status": "failed", "device_addr": "127.0.0.1:16512", "error_message": "收藏未达标",
         "started_at": _CREATED_AT, "created_at": _CREATED_AT},
    ]
    _, statements = _tick_statements(
        monkeypatch, item=_stalled_item(attempt=1), rows=rows, now=now
    )

    retries = _retry_updates(statements)
    assert len(retries) == 1
    assert "retry_devices_json=%s" in retries[0], (
        "真失败必须记下是哪几台挂的：%s" % (retries[0],)
    )
    written = [
        params[0]
        for sql, params in statements
        if "retry_devices_json=%s" in " ".join(str(sql).split())
    ]
    assert written, statements
    assert json.loads(written[0]) == ["127.0.0.1:16480", "127.0.0.1:16512"]


def test_an_infrastructure_failure_still_clears_the_retry_list(monkeypatch):
    """从没启动过的批次四台都要重来，不能沿用上一次的清单。"""
    now = _CREATED_AT + timedelta(hours=1)
    _, statements = _tick_statements(
        monkeypatch,
        item=_stalled_item(infra_retries=0, retry_devices_json=json.dumps(["a"])),
        rows=_STALLED_ROWS,
        now=now,
    )

    retries = _retry_updates(statements)
    assert len(retries) == 1
    assert "retry_devices_json=NULL" in retries[0], retries[0]


_FOUR_DEVICES = [
    {"addr": "127.0.0.1:16416"},
    {"addr": "127.0.0.1:16448"},
    {"addr": "127.0.0.1:16480"},
    {"addr": "127.0.0.1:16512"},
]


def _retry_item(**overrides):
    item = {
        "id": 7,
        "queue_id": "queue-1",
        "seq": 7,
        "drama_name": "丧尸狂潮",
        "status": "pending",
        "attempt": 1,
        "infra_retries": 0,
        "multi_run_id": "multi-1",
        "devices_json": json.dumps(_FOUR_DEVICES),
        "retry_devices_json": json.dumps(["127.0.0.1:16480", "127.0.0.1:16512"]),
    }
    item.update(overrides)
    return item


def _devices_handed_to_start(monkeypatch, *, item):
    """Run one tick whose only job is to start ``item``; return its devices."""
    seen = {}

    class _Cur:
        rowcount = 1

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def execute(self, sql, params=None):
            pass

        def fetchone(self):
            return None

        def fetchall(self):
            return []

    class _Conn:
        def cursor(self):
            return _Cur()

        def commit(self):
            pass

    class _Ctx:
        def __enter__(self):
            return _Conn()

        def __exit__(self, *exc_info):
            return False

    monkeypatch.setattr(q, "_connection", lambda: _Ctx())
    monkeypatch.setattr(q, "_ensure_queue_columns", lambda conn: None)
    monkeypatch.setattr(q, "_ensure_config", lambda conn: {})
    monkeypatch.setattr(q, "daily_should_fire", lambda **kwargs: False)
    monkeypatch.setattr(q, "_unfinished_queue_id", lambda conn: "queue-1")
    monkeypatch.setattr(q, "_queue_items", lambda conn, queue_id: [dict(item)])

    def _start(conn, nxt, devices, now):
        seen["devices"] = [dict(device) for device in devices]
        return {
            "run_id": "multi-2",
            "task_ids": [11, 12],
            "devices": seen["devices"],
            "claimed": True,
        }

    monkeypatch.setattr(q, "_start_item", _start)
    plan = q._tick_plan(_CREATED_AT + timedelta(hours=1))
    assert plan["start"], "这一 tick 本应启动条目：%s" % (plan,)
    return seen["devices"], plan


def test_a_retry_only_restarts_the_devices_that_failed(monkeypatch):
    devices, plan = _devices_handed_to_start(monkeypatch, item=_retry_item())

    assert [device["addr"] for device in devices] == [
        "127.0.0.1:16480",
        "127.0.0.1:16512",
    ]
    assert any("只重跑这几台" in note for note in plan["notes"]), plan["notes"]


def test_a_first_attempt_still_uses_every_device(monkeypatch):
    devices, _ = _devices_handed_to_start(
        monkeypatch, item=_retry_item(retry_devices_json=None)
    )

    assert [device["addr"] for device in devices] == [
        "127.0.0.1:16416",
        "127.0.0.1:16448",
        "127.0.0.1:16480",
        "127.0.0.1:16512",
    ]


def test_a_retry_list_that_matches_no_device_falls_back_to_all(monkeypatch):
    """设备换过号就退回全量，别因为对不上号把条目卡住。"""
    devices, _ = _devices_handed_to_start(
        monkeypatch,
        item=_retry_item(retry_devices_json=json.dumps(["127.0.0.1:19999"])),
    )

    assert len(devices) == 4


def test_a_retry_naming_every_device_changes_nothing(monkeypatch):
    devices, plan = _devices_handed_to_start(
        monkeypatch,
        item=_retry_item(
            retry_devices_json=json.dumps([device["addr"] for device in _FOUR_DEVICES])
        ),
    )

    assert len(devices) == 4
    assert not any("只重跑这几台" in note for note in plan["notes"]), plan["notes"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
