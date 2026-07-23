"""Idempotent base schema for Hongguo task storage."""

from __future__ import annotations


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
)


def ensure_base_schema(conn) -> None:
    with conn.cursor() as cur:
        for statement in BASE_DDL:
            cur.execute(statement)
