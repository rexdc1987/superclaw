"""Initialize the current SuperClaw schema and seed named comment templates."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from models.database import init_db  # noqa: E402
from rpa.dashboard.routes_hongguo import _connection  # noqa: E402


DEFAULT_TEMPLATES = [
    ("通用追剧", "这剧情太上头了，忍不住继续追下去", "通用"),
    ("逆袭反击", "女主这波反击真解气，期待后面发展", "逆袭"),
    ("甜宠互动", "男主终于开窍了，这段甜度有点超标", "甜宠"),
    ("剧情反转", "反转来得太突然了，编剧是真的会写", "通用"),
    ("角色期待", "这个角色越看越带感，下一集快安排上", "通用"),
]


def main() -> int:
    init_db()
    with _connection() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO hongguo_comment_templates (
                    name, content, category, is_default, use_count, owner_user_id
                ) VALUES (%s, %s, %s, 1, 0, 0)
                ON DUPLICATE KEY UPDATE
                    name=COALESCE(NULLIF(name, ''), VALUES(name)),
                    category=VALUES(category),
                    is_default=1
                """,
                DEFAULT_TEMPLATES,
            )
    print("SuperClaw database schema is current.")
    print(f"Default named templates ensured: {len(DEFAULT_TEMPLATES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
