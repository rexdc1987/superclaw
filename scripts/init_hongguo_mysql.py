"""Create Hongguo comment MySQL tables and seed default templates."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import pymysql
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_TEMPLATES = [
    ("这剧情太上头了，忍不住继续追下去", "通用"),
    ("女主这波反击真解气，期待后面发展", "逆袭"),
    ("男主终于开窍了，这段甜度有点超标", "甜宠"),
    ("反转来得太突然了，编剧是真的会写", "通用"),
    ("这个角色越看越带感，下一集快安排上", "通用"),
]


def load_db_config() -> Dict[str, Any]:
    config_path = PROJECT_ROOT / "config" / "default.yaml"
    cfg: Dict[str, Any] = {}
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    db = cfg.get("database", {})
    return {
        "host": db.get("host", "localhost"),
        "port": int(db.get("port", 3308)),
        "database": db.get("name", "superclaw"),
        "user": db.get("user", "superclaw"),
        "password": os.environ.get("SUPERCLAW_DB_PASSWORD") or db.get("password", ""),
        "charset": "utf8mb4",
        "autocommit": False,
    }


DDL = [
    """
    CREATE TABLE IF NOT EXISTS hongguo_comment_tasks (
        id INT NOT NULL AUTO_INCREMENT,
        drama_name VARCHAR(200) NOT NULL,
        comment_mode VARCHAR(20) DEFAULT NULL,
        start_episode INT DEFAULT NULL,
        episode_interval INT DEFAULT NULL,
        comment_interval_sec INT DEFAULT NULL,
        random_comment_count INT DEFAULT NULL,
        random_min_interval INT DEFAULT NULL,
        random_max_interval INT DEFAULT NULL,
        content_source VARCHAR(20) DEFAULT NULL,
        templates_json TEXT DEFAULT NULL,
        playback_speed VARCHAR(10) DEFAULT '1.0x',
        execution_plan_json TEXT DEFAULT NULL,
        status VARCHAR(20) DEFAULT NULL,
        current_episode INT DEFAULT NULL,
        total_episodes INT DEFAULT NULL,
        comments_sent INT DEFAULT NULL,
        comments_verified INT DEFAULT NULL,
        error_message TEXT DEFAULT NULL,
        started_at DATETIME DEFAULT NULL,
        completed_at DATETIME DEFAULT NULL,
        duration_seconds INT DEFAULT NULL,
        created_at DATETIME DEFAULT NULL,
        updated_at DATETIME DEFAULT NULL,
        PRIMARY KEY (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS hongguo_comment_records (
        id INT NOT NULL AUTO_INCREMENT,
        task_id INT NOT NULL,
        episode_number INT NOT NULL,
        episode_title VARCHAR(200) DEFAULT NULL,
        comment_text TEXT NOT NULL,
        generated_by VARCHAR(20) DEFAULT NULL,
        status VARCHAR(20) DEFAULT NULL,
        sent_at DATETIME DEFAULT NULL,
        verified_at DATETIME DEFAULT NULL,
        screenshot_input VARCHAR(500) DEFAULT NULL,
        screenshot_sent VARCHAR(500) DEFAULT NULL,
        screenshot_verified VARCHAR(500) DEFAULT NULL,
        error_message TEXT DEFAULT NULL,
        created_at DATETIME DEFAULT NULL,
        PRIMARY KEY (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS hongguo_execution_logs (
        id INT NOT NULL AUTO_INCREMENT,
        task_id INT NOT NULL,
        level VARCHAR(10) DEFAULT NULL,
        message TEXT NOT NULL,
        screenshot_path VARCHAR(500) DEFAULT NULL,
        created_at DATETIME DEFAULT NULL,
        PRIMARY KEY (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS hongguo_comment_templates (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
        content TEXT NOT NULL,
        category VARCHAR(50) NULL,
        is_default TINYINT(1) NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (id),
        KEY idx_category (category),
        KEY idx_is_default (is_default),
        UNIQUE KEY uq_hongguo_template_content (content(191))
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
]


def main() -> None:
    conn = pymysql.connect(**load_db_config())
    try:
        with conn.cursor() as cur:
            for ddl in DDL:
                cur.execute(ddl)
            cur.executemany(
                """
                INSERT INTO hongguo_comment_templates (content, category, is_default)
                VALUES (%s, %s, 1)
                ON DUPLICATE KEY UPDATE
                    category=VALUES(category),
                    is_default=VALUES(is_default)
                """,
                DEFAULT_TEMPLATES,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("Hongguo MySQL schema initialized.")
    print(f"Default templates ensured: {len(DEFAULT_TEMPLATES)}")


if __name__ == "__main__":
    main()
