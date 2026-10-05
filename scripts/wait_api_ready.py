"""Wait until the SuperClaw API answers /health, then report what it found.

Called by the double-click launchers so a failure shows up in the console
they opened, instead of silently leaving the operator with a dead page.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass


def _netstat_text() -> str:
    """Decode netstat's output whatever codepage the console happens to use.

    A Chinese Windows writes GBK when the console is at its default codepage
    and UTF-8 once the launcher has run ``chcp 65001``, so neither choice is
    safe on its own - and getting it wrong kills the reader thread inside
    subprocess and loses the list of pids entirely.
    """
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
    for line in _netstat_text().splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3].upper() == "LISTENING" and parts[1].endswith(suffix):
            if parts[4] not in pids:
                pids.append(parts[4])
    return pids


def health(port: int, timeout: float = 5.0):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:%d/health" % port, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8987)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    _force_utf8_output()

    deadline = time.monotonic() + args.timeout
    last_error = "端口还没有被监听"
    while time.monotonic() < deadline:
        try:
            data = health(args.port)
        except urllib.error.URLError as exc:
            last_error = str(getattr(exc, "reason", exc))
        except Exception as exc:
            last_error = str(exc)
        else:
            pids = listening_pids(args.port)
            auth = bool(data.get("auth_required"))
            print("")
            print("[OK] 服务已就绪")
            print("     地址        : http://localhost:%d" % args.port)
            print("     进程 PID    : %s" % (", ".join(pids) if pids else "?"))
            print("     数据库      : %s" % ("正常" if data.get("database") else "不可用"))
            print("     执行模式    : %s" % data.get("execution_mode"))
            print("     可执行任务  : %s" % ("是" if data.get("task_execution_ready") else "否"))
            print("     运行中任务  : %s 个（全库口径，含其他机器）" % data.get("running_tasks"))
            print("     鉴权        : %s" % ("已开启" if auth else "已关闭"))
            print("     打开看板    : http://localhost:%d/hongguo/multi" % args.port)
            if not auth:
                print("")
                print("[警告] 鉴权已关闭，而服务监听在 0.0.0.0 上 ——")
                print("       同一局域网里任何人都能直接进后台，请确认这是你要的。")
            if not data.get("database"):
                print("")
                print("[警告] 数据库不可用，任务跑不起来。")
                print("       检查 config/local.yaml 里的数据库地址、账号与密码。")
                return 1
            return 0
        time.sleep(2.0)

    print("")
    print("[失败] 等了 %.0f 秒仍未就绪。最后一条错误：%s" % (args.timeout, last_error))
    return 1


if __name__ == "__main__":
    sys.exit(main())
