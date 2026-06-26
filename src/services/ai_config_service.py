"""Global AI configuration and usage helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml

from rpa.hongguo.ai_usage import load_usage_stats


AI_MODEL_PRESETS = [
    {
        "label": "小米 MiMo v2.5",
        "provider": "openai_compatible",
        "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
        "model": "mimo-v2.5",
        "api_key_env": "XIAOMI_API_KEY",
    },
    {
        "label": "OpenAI GPT-4.1 mini",
        "provider": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
        "api_key_env": "OPENAI_API_KEY",
    },
    {
        "label": "OpenAI GPT-4o mini",
        "provider": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
    },
]


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def app_config() -> Dict[str, Any]:
    config_path = project_root() / "config" / "default.yaml"
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_app_config(cfg: Dict[str, Any]) -> None:
    config_path = project_root() / "config" / "default.yaml"
    with config_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


def ai_config(include_secret: bool = True) -> Dict[str, Any]:
    ai = dict(app_config().get("ai", {}))
    api_key_env = ai.get("api_key_env") or "OPENAI_API_KEY"
    if include_secret:
        ai["api_key"] = os.environ.get(api_key_env) or ai.get("api_key", "")
    return ai


def public_ai_settings(ai: Dict[str, Any] | None = None) -> Dict[str, Any]:
    current = dict(ai if ai is not None else app_config().get("ai", {}))
    api_key_env = current.get("api_key_env") or "OPENAI_API_KEY"
    return {
        "provider": current.get("provider", "openai_compatible"),
        "enabled": bool(current.get("enabled", False)),
        "api_key_env": api_key_env,
        "api_key_configured": bool(os.environ.get(api_key_env) or current.get("api_key")),
        "base_url": current.get("base_url", ""),
        "model": current.get("model", ""),
        "timeout": int(current.get("timeout", 30)),
        "temperature": float(current.get("temperature", 0.8)),
        "max_tokens": int(current.get("max_tokens", 512)),
        "fallback_to_local": bool(current.get("fallback_to_local", True)),
        "comment_scope": current.get("comment_scope", ""),
        "model_presets": AI_MODEL_PRESETS,
        "usage": load_usage_stats(),
    }


def update_ai_config(data: Dict[str, Any]) -> Dict[str, Any]:
    cfg = app_config()
    current = dict(cfg.get("ai", {}))
    api_key = data.pop("api_key", None)
    if api_key is not None and str(api_key).strip():
        current["api_key"] = str(api_key).strip()
    for key, value in data.items():
        current[key] = value
    cfg["ai"] = current
    save_app_config(cfg)
    return current


def hongguo_config() -> Dict[str, Any]:
    current = dict(app_config().get("hongguo", {}))
    env_addr = os.environ.get("SUPERCLAW_HONGGUO_DEVICE_ADDR", "").strip()
    device_addr = env_addr or str(current.get("device_addr") or "127.0.0.1:5555").strip()
    current["device_addr"] = device_addr
    return current


def public_hongguo_settings(current: Dict[str, Any] | None = None) -> Dict[str, Any]:
    settings = dict(current if current is not None else hongguo_config())
    return {
        "device_addr": str(settings.get("device_addr") or "127.0.0.1:5555").strip(),
        "device_addr_env": os.environ.get("SUPERCLAW_HONGGUO_DEVICE_ADDR", "").strip(),
    }


def update_hongguo_config(data: Dict[str, Any]) -> Dict[str, Any]:
    cfg = app_config()
    current = dict(cfg.get("hongguo", {}))
    for key, value in data.items():
        current[key] = value
    cfg["hongguo"] = current
    save_app_config(cfg)
    return current
