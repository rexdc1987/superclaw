"""Token 生命周期管理器 — 存储、刷新、多账号隔离、自动续期。

使用方式:
    # 初始化
    tm = TokenManager(storage_dir="./tokens")

    # 保存 token
    tm.save("account_1", TokenInfo(
        access_token="xxx",
        refresh_token="yyy",
        expires_at=time.time() + 3600,
    ))

    # 获取 token（自动检测过期）
    token = tm.get("account_1")

    # 自动刷新
    await tm.refresh("account_1", token_url="https://api.example.com/oauth/token")

    # 获取 Authorization 头
    headers = tm.auth_headers("account_1")
"""
import base64

import json
import logging

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


# ============================================================
# Token 数据模型
# ============================================================

@dataclass
class TokenInfo:
    """Token 信息。"""
    access_token: str = ""
    refresh_token: str = ""
    token_type: str = "Bearer"
    expires_at: float = 0.0  # Unix 时间戳
    scope: str = ""
    created_at: float = field(default_factory=time.time)
    extra: Dict = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Token 是否已过期（提前 60 秒判断）。"""
        return time.time() > (self.expires_at - 60)

    @property
    def remaining_seconds(self) -> float:
        """剩余有效秒数。"""
        return max(0, self.expires_at - time.time())

    @property
    def authorization(self) -> str:
        """生成 Authorization 头值。"""
        return f"{self.token_type} {self.access_token}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TokenInfo":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ============================================================
# Token 持久化存储
# ============================================================

class TokenStore:
    """Token 持久化存储（JSON 文件 + 简单加密）。

    每个账号一个文件，内容为 JSON。
    可选：对 token 值做 base64 编码（非真加密，防明文泄露）。

    Attributes:
        storage_dir: 存储目录
        encode_tokens: 是否对 token 值做 base64 编码
    """

    def __init__(self, storage_dir: str = "./tokens", encode_tokens: bool = True):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.encode_tokens = encode_tokens

    def _get_path(self, account_id: str) -> Path:
        """获取账号的 token 文件路径。"""
        safe_name = account_id.replace("/", "_").replace("\\", "_")
        return self.storage_dir / f"{safe_name}.json"

    def _encode(self, value: str) -> str:
        """Base64 编码。"""
        if not self.encode_tokens or not value:
            return value
        return base64.b64encode(value.encode("utf-8")).decode("utf-8")

    def _decode(self, value: str) -> str:
        """Base64 解码。"""
        if not self.encode_tokens or not value:
            return value
        try:
            return base64.b64decode(value.encode("utf-8")).decode("utf-8")
        except Exception:
            return value

    def save(self, account_id: str, token: TokenInfo) -> None:
        """保存 token 到文件。"""
        data = token.to_dict()
        if self.encode_tokens:
            data["access_token"] = self._encode(data["access_token"])
            data["refresh_token"] = self._encode(data["refresh_token"])

        path = self._get_path(account_id)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Token 已保存: %s (expires_at=%.0f)", account_id, token.expires_at)

    def load(self, account_id: str) -> Optional[TokenInfo]:
        """从文件加载 token。"""
        path = self._get_path(account_id)
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if self.encode_tokens:
                data["access_token"] = self._decode(data["access_token"])
                data["refresh_token"] = self._decode(data["refresh_token"])
            return TokenInfo.from_dict(data)
        except Exception as e:
            logger.error("加载 token 失败: %s - %s", account_id, e)
            return None

    def delete(self, account_id: str) -> bool:
        """删除 token 文件。"""
        path = self._get_path(account_id)
        if path.exists():
            path.unlink()
            logger.info("Token 已删除: %s", account_id)
            return True
        return False

    def list_accounts(self) -> List[str]:
        """列出所有已存储的账号 ID。"""
        return [f.stem for f in self.storage_dir.glob("*.json")]

    def clear(self) -> int:
        """清除所有 token，返回删除数量。"""
        count = 0
        for f in self.storage_dir.glob("*.json"):
            f.unlink()
            count += 1
        logger.info("已清除 %d 个 token 文件", count)
        return count


# ============================================================
# Token Manager
# ============================================================

class TokenManager:
    """Token 生命周期管理器。

    功能：
    - 多账号 Token 存储与隔离
    - Token 过期检测与自动续期
    - OAuth2 refresh_token 流程
    - 请求头生成

    使用方式:
        tm = TokenManager(storage_dir="./tokens")

        # 保存
        tm.save("account_1", TokenInfo(access_token="xxx", expires_at=time.time()+3600))

        # 获取（自动检测过期）
        token = tm.get("account_1")

        # 自动刷新
        await tm.refresh("account_1", token_url="https://api.example.com/token",
                         client_id="xxx", client_secret="yyy")

        # 获取请求头
        headers = tm.auth_headers("account_1")
    """

    def __init__(
        self,
        storage_dir: str = "./tokens",
        encode_tokens: bool = True,
        auto_refresh: bool = True,
    ):
        """初始化 Token Manager。

        Args:
            storage_dir: Token 文件存储目录
            encode_tokens: 是否对 token 值做 base64 编码
            auto_refresh: 是否在 token 过期时自动尝试刷新
        """
        self._store = TokenStore(storage_dir, encode_tokens)
        self._tokens: Dict[str, TokenInfo] = {}
        self._auto_refresh = auto_refresh

        # 加载已有的 token
        for account_id in self._store.list_accounts():
            token = self._store.load(account_id)
            if token:
                self._tokens[account_id] = token

        logger.info("TokenManager 初始化完成，加载 %d 个账号", len(self._tokens))

    def save(self, account_id: str, token: TokenInfo) -> None:
        """保存 token。"""
        self._tokens[account_id] = token
        self._store.save(account_id, token)

    def get(self, account_id: str) -> Optional[TokenInfo]:
        """获取 token（从内存缓存）。"""
        return self._tokens.get(account_id)

    def get_valid(self, account_id: str) -> Optional[TokenInfo]:
        """获取有效的 token（检查过期）。

        如果 token 已过期且有 refresh_token，返回 None 提示需要刷新。
        """
        token = self._tokens.get(account_id)
        if token is None:
            return None
        if token.is_expired:
            logger.warning("Token 已过期: %s (剩余 %.0fs)", account_id, token.remaining_seconds)
            return None
        return token

    def delete(self, account_id: str) -> bool:
        """删除 token。"""
        self._tokens.pop(account_id, None)
        return self._store.delete(account_id)

    def list_accounts(self) -> List[str]:
        """列出所有账号 ID。"""
        return list(self._tokens.keys())

    def auth_headers(self, account_id: str) -> Dict[str, str]:
        """获取带 Authorization 的请求头。"""
        token = self.get(account_id)
        if not token:
            return {}
        return {"Authorization": token.authorization}

    async def refresh(
        self,
        account_id: str,
        token_url: str,
        client_id: str,
        client_secret: str,
        extra_params: Optional[dict] = None,
    ) -> Optional[TokenInfo]:
        """刷新 token（OAuth2 refresh_token 流程）。

        Args:
            account_id: 账号标识
            token_url: Token 端点 URL
            client_id: OAuth2 Client ID
            client_secret: OAuth2 Client Secret
            extra_params: 额外的请求参数

        Returns:
            新的 TokenInfo，失败返回 None
        """
        token = self._tokens.get(account_id)
        if not token or not token.refresh_token:
            logger.error("无法刷新: 账号 %s 无 refresh_token", account_id)
            return None

        data = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": token.refresh_token,
        }
        if extra_params:
            data.update(extra_params)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(token_url, data=data)
                resp.raise_for_status()
                result = resp.json()

            new_token = TokenInfo(
                access_token=result["access_token"],
                refresh_token=result.get("refresh_token", token.refresh_token),
                token_type=result.get("token_type", "Bearer"),
                expires_at=time.time() + result.get("expires_in", 3600),
                scope=result.get("scope", token.scope),
                extra=result,
            )

            self.save(account_id, new_token)
            logger.info("Token 已刷新: %s (有效期 %ds)", account_id, result.get("expires_in", 0))
            return new_token

        except Exception as e:
            logger.error("Token 刷新失败: %s - %s", account_id, e)
            return None

    async def ensure_valid(
        self,
        account_id: str,
        token_url: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ) -> Optional[TokenInfo]:
        """确保 token 有效（过期则自动刷新）。

        Args:
            account_id: 账号标识
            token_url: Token 端点（刷新时需要）
            client_id: OAuth2 Client ID
            client_secret: OAuth2 Client Secret

        Returns:
            有效的 TokenInfo，无法刷新返回 None
        """
        token = self.get_valid(account_id)
        if token:
            return token

        if not self._auto_refresh:
            return None

        if not all([token_url, client_id, client_secret]):
            logger.warning("Token 过期但缺少刷新参数，无法自动刷新: %s", account_id)
            return None

        return await self.refresh(account_id, token_url, client_id, client_secret)

    def stats(self) -> dict:
        """获取 Token 管理统计。"""
        total = len(self._tokens)
        valid = sum(1 for t in self._tokens.values() if not t.is_expired)
        expired = total - valid
        return {
            "total_accounts": total,
            "valid_tokens": valid,
            "expired_tokens": expired,
            "accounts": list(self._tokens.keys()),
        }
