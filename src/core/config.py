"""Configuration loader"""
import os
import sys
import yaml

DEFAULT_CONFIG = {
    "database": {"path": "data/superclaw.db"},
    "logging": {"level": "INFO", "dir": "logs"},
    "browser": {"headless": False, "timeout": 30000},
    "risk": {
        "daily_comment_limit": 50,
        "daily_dm_limit": 20,
        "hourly_action_limit": 30,
        "min_interval_seconds": 5,
        "max_interval_seconds": 10,
        "rest_after_n_actions": 10,
        "rest_duration_min": 30,
        "rest_duration_max": 60,
        "circuit_breaker_threshold": 5,
    },
}


def _get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Config:
    def __init__(self, config_path=None):
        self._data = DEFAULT_CONFIG.copy()
        # Support env var SUPERCLAW_CONFIG as fallback
        resolved_path = config_path or os.environ.get("SUPERCLAW_CONFIG")
        if not resolved_path:
            resolved_path = os.path.join(_get_base_dir(), "config", "default.yaml")
        if resolved_path and os.path.exists(resolved_path):
            with open(resolved_path, "r", encoding="utf-8") as f:
                user_cfg = yaml.safe_load(f) or {}
                self._deep_merge(self._data, user_cfg)

    def _deep_merge(self, base, override):
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                self._deep_merge(base[k], v)
            else:
                base[k] = v

    def get(self, key, default=None):
        keys = key.split(".")
        val = self._data
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k, default)
            else:
                return default
        return val

config = Config()
