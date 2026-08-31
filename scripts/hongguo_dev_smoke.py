"""Fast HTTP preflight for the current SuperClaw Windows topology."""

from __future__ import annotations

import argparse
import json
import os
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


def request_json(
    url: str,
    timeout: float = 10.0,
    headers: Dict[str, str] | None = None,
    payload: Dict[str, Any] | None = None,
) -> Tuple[bool, str, Any]:
    try:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST" if payload is not None else "GET",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
            return 200 <= response.status < 300, str(response.status), value
    except urllib.error.HTTPError as exc:
        return False, str(exc.code), {}
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

    health_ok, health_detail, health = request_json(f"{api}/health")
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
    auth_headers: Dict[str, str] = {}
    auth_ready = True
    if health.get("auth_required"):
        username = os.environ.get("SUPERCLAW_SMOKE_USERNAME", "").strip()
        password = os.environ.get("SUPERCLAW_SMOKE_PASSWORD", "")
        if username and password:
            login_ok, login_detail, login_result = request_json(
                f"{api}/api/v1/auth/login",
                payload={"username": username, "password": password},
            )
            auth_ready = login_ok and bool(login_result.get("access_token"))
            checks.append({"name": f"authenticated login ({login_detail})", "ok": auth_ready})
            if auth_ready:
                auth_headers = {"Authorization": f"Bearer {login_result['access_token']}"}

    templates_ok, templates_detail, templates = request_json(
        f"{api}/api/v1/hongguo/templates",
        headers=auth_headers,
    )
    protected_without_credentials = (
        bool(health.get("auth_required"))
        and not auth_headers
        and templates_detail == "401"
    )
    checks.append(
        {
            "name": f"templates API ({templates_detail})",
            "ok": protected_without_credentials or (
                auth_ready and templates_ok and isinstance(templates, list)
            ),
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
        devices_ok, devices_detail, devices = request_json(
            f"{api}/api/v1/hongguo/multi/devices", timeout=300, headers=auth_headers
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
