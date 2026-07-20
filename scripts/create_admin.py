"""Create the first SuperClaw administrator from environment variables."""

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from models.database import init_db  # noqa: E402
from services.user_service import UserService  # noqa: E402


def main() -> int:
    username = os.environ.get("SUPERCLAW_ADMIN_USERNAME", "admin").strip()
    password = os.environ.get("SUPERCLAW_ADMIN_PASSWORD", "")
    if len(password) < 8:
        print("SUPERCLAW_ADMIN_PASSWORD must contain at least 8 characters", file=sys.stderr)
        return 2
    init_db()
    service = UserService()
    existing = next((user for user in service.list_users() if user.username == username), None)
    if existing:
        print(f"Administrator already exists: {username}")
        return 0
    service.create_user(username, password, nickname=username, role="admin", usage_days=36500)
    print(f"Administrator created: {username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
