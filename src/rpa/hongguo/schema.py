"""Idempotent base schema for Hongguo task storage."""

from __future__ import annotations

import logging


BASE_DDL = (
    """
    CREATE TABLE IF NOT EXISTS hongguo_comment_tasks (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        drama_name VARCHAR(200) NOT NULL,
        comment_mode VARCHAR(20) DEFAULT 'specified',
        start_episode INT DEFAULT 1,
        episode_interval INT DEFAULT 1,
        comment_interval_sec INT DEFAULT 30,
        random_comment_count INT DEFAULT 10,
        random_min_interval INT DEFAULT 20,
        random_max_interval INT DEFAULT 60,
        random_like_count INT DEFAULT 5,
        random_favorite_count INT DEFAULT 1,
        content_source VARCHAR(20) DEFAULT 'ai',
        templates_json TEXT DEFAULT NULL,
        playback_speed VARCHAR(10) DEFAULT '1.0x',
        execution_plan_json TEXT DEFAULT NULL,
        device_addr VARCHAR(80) DEFAULT NULL,
        device_label VARCHAR(200) DEFAULT NULL,
        multi_run_id VARCHAR(64) DEFAULT NULL,
        owner_user_id BIGINT NOT NULL DEFAULT 0,
        worker_id VARCHAR(120) DEFAULT NULL,
        dispatch_requested_at DATETIME DEFAULT NULL,
        control_command VARCHAR(16) DEFAULT NULL,
        status VARCHAR(20) DEFAULT 'pending',
        current_episode INT DEFAULT 0,
        total_episodes INT DEFAULT 0,
        comments_sent INT DEFAULT 0,
        comments_verified INT DEFAULT 0,
        likes_completed INT DEFAULT 0,
        favorites_completed INT DEFAULT 0,
        completion_screenshot_path VARCHAR(500) DEFAULT NULL,
        error_message TEXT DEFAULT NULL,
        started_at DATETIME DEFAULT NULL,
        completed_at DATETIME DEFAULT NULL,
        duration_seconds INT DEFAULT NULL,
        rule_updated_at DATETIME DEFAULT NULL,
        created_at DATETIME DEFAULT NULL,
        updated_at DATETIME DEFAULT NULL,
        INDEX idx_hongguo_task_owner (owner_user_id),
        INDEX idx_hongguo_task_worker (worker_id),
        INDEX idx_hongguo_task_run (multi_run_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS hongguo_comment_records (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        task_id BIGINT NOT NULL,
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
        INDEX idx_hongguo_record_task (task_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS hongguo_execution_logs (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        task_id BIGINT NOT NULL,
        level VARCHAR(10) DEFAULT 'info',
        message TEXT NOT NULL,
        episode_number INT DEFAULT NULL,
        screenshot_path VARCHAR(500) DEFAULT NULL,
        duration_seconds INT DEFAULT NULL,
        created_at DATETIME DEFAULT NULL,
        INDEX idx_hongguo_log_task (task_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS hongguo_comment_templates (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(100) DEFAULT NULL,
        content TEXT NOT NULL,
        category VARCHAR(50) DEFAULT NULL,
        is_default TINYINT(1) NOT NULL DEFAULT 0,
        use_count INT NOT NULL DEFAULT 0,
        owner_user_id BIGINT NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_hongguo_template_owner (owner_user_id),
        INDEX idx_hongguo_template_category (category),
        UNIQUE KEY uq_hongguo_template_content (content(191))
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,

    """
    CREATE TABLE IF NOT EXISTS hongguo_drama_playlist (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        drama_name VARCHAR(200) NOT NULL,
        enabled TINYINT NOT NULL DEFAULT 1,
        sort_order INT NOT NULL DEFAULT 0,
        run_count INT NOT NULL DEFAULT 0,
        last_run_at DATETIME DEFAULT NULL,
        owner_user_id BIGINT NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uq_hongguo_playlist_name (drama_name),
        INDEX idx_hongguo_playlist_enabled (enabled)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS hongguo_queue_item (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        queue_id VARCHAR(64) NOT NULL,
        seq INT NOT NULL DEFAULT 0,
        drama_name VARCHAR(200) NOT NULL,
        multi_run_id VARCHAR(64) DEFAULT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        source VARCHAR(20) NOT NULL DEFAULT 'manual',
        trigger_date DATE DEFAULT NULL,
        devices_json TEXT DEFAULT NULL,
        template_json TEXT DEFAULT NULL,
        attempt INT NOT NULL DEFAULT 0,
        infra_retries INT NOT NULL DEFAULT 0,
        retry_devices_json TEXT DEFAULT NULL,
        error_message TEXT DEFAULT NULL,
        owner_user_id BIGINT NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        started_at DATETIME DEFAULT NULL,
        finished_at DATETIME DEFAULT NULL,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uq_hongguo_queue_seq (queue_id, seq),
        INDEX idx_hongguo_queue_status (status),
        INDEX idx_hongguo_queue_run (multi_run_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS hongguo_queue_config (
        id INT NOT NULL PRIMARY KEY,
        daily_enabled TINYINT NOT NULL DEFAULT 0,
        daily_time VARCHAR(5) NOT NULL DEFAULT '09:00',
        daily_mode VARCHAR(20) NOT NULL DEFAULT 'all_random',
        devices_json TEXT DEFAULT NULL,
        template_json TEXT DEFAULT NULL,
        last_fired_date DATE DEFAULT NULL,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
    """,
)


def ensure_base_schema(conn) -> None:
    with conn.cursor() as cur:
        for statement in BASE_DDL:
            cur.execute(statement)

PLAYLIST_UNIQUE_INDEX = "uq_hongguo_playlist_name"

logger = logging.getLogger(__name__)


def ensure_queue_schema(conn) -> None:
    """Apply the playlist constraints ``create_all`` could not add.

    ``ensure_base_schema`` uses ``CREATE TABLE IF NOT EXISTS``, which is a no-op
    on a database where SQLAlchemy already created these tables - and the models
    do not carry every constraint the DDL declares. The missing UNIQUE key on
    ``drama_name`` is the one that actually corrupts data: without it
    ``INSERT ... ON DUPLICATE KEY UPDATE`` inserts a twin row, so the same drama
    sits in the 剧单 twice and the daily timer promotes it twice.

    Duplicates are collapsed to the oldest row (smallest ``id``) - the one the
    operator has been running all along.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT DATABASE()")
        row = cur.fetchone() or {}
        db_name = next(iter(row.values()), "")

        cur.execute(
            """
            SELECT COUNT(*) AS n
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA=%s
              AND TABLE_NAME='hongguo_drama_playlist'
              AND INDEX_NAME=%s
            """,
            (db_name, PLAYLIST_UNIQUE_INDEX),
        )
        if int((cur.fetchone() or {}).get("n") or 0) > 0:
            return
        if not _playlist_table_exists(cur, db_name):
            # A brand-new database gets the key from create_all / BASE_DDL.
            return

        cur.execute(
            """
            DELETE dup FROM hongguo_drama_playlist dup
            JOIN hongguo_drama_playlist keep
              ON dup.drama_name = keep.drama_name
             AND dup.id > keep.id
            """
        )
        removed = int(cur.rowcount or 0)
        cur.execute(
            "ALTER TABLE hongguo_drama_playlist "
            "ADD UNIQUE KEY %s (drama_name)" % PLAYLIST_UNIQUE_INDEX
        )
    conn.commit()
    if removed:
        logger.warning(
            "剧单已合并 %d 条重复剧名，并补上唯一键 %s", removed, PLAYLIST_UNIQUE_INDEX
        )


def _playlist_table_exists(cur, db_name: str) -> bool:
    cur.execute(
        """
        SELECT COUNT(*) AS n
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME='hongguo_drama_playlist'
        """,
        (db_name,),
    )
    return int((cur.fetchone() or {}).get("n") or 0) > 0


QUEUE_ITEM_COLUMNS = (
    ("infra_retries", "INT NOT NULL DEFAULT 0"),
    ("retry_devices_json", "TEXT DEFAULT NULL"),
)


def ensure_queue_item_columns(cur) -> list:
    """Add columns ``hongguo_queue_item`` gained after the table was created.

    ``ensure_base_schema`` runs ``CREATE TABLE IF NOT EXISTS``, which is a
    no-op on the production database - a column added to the model only ever
    reaches a fresh one. ``infra_retries`` counts the retries of a batch that
    was created but never launched (a MySQL blip while the tick was starting
    it). It exists so that kind of failure stops consuming ``attempt`` and
    dropping a drama that never played a single episode: on 2026-09-30 the
    queue lost seq2 and seq4 that way.

    Idempotent, and cheap enough for the dispatcher to call once per process.
    """
    cur.execute("SELECT DATABASE()")
    row = cur.fetchone() or {}
    db_name = next(iter(row.values()), "")
    names = [name for name, _ in QUEUE_ITEM_COLUMNS]
    placeholders = ", ".join(["%s"] * len(names))
    cur.execute(
        f"""
        SELECT COLUMN_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=%s
          AND TABLE_NAME='hongguo_queue_item'
          AND COLUMN_NAME IN ({placeholders})
        """,
        (db_name, *names),
    )
    existing = {str(r.get("COLUMN_NAME")) for r in (cur.fetchall() or [])}
    added = []
    for name, ddl in QUEUE_ITEM_COLUMNS:
        if name in existing:
            continue
        cur.execute(f"ALTER TABLE hongguo_queue_item ADD COLUMN {name} {ddl}")
        added.append(name)
    return added
