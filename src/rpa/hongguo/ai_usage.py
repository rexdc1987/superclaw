"""Token usage accounting for Hongguo AI calls."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


_LOCK = threading.Lock()
_RECENT_LIMIT = 50


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _usage_path() -> Path:
    return _project_root() / "config" / "hongguo_ai_usage.json"


def _empty_stats() -> Dict[str, Any]:
    return {
        "totals": {
            "requests": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "by_model": {},
        "recent": [],
    }


def load_usage_stats() -> Dict[str, Any]:
    path = _usage_path()
    if not path.exists():
        return _empty_stats()
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _empty_stats()
    stats = _empty_stats()
    stats.update(data if isinstance(data, dict) else {})
    stats.setdefault("totals", _empty_stats()["totals"])
    stats.setdefault("by_model", {})
    stats.setdefault("recent", [])
    return stats


def save_usage_stats(stats: Dict[str, Any]) -> None:
    path = _usage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)


def reset_usage_stats() -> Dict[str, Any]:
    with _LOCK:
        stats = _empty_stats()
        save_usage_stats(stats)
        return stats


def record_usage(usage: Dict[str, Any], context: str = "") -> Dict[str, Any]:
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)
    model = str(usage.get("model") or "unknown")
    provider = str(usage.get("provider") or "openai_compatible")
    base_url = str(usage.get("base_url") or "")
    source = str(usage.get("source") or "ai")

    with _LOCK:
        stats = load_usage_stats()
        totals = stats.setdefault("totals", {})
        totals["requests"] = int(totals.get("requests") or 0) + 1
        totals["prompt_tokens"] = int(totals.get("prompt_tokens") or 0) + prompt_tokens
        totals["completion_tokens"] = int(totals.get("completion_tokens") or 0) + completion_tokens
        totals["total_tokens"] = int(totals.get("total_tokens") or 0) + total_tokens

        key = f"{provider}:{model}"
        by_model = stats.setdefault("by_model", {})
        item = by_model.setdefault(
            key,
            {
                "provider": provider,
                "model": model,
                "base_url": base_url,
                "requests": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        )
        item["base_url"] = base_url
        item["requests"] = int(item.get("requests") or 0) + 1
        item["prompt_tokens"] = int(item.get("prompt_tokens") or 0) + prompt_tokens
        item["completion_tokens"] = int(item.get("completion_tokens") or 0) + completion_tokens
        item["total_tokens"] = int(item.get("total_tokens") or 0) + total_tokens

        record = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "context": context,
            "source": source,
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }
        recent = [record] + list(stats.get("recent") or [])
        stats["recent"] = recent[:_RECENT_LIMIT]
        save_usage_stats(stats)
        return stats
