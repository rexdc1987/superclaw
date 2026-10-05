# -*- coding: utf-8 -*-
"""机器归属档案的回归测试。

只测**决策分支**：哪条路走哪个 SQL、返回什么、以及「归属失败绝不能拖垮任务创建」
这条硬约束。真实 SQL 的正确性由 `tmp/verify_attribution.py` 打真库验证。

为什么状态必须是 `registered` 而不是 `online`：`hongguo_runtime_health()` 用
`status='online' AND last_seen_at >= 90s 前` 算在线节点数，进而决定
`task_execution_ready`。认领写 `online` 会让一个根本不轮询的机器被算成
"有执行节点在线"，控制端因此可能把任务派给没人领的机器。
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from rpa.hongguo import attribution as A  # noqa: E402


def _conn_for(existing, rowcount=1):
    """搭一个能被 `with conn.cursor() as cur:` 使用的假连接。

    `rowcount` 同时喂给 INSERT 与 UPDATE —— 每个用例只会走其中一条，
    所以一个值就够（两条分支读的是同一个 `cur.rowcount`）。
    """
    cur = MagicMock()
    cur.fetchone.return_value = existing
    cur.fetchall.return_value = []
    cur.rowcount = rowcount
    enter = MagicMock(return_value=cur)
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = enter
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cur


def _executed_sql(cur):
    return " || ".join(str(c.args[0]) for c in cur.execute.call_args_list if c.args)


# --------------------------------------------------------------- 不该写库的情况

def test_zero_user_id_is_not_an_owner():
    """user_id=0 是"本地/未登录"虚拟主体，不能当归属写进库。"""
    conn, cur = _conn_for(None)
    result = A.bind_machine_account(conn, "MACHINE-A", 0, "local")
    assert result == {"bound": False, "reason": "no_principal"}
    cur.execute.assert_not_called()


def test_missing_worker_id_is_rejected():
    conn, cur = _conn_for(None)
    result = A.bind_machine_account(conn, "   ", 18, "admins")
    assert result == {"bound": False, "reason": "no_worker_id"}
    cur.execute.assert_not_called()


# ------------------------------------------------------------------ 四条主分支

def test_first_claim_registers_machine_as_registered_not_online():
    conn, cur = _conn_for(None, rowcount=1)
    result = A.bind_machine_account(conn, "MACHINE-A", 18, "admins")

    assert result["bound"] is True and result["claimed"] is True
    sql = _executed_sql(cur)
    assert "INSERT IGNORE INTO hongguo_workers" in sql
    insert_calls = [c for c in cur.execute.call_args_list if "INSERT IGNORE" in str(c.args[0])]
    assert len(insert_calls) == 1
    insert_sql = str(insert_calls[0].args[0])
    assert "'registered'" in insert_sql, "建档必须是 registered，否则会被算成在线执行节点"
    assert "'online'" not in insert_sql
    # 参数里不该出现 status 的绑定值，避免有人改成外部传入而绕过上面的约束
    assert "registered" not in insert_calls[0].args[1]


def test_same_owner_refreshes_without_reclaiming():
    conn, cur = _conn_for({"worker_id": "MACHINE-A", "owner_user_id": 18,
                           "owner_username": "admins", "owner_conflict": ""})
    result = A.bind_machine_account(conn, "MACHINE-A", 18, "admins")

    assert result["bound"] is True and result["claimed"] is False
    sql = _executed_sql(cur)
    assert "UPDATE hongguo_workers" in sql
    assert "owner_user_id=" not in sql.split("SET", 1)[1].split("WHERE")[0], \
        "同账号刷新不应该改写 owner_user_id"


def test_different_owner_is_a_conflict_and_is_not_overwritten():
    conn, cur = _conn_for({"worker_id": "MACHINE-A", "owner_user_id": 18,
                           "owner_username": "admins", "owner_conflict": ""})
    result = A.bind_machine_account(conn, "MACHINE-A", 1, "admin")

    assert result["conflict"] is True
    assert result["owner_user_id"] == 18 and result["owner_username"] == "admins"
    assert result["attempted_username"] == "admin"
    sql = _executed_sql(cur)
    assert "owner_conflict=" in sql
    assert "owner_user_id=1" not in sql, "冲突路径绝不能改写归属"


def test_force_overwrites_and_keeps_audit_trail():
    conn, cur = _conn_for({"worker_id": "MACHINE-A", "owner_user_id": 18,
                           "owner_username": "admins", "owner_conflict": "admin"})
    result = A.bind_machine_account(conn, "MACHINE-A", 1, "admin", force=True)

    assert result["forced"] is True
    assert result["previous_owner"] == "admins"
    assert result["owner_user_id"] == 1
    params = cur.execute.call_args_list[-1].args[1]
    assert "admins" in params, "被顶掉的原归属必须留在 owner_conflict 里"


def test_unowned_machine_can_be_claimed_but_race_is_reported():
    conn, cur = _conn_for({"worker_id": "MACHINE-A", "owner_user_id": 0,
                           "owner_username": "", "owner_conflict": ""},
                          rowcount=1)
    result = A.bind_machine_account(conn, "MACHINE-A", 18, "admins")
    assert result["bound"] is True and result["claimed"] is True

    conn2, _ = _conn_for({"worker_id": "MACHINE-A", "owner_user_id": 0,
                          "owner_username": "", "owner_conflict": ""},
                         rowcount=0)
    result2 = A.bind_machine_account(conn2, "MACHINE-A", 18, "admins")
    assert result2 == {"bound": False, "reason": "race_lost"}


# ------------------------------------------- 归属失败绝不能拖垮任务创建

def test_claim_helper_swallows_bind_failure(monkeypatch):
    """归属是附加信息：写不进去也不能让任务创建抛异常。"""
    from rpa.dashboard import routes_hongguo as R

    def boom(*a, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(R, "bind_machine_account", boom)
    R._claim_machine_for_task(MagicMock(), 123, "MACHINE-A")  # 不抛即通过


def test_claim_helper_logs_conflict(monkeypatch):
    from rpa.dashboard import routes_hongguo as R

    logged = []
    monkeypatch.setattr(R, "bind_machine_account",
                        lambda *a, **kw: {"bound": False, "conflict": True,
                                          "owner_username": "admins",
                                          "attempted_username": "admin"})
    monkeypatch.setattr(R, "_insert_log",
                        lambda conn, task_id, msg, level="info": logged.append((task_id, msg, level)))

    R._claim_machine_for_task(MagicMock(), 123, "MACHINE-A")

    assert len(logged) == 1
    task_id, msg, level = logged[0]
    assert task_id == 123 and level == "warn"
    assert "admins" in msg and "admin" in msg


def test_claim_helper_is_silent_on_success(monkeypatch):
    from rpa.dashboard import routes_hongguo as R

    logged = []
    monkeypatch.setattr(R, "bind_machine_account",
                        lambda *a, **kw: {"bound": True, "claimed": True})
    monkeypatch.setattr(R, "_insert_log",
                        lambda *a, **kw: logged.append(a))

    R._claim_machine_for_task(MagicMock(), 123, "MACHINE-A")
    assert logged == []


# --------------------------------------------------------------- 推断与迁移

def test_inference_prefers_majority_account_and_flags_ambiguity():
    conn, cur = _conn_for(None)
    cur.fetchall.return_value = [
        {"worker_id": "M-A", "owner_user_id": 1, "username": "admin", "n": 9},
        {"worker_id": "M-A", "owner_user_id": 0, "username": None, "n": 4},
        {"worker_id": "M-B", "owner_user_id": 1, "username": "admin", "n": 2},
        {"worker_id": "M-B", "owner_user_id": 18, "username": "admins", "n": 7},
    ]
    proposals = {p["worker_id"]: p for p in A.infer_machine_owners(conn)}

    assert proposals["M-A"]["proposed_owner_username"] == "admin"
    assert proposals["M-A"]["ambiguous"] is False
    assert proposals["M-A"]["tasks_without_owner"] == 4
    assert proposals["M-B"]["proposed_owner_username"] == "admins"
    assert proposals["M-B"]["ambiguous"] is True


def test_machine_owner_columns_cover_the_four_fields():
    names = [name for name, _ in A.MACHINE_OWNER_COLUMNS]
    assert names == ["owner_user_id", "owner_username", "owner_bound_at", "owner_conflict"]


def test_ensure_machine_columns_adds_only_missing_ones():
    cur = MagicMock()
    cur.fetchall.return_value = [{"COLUMN_NAME": "owner_user_id"}]
    cur.fetchone.return_value = {"count": 1}

    A.ensure_machine_columns(cur, "superclaw")

    sql = _executed_sql(cur)
    assert "ADD COLUMN owner_username" in sql
    assert "ADD COLUMN owner_bound_at" in sql
    assert "ADD COLUMN owner_conflict" in sql
    assert "ADD COLUMN owner_user_id" not in sql, "已存在的列不应重复 ADD"
    assert "ADD INDEX" not in sql, "索引已存在时不应重复创建"
