"""User operations — 用户搜索、主页抓取、视频采集（ToB获客核心）"""
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class UserOps:
    """用户搜索与抓取操作封装，适配任何 BasePlatformAdapter"""

    def __init__(self, adapter):
        self.adapter = adapter

    async def search_users(self, keyword: str, count: int = 20) -> List[Dict]:
        """
        按关键词搜索用户
        返回: [{user_id, nickname, avatar_url, signature, follower_count, is_verified}]
        """
        logger.info(f"Searching users: keyword={keyword}, count={count}")
        results = await self.adapter.search_users(keyword, count)
        logger.info(f"Found {len(results)} users for '{keyword}'")
        return results

    async def get_user_detail(self, user_url: str) -> Optional[Dict]:
        """
        获取用户完整资料
        返回: {user_id, nickname, signature, follower_count, following_count,
               like_count, ip_location, is_business, is_verified, video_count}
        """
        profile = await self.adapter.get_user_profile(user_url)
        if not profile:
            logger.warning(f"Failed to fetch profile: {user_url}")
            return None
        return profile

    async def get_user_recent_videos(self, user_url: str, count: int = 10) -> List[Dict]:
        """
        获取用户最近视频
        返回: [{video_id, title, url, like_count, comment_count, publish_time}]
        """
        return await self.adapter.get_user_videos(user_url, count)

    async def batch_search(self, keywords: List[str], count_per_keyword: int = 10) -> List[Dict]:
        """
        批量关键词搜索，去重合并
        返回: 去重后的用户列表
        """
        seen = set()
        all_users = []
        for kw in keywords:
            users = await self.search_users(kw, count_per_keyword)
            for u in users:
                uid = u.get("user_id", "")
                if uid and uid not in seen:
                    seen.add(uid)
                    all_users.append(u)
        logger.info(f"Batch search: {len(all_users)} unique users from {len(keywords)} keywords")
        return all_users

    async def enrich_profile(self, user_url: str) -> Optional[Dict]:
        """
        综合抓取用户主页 + 最近视频，返回完整画像
        """
        profile = await self.get_user_detail(user_url)
        if not profile:
            return None
        videos = await self.get_user_recent_videos(user_url, count=5)
        profile["recent_videos"] = videos
        return profile
