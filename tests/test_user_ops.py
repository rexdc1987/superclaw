"""UserOps 测试 — 使用 mock，不依赖网络"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class MockAdapter:
    """模拟平台适配器，返回预设数据"""
    def __init__(self):
        self.search_users = AsyncMock(return_value=[
            {"user_id": "u1", "nickname": "张三", "avatar_url": "http://a.com/1.jpg",
             "signature": "我是装修工长", "follower_count": 5000, "is_verified": False},
            {"user_id": "u2", "nickname": "李四", "avatar_url": "http://a.com/2.jpg",
             "signature": "教育机构", "follower_count": 120000, "is_verified": True},
        ])
        self.get_user_profile = AsyncMock(return_value={
            "user_id": "u1", "nickname": "张三", "signature": "装修工长",
            "follower_count": 5000, "following_count": 200, "like_count": 8000,
            "ip_location": "北京", "is_business": False, "is_verified": False,
            "video_count": 30,
        })
        self.get_user_videos = AsyncMock(return_value=[
            {"video_id": "v1", "title": "装修避坑指南", "url": "http://dy.com/v/1",
             "like_count": 1200, "comment_count": 80, "publish_time": "3天前"},
            {"video_id": "v2", "title": "装修材料推荐", "url": "http://dy.com/v/2",
             "like_count": 800, "comment_count": 45, "publish_time": "1周前"},
        ])


class TestUserOps:
    def _svc(self):
        from automation.user_ops import UserOps
        return UserOps(MockAdapter())

    @pytest.mark.asyncio
    async def test_search_users(self):
        svc = self._svc()
        results = await svc.search_users("装修", count=10)
        assert len(results) == 2
        assert results[0]["user_id"] == "u1"
        assert results[0]["nickname"] == "张三"

    @pytest.mark.asyncio
    async def test_get_user_detail(self):
        svc = self._svc()
        profile = await svc.get_user_detail("http://dy.com/user/u1")
        assert profile["user_id"] == "u1"
        assert profile["follower_count"] == 5000
        assert profile["ip_location"] == "北京"

    @pytest.mark.asyncio
    async def test_get_user_recent_videos(self):
        svc = self._svc()
        videos = await svc.get_user_recent_videos("http://dy.com/user/u1")
        assert len(videos) == 2
        assert videos[0]["video_id"] == "v1"

    @pytest.mark.asyncio
    async def test_batch_search_dedup(self):
        from automation.user_ops import UserOps
        adapter = MockAdapter()
        # Same mock returns same data for both calls -> dedup removes duplicates
        adapter.search_users = AsyncMock(return_value=[
            {"user_id": "u1", "nickname": "张三"},
            {"user_id": "u3", "nickname": "王五"},
        ])
        svc = UserOps(adapter)
        results = await svc.batch_search(["装修", "家装"], count_per_keyword=5)
        assert adapter.search_users.call_count == 2
        # Dedup: same u1/u3 returned both times -> only 2 unique
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_enrich_profile(self):
        svc = self._svc()
        enriched = await svc.enrich_profile("http://dy.com/user/u1")
        assert enriched is not None
        assert enriched["user_id"] == "u1"
        assert "recent_videos" in enriched
        assert len(enriched["recent_videos"]) == 2

    @pytest.mark.asyncio
    async def test_empty_adapter_returns_empty(self):
        from automation.user_ops import UserOps
        adapter = MockAdapter()
        adapter.search_users = AsyncMock(return_value=[])
        adapter.get_user_profile = AsyncMock(return_value={})
        svc = UserOps(adapter)
        results = await svc.search_users("不存在的关键词")
        assert results == []
        profile = await svc.get_user_detail("http://bad-url")
        assert profile is None
