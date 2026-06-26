"""
SuperClaw RPA - 抖音平台适配器

基于 Playwright 的抖音网页版自动化适配器。
集成反检测、行为模拟、验证码检测。
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, Dict, Optional

from rpa.adapters.base import (
    AdapterResult,
    AdapterStatus,
    BaseAdapter,
    ContentItem,
)
from rpa.adapters.douyin_config import DouyinConfig
from rpa.anti_detect.behavior import BehaviorSimulator
from rpa.anti_detect.stealth import StealthMiddleware

logger = logging.getLogger(__name__)


class DouyinAdapter(BaseAdapter):
    """抖音平台适配器"""

    platform = "douyin"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.douyin_config = DouyinConfig(**(config or {}))
        self._behavior = BehaviorSimulator()
        self._stealth = StealthMiddleware()
        self._logged_in = False

    async def setup(self, context=None):
        """初始化，注入反检测脚本"""
        await super().setup(context)
        if self._context and self.douyin_config.anti_detect:
            await self._stealth.apply(self._context)
            self.logger.info("反检测脚本已注入")

    # ---- 登录 ----

    async def login(self, credentials: Dict[str, str]) -> AdapterResult:
        """登录抖音"""
        t0 = time.monotonic()
        try:
            await self.page.goto(
                self.douyin_config.login_url,
                wait_until="domcontentloaded",
            )
            await self._random_delay("interval_page_load")

            # 检查是否已登录
            if await self.check_login():
                self._logged_in = True
                return AdapterResult(
                    status=AdapterStatus.SUCCESS,
                    data={"logged_in": True, "method": "cookie"},
                    latency_ms=(time.monotonic() - t0) * 1000,
                )

            # 需要手动登录（抖音网页版验证码复杂，建议 cookie 登录）
            self.logger.warning("需要登录，请在浏览器中手动完成登录")
            # 等待用户手动登录
            for _ in range(self.douyin_config.captcha_wait_seconds // 5):
                await asyncio.sleep(5)
                if await self.check_login():
                    self._logged_in = True
                    return AdapterResult(
                        status=AdapterStatus.SUCCESS,
                        data={"logged_in": True, "method": "manual"},
                        latency_ms=(time.monotonic() - t0) * 1000,
                    )

            return AdapterResult(
                status=AdapterStatus.FAILED,
                error="登录超时",
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        except Exception as e:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error=str(e),
                latency_ms=(time.monotonic() - t0) * 1000,
            )

    async def check_login(self) -> bool:
        """检查是否已登录"""
        try:
            # 查找用户头像或登录按钮
            login_btn = await self.page.query_selector(
                self.douyin_config.selectors["login_check"]
            )
            if login_btn:
                text = await login_btn.inner_text()
                if "登录" in text:
                    return False
            return True
        except Exception:
            return False

    # ---- 搜索 ----

    async def search_content(self, keyword: str, count: int = 10) -> AdapterResult:
        """搜索抖音视频"""
        t0 = time.monotonic()
        try:
            url = f"{self.douyin_config.search_url}/{keyword}?type=video"
            await self.page.goto(url, wait_until="domcontentloaded")
            await self._random_delay("interval_page_load")

            # 检查页面状态
            status = await self._check_page_status()
            if status:
                return AdapterResult(
                    status=status,
                    error=f"页面状态异常: {status.value}",
                    latency_ms=(time.monotonic() - t0) * 1000,
                )

            # 滚动加载更多
            for _ in range(max(1, count // 5)):
                await self.page.evaluate("window.scrollBy(0, 800)")
                await asyncio.sleep(random.uniform(0.8, 1.5))

            # 提取视频卡片
            cards = await self.page.query_selector_all(
                self.douyin_config.selectors["video_card"]
            )
            results = []
            for card in cards[:count]:
                try:
                    title_el = await card.query_selector(
                        self.douyin_config.selectors["video_title"]
                    )
                    title = await title_el.inner_text() if title_el else ""

                    link_el = await card.query_selector(
                        self.douyin_config.selectors["video_link"]
                    )
                    href = await link_el.get_attribute("href") if link_el else ""
                    full_url = href if href.startswith("http") else f"{self.douyin_config.base_url}{href}"

                    results.append(ContentItem(
                        content_id=href.split("/")[-1] if href else "",
                        title=title.strip(),
                        url=full_url,
                        platform="douyin",
                    ).model_dump())
                except Exception:
                    continue

            return AdapterResult(
                status=AdapterStatus.SUCCESS,
                data={"results": results, "count": len(results)},
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        except Exception as e:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error=str(e),
                latency_ms=(time.monotonic() - t0) * 1000,
            )

    # ---- 评论 ----

    async def post_comment(self, target_url: str, content: str) -> AdapterResult:
        """发布评论"""
        t0 = time.monotonic()
        try:
            await self.page.goto(target_url, wait_until="domcontentloaded")
            await self._random_delay("interval_page_load")

            # 检查页面状态
            status = await self._check_page_status()
            if status:
                return AdapterResult(status=status, error=f"页面状态异常: {status.value}")

            # 查找评论输入框
            input_el = await self.page.query_selector(
                self.douyin_config.selectors["comment_input"]
            )
            if not input_el:
                return AdapterResult(
                    status=AdapterStatus.FAILED,
                    error="未找到评论输入框",
                    latency_ms=(time.monotonic() - t0) * 1000,
                )

            # 点击输入框
            await input_el.click()
            await asyncio.sleep(random.uniform(0.3, 0.8))

            # 模拟人类打字
            await self._behavior.human_like_type(
                self.page,
                self.douyin_config.selectors["comment_input"],
                content[:self.douyin_config.max_comment_length],
            )
            await self._random_delay("interval_between_actions")

            # 点击提交
            submit_btn = await self.page.query_selector(
                self.douyin_config.selectors["comment_submit"]
            )
            if submit_btn:
                # 模拟鼠标移动到按钮
                box = await submit_btn.bounding_box()
                if box:
                    await self._behavior.human_like_mouse_move(
                        self.page,
                        (random.uniform(100, 400), random.uniform(100, 400)),
                        (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2),
                    )
                await submit_btn.click()
                await asyncio.sleep(random.uniform(1.0, 2.0))

                # 检查结果
                status = await self._check_page_status()
                if status:
                    return AdapterResult(status=status, error=f"评论失败: {status.value}")

                return AdapterResult(
                    status=AdapterStatus.SUCCESS,
                    data={"comment": content, "url": target_url},
                    latency_ms=(time.monotonic() - t0) * 1000,
                )

            return AdapterResult(
                status=AdapterStatus.FAILED,
                error="未找到提交按钮",
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        except Exception as e:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error=str(e),
                latency_ms=(time.monotonic() - t0) * 1000,
            )

    # ---- 点赞 ----

    async def like_content(self, target_url: str) -> AdapterResult:
        """点赞视频"""
        t0 = time.monotonic()
        try:
            if self.page.url != target_url:
                await self.page.goto(target_url, wait_until="domcontentloaded")
                await self._random_delay("interval_page_load")

            status = await self._check_page_status()
            if status:
                return AdapterResult(status=status, error=f"页面状态异常: {status.value}")

            like_btn = await self.page.query_selector(
                self.douyin_config.selectors["like_button"]
            )
            if like_btn:
                await like_btn.click()
                await self._random_delay("interval_between_likes")
                return AdapterResult(
                    status=AdapterStatus.SUCCESS,
                    data={"liked": True, "url": target_url},
                    latency_ms=(time.monotonic() - t0) * 1000,
                )

            return AdapterResult(
                status=AdapterStatus.FAILED,
                error="未找到点赞按钮",
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        except Exception as e:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error=str(e),
                latency_ms=(time.monotonic() - t0) * 1000,
            )

    # ---- 关注 ----

    async def follow_user(self, user_url: str) -> AdapterResult:
        """关注用户"""
        t0 = time.monotonic()
        try:
            await self.page.goto(user_url, wait_until="domcontentloaded")
            await self._random_delay("interval_page_load")

            status = await self._check_page_status()
            if status:
                return AdapterResult(status=status, error=f"页面状态异常: {status.value}")

            follow_btn = await self.page.query_selector(
                self.douyin_config.selectors["follow_button"]
            )
            if follow_btn:
                text = await follow_btn.inner_text()
                if "已关注" in text or "互相关注" in text:
                    return AdapterResult(
                        status=AdapterStatus.SUCCESS,
                        data={"already_followed": True},
                        latency_ms=(time.monotonic() - t0) * 1000,
                    )

                await follow_btn.click()
                await self._random_delay("interval_between_actions")
                return AdapterResult(
                    status=AdapterStatus.SUCCESS,
                    data={"followed": True, "url": user_url},
                    latency_ms=(time.monotonic() - t0) * 1000,
                )

            return AdapterResult(
                status=AdapterStatus.FAILED,
                error="未找到关注按钮",
                latency_ms=(time.monotonic() - t0) * 1000,
            )

        except Exception as e:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error=str(e),
                latency_ms=(time.monotonic() - t0) * 1000,
            )

    # ---- 工具方法 ----

    async def _random_delay(self, config_key: str):
        """根据配置随机延迟"""
        delay_range = getattr(self.douyin_config, config_key, [1.0, 2.0])
        delay = random.uniform(delay_range[0], delay_range[1])
        await asyncio.sleep(delay)

    def get_random_comment(self) -> str:
        """从模板中随机获取评论"""
        return random.choice(self.douyin_config.comment_templates)
