"""Merge machine-local database and MuMu settings into config/local.yaml."""

from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path
from typing import Any, Dict

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_CONFIG = PROJECT_ROOT / "config" / "local.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-host", required=True)
    parser.add_argument("--db-port", required=True, type=int)
    parser.add_argument("--db-name", required=True)
    parser.add_argument("--db-user", required=True)
    parser.add_argument("--db-password", default="")
    parser.add_argument("--mumu-root", default="")
    parser.add_argument("--enable-auth", action="store_true")
    return parser.parse_args()


def load_local_config() -> Dict[str, Any]:
    if not LOCAL_CONFIG.exists():
        return {}
    with LOCAL_CONFIG.open("r", encoding="utf-8") as stream:
        value = yaml.safe_load(stream) or {}
    if not isinstance(value, dict):
        raise ValueError("config/local.yaml must contain a YAML mapping")
    return value


def main() -> int:
    args = parse_args()
    db_password = args.db_password or os.environ.get("SUPERCLAW_SETUP_DB_PASSWORD", "")
    if not db_password:
        raise ValueError("database password is required")
    config = load_local_config()
    config["database"] = {
        "engine": "mysql",
        "host": args.db_host,
        "port": args.db_port,
        "name": args.db_name,
        "user": args.db_user,
        "password": db_password,
    }
    if args.mumu_root:
        config.setdefault("hongguo", {})["mumu_root"] = args.mumu_root
    if args.enable_auth:
        security = config.setdefault("security", {})
        security["auth_required"] = True
        security["auth_secret"] = (
            os.environ.get("SUPERCLAW_SETUP_AUTH_SECRET", "").strip()
            or str(security.get("auth_secret") or "").strip()
            or secrets.token_urlsafe(48)
        )

    LOCAL_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with LOCAL_CONFIG.open("w", encoding="utf-8", newline="\n") as stream:
        yaml.safe_dump(config, stream, allow_unicode=True, sort_keys=False)
    print(f"Updated machine-local configuration: {LOCAL_CONFIG}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
