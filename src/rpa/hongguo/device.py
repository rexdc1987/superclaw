"""Device helpers for Hongguo mobile automation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Tuple


DEFAULT_ADDR = os.environ.get("SUPERCLAW_HONGGUO_DEVICE_ADDR", "127.0.0.1:5555")
FALLBACK_ADDRS = ("127.0.0.1:5555", "127.0.0.1:7555", "emulator-5554")


def _load_u2():
    try:
        import uiautomator2 as u2
    except ImportError as exc:
        raise RuntimeError("uiautomator2 is not installed") from exc
    return u2


def _discover_addrs() -> list[str]:
    try:
        import adbutils
    except ImportError:
        return []
    try:
        client = adbutils.AdbClient()
        return [device.serial for device in client.device_list() if getattr(device, "serial", None)]
    except Exception:
        return []


def discover_addrs() -> list[str]:
    candidates = []
    for addr in (os.environ.get("SUPERCLAW_HONGGUO_DEVICE_ADDR", ""), *_discover_addrs(), *FALLBACK_ADDRS):
        if addr and addr not in candidates:
            candidates.append(addr)
    return candidates


def connect_exact(addr: str) -> Any:
    """Connect to one specific uiautomator2 device without fallback."""
    os.environ.pop("PYTHONPATH", None)
    u2 = _load_u2()
    d = u2.connect(addr)
    _ = d.info
    return d

def connect(addr: str = DEFAULT_ADDR) -> Any:
    """Connect to a uiautomator2 device."""
    os.environ.pop("PYTHONPATH", None)
    u2 = _load_u2()
    candidates = []
    if addr:
        candidates.append(addr)
    for candidate in discover_addrs():
        if candidate not in candidates:
            candidates.append(candidate)
    last_error: Exception | None = None
    for candidate in candidates or [addr]:
        try:
            d = u2.connect(candidate)
            _ = d.info
            return d
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Unable to connect to device {addr}") from last_error


def check_connection(addr: str = DEFAULT_ADDR) -> bool:
    """Return whether the emulator can be reached."""
    try:
        d = connect(addr)
        _ = d.info
        return True
    except Exception:
        return False


def get_screen_size(device: Any) -> Tuple[int, int]:
    """Return the current screen size as (width, height)."""
    return tuple(device.window_size())


def screenshot(device: Any, path: str) -> str:
    """Capture a screenshot and return the normalized path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    device.screenshot(str(target))
    return str(target).replace("\\", "/")
