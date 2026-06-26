"""
账号数据模型

定义账号信息、凭据、健康度指标等核心数据结构。
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional


class AccountStatus(Enum):
    """账号状态"""
    ACTIVE = "active"       # 正常可用
    COOLDOWN = "cooldown"   # 冷却中（错误过多）
    DISABLED = "disabled"   # 已禁用（人工操作）
    BANNED = "banned"       # 已封禁（平台处罚）


@dataclass
class AccountCredentials:
    """账号凭据"""
    username: str = ""
    password: str = ""
    # OAuth2 tokens
    access_token: str = ""
    refresh_token: str = ""
    token_expires_at: float = 0.0
    # Cookie
    cookies: Dict[str, str] = field(default_factory=dict)
    # 扩展字段
    extra: Dict = field(default_factory=dict)


@dataclass
class AccountInfo:
    """账号信息

    核心字段：
    - account_id: 唯一标识
    - platform: 平台名称（douyin/weibo/xiaohongshu 等）
    - status: 账号状态
    - health_score: 健康度评分（0-100）

    使用统计：
    - use_count: 总使用次数
    - success_count: 成功次数
    - fail_count: 失败次数
    - consecutive_fails: 连续失败次数（触发冷却的关键指标）
    - last_used: 上次使用时间戳

    冷却机制：
    - cooldown_until: 冷却结束时间戳
    - cooldown_seconds: 默认冷却时长
    """
    account_id: str = ""
    username: str = ""
    platform: str = ""
    status: AccountStatus = AccountStatus.ACTIVE
    health_score: float = 100.0
    last_used: float = 0.0
    cooldown_until: float = 0.0
    cooldown_seconds: float = 300.0  # 默认 5 分钟
    use_count: int = 0
    success_count: int = 0
    fail_count: int = 0
    consecutive_fails: int = 0
    metadata: Dict = field(default_factory=dict)

    @property
    def is_available(self) -> bool:
        """账号是否可用"""
        if self.status in (AccountStatus.DISABLED, AccountStatus.BANNED):
            return False
        if self.status == AccountStatus.COOLDOWN:
            if time.time() >= self.cooldown_until:
                self.status = AccountStatus.ACTIVE
                return True
            return False
        return True

    @property
    def success_rate(self) -> float:
        """成功率"""
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 1.0

    @property
    def cooldown_remaining(self) -> float:
        """剩余冷却秒数（0 表示未在冷却）"""
        if self.status != AccountStatus.COOLDOWN:
            return 0.0
        return max(0.0, self.cooldown_until - time.time())

    def start_cooldown(self, seconds: Optional[float] = None) -> None:
        """进入冷却期"""
        self.status = AccountStatus.COOLDOWN
        self.cooldown_until = time.time() + (seconds or self.cooldown_seconds)

    def record_success(self) -> None:
        """记录一次成功操作"""
        self.success_count += 1
        self.use_count += 1
        self.consecutive_fails = 0
        self.last_used = time.time()
        if self.status == AccountStatus.COOLDOWN:
            self.status = AccountStatus.ACTIVE

    def record_failure(self, cooldown_seconds: Optional[float] = None) -> None:
        """记录一次失败操作，连续 3 次失败自动冷却"""
        self.fail_count += 1
        self.use_count += 1
        self.consecutive_fails += 1
        self.last_used = time.time()
        if self.consecutive_fails >= 3:
            self.start_cooldown(cooldown_seconds)

    def to_dict(self) -> Dict:
        """序列化为字典"""
        return {
            "account_id": self.account_id,
            "username": self.username,
            "platform": self.platform,
            "status": self.status.value,
            "health_score": self.health_score,
            "last_used": self.last_used,
            "cooldown_until": self.cooldown_until,
            "cooldown_seconds": self.cooldown_seconds,
            "use_count": self.use_count,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "consecutive_fails": self.consecutive_fails,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "AccountInfo":
        """从字典反序列化"""
        d = data.copy()
        d["status"] = AccountStatus(d.pop("status", "active"))
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


@dataclass
class HealthMetrics:
    """健康度指标"""
    login_success: int = 0
    login_failure: int = 0
    action_success: int = 0
    action_failure: int = 0
    captcha_triggered: int = 0
    flagged_count: int = 0
    ban_count: int = 0
    last_check: float = 0.0
    total_sessions: int = 0
    avg_session_duration: float = 0.0

    @property
    def login_rate(self) -> float:
        total = self.login_success + self.login_failure
        return self.login_success / total if total > 0 else 1.0

    @property
    def action_rate(self) -> float:
        total = self.action_success + self.action_failure
        return self.action_success / total if total > 0 else 1.0

    @property
    def captcha_rate(self) -> float:
        total = self.action_success + self.action_failure
        return self.captcha_triggered / total if total > 0 else 0.0
