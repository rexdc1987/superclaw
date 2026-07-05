"""
SuperClaw RPA - 平台适配器基类

定义所有平台适配器必须实现的接口。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================
# 数据模型
# ============================================================

class AdapterStatus(str, Enum):
    """适配器操作状态"""
    SUCCESS = "success"
    FAILED = "failed"
    CAPTCHA = "captcha"
    RATE_LIMITED = "rate_limited"
    ACCOUNT_BANNED = "account_banned"
    LOGIN_REQUIRED = "login_required"
    TIMEOUT = "timeout"


class AdapterError(Exception):
    """适配器错误基类"""
    def __init__(self, platform: str, operation: str, message: str, status: AdapterStatus = AdapterStatus.FAILED):
        self.platform = platform
        self.operation = operation
        self.status = status
        super().__init__(f"[{platform}] {operation}: {message}")


class CaptchaDetected(AdapterError):
    """验证码检测"""
    def __init__(self, platform: str, operation: str, message: str = "检测到验证码"):
        super().__init__(platform, operation, message, AdapterStatus.CAPTCHA)


class RateLimited(AdapterError):
    """频率限制"""
    def __init__(self, platform: str, operation: str, message: str = "操作过于频繁"):
        super().__init__(platform, operation, message, AdapterStatus.RATE_LIMITED)


class AccountBanned(AdapterError):
    """账号被封禁"""
    def __init__(self, platform: str, operation: str, message: str = "账号疑似被封禁"):
        super().__init__(platform, operation, message, AdapterStatus.ACCOUNT_BANNED)


@dataclass
class AdapterResult:
    """适配器操作结果"""
    status: AdapterStatus
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    latency_ms: float = 0.0

    @property
    def success(self) -> bool:
        return self.status == AdapterStatus.SUCCESS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "data": self.data,
            "error": self.error,
            "latency_ms": self.latency_ms,
        }


class ContentItem(BaseModel):
    """通用内容模型"""
    content_id: str = ""
    title: str = ""
    url: str = ""
    platform: str = ""
    author_id: str = ""
    author_name: str = ""
    content_text: str = ""
    metrics: Dict[str, int] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UserInfo(BaseModel):
    """通用用户模型"""
    user_id: str = ""
    nickname: str = ""
    platform: str = ""
    avatar_url: str = ""
    signature: str = ""
    follower_count: int = 0
    following_count: int = 0
    is_verified: bool = False
    is_business: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CommentItem(BaseModel):
    """通用评论模型"""
    comment_id: str = ""
    content: str = ""
    platform: str = ""
    author_id: str = ""
    author_name: str = ""
    likes: int = 0
    timestamp: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ============================================================
# 适配器基类
# ============================================================

class BaseAdapter(ABC):
    """
    平台适配器抽象基类。

    所有平台适配器必须继承此类并实现抽象方法。
    适配器通过 Playwright BrowserContext 操作浏览器。

    使用示例:
        adapter = DouyinAdapter(config)
        async with adapter as adp:
            await adp.login(credentials)
            results = await adp.search_content("关键词", count=10)
    """

    platform: str = ""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self.logger = logging.getLogger(f"rpa.adapter.{self.platform}")

    # ---- 生命周期 ----

    async def setup(self, context=None):
        """
        初始化适配器。

        Args:
            context: 已有的 BrowserContext（可选，不传则自动创建）
        """
        if context:
            self._context = context
            self._page = await context.new_page()
        self.logger.info(f"{self.platform} 适配器已初始化")

    async def teardown(self):
        """清理资源"""
        if self._page:
            try:
                await self._page.close()
            except Exception:
                pass
        self._page = None
        self.logger.info(f"{self.platform} 适配器已清理")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.teardown()
        return False

    @property
    def page(self):
        """当前页面"""
        return self._page

    # ---- 抽象方法 ----

    @abstractmethod
    async def login(self, credentials: Dict[str, str]) -> AdapterResult:
        """
        登录平台。

        Args:
            credentials: 登录凭据 {"username": ..., "password": ...}
        """
        ...

    @abstractmethod
    async def check_login(self) -> bool:
        """检查当前是否已登录"""
        ...

    @abstractmethod
    async def search_content(self, keyword: str, count: int = 10) -> AdapterResult:
        """
        搜索内容。

        Args:
            keyword: 搜索关键词
            count: 期望返回数量
        """
        ...

    @abstractmethod
    async def post_comment(self, target_url: str, content: str) -> AdapterResult:
        """
        发布评论。

        Args:
            target_url: 目标内容 URL
            content: 评论内容
        """
        ...

    @abstractmethod
    async def like_content(self, target_url: str) -> AdapterResult:
        """点赞内容"""
        ...

    @abstractmethod
    async def follow_user(self, user_url: str) -> AdapterResult:
        """关注用户"""
        ...

    # ---- 可选方法（子类按需实现） ----

    async def get_comments(self, target_url: str, count: int = 20) -> AdapterResult:
        """获取评论列表"""
        return AdapterResult(status=AdapterStatus.FAILED, error="未实现")

    async def get_user_info(self, user_url: str) -> AdapterResult:
        """获取用户信息"""
        return AdapterResult(status=AdapterStatus.FAILED, error="未实现")

    async def send_dm(self, user_url: str, content: str) -> AdapterResult:
        """发送私信"""
        return AdapterResult(status=AdapterStatus.FAILED, error="未实现")

    # ---- 通用工具 ----

    def _check_captcha(self, page_text: str) -> bool:
        """检测页面是否包含验证码关键词"""
        captcha_keywords = [
            "captcha", "recaptcha", "验证码", "robot", "我不是机器人",
            "请完成验证", "安全验证", "滑动验证",
        ]
        text_lower = page_text.lower()
        return any(kw in text_lower for kw in captcha_keywords)

    def _check_rate_limit(self, page_text: str) -> bool:
        """检测是否被频率限制"""
        rate_keywords = [
            "操作过于频繁", "请稍后再试", "too many requests",
            "rate limit", "频繁", "休息一下",
        ]
        text_lower = page_text.lower()
        return any(kw in text_lower for kw in rate_keywords)

    def _check_ban(self, page_text: str) -> bool:
        """检测账号是否被封禁"""
        ban_keywords = [
            "账号被封禁", "账号异常", "违规", "banned", "suspended",
            "账号已被限制", "永久封禁",
        ]
        text_lower = page_text.lower()
        return any(kw in text_lower for kw in ban_keywords)

    async def _safe_page_text(self) -> str:
        """安全获取页面文本"""
        try:
            if self._page:
                return (await self._page.inner_text("body"))[:2000]
        except Exception:
            pass
        return ""

    async def _check_page_status(self) -> Optional[AdapterStatus]:
        """综合检查页面状态（验证码/频率限制/封禁）"""
        text = await self._safe_page_text()
        if self._check_captcha(text):
            return AdapterStatus.CAPTCHA
        if self._check_ban(text):
            return AdapterStatus.ACCOUNT_BANNED
        if self._check_rate_limit(text):
            return AdapterStatus.RATE_LIMITED
        return None
