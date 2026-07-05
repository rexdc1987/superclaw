"""
SuperClaw RPA - 小红书适配器配置
"""

from pydantic import BaseModel, Field
from typing import Dict, List


class XiaohongshuConfig(BaseModel):
    """小红书平台配置"""

    # 平台基础
    base_url: str = "https://www.xiaohongshu.com"
    login_url: str = "https://www.xiaohongshu.com"
    search_url: str = "https://www.xiaohongshu.com/search_result"

    # 操作间隔（秒）
    interval_between_actions: List[float] = Field(default_factory=lambda: [2.0, 5.0])
    interval_between_comments: List[float] = Field(default_factory=lambda: [15.0, 45.0])
    interval_between_likes: List[float] = Field(default_factory=lambda: [1.0, 3.0])
    interval_page_load: List[float] = Field(default_factory=lambda: [2.0, 4.0])

    # 评论模板
    comment_templates: List[str] = Field(default_factory=lambda: [
        "好棒！收藏了📌",
        "太实用了，感谢分享！",
        "姐妹推荐的真不错",
        "已种草！马上试试",
        "干货满满，码住！",
        "终于找到靠谱的攻略了",
    ])
    max_comment_length: int = 200

    # 笔记交互
    collect_note: bool = True  # 是否收藏笔记

    # 反检测
    anti_detect: bool = True
    headless: bool = False
    viewport_width: int = 1440
    viewport_height: int = 900

    # 错误处理
    max_retries: int = 3
    retry_delay_seconds: float = 5.0
    captcha_wait_seconds: int = 120

    # CSS 选择器
    selectors: Dict[str, str] = Field(default_factory=lambda: {
        "search_input": '#search-input, [class*="search-input"] input',
        "search_button": '[class*="search-btn"], button:has-text("搜索")',
        "note_card": '[class*="note-item"], [class*="search-result"]',
        "note_title": '[class*="title"], a span',
        "note_link": 'a[href*="/explore/"], a[href*="/discovery/"]',
        "note_image": '[class*="note-image"] img, [class*="cover"] img',
        "comment_input": '[class*="comment-input"], textarea, [contenteditable="true"]',
        "comment_submit": '[class*="submit"], button:has-text("发送")',
        "like_button": '[class*="like-btn"], [class*="like-icon"]',
        "collect_button": '[class*="collect-btn"], [class*="star-icon"]',
        "follow_button": '[class*="follow-btn"], button:has-text("关注")',
        "login_check": '[class*="login"], [class*="sign-in"]',
    })
