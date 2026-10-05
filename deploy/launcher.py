#!/usr/bin/env python
"""SuperClaw launcher — apply any pending update, then supervise the API server.

Why a launcher instead of just starting uvicorn: on Windows you cannot replace
files that a running process has loaded. So an update is applied *before* the
server starts, and "restart to update" is just the launcher looping once.

Boot sequence:
  1. read ``data/instance.json`` (port, execution mode, ...)
  2. if ``data/updates/apply.flag`` exists, apply the staged version
  3. make sure ``app/config/local.yaml`` exists (from the shipped preset)
  4. start uvicorn and open the browser
  5. if the API drops ``updates/restart.flag``, stop the server and re-exec

Why this file lives in ``app/`` and not at the install root: the auto updater
only ever rewrites ``app/``. A launcher parked at the root would be unreachable
to it, so every launcher bug would need a full reinstall to fix — including the
bug this file exists to prevent. The root only keeps ``start_superclaw.bat``, a
stub small enough that it should never need to change.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

# ``app/launcher.py`` -> install root is one level up. ``<root>/launcher.py``
# (the layout installs used before 1.0.5) still resolves correctly.
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent if HERE.name == "app" else HERE
LAUNCHER_PATH = Path(__file__).resolve()
APP_DIR = ROOT / "app"
DATA_DIR = ROOT / "data"
UPDATES_DIR = DATA_DIR / "updates"
STAGING_DIR = UPDATES_DIR / "staging"
INSTANCE_FILE = DATA_DIR / "instance.json"
PENDING_FILE = UPDATES_DIR / "pending.json"
APPLY_FLAG = UPDATES_DIR / "apply.flag"
RESTART_FLAG = UPDATES_DIR / "restart.flag"
LOG_FILE = DATA_DIR / "logs" / "launcher.log"

DEFAULT_INSTANCE = {
    "port": 8987,
    "execution_mode": "api",
    "open_browser": True,
    "auto_check_update": True,
    "update_repo": "",
    "update_channel": "stable",
}

# Holds the single-instance guard for the life of the process. Kept at module
# scope on purpose — letting the handle be garbage collected would release it.
_mutex_handle = None


def acquire_single_instance() -> bool:
    """Take a named mutex so two launchers can never share one install.

    Matters twice over:
      * double-clicking the shortcut twice would otherwise start a second
        uvicorn on the same port (and a second updater racing on app/)
      * Inno Setup's AppMutex watches this exact name, so the installer and the
        uninstaller can tell that the service is still running before they
        replace or delete files

    Override the name with SUPERCLAW_MUTEX_NAME when running a throwaway copy
    (e.g. an automated update test) side by side with a real install.
    """
    global _mutex_handle
    if os.name != "nt":
        return True

    import ctypes

    ERROR_ALREADY_EXISTS = 183
    name = os.environ.get("SUPERCLAW_MUTEX_NAME", "SuperClaw.Launcher")

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    handle = kernel32.CreateMutexW(None, 1, name)
    if not handle:
        # Never let the guard itself block a legitimate start.
        log("单实例锁创建失败，继续启动（可能被重复启动）")
        return True

    already_running = kernel32.GetLastError() == ERROR_ALREADY_EXISTS
    if already_running:
        kernel32.CloseHandle(handle)
        return False
    _mutex_handle = handle
    return True


def release_single_instance() -> None:
    """Drop the mutex so the replacement process can take it.

    os.execv() on Windows starts the child *before* the parent goes away, so
    without this the child can lose the CreateMutexW race, decide that another
    instance is already running, and exit — leaving nobody serving at all.
    """
    global _mutex_handle
    if not _mutex_handle:
        return
    import ctypes

    try:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(_mutex_handle))
    except Exception:  # noqa: BLE001 - the process is about to be replaced
        pass
    _mutex_handle = None


def log(message: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = "%s [launcher] %s" % (stamp, message)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    print(line, flush=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_ip() -> str:
    """Best-effort primary LAN address, for telling colleagues where to point."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


# --------------------------------------------------------------------------- #
# instance settings
# --------------------------------------------------------------------------- #

def load_instance() -> dict:
    settings = dict(DEFAULT_INSTANCE)
    if INSTANCE_FILE.is_file():
        try:
            settings.update(json.loads(INSTANCE_FILE.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            log("instance.json 读取失败，改用默认值：%s" % exc)
    else:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        INSTANCE_FILE.write_text(
            json.dumps(DEFAULT_INSTANCE, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        log("已生成默认 instance.json")
    return settings


def materialize_local_config() -> None:
    """app/config/local.yaml is the file the backend actually reads.

    It is generated from the shipped preset and is on the updater's preserve
    list, so a new version never clobbers real database credentials.
    """
    target = APP_DIR / "config" / "local.yaml"
    if target.is_file():
        return
    preset = APP_DIR / "config" / "local.yaml.preset"
    target.parent.mkdir(parents=True, exist_ok=True)
    if preset.is_file():
        shutil.copy2(preset, target)
        log("已从 local.yaml.preset 生成 app/config/local.yaml")
    else:
        target.write_text(
            "database:\n  engine: mysql\n  host: 127.0.0.1\n  port: 3306\n"
            "  name: superclaw\n  user: superclaw\n  password: ''\n",
            encoding="utf-8",
        )
        log("警告：缺少 local.yaml.preset，已生成空配置，请手工填写数据库信息")


# --------------------------------------------------------------------------- #
# update application
# --------------------------------------------------------------------------- #

def read_manifest(app_dir: Path) -> dict:
    path = app_dir / "BUILD.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def read_pending() -> dict:
    if not PENDING_FILE.is_file():
        return {}
    try:
        return json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def apply_staged_update() -> bool:
    """Swap app/ for the staged version. Returns True when something changed.

    Order matters: every staged file is hash-verified *before* a single byte of
    app/ is touched, so a corrupt download can never leave a half-updated tree.
    """
    pending = read_pending()
    version = str(pending.get("version") or "").strip()
    staging_root = STAGING_DIR / version if version else None
    if not staging_root or not (staging_root / "app" / "BUILD.json").is_file():
        log("apply.flag 存在，但暂存目录无效，已忽略（version=%r）" % version)
        cleanup_update_flags()
        return False

    new_manifest = read_manifest(staging_root / "app")
    old_manifest = read_manifest(APP_DIR)
    new_files = {item["path"]: item for item in new_manifest.get("files", [])}
    preserved = set(new_manifest.get("preserved", [])) | set(old_manifest.get("preserved", []))
    if not new_files:
        log("暂存清单为空，放弃更新")
        cleanup_update_flags()
        return False

    log("开始应用 v%s（%d 个文件）" % (version, len(new_files)))

    for rel, item in new_files.items():
        source = staging_root / "app" / rel
        if not source.is_file():
            log("暂存文件缺失，放弃更新：%s" % rel)
            cleanup_update_flags()
            return False
        actual = sha256_file(source)
        if actual != item.get("sha256"):
            log("校验失败，放弃更新：%s（期望 %s 实际 %s）"
                % (rel, item.get("sha256"), actual))
            cleanup_update_flags()
            return False
    log("  全部暂存文件校验通过")

    written = 0
    for rel, item in new_files.items():
        target = APP_DIR / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staging_root / "app" / rel, target)
        written += 1

    old_paths = {item["path"] for item in old_manifest.get("files", [])}
    preserved_prefixes = tuple(prefix + "/" for prefix in preserved)
    removed = 0
    for rel in sorted(old_paths - set(new_files)):
        if rel in preserved or rel.startswith(preserved_prefixes):
            continue
        target = APP_DIR / rel
        if target.is_file():
            try:
                target.unlink()
                removed += 1
            except OSError as exc:
                log("  旧文件删除失败（忽略）：%s %s" % (rel, exc))

    shutil.copy2(staging_root / "app" / "BUILD.json", APP_DIR / "BUILD.json")
    version_file = staging_root / "app" / "VERSION"
    if version_file.is_file():
        shutil.copy2(version_file, APP_DIR / "VERSION")

    log("  v%s 应用完成：写入 %d 个，清理 %d 个旧文件" % (version, written, removed))
    cleanup_update_flags()
    try:
        shutil.rmtree(staging_root, ignore_errors=True)
    except OSError:
        pass
    return True


def cleanup_update_flags() -> None:
    for flag in (APPLY_FLAG, RESTART_FLAG, PENDING_FILE):
        try:
            if flag.exists():
                flag.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# server supervision
# --------------------------------------------------------------------------- #

def watch_for_restart(server) -> None:
    """The API asks for a restart by dropping a flag file we poll for."""
    while True:
        time.sleep(2)
        if RESTART_FLAG.exists() or APPLY_FLAG.exists():
            log("收到重启请求，正在停止服务…")
            server.should_exit = True
            return


def open_browser_when_ready(port: int, timeout: float = 90.0) -> None:
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    url = "http://127.0.0.1:%d/health" % port
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.time() < deadline:
        try:
            with opener.open(url, timeout=3) as response:
                if response.status == 200:
                    webbrowser.open("http://127.0.0.1:%d/" % port)
                    return
        except (urllib.error.URLError, OSError):
            time.sleep(1.5)
    log("健康检查超时，未自动打开浏览器；请手动访问 http://127.0.0.1:%d/" % port)


def run_server(settings: dict):
    """Run uvicorn to completion and hand back the server object.

    The caller inspects ``server.started``: uvicorn swallows a failed lifespan
    (bad database credentials, short auth_secret) and just returns, so without
    that check a misconfigured install looks like a clean shutdown.
    """
    import uvicorn

    port = int(settings.get("port") or 8987)
    os.environ["SUPERCLAW_API_PORT"] = str(port)
    os.environ["SUPERCLAW_EXECUTION_MODE"] = str(settings.get("execution_mode") or "api")
    os.environ.setdefault("SUPERCLAW_DATA_DIR", str(DATA_DIR))
    os.environ.setdefault("SUPERCLAW_SCREENSHOT_ROOT", str(DATA_DIR / "screenshots"))

    log("服务启动中 → http://127.0.0.1:%d/  局域网 http://%s:%d/"
        % (port, local_ip(), port))
    log("执行模式 %s；数据目录 %s" % (os.environ["SUPERCLAW_EXECUTION_MODE"], DATA_DIR))

    config = uvicorn.Config(
        "api.main:app", host="0.0.0.0", port=port, reload=False, log_level="info",
    )
    server = uvicorn.Server(config)
    threading.Thread(target=watch_for_restart, args=(server,), daemon=True).start()
    if settings.get("open_browser", True):
        threading.Thread(target=open_browser_when_ready, args=(port,), daemon=True).start()
    server.run()
    return server


def explain_startup_failure(settings: dict) -> None:
    port = int(settings.get("port") or 8987)
    log("服务未能启动。按顺序检查：")
    log("  1. app/config/local.yaml 里的数据库 host / 账号 / 口令是否正确")
    log("  2. 同文件里 security.auth_secret 是否至少有 32 个字符")
    log("  3. 端口 %d 是否被别的程序占用（data/instance.json 里可改）" % port)
    log("  4. 上面的报错堆栈——最后一行通常就是根因")


def main() -> int:
    sys.path.insert(0, str(APP_DIR / "src"))
    sys.path.insert(0, str(APP_DIR))
    sys.path = [p for p in sys.path if "hermes" not in p.lower()]

    if not (APP_DIR / "src" / "api" / "main.py").is_file():
        log("找不到 app/src/api/main.py —— 安装目录不完整，请重新安装")
        return 2

    if not acquire_single_instance():
        log("已有另一个 SuperClaw 实例在运行，本次启动退出")
        print("", flush=True)
        print("  SuperClaw 已经在运行中，不需要重复启动。", flush=True)
        print("  如果要重启，请先关闭原来那个服务窗口。", flush=True)
        return 3

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPDATES_DIR.mkdir(parents=True, exist_ok=True)

    log("=" * 62)
    log("SuperClaw 启动（安装目录 %s）" % ROOT)

    while True:
        if APPLY_FLAG.exists():
            if apply_staged_update():
                if supervised_by_shell():
                    log("更新已应用，交给启动脚本用新版本重新拉起…")
                    return RELAUNCH_EXIT_CODE
                exec_self()  # returns only when the handover was impossible
        cleanup_restart_flag()
        materialize_local_config()
        settings = load_instance()
        try:
            server = run_server(settings)
        except KeyboardInterrupt:
            log("收到 Ctrl+C，退出")
            return 0
        restarting = RESTART_FLAG.exists() or APPLY_FLAG.exists()
        if not getattr(server, "started", False) and not restarting:
            explain_startup_failure(settings)
            return 4
        if not restarting:
            log("服务已停止，退出启动器")
            return 0
        cleanup_restart_flag()
        log("准备应用更新后重启…")
        time.sleep(1)


def cleanup_restart_flag() -> None:
    try:
        if RESTART_FLAG.exists():
            RESTART_FLAG.unlink()
    except OSError:
        pass


RELAUNCH_EXIT_CODE = 7


def supervised_by_shell() -> bool:
    """Is start_superclaw.bat looping above us?

    os.execv hands the process over, but cmd.exe sees the *original* process
    exit and therefore believes the script finished: the window prints
    "Service stopped (exit code 0)" while the new process is busy serving. The
    stub therefore sets this flag, and the launcher exits instead, letting the
    .bat re-run it as a normal child — accurate messages, and the console still
    owns the service so closing the window stops it.
    """
    return os.environ.get("SUPERCLAW_SUPERVISOR", "").strip().lower() == "bat"


def exec_self() -> None:
    """Replace this process so the freshly written app/ is actually imported.

    Looping uvicorn in-process is NOT enough after an update: ``sys.modules``
    still holds the previous version's modules, so the service would keep
    running the old code — while reporting the *new* version number, because
    that is read from disk. It looked fixed until someone closed the window and
    started it again.

    Returns only when the handover was impossible, so the caller can fall back
    to restarting in-process (stale code, working service) rather than leaving
    the user with nothing.
    """
    log("更新已应用，重新启动进程以加载新代码…")
    release_single_instance()
    args = [sys.executable, str(LAUNCHER_PATH)] + sys.argv[1:]
    try:
        os.execv(sys.executable, args)
    except OSError as exc:
        log("进程替换失败（%s）——本次更新要等下次重启才完全生效" % exc)
        acquire_single_instance()


if __name__ == "__main__":
    sys.exit(main())
