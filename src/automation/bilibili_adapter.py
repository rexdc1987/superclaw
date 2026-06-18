"""Bilibili platform adapter"""
import asyncio
import logging
from typing import List, Dict
from automation.platform_base import BasePlatformAdapter

logger = logging.getLogger(__name__)


class BilibiliAdapter(BasePlatformAdapter):
    def __init__(self, browser_manager):
        super().__init__(browser_manager)
        self.platform_name = "bilibili"
        self.base_url = "https://search.bilibili.com"

    async def login(self, account) -> bool:
        page = self.browser.page
        if not page: return False
        await page.goto("https://www.bilibili.com", wait_until="domcontentloaded")
        await asyncio.sleep(3)
        try:
            login_btn = await page.query_selector('[class*="login"]')
            return login_btn is None
        except Exception as e:
            logger.debug(f"Login check failed: {e}")
            return False

    async def search_keyword(self, keyword: str, video_count: int = 10) -> List[Dict]:
        page = self.browser.page
        if not page: return []
        url = f"{self.base_url}/all?keyword={keyword}"
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        videos = []
        try:
            for _ in range(max(1, video_count // 5)):
                await page.evaluate("window.scrollBy(0, 800)")
                await asyncio.sleep(1)
            cards = await page.query_selector_all('[class*="video-card"], [class*="bili-video-card"]')
            for card in cards[:video_count]:
                try:
                    title_el = await card.query_selector('[class*="title"], a')
                    title = await title_el.inner_text() if title_el else ""
                    link_el = await card.query_selector("a[href]")
                    href = await link_el.get_attribute("href") if link_el else ""
                    videos.append({"video_id": href.split("/")[-1] if href else "", "video_title": title.strip(), "video_url": f"https:{href}" if href.startswith("//") else href})
                except Exception as e:
                    logger.debug(f"Error parsing video card: {e}")
                    continue
        except Exception as e:
            logger.error(f"Search error: {e}")
        return videos

    async def get_comments(self, video_url: str, count: int = 50) -> List[Dict]:
        page = self.browser.page
        if not page: return []
        await page.goto(video_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        comments = []
        try:
            for _ in range(max(1, count // 10)):
                await page.evaluate("window.scrollBy(0, 500)")
                await asyncio.sleep(1)
            els = await page.query_selector_all('[class*="comment-item"], [class*="reply-item"]')
            for el in els[:count]:
                try:
                    text_el = await el.query_selector('[class*="text"], [class*="content"]')
                    text = await text_el.inner_text() if text_el else ""
                    user_el = await el.query_selector('[class*="name"], [class*="user"]')
                    user = await user_el.inner_text() if user_el else ""
                    comments.append({"author_id": "", "author_nickname": user.strip(), "content": text.strip()})
                except Exception as e:
                    logger.debug(f"Error parsing comment card: {e}")
                    continue
        except Exception as e:
            logger.error(f"Comment error: {e}")
        return comments

    async def post_comment(self, video_url: str, content: str) -> bool:
        page = self.browser.page
        if not page: return False
        try:
            await page.goto(video_url, wait_until="domcontentloaded")
            await asyncio.sleep(2)
            inp = await page.query_selector('[class*="comment-send"], textarea, [contenteditable]')
            if inp:
                await inp.type(content)
                btn = await page.query_selector('[class*="submit"], button:has-text("发布")')
                if btn:
                    await btn.click()
                    return True
            return False
        except Exception as e:
            logger.error(f"post_comment failed: {e}")
            return False

    async def reply_comment(self, comment_url: str, content: str) -> bool:
        return False

    async def like_comment(self, comment_url: str) -> bool:
        return False

    async def follow_user(self, user_url: str) -> bool:
        page = self.browser.page
        if not page: return False
        try:
            await page.goto(user_url, wait_until="domcontentloaded")
            await asyncio.sleep(2)
            btn = await page.query_selector('[class*="follow-btn"], button:has-text("关注")')
            if btn:
                await btn.click()
                return True
            return False
        except Exception as e:
            logger.error(f"follow_user failed: {e}")
            return False

    async def send_dm(self, user_url: str, content: str) -> bool:
        return False
