"""Douyin platform adapter"""
import asyncio
import logging
import re
from typing import List, Dict
from automation.platform_base import BasePlatformAdapter

logger = logging.getLogger(__name__)


class DouyinAdapter(BasePlatformAdapter):
    """Douyin adapter using Playwright"""

    def __init__(self, browser_manager):
        super().__init__(browser_manager)
        self.platform_name = "douyin"
        self.base_url = "https://www.douyin.com"

    async def login(self, account) -> bool:
        """Navigate to Douyin and check login status"""
        page = self.browser.page
        if not page:
            return False
        await page.goto(self.base_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        # Check if logged in by looking for user avatar or login button
        try:
            login_btn = await page.query_selector('[class*="login"]')
            if login_btn:
                text = await login_btn.inner_text()
                if "登录" in text:
                    return False  # Not logged in
            return True
        except Exception as e:
            logger.debug(f"Login check failed: {e}")
            return False

    async def search_keyword(self, keyword: str, video_count: int = 10) -> List[Dict]:
        """Search for videos by keyword"""
        page = self.browser.page
        if not page:
            return []
        url = f"{self.base_url}/search/{keyword}?type=video"
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        videos = []
        try:
            # Scroll to load more videos
            for _ in range(max(1, video_count // 5)):
                await page.evaluate("window.scrollBy(0, 800)")
                await asyncio.sleep(1)

            # Find video cards
            cards = await page.query_selector_all('[class*="video-card"], [class*="search-result"]')
            for card in cards[:video_count]:
                try:
                    title_el = await card.query_selector('[class*="title"], a')
                    title = await title_el.inner_text() if title_el else ""
                    link_el = await card.query_selector("a[href]")
                    href = await link_el.get_attribute("href") if link_el else ""
                    author_el = await card.query_selector('[class*="author"], [class*="nickname"]')
                    author = await author_el.inner_text() if author_el else ""
                    videos.append({
                        "video_id": href.split("/")[-1] if href else "",
                        "video_title": title.strip(),
                        "video_url": href if href.startswith("http") else f"{self.base_url}{href}",
                        "author": author.strip(),
                    })
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"Search error: {e}")
        return videos

    async def get_comments(self, video_url: str, count: int = 50) -> List[Dict]:
        """Get comments from a video page"""
        page = self.browser.page
        if not page:
            return []
        await page.goto(video_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        comments = []
        try:
            # Scroll comment section to load more
            for _ in range(max(1, count // 10)):
                await page.evaluate("window.scrollBy(0, 500)")
                await asyncio.sleep(1)

            comment_els = await page.query_selector_all('[class*="comment-item"], [class*="comment-content"]')
            for el in comment_els[:count]:
                try:
                    text_el = await el.query_selector('[class*="text"], [class*="content"]')
                    text = await text_el.inner_text() if text_el else ""
                    user_el = await el.query_selector('[class*="name"], [class*="nickname"]')
                    user = await user_el.inner_text() if user_el else ""
                    user_link = await el.query_selector("a[href]")
                    user_href = await user_link.get_attribute("href") if user_link else ""
                    comments.append({
                        "author_id": user_href.split("/")[-1] if user_href else "",
                        "author_nickname": user.strip(),
                        "content": text.strip(),
                    })
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"Comment error: {e}")
        return comments

    async def post_comment(self, video_url: str, content: str) -> bool:
        """Post a comment on a video"""
        page = self.browser.page
        if not page:
            return False
        try:
            await page.goto(video_url, wait_until="domcontentloaded")
            await asyncio.sleep(2)
            input_el = await page.query_selector('[class*="comment-input"], textarea, [contenteditable]')
            if input_el:
                await input_el.click()
                await asyncio.sleep(0.5)
                await input_el.fill(content) if input_el.evaluate("el => el.tagName") == "TEXTAREA" else await input_el.type(content)
                await asyncio.sleep(0.5)
                submit = await page.query_selector('[class*="submit"], button:has-text("发布")')
                if submit:
                    await submit.click()
                    await asyncio.sleep(2)
                    return True
            return False
        except Exception:
            return False

    async def reply_comment(self, comment_url: str, content: str) -> bool:
        """Reply to a comment"""
        page = self.browser.page
        if not page:
            return False
        try:
            reply_btn = await page.query_selector('[class*="reply-btn"]')
            if reply_btn:
                await reply_btn.click()
                await asyncio.sleep(1)
                input_el = await page.query_selector('[class*="reply-input"], textarea')
                if input_el:
                    await input_el.type(content)
                    submit = await page.query_selector('[class*="submit"]')
                    if submit:
                        await submit.click()
                        return True
            return False
        except Exception:
            return False

    async def like_comment(self, comment_url: str) -> bool:
        """Like a comment"""
        page = self.browser.page
        if not page:
            return False
        try:
            like_btn = await page.query_selector('[class*="like-btn"], [class*="digg"]')
            if like_btn:
                await like_btn.click()
                return True
            return False
        except Exception:
            return False

    async def follow_user(self, user_url: str) -> bool:
        """Follow a user"""
        page = self.browser.page
        if not page:
            return False
        try:
            await page.goto(user_url, wait_until="domcontentloaded")
            await asyncio.sleep(2)
            follow_btn = await page.query_selector('[class*="follow-btn"], button:has-text("关注")')
            if follow_btn:
                await follow_btn.click()
                return True
            return False
        except Exception:
            return False

    async def send_dm(self, user_url: str, content: str) -> bool:
        """Send a direct message"""
        page = self.browser.page
        if not page:
            return False
        try:
            await page.goto(user_url, wait_until="domcontentloaded")
            await asyncio.sleep(2)
            msg_btn = await page.query_selector('[class*="message"], button:has-text("私信")')
            if msg_btn:
                await msg_btn.click()
                await asyncio.sleep(1)
                input_el = await page.query_selector('[class*="msg-input"], textarea')
                if input_el:
                    await input_el.type(content)
                    send_btn = await page.query_selector('[class*="send"]')
                    if send_btn:
                        await send_btn.click()
                        return True
            return False
        except Exception:
            return False

    async def search_users(self, keyword: str, count: int = 20) -> List[Dict]:
        """Search for users by keyword on Douyin"""
        page = self.browser.page
        if not page:
            return []
        url = f"{self.base_url}/search/{keyword}?type=user"
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        users = []
        try:
            for _ in range(max(1, count // 5)):
                await page.evaluate("window.scrollBy(0, 800)")
                await asyncio.sleep(1)

            cards = await page.query_selector_all('[class*="user-card"], [class*="search-result-user"]')
            for card in cards[:count]:
                try:
                    name_el = await card.query_selector('[class*="name"], [class*="nickname"]')
                    nickname = await name_el.inner_text() if name_el else ""
                    link_el = await card.query_selector('a[href*="/user/"]')
                    href = await link_el.get_attribute("href") if link_el else ""
                    user_id = href.rstrip("/").split("/")[-1] if href else ""
                    avatar_el = await card.query_selector('img[src]')
                    avatar = await avatar_el.get_attribute("src") if avatar_el else ""
                    sig_el = await card.query_selector('[class*="signature"], [class*="desc"]')
                    signature = await sig_el.inner_text() if sig_el else ""
                    fans_el = await card.query_selector('[class*="follower"], [class*="fans"]')
                    fans_text = await fans_el.inner_text() if fans_el else "0"
                    fans_count = self._parse_count(fans_text)
                    verified = bool(await card.query_selector('[class*="verified"], [class*="blue"], svg'))
                    users.append({
                        "user_id": user_id,
                        "nickname": nickname.strip(),
                        "avatar_url": avatar,
                        "signature": signature.strip(),
                        "follower_count": fans_count,
                        "is_verified": verified,
                    })
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"User search error: {e}")
        return users

    async def get_user_profile(self, user_url: str) -> Dict:
        """Fetch user profile from Douyin"""
        page = self.browser.page
        if not page:
            return {}
        await page.goto(user_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        profile = {}
        try:
            name_el = await page.query_selector('[class*="nickname"], h1')
            profile["nickname"] = (await name_el.inner_text()).strip() if name_el else ""
            sig_el = await page.query_selector('[class*="signature"], [class*="desc"]')
            profile["signature"] = (await sig_el.inner_text()).strip() if sig_el else ""
            # Parse stats
            stats = await page.query_selector_all('[class*="count"], [class*="num"]')
            nums = []
            for s in stats:
                try:
                    nums.append(self._parse_count(await s.inner_text()))
                except Exception:
                    nums.append(0)
            profile["follower_count"] = nums[0] if len(nums) > 0 else 0
            profile["following_count"] = nums[1] if len(nums) > 1 else 0
            profile["like_count"] = nums[2] if len(nums) > 2 else 0
            # IP location
            ip_el = await page.query_selector('[class*="location"], [class*="ip"]')
            profile["ip_location"] = (await ip_el.inner_text()).strip() if ip_el else ""
            # Business account
            biz = await page.query_selector('[class*="business"], [class*="company"]')
            profile["is_business"] = biz is not None
            # Verified
            verified = await page.query_selector('[class*="verified"], [class*="blue"]')
            profile["is_verified"] = verified is not None
            # Video count
            vid_el = await page.query_selector('[class*="video-count"]')
            profile["video_count"] = self._parse_count(await vid_el.inner_text()) if vid_el else 0
            # User ID from URL
            profile["user_id"] = user_url.rstrip("/").split("/")[-1]
        except Exception as e:
            logger.error(f"Profile fetch error: {e}")
        return profile

    async def get_user_videos(self, user_url: str, count: int = 10) -> List[Dict]:
        """Fetch user's recent videos"""
        page = self.browser.page
        if not page:
            return []
        await page.goto(user_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        videos = []
        try:
            for _ in range(max(1, count // 5)):
                await page.evaluate("window.scrollBy(0, 600)")
                await asyncio.sleep(1)

            cards = await page.query_selector_all('[class*="video-card"], [class*="video-item"]')
            for card in cards[:count]:
                try:
                    title_el = await card.query_selector('[class*="title"]')
                    title = await title_el.inner_text() if title_el else ""
                    link_el = await card.query_selector('a[href]')
                    href = await link_el.get_attribute("href") if link_el else ""
                    vid = href.rstrip("/").split("/")[-1] if href else ""
                    like_el = await card.query_selector('[class*="like"], [class*="digg"]')
                    likes = self._parse_count(await like_el.inner_text()) if like_el else 0
                    cmt_el = await card.query_selector('[class*="comment"]')
                    comments = self._parse_count(await cmt_el.inner_text()) if cmt_el else 0
                    time_el = await card.query_selector('[class*="time"], [class*="date"]')
                    pub_time = (await time_el.inner_text()).strip() if time_el else ""
                    videos.append({
                        "video_id": vid,
                        "title": title.strip(),
                        "url": href if href.startswith("http") else f"{self.base_url}{href}",
                        "like_count": likes,
                        "comment_count": comments,
                        "publish_time": pub_time,
                    })
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"User videos error: {e}")
        return videos

    def _parse_count(self, text: str) -> int:
        """Parse count strings like '1.2万', '999', '10w' into int"""
        if not text:
            return 0
        text = text.strip().replace(" ", "")
        try:
            if "万" in text or "w" in text.lower():
                num = float(text.replace("万", "").replace("W", "").replace("w", ""))
                return int(num * 10000)
            if "亿" in text or "b" in text.lower():
                num = float(text.replace("亿", "").replace("B", "").replace("b", ""))
                return int(num * 100000000)
            return int(float(text))
        except (ValueError, TypeError):
            return 0
