"""Fast preflight checks for Hongguo development."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]


def port_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_http(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    try:
        r = requests.get(url, timeout=timeout)
        return r.ok, f"{r.status_code}"
    except Exception as exc:
        return False, str(exc)


def main() -> int:
    checks = []

    checks.append(("frontend:3000", port_open("127.0.0.1", 3000)))
    checks.append(("api:8890", port_open("127.0.0.1", 8890)))

    ok, detail = check_http("http://127.0.0.1:8890/health")
    checks.append((f"api /health ({detail})", ok))

    ok, detail = check_http("http://127.0.0.1:3000/")
    checks.append((f"frontend / ({detail})", ok))

    ok, detail = check_http("http://127.0.0.1:8890/api/v1/hongguo/tasks/10")
    checks.append((f"hongguo task 10 ({detail})", ok))

    failed = [name for name, ok in checks if not ok]
    payload = {"ok": not failed, "checks": [{"name": n, "ok": b} for n, b in checks]}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
