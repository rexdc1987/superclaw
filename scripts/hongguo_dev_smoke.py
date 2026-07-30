"""Fast HTTP preflight for the current SuperClaw Windows topology."""

from __future__ import annotations

import argparse
import json
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-port", type=int, default=8987)
    parser.add_argument("--frontend-port", type=int, default=3000)
    parser.add_argument("--require-devices", action="store_true")
    return parser.parse_args()


def port_open(port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def get_json(url: str, timeout: float = 10.0) -> Tuple[bool, str, Dict[str, Any]]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return 200 <= response.status < 300, str(response.status), payload
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return False, str(exc), {}


def main() -> int:
    args = parse_args()
    api = f"http://127.0.0.1:{args.api_port}"
    frontend = f"http://127.0.0.1:{args.frontend_port}"
    checks = [
        {"name": f"frontend:{args.frontend_port}", "ok": port_open(args.frontend_port)},
        {"name": f"api:{args.api_port}", "ok": port_open(args.api_port)},
    ]

    health_ok, health_detail, health = get_json(f"{api}/health")
    checks.append(
        {
            "name": f"api /health ({health_detail})",
            "ok": (
                health_ok
                and health.get("status") == "ok"
                and bool(health.get("database"))
                and bool(health.get("task_execution_ready"))
            ),
            "detail": health,
        }
    )
    templates_ok, templates_detail, templates = get_json(f"{api}/api/v1/hongguo/templates")
    checks.append(
        {
            "name": f"templates API ({templates_detail})",
            "ok": templates_ok and isinstance(templates, list),
        }
    )
    try:
        with urllib.request.urlopen(frontend, timeout=5) as response:
            frontend_ok = 200 <= response.status < 400
            frontend_detail = str(response.status)
    except OSError as exc:
        frontend_ok = False
        frontend_detail = str(exc)
    checks.append({"name": f"frontend / ({frontend_detail})", "ok": frontend_ok})

    if args.require_devices:
        devices_ok, devices_detail, devices = get_json(
            f"{api}/api/v1/hongguo/multi/devices", timeout=300
        )
        checks.append(
            {
                "name": f"MuMu devices ({devices_detail})",
                "ok": devices_ok and int(devices.get("online_count") or 0) > 0,
                "detail": {
                    "online_count": devices.get("online_count", 0),
                    "logged_in_count": devices.get("logged_in_count", 0),
                },
            }
        )

    failed = [item["name"] for item in checks if not item["ok"]]
    print(json.dumps({"ok": not failed, "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
