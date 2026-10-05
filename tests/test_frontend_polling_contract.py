# -*- coding: utf-8 -*-
"""前端「实例执行统计」实时性的静态契约。

2026-09-17：用户报告「单独重跑？我看不到过程」。根因是页面只在用户点了
「开始执行」时才启动 5 秒轮询，所以任何从这个页面之外启动的批次（脚本、
另一个标签页、另一台机器）在界面上都是**静止的**——`最近过程` 列和执行过程
面板停在页面加载那一刻的快照。

修法是把「是否轮询」从「谁点的开始」改成「批次里还有没有活着的任务」。
这几条断言把这个契约钉住，避免以后再滑回只看 startRun 的写法。
"""
import re
from pathlib import Path

import pytest

MULTI_VIEW = Path(__file__).resolve().parents[1] / "frontend" / "src" / "views" / "HongguoMulti.vue"


@pytest.fixture(scope="module")
def source() -> str:
    assert MULTI_VIEW.exists(), "找不到 {0}".format(MULTI_VIEW)
    return MULTI_VIEW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def script(source: str) -> str:
    match = re.search(r"<script setup>(.*?)</script>", source, re.S)
    assert match, "HongguoMulti.vue 里找不到 <script setup> 段"
    return match.group(1)


def test_polling_decision_is_based_on_task_status_not_on_who_clicked_start(script: str):
    assert "function runIsLive(run)" in script
    assert "function ensurePolling()" in script
    # ensurePolling must consult runIsLive, not a "did I start it" flag.
    body = script[script.index("function ensurePolling()") :]
    body = body[: body.index("\nfunction ")]
    assert "runIsLive(activeRun.value)" in body


def test_run_detail_refresh_re_arms_the_live_loop(script: str):
    """loadRunDetail is the single funnel for mount / batch switch / 刷新统计."""
    body = script[script.index("async function loadRunDetail(") :]
    body = body[: body.index("\nfunction ")]
    assert "ensurePolling()" in body


def test_poll_loop_refreshes_the_open_process_panel(script: str):
    """The 执行过程 panel must follow the run, otherwise it looks frozen."""
    body = script[script.index("function startPolling()") :]
    body = body[: body.index("\nfunction stopPolling()")]
    assert "selectedLogTaskId.value" in body
    assert "loadTaskLogs(" in body


def test_a_paused_task_also_counts_as_live(script: str):
    """A paused run still has a process to watch; stopping the poll hides it."""
    body = script[script.index("function runIsLive(run)") :]
    body = body[: body.index("\nfunction ")]
    assert "'paused'" in body


def test_device_detection_temporarily_suspends_polling(script: str):
    """getMultiDevices can take minutes; polling on top of it just stacks load."""
    assert "pollingSuspended = true" in script
    assert "pollingSuspended = false" in script
    # And the declaration must exist, or ensurePolling throws a ReferenceError.
    assert "let pollingSuspended = false" in script
