"""SuperClaw 通用工具函数"""
import os
import json
import hashlib
import secrets
import string
from datetime import datetime, timezone, timedelta
from typing import Optional


def gen_short_id(length: int = 8) -> str:
    """生成短随机ID"""
    chars = string.ascii_lowercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


def format_datetime(dt: Optional[datetime], fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """格式化日期时间"""
    if not dt:
        return ""
    return dt.strftime(fmt)


def time_ago(dt: Optional[datetime]) -> str:
    """相对时间描述"""
    if not dt:
        return ""
    now = datetime.utcnow()
    diff = now - dt
    seconds = int(diff.total_seconds())
    if seconds < 60:
        return "刚刚"
    elif seconds < 3600:
        return f"{seconds // 60}分钟前"
    elif seconds < 86400:
        return f"{seconds // 3600}小时前"
    elif seconds < 604800:
        return f"{seconds // 86400}天前"
    else:
        return format_datetime(dt, "%m-%d %H:%M")


def truncate(text: str, max_len: int = 50, suffix: str = "...") -> str:
    """截断文本"""
    if not text or len(text) <= max_len:
        return text or ""
    return text[:max_len - len(suffix)] + suffix


def md5(text: str) -> str:
    """计算MD5（仅用于缓存key/去重指纹等非安全场景）"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def sha256(text: str) -> str:
    """计算SHA-256（用于需要安全性的哈希场景）"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ensure_dir(path: str):
    """确保目录存在"""
    os.makedirs(path, exist_ok=True)


def safe_json_loads(text: str, default=None):
    """安全JSON解析"""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else {}


def flatten_dict(d: dict, parent_key: str = "", sep: str = ".") -> dict:
    """展平嵌套字典"""
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def chunk_list(lst: list, size: int) -> list:
    """列表分块"""
    return [lst[i:i + size] for i in range(0, len(lst), size)]


def format_number(n: int) -> str:
    """数字格式化（千位分隔）"""
    if n >= 10000:
        return f"{n/10000:.1f}万"
    return f"{n:,}"
