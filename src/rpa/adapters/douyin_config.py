"""
SuperClaw RPA - 抖音适配器配置
"""

from pydantic import BaseModel, Field
from typing import Dict, List


class DouyinConfig(BaseModel):
    """抖音平台配置"""

    # 平台基础
    base_url: str = "https://www.douyin.com"
    login_url: str = "https://www.douyin.com"
    search_url: str = "https://www.douyin.com/search"

    # 操作间隔（秒）—— 随机范围 [min, max]
    interval_between_actions: List[float] = Field(default_factory=lambda: [2.0, 5.0])
    interval_between_comments: List[float] = Field(default_factory=lambda: [10.0, 30.0])
    interval_between_likes: List[float] = Field(default_factory=lambda: [1.0, 3.0])
    interval_page_load: List[float] = Field(default_factory=lambda: [2.0, 4.0])

    # 评论配置
    comment_templates: List[str] = Field(default_factory=lambda: [
        "太棒了！🔥",
        "学到了，感谢分享！",
        "好内容，收藏了",
        "真的有用，已关注",
        "写得太好了，期待更多",
    ])
    max_comment_length: int = 100

    # 反检测配置
    anti_detect: bool = True
    headless: bool = False
    viewport_width: int = 1920
    viewport_height: int = 1080

    # 错误处理
    max_retries: int = 3
    retry_delay_seconds: float = 5.0
    captcha_wait_seconds: int = 120  # 等待手动解决验证码的时间

    # CSS 选择器
    selectors: Dict[str, str] = Field(default_factory=lambda: {
        "search_input": '[class*="search"] input, [data-e2e="searchbar-input"]',
        "search_button": '[class*="search-btn"], [data-e2e="searchbar-button"]',
        "video_card": '[class*="video-card"], [class*="search-result-card"]',
        "video_title": '[class*="title"], a',
        "video_link": 'a[href*="/video/"]',
        "comment_input": '[class*="comment-input"], textarea, [contenteditable="true"]',
        "comment_submit": '[class*="submit"], button:has-text("发布")',
        "like_button": '[class*="like-btn"], [class*="digg"], [data-e2e="like-icon"]',
        "follow_button": '[class*="follow-btn"], button:has-text("关注")',
        "login_check": '[class*="login"], [data-e2e="user-avatar"]',
    })
