# -*- coding: utf-8 -*-
"""「实例执行统计」卡跟随队列当前批次的接线契约（静态）。

队列由服务端调度器推进：一部短剧跑完会自动起下一部，而**每一部都是一个新批次**
（`multi-<时间戳>-<序号>`）。前端 `activeRunId` 是那张卡的批次选择器；如果没人把它
接到队列上，页面就会一直停在上一次手选的批次 —— 2026-09-29 用户报的
「下面这个执行中的好像跟操作的不一样」正是如此：队列卡在跑 09-29 那批，
统计卡却停在 09-25 那批（任务 466/467 都已完成）。

修复引入 `followQueue`（默认 true）+ `syncFollowedRun()`：队列状态每次更新后把统计卡
切到「队列里正在跑的那一项」的 `multi_run_id`；用户一旦手动挑批次（下拉框、点队列行
的批次链接、新建、重建）就锁定，不再被跟随抢走。

这些调用点全在 `<script setup>` 里，删掉任何一处都不会编译报错，只会让统计卡重新
变回「粘住」的状态，所以用静态断言钉住。
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "frontend" / "src" / "views" / "HongguoMulti.vue"


def read(path: Path) -> str:
    assert path.exists(), "找不到 {0}".format(path)
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def view() -> str:
    return read(VIEW)


@pytest.fixture(scope="module")
def script(view: str) -> str:
    match = re.search(r"<script setup>(.*?)</script>", view, re.S)
    assert match, "HongguoMulti.vue 里找不到 <script setup> 段"
    return match.group(1)


def between(source: str, start_anchor: str, stop_anchor: str) -> str:
    """取两个锚点之间的原文（含起始锚点）。

    比按花括号配对切片更耐折腾：这段代码里有 `${...}` 插值和中文模板串，
    逐个配对容易被字面量里的括号带偏。
    """
    at = source.find(start_anchor)
    assert at != -1, "找不到锚点 {0}".format(start_anchor)
    end = source.find(stop_anchor, at + len(start_anchor))
    assert end != -1, "在 {0} 之后找不到锚点 {1}".format(start_anchor, stop_anchor)
    return source[at:end]


def test_following_is_on_by_default(script: str):
    assert re.search(r"const followQueue = ref\(true\)", script), (
        "followQueue 默认必须为 true：打开页面就该落在队列正在跑的那一批上"
    )


def test_sync_followed_run_guards_both_the_switch_and_the_current_batch(script: str):
    body = between(script, "function syncFollowedRun(", "// 手动选批次就锁定")
    assert "if (!followQueue.value) return" in body, (
        "锁定（followQueue=false）时必须直接返回，否则用户手选的历史批次会被抢走"
    )
    assert "runId === activeRunId.value" in body, (
        "已经停在目标批次上就要跳过，否则每个轮询周期都会重复拉一次批次详情"
    )
    assert "loadRunDetail(runId" in body, "跟随要落到 loadRunDetail 才算真的切过去"


def test_every_queue_update_pulls_the_panel_over(script: str):
    """三处队列状态更新点都必须跟随，缺一个就会出现「队列在动、卡不动」。"""
    cases = (
        ("function applyActive(", "async function loadQueueState(", "入队 / 手动 tick"),
        ("async function loadQueueState(", "function syncDailyForm(", "首屏加载与重同步"),
        ("function startQueuePolling(", "function stopQueuePolling(", "8s 轮询（跑完自动换下一部）"),
    )
    for start, stop, label in cases:
        body = between(script, start, stop)
        assert "syncFollowedRun()" in body, "「{0}」这条路径没有跟随队列".format(label)


def test_manual_picks_lock_the_panel(script: str):
    """用户主动挑批次的地方都要锁定，否则跟随会把画面抢走。"""
    cases = (
        ("function selectRun(", "function currentQueueRunId(", "点队列行的批次链接"),
        ("function onPickRun(", "function onFollowQueueChange(", "手动改批次下拉框"),
        ("async function createRun(", "async function startRun(", "新建单批次"),
        ("async function rebuildRunFromActiveRun(", "async function loadTaskLogs(", "按此批次重建"),
    )
    for start, stop, label in cases:
        body = between(script, start, stop)
        assert "followQueue.value = false" in body, "「{0}」没有锁定批次".format(label)


def test_turning_the_switch_back_on_follows_immediately(script: str):
    body = between(script, "function onFollowQueueChange(", "function ruleFromTask(")
    assert "if (enabled) syncFollowedRun()" in body, (
        "把开关拨回来要立刻就位，不能等下一个 8s 轮询周期"
    )


def test_template_wires_the_switch_and_routes_manual_change_through_on_pick_run(view: str):
    assert 'v-model="followQueue"' in view, "统计卡头部缺少「跟随队列」开关"
    assert "跟随队列" in view and "已锁定" in view, "开关两态文案缺失，用户看不出当前是否在跟随"
    assert '@change="onPickRun"' in view, (
        "批次下拉框要接 onPickRun：手动选择必须顺带锁定，接回 loadRunDetail 会丢掉锁定"
    )
