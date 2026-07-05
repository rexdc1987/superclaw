"""
账号池管理器

功能：账号增删改查、轮换策略（轮询/健康度优先/随机/最少使用）、并发控制、状态管理
"""

import asyncio
import random
import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class AccountStatus(Enum):
    """账号状态"""
    ACTIVE = "active"
    COOLDOWN = "cooldown"
    DISABLED = "disabled"
    BANNED = "banned"


@dataclass
class AccountInfo:
    """账号信息"""
    account_id: str
    username: str
    platform: str
    status: AccountStatus = AccountStatus.ACTIVE
    health_score: float = 100.0
    last_used: float = 0.0
    cooldown_until: float = 0.0
    use_count: int = 0
    success_count: int = 0
    fail_count: int = 0
    consecutive_fails: int = 0
    metadata: dict = field(default_factory=dict)

    @property
    def is_available(self) -> bool:
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
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 1.0

    def start_cooldown(self, seconds: float = 300) -> None:
        self.status = AccountStatus.COOLDOWN
        self.cooldown_until = time.time() + seconds
        logger.info(f"Account {self.account_id} cooling down {seconds}s")

    def record_success(self) -> None:
        self.success_count += 1
        self.use_count += 1
        self.consecutive_fails = 0
        self.last_used = time.time()
        if self.status == AccountStatus.COOLDOWN:
            self.status = AccountStatus.ACTIVE

    def record_failure(self, cooldown_seconds: float = 300) -> None:
        self.fail_count += 1
        self.use_count += 1
        self.consecutive_fails += 1
        self.last_used = time.time()
        if self.consecutive_fails >= 3:
            self.start_cooldown(cooldown_seconds)

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "username": self.username,
            "platform": self.platform,
            "status": self.status.value,
            "health_score": self.health_score,
            "use_count": self.use_count,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "consecutive_fails": self.consecutive_fails,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AccountInfo":
        d = data.copy()
        d["status"] = AccountStatus(d.pop("status", "active"))
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


class AccountPool:
    """账号池，支持 round_robin/health_first/random/least_used"""

    STRATEGIES = ("round_robin", "health_first", "random", "least_used")

    def __init__(self, strategy: str = "round_robin"):
        if strategy not in self.STRATEGIES:
            raise ValueError(f"Unsupported strategy: {strategy}")
        self._accounts: Dict[str, AccountInfo] = {}
        self._strategy = strategy
        self._robin_index = 0
        self._lock = asyncio.Lock()

    @property
    def size(self) -> int:
        return len(self._accounts)

    @property
    def available_count(self) -> int:
        return sum(1 for a in self._accounts.values() if a.is_available)

    def add_account(self, account: AccountInfo) -> None:
        self._accounts[account.account_id] = account
        logger.info(f"Added account {account.account_id} ({account.platform})")

    def remove_account(self, account_id: str) -> bool:
        if account_id in self._accounts:
            del self._accounts[account_id]
            return True
        return False

    def get_account(self, account_id: str) -> Optional[AccountInfo]:
        return self._accounts.get(account_id)

    def get_by_platform(self, platform: str) -> List[AccountInfo]:
        return [a for a in self._accounts.values() if a.platform == platform]

    def get_available(self, platform: str = None) -> List[AccountInfo]:
        return [
            a for a in self._accounts.values()
            if a.is_available and (platform is None or a.platform == platform)
        ]

    async def acquire(self, platform: str = None) -> Optional[AccountInfo]:
        async with self._lock:
            candidates = self.get_available(platform)
            if not candidates:
                logger.warning(f"No available accounts (platform={platform})")
                return None
            account = self._select(candidates)
            account.last_used = time.time()
            return account

    async def release(self, account_id: str, success: bool = True,
                      cooldown_seconds: float = 300) -> None:
        async with self._lock:
            account = self._accounts.get(account_id)
            if account:
                if success:
                    account.record_success()
                else:
                    account.record_failure(cooldown_seconds)

    def _select(self, candidates: List[AccountInfo]) -> AccountInfo:
        if self._strategy == "round_robin":
            idx = self._robin_index % len(candidates)
            self._robin_index += 1
            return candidates[idx]
        elif self._strategy == "health_first":
            return max(candidates, key=lambda a: a.health_score)
        elif self._strategy == "random":
            return random.choice(candidates)
        elif self._strategy == "least_used":
            return min(candidates, key=lambda a: a.use_count)
        return candidates[0]

    def export_state(self) -> List[dict]:
        return [a.to_dict() for a in self._accounts.values()]

    def import_state(self, data: List[dict]) -> int:
        count = 0
        for item in data:
            try:
                account = AccountInfo.from_dict(item)
                self._accounts[account.account_id] = account
                count += 1
            except Exception as e:
                logger.error(f"Import failed: {e}")
        return count

    def save(self, path: str = None) -> str:
        """持久化保存到 JSON 文件"""
        import json, os
        path = path or os.path.join(os.getcwd(), "accounts.json")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.export_state(), f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {self.size} accounts to {path}")
        return path

    def load(self, path: str = None) -> int:
        """从 JSON 文件加载"""
        import json, os
        path = path or os.path.join(os.getcwd(), "accounts.json")
        if not os.path.exists(path):
            return 0
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        count = self.import_state(data)
        logger.info(f"Loaded {count} accounts from {path}")
        return count

    def get_stats(self) -> dict:
        sc = {s.value: 0 for s in AccountStatus}
        for a in self._accounts.values():
            sc[a.status.value] += 1
        pc: Dict[str, int] = {}
        for a in self._accounts.values():
            pc[a.platform] = pc.get(a.platform, 0) + 1
        avg = (sum(a.health_score for a in self._accounts.values())
               / len(self._accounts) if self._accounts else 0.0)
        return {
            "total": self.size,
            "available": self.available_count,
            "strategy": self._strategy,
            "by_status": sc,
            "by_platform": pc,
            "avg_health_score": round(avg, 1),
        }
