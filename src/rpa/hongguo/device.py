"""Device helpers for Hongguo mobile automation."""

from __future__ import annotations

import os
import queue
import json
import re
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar, Tuple


DEFAULT_ADDR = os.environ.get("SUPERCLAW_HONGGUO_DEVICE_ADDR", "127.0.0.1:5555")
FALLBACK_ADDRS = ("127.0.0.1:5555", "127.0.0.1:7555", "emulator-5554")
DEFAULT_MUMU_ROOT = Path(os.environ.get("SUPERCLAW_MUMU_ROOT", r"D:\Program Files\Netease\MuMu"))
T = TypeVar("T")


class DeviceCallTimeout(TimeoutError):
    """Raised when an emulator/ADB call does not return in time."""


def call_with_timeout(func: Callable[[], T], timeout: float, label: str = "device call") -> T:
    """Run a blocking device call with a hard wall-clock timeout.

    uiautomator2/adbutils calls can block forever when the shared ADB server
    gets wedged. Keep the worker alive by timing out the caller thread.
    """
    result: "queue.Queue[tuple[bool, Any]]" = queue.Queue(maxsize=1)

    def runner() -> None:
        try:
            result.put((True, func()), block=False)
        except Exception as exc:
            result.put((False, exc), block=False)

    thread = threading.Thread(target=runner, name=f"hongguo-{label}", daemon=True)
    thread.start()
    thread.join(max(0.1, float(timeout)))
    if thread.is_alive():
        raise DeviceCallTimeout(f"{label} timed out after {timeout:.0f}s")
    ok, value = result.get_nowait()
    if ok:
        return value
    raise value


def _load_u2():
    try:
        import uiautomator2 as u2
    except ImportError as exc:
        raise RuntimeError("uiautomator2 is not installed") from exc
    return u2


def _discover_addrs() -> list[str]:
    def list_devices() -> list[str]:
        import adbutils

        client = adbutils.AdbClient()
        return [device.serial for device in client.device_list() if getattr(device, "serial", None)]

    try:
        return call_with_timeout(list_devices, 5, "adb device list")
    except Exception:
        return []


def discover_online_addrs() -> list[str]:
    """Return devices currently reported by ADB without fallback addresses."""
    return _discover_addrs()


def _mumu_manager_path() -> Optional[Path]:
    configured = os.environ.get("SUPERCLAW_MUMU_MANAGER")
    candidates = []
    if configured:
        candidates.append(Path(configured))
    candidates.extend(
        [
            DEFAULT_MUMU_ROOT / "nx_main" / "MuMuManager.exe",
            Path(r"D:\Program Files\Netease\MuMu\nx_main\MuMuManager.exe"),
        ]
    )
    for path in candidates:
        if path.exists():
            return path
    return None


def _mumu_adb_path() -> Optional[Path]:
    configured = os.environ.get("SUPERCLAW_ADB")
    candidates = []
    if configured:
        candidates.append(Path(configured))
    candidates.extend(
        [
            DEFAULT_MUMU_ROOT / "nx_main" / "adb.exe",
            DEFAULT_MUMU_ROOT / "nx_device" / "12.0" / "shell" / "adb.exe",
            DEFAULT_MUMU_ROOT / "nx_device" / "15.0" / "shell" / "adb.exe",
        ]
    )
    for path in candidates:
        if path.exists():
            return path
    return None


def _run_mumu_manager(args: List[str], timeout: float = 12) -> Dict[str, Any]:
    manager = _mumu_manager_path()
    if not manager:
        return {"success": False, "message": "MuMuManager.exe not found"}

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(manager), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )

    try:
        proc = call_with_timeout(run, timeout + 2, "mumu manager")
    except Exception as exc:
        return {"success": False, "message": str(exc)}
    output = (proc.stdout or "").strip()
    if not output:
        output = (proc.stderr or "").strip()
    try:
        data = json.loads(output) if output else {}
    except json.JSONDecodeError:
        data = {"raw": output}
    return {
        "success": proc.returncode == 0,
        "returncode": proc.returncode,
        "data": data,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _tcp_port_open(host: str, port: str, timeout: float = 0.8) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except Exception:
        return False


def _adb_connect_addr(addr: str, timeout: float = 5) -> Dict[str, Any]:
    adb = _mumu_adb_path()
    if not adb:
        return {"success": False, "message": "adb.exe not found"}

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(adb), "connect", addr],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )

    try:
        proc = call_with_timeout(run, timeout + 1, f"adb connect {addr}")
    except Exception as exc:
        return {"success": False, "message": str(exc)}
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    ok = proc.returncode == 0 and ("connected to" in output or "already connected" in output)
    return {"success": ok, "returncode": proc.returncode, "output": output}


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _mumu_vm_dir(index: str, android_version: str) -> Optional[Path]:
    major = str(android_version or "").split(".", 1)[0]
    if not major:
        return None
    return DEFAULT_MUMU_ROOT / "vms" / f"MuMuPlayer-{major}.0-{index}"


def _mumu_nemu_path(index: str, android_version: str) -> Optional[Path]:
    major = str(android_version or "").split(".", 1)[0]
    vm_dir = _mumu_vm_dir(index, android_version)
    if not major or not vm_dir:
        return None
    return vm_dir / f"MuMuPlayer-{major}.0-{index}.nemu"


def _mumu_configured_ports(index: str, android_version: str) -> List[str]:
    ports: List[str] = []
    vm_dir = _mumu_vm_dir(index, android_version)
    if vm_dir:
        vm_config = _read_json(vm_dir / "configs" / "vm_config.json")
        adb_port = (
            vm_config.get("vm", {})
            .get("nat", {})
            .get("port_forward", {})
            .get("adb", {})
            .get("host_port")
        )
        if adb_port:
            ports.append(str(adb_port))
        nemu_path = _mumu_nemu_path(index, android_version)
        try:
            text = nemu_path.read_text(encoding="utf-8", errors="replace") if nemu_path else ""
            for name in ("ADB_PORT_EX", "ADB_PORT"):
                match = re.search(rf'name="{name}"[^>]*hostport="(\d+)"', text)
                if match:
                    ports.append(match.group(1))
        except Exception:
            pass
    result: List[str] = []
    for port in ports:
        if port and port not in result:
            result.append(port)
    return result


def _mumu_adb_addr_from_devices(configured_ports: List[str], online_addrs: Optional[List[str]] = None) -> str:
    devices = set(online_addrs if online_addrs is not None else discover_online_addrs())
    for port in configured_ports:
        for addr in (f"127.0.0.1:{port}", f"localhost:{port}"):
            if addr in devices:
                return addr
    return ""


def _mumu_adb_addr_from_configured_ports(configured_ports: List[str]) -> Tuple[str, List[Dict[str, Any]]]:
    attempts: List[Dict[str, Any]] = []
    for port in configured_ports:
        addr = f"127.0.0.1:{port}"
        port_open = _tcp_port_open("127.0.0.1", port)
        attempt: Dict[str, Any] = {"addr": addr, "port_open": port_open}
        if port_open:
            connect_result = _adb_connect_addr(addr)
            attempt["connect"] = connect_result
            online_addrs = discover_online_addrs()
            attempt["online_after_connect"] = online_addrs
            if addr in online_addrs or f"localhost:{port}" in online_addrs:
                attempts.append(attempt)
                return addr, attempts
        attempts.append(attempt)
    return "", attempts


def _normalize_mac(value: str) -> str:
    return re.sub(r"[^0-9a-f]", "", str(value or "").lower())


def _mumu_bridge_mac(index: str, android_version: str) -> str:
    nemu_path = _mumu_nemu_path(index, android_version)
    if not nemu_path:
        return ""
    try:
        text = nemu_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    match = re.search(r'MACAddress="([0-9A-Fa-f]+)"', text)
    return _normalize_mac(match.group(1)) if match else ""


def _arp_ip_for_mac(mac: str) -> str:
    normalized = _normalize_mac(mac)
    if not normalized:
        return ""

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["arp", "-a"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )

    try:
        proc = call_with_timeout(run, 7, "arp table")
    except Exception:
        return ""
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        ip, raw_mac = parts[0], parts[1]
        if _normalize_mac(raw_mac) == normalized and re.match(r"^\d+\.\d+\.\d+\.\d+$", ip):
            return ip
    return ""


def _mumu_adb_addr_from_bridge(index: str, android_version: str) -> Tuple[str, Dict[str, Any]]:
    mac = _mumu_bridge_mac(index, android_version)
    ip = _arp_ip_for_mac(mac)
    attempt: Dict[str, Any] = {"mac": mac, "ip": ip, "addr": ""}
    if not ip:
        return "", attempt
    addr = f"{ip}:5555"
    attempt["addr"] = addr
    attempt["port_open"] = _tcp_port_open(ip, "5555")
    if not attempt["port_open"]:
        return "", attempt
    connect_result = _adb_connect_addr(addr)
    attempt["connect"] = connect_result
    online_addrs = discover_online_addrs()
    attempt["online_after_connect"] = online_addrs
    if addr in online_addrs:
        return addr, attempt
    return "", attempt


def _discover_mumu_instances_from_config(connect_adb: bool = True) -> List[Dict[str, Any]]:
    """Recover local MuMu instances when MuMuManager RPC is unavailable."""
    vm_root = DEFAULT_MUMU_ROOT / "vms"
    try:
        vm_dirs = list(vm_root.iterdir())
    except OSError:
        return []

    online_addrs = discover_online_addrs()
    instances: List[Dict[str, Any]] = []
    for vm_dir in vm_dirs:
        if not vm_dir.is_dir():
            continue
        match = re.fullmatch(r"MuMuPlayer-(\d+(?:\.\d+)?)-(\d+)", vm_dir.name)
        if not match:
            continue
        android_version, index = match.groups()
        configured_ports = _mumu_configured_ports(index, android_version)
        addr = _mumu_adb_addr_from_devices(configured_ports, online_addrs)
        port_attempts: List[Dict[str, Any]] = []
        if not addr and connect_adb and configured_ports:
            addr, port_attempts = _mumu_adb_addr_from_configured_ports(configured_ports)
            if addr:
                online_addrs = discover_online_addrs()

        extra_config = _read_json(vm_dir / "configs" / "extra_config.json")
        name = str(extra_config.get("playerName") or f"MuMu #{index}")
        port_is_open = any(bool(item.get("port_open")) for item in port_attempts)
        is_started = bool(addr or port_is_open)
        message = "ADB connected via local MuMu config" if addr else "MuMu instance is not running"
        instances.append(
            {
                "index": index,
                "name": name,
                "android_version": android_version,
                "is_process_started": is_started,
                "is_android_started": bool(addr),
                "addr": addr,
                "adb_ready": bool(addr),
                "adb_message": message,
                "configured_adb_ports": configured_ports,
                "adb_port_attempts": port_attempts,
                "bridge_attempt": {},
                "info": {
                    "index": index,
                    "name": name,
                    "android_version": android_version,
                    "is_process_started": is_started,
                    "is_android_started": bool(addr),
                    "info_source": "local_config_fallback",
                },
                "connect": {},
            }
        )
    return sorted(instances, key=lambda item: int(item["index"]))


def discover_mumu_instances(connect_adb: bool = True) -> List[Dict[str, Any]]:
    """Discover MuMu multi-player instances through MuMuManager."""
    info_result = _run_mumu_manager(["info", "--vmindex", "all"])
    data = info_result.get("data")
    if not info_result.get("success") or not isinstance(data, dict):
        return _discover_mumu_instances_from_config(connect_adb=connect_adb)

    connect_data: Dict[str, Any] = {}
    if connect_adb:
        connect_result = _run_mumu_manager(["adb", "--vmindex", "all", "--cmd", "connect"], timeout=18)
        if isinstance(connect_result.get("data"), dict):
            connect_data = connect_result["data"]

    online_addrs = discover_online_addrs()
    instances: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []
    assigned_addrs: set[str] = set()
    for index, info in sorted(data.items(), key=lambda item: int(item[0]) if str(item[0]).isdigit() else 9999):
        if not isinstance(info, dict):
            continue
        connect_info = connect_data.get(str(index), {}) if isinstance(connect_data, dict) else {}
        if not isinstance(connect_info, dict):
            connect_info = {}
        configured_ports = _mumu_configured_ports(str(index), str(info.get("android_version") or ""))
        host = str(connect_info.get("adb_host") or "").strip()
        port = str(connect_info.get("adb_port") or "").strip()
        addr = f"{host}:{port}" if host and port else ""
        if not addr:
            info_host = str(info.get("adb_host_ip") or "").strip()
            info_port = str(info.get("adb_port") or "").strip()
            if info_host and info_port:
                addr = f"{info_host}:{info_port}"
        if not addr:
            addr = _mumu_adb_addr_from_devices(configured_ports, online_addrs)
        port_attempts: List[Dict[str, Any]] = []
        if not addr and connect_adb and configured_ports:
            addr, port_attempts = _mumu_adb_addr_from_configured_ports(configured_ports)
            if addr:
                online_addrs = discover_online_addrs()
        bridge_attempt: Dict[str, Any] = {}
        if not addr and connect_adb:
            addr, bridge_attempt = _mumu_adb_addr_from_bridge(str(index), str(info.get("android_version") or ""))
            if addr:
                online_addrs = discover_online_addrs()
        ready = bool(addr and int(connect_info.get("errcode") or 0) == 0)
        if addr and not ready:
            ready = addr in online_addrs
        message = str(connect_info.get("cmd_output") or connect_info.get("errmsg") or "").strip()
        if ready and bridge_attempt.get("addr"):
            message = f"{message or 'ADB connected'}; bridge ADB matched {bridge_attempt.get('addr')}"
        if not ready and port_attempts:
            closed = [
                item.get("addr", "")
                for item in port_attempts
                if item.get("addr") and not item.get("port_open")
            ]
            if closed:
                message = f"{message or 'ADB not ready'}; configured ADB ports not listening: {', '.join(closed)}"
        if not message:
            message = "ADB 已连接" if ready else "实例已启动，ADB 未就绪"
        instances.append(
            {
                "index": str(index),
                "name": str(info.get("name") or f"MuMu #{index}"),
                "android_version": str(info.get("android_version") or ""),
                "is_process_started": bool(info.get("is_process_started")),
                "is_android_started": bool(info.get("is_android_started")),
                "addr": addr,
                "adb_ready": ready,
                "adb_message": message,
                "configured_adb_ports": configured_ports,
                "adb_port_attempts": port_attempts,
                "bridge_attempt": bridge_attempt,
                "info": info,
                "connect": connect_info,
            }
        )
        if addr:
            assigned_addrs.add(addr)
        elif bool(info.get("is_process_started")):
            unresolved.append(instances[-1])

    remaining_addrs = [
        addr
        for addr in online_addrs
        if addr not in assigned_addrs
        and re.match(r"^\d+\.\d+\.\d+\.\d+:5555$", addr)
    ]
    if len(unresolved) == len(remaining_addrs):
        for instance, addr in zip(unresolved, remaining_addrs):
            instance["addr"] = addr
            instance["adb_ready"] = True
            message = str(instance.get("adb_message") or "ADB 已连接")
            instance["adb_message"] = f"{message}；已从 ADB 在线设备兜底匹配 {addr}"
    elif len(remaining_addrs) == 1 and unresolved:
        preferred = next((item for item in unresolved if str(item.get("index")) == "0"), unresolved[0])
        addr = remaining_addrs[0]
        preferred["addr"] = addr
        preferred["adb_ready"] = True
        message = str(preferred.get("adb_message") or "ADB 已连接")
        preferred["adb_message"] = f"{message}；已将唯一在线 ADB 设备兜底匹配到 MuMu #{preferred.get('index')}：{addr}"
    return instances


def launch_mumu_app(index: str, package: str) -> Dict[str, Any]:
    """Launch an app through MuMuManager RPC when ADB is not ready."""
    return _run_mumu_manager(
        ["control", "--vmindex", str(index), "app", "launch", "--package", package],
        timeout=10,
    )


def discover_addrs() -> list[str]:
    candidates = []
    for addr in (os.environ.get("SUPERCLAW_HONGGUO_DEVICE_ADDR", ""), *_discover_addrs(), *FALLBACK_ADDRS):
        if addr and addr not in candidates:
            candidates.append(addr)
    return candidates


def connect_exact(addr: str) -> Any:
    """Connect to one specific uiautomator2 device without fallback."""
    os.environ.pop("PYTHONPATH", None)

    def do_connect() -> Any:
        u2 = _load_u2()
        return u2.connect(addr)

    return call_with_timeout(do_connect, 12, f"connect {addr}")


def connect(addr: str = DEFAULT_ADDR) -> Any:
    """Connect to a uiautomator2 device."""
    os.environ.pop("PYTHONPATH", None)
    candidates = []
    if addr:
        candidates.append(addr)
    for candidate in discover_addrs():
        if candidate not in candidates:
            candidates.append(candidate)
    last_error: Exception | None = None
    for candidate in candidates or [addr]:
        try:
            return connect_exact(candidate)
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Unable to connect to device {addr}") from last_error


def check_connection(addr: str = DEFAULT_ADDR) -> bool:
    """Return whether the emulator can be reached."""
    if addr and addr in discover_online_addrs():
        return True
    try:
        d = connect(addr)
        serial = getattr(d, "serial", None) or getattr(d, "_serial", None)
        return not addr or not serial or str(serial) == str(addr)
    except Exception:
        return False


def get_screen_size(device: Any) -> Tuple[int, int]:
    """Return the current screen size as (width, height)."""
    serial = getattr(device, "serial", None) or getattr(device, "_serial", None)
    if serial:
        try:
            def adb_screenshot_size() -> Tuple[int, int]:
                import adbutils

                image = adbutils.adb.device(serial).screenshot()
                return tuple(image.size)

            return call_with_timeout(adb_screenshot_size, 10, f"screen size {serial}")
        except Exception:
            pass
    return tuple(call_with_timeout(lambda: device.window_size(), 5, "window size"))


def screenshot(device: Any, path: str) -> str:
    """Capture a screenshot and return the normalized path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    first_error: Exception | None = None
    serial = getattr(device, "serial", None) or getattr(device, "_serial", None)
    if serial:
        try:
            def adb_screenshot() -> None:
                import adbutils

                adbutils.adb.device(serial).screenshot().save(str(target))

            call_with_timeout(adb_screenshot, 8, f"adb screenshot {serial}")
            return str(target).replace("\\", "/")
        except Exception as exc:
            first_error = exc
    try:
        call_with_timeout(lambda: device.screenshot(str(target)), 12, "uiautomator screenshot")
        return str(target).replace("\\", "/")
    except Exception as exc:
        first_error = exc

    if serial:
        try:
            def u2_reconnect_screenshot() -> None:
                d = _load_u2().connect(serial)
                time.sleep(1)
                d.screenshot(str(target))

            call_with_timeout(u2_reconnect_screenshot, 15, f"uiautomator reconnect screenshot {serial}")
            return str(target).replace("\\", "/")
        except Exception as exc:
            first_error = exc
        try:
            def adb_screenshot() -> None:
                import adbutils

                adbutils.adb.device(serial).screenshot().save(str(target))

            call_with_timeout(adb_screenshot, 8, f"adb screenshot {serial}")
            return str(target).replace("\\", "/")
        except Exception as exc:
            first_error = exc
    raise RuntimeError(f"Screenshot failed: {first_error}") from first_error
