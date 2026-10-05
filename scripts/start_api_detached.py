"""Start the SuperClaw API as a detached background service.

Why this file exists
--------------------
Launched as a child of an editor or an agent session, this API dies with that
session. It happened four times: the process vanished overnight leaving no
shutdown line in its log at all, and the tasks it was running were stranded
mid-batch. Two Windows flags fix that properly:

``DETACHED_PROCESS``
    Give the child no console of its own, so closing the window that started
    it cannot deliver a CTRL_CLOSE to the service.
``CREATE_BREAKAWAY_FROM_JOB``
    Leave the parent's job object. When something kills a job it kills every
    process inside it - which is exactly how the earlier disappearances
    happened. A job may forbid breakaway; then we settle for DETACHED_PROCESS
    and say so, instead of failing outright.

Everything the operator sees is printed here, in Chinese, from a UTF-8
stream - a batch file cannot carry non-ASCII text safely (a cp936 console
mangles it).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "venv" / "Scripts" / "python.exe"
LOG_DIR = ROOT / "logs"
STDOUT_LOG = LOG_DIR / "api-dev.out.log"
STDERR_LOG = LOG_DIR / "api-dev.err.log"

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass


def netstat_text() -> str:
    """Decode netstat whatever codepage the console happens to be using."""
    try:
        proc = subprocess.run(["netstat", "-ano"], capture_output=True, timeout=25)
    except Exception:
        return ""
    raw = proc.stdout or b""
    for encoding in ("utf-8", "mbcs", "gbk", "latin-1"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


def listening_pids(port: int):
    suffix = ":%d" % port
    pids = []
    for line in netstat_text().splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3].upper() == "LISTENING" and parts[1].endswith(suffix):
            if parts[4] not in pids:
                pids.append(parts[4])
    return pids


def build_env(port: int):
    env = os.environ.copy()
    env["PYTHONPATH"] = ""
    env["SUPERCLAW_API_PORT"] = str(port)
    env["SUPERCLAW_EXECUTION_MODE"] = "embedded"
    # Read by the queue dispatcher; without it no scheduled batch ever fires,
    # and the failure is silent - so it is set here rather than left to chance.
    env["SUPERCLAW_QUEUE_DISPATCHER"] = "1"
    return env


def spawn(port: int):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not PYTHON.is_file():
        raise SystemExit("[错误] 找不到 %s，请确认是在项目目录里运行。" % PYTHON)
    base_flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    attempts = [
        (base_flags | CREATE_BREAKAWAY_FROM_JOB, "breakaway"),
        (base_flags, "detached-only"),
    ]
    last_error = None
    for flags, label in attempts:
        stdout_handle = open(STDOUT_LOG, "ab")
        stderr_handle = open(STDERR_LOG, "ab")
        try:
            process = subprocess.Popen(
                [str(PYTHON), str(ROOT / "run_api.py")],
                cwd=str(ROOT),
                env=build_env(port),
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                creationflags=flags,
                close_fds=True,
            )
        except OSError as exc:
            stdout_handle.close()
            stderr_handle.close()
            last_error = exc
            continue
        return process.pid, label
    raise SystemExit("[错误] 无法启动服务进程：%s" % last_error)


def main() -> int:
    parser = argparse.ArgumentParser(description="以脱离会话的方式启动 SuperClaw 服务")
    parser.add_argument("--port", type=int, default=8987)
    parser.add_argument("--timeout", type=float, default=150.0)
    args = parser.parse_args()
    force_utf8_output()

    existing = listening_pids(args.port)
    if existing:
        print("[提示] 端口 %d 已经有服务在监听（PID %s），不再重复启动。" % (args.port, ", ".join(existing)))
        print("       同一台机器跑两个 embedded 实例会互相抢任务，所以这里直接退出。")
        return 0

    pid, label = spawn(args.port)
    print("[OK] 已启动后台服务进程，PID=%d（方式：%s）" % (pid, label))
    if label != "breakaway":
        print("     [注意] 未能脱离父作业对象，本次由资源管理器双击启动不受影响；")
        print("            若将来由其他程序拉起，可能在那个程序退出时被一起结束。")

    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        time.sleep(2.0)
        try:
            import json
            import urllib.request

            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open("http://127.0.0.1:%d/health" % args.port, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8", "replace"))
        except Exception:
            continue
        auth = bool(data.get("auth_required"))
        print("")
        print("[OK] 服务已就绪：http://localhost:%d" % args.port)
        print("     进程 PID    : %s" % (", ".join(listening_pids(args.port)) or str(pid)))
        print("     数据库      : %s" % ("正常" if data.get("database") else "不可用"))
        print("     执行模式    : %s" % data.get("execution_mode"))
        print("     可执行任务  : %s" % ("是" if data.get("task_execution_ready") else "否"))
        print("     运行中任务  : %s 个（全库口径，含其他机器）" % data.get("running_tasks"))
        print("     鉴权        : %s" % ("已开启" if auth else "已关闭"))
        print("     打开看板    : http://localhost:%d/hongguo/multi" % args.port)
        if not auth:
            print("")
            print("[警告] 鉴权已关闭，而服务监听在 0.0.0.0 上 —— ")
            print("       同一局域网内任何人都能直接进入后台，请确认这是你要的。")
        if not data.get("database"):
            print("")
            print("[警告] 数据库不可用，任务跑不起来，检查 config/local.yaml。")
            return 1
        return 0

    print("")
    print("[失败] 等了 %.0f 秒服务仍未就绪，看 logs/api-dev.err.log 的最后几行。" % args.timeout)
    return 1


if __name__ == "__main__":
    sys.exit(main())
