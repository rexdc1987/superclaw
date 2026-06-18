"""Platform adapter base class"""
from abc import ABC, abstractmethod
from typing import List, Dict


class BasePlatformAdapter(ABC):
    """Abstract base for platform adapters"""

    def __init__(self, browser_manager):
        self.browser = browser_manager
        self.platform_name = ""

    @abstractmethod
    async def login(self, account) -> bool:
        pass

    @abstractmethod
    async def search_keyword(self, keyword: str, video_count: int = 10) -> List[Dict]:
        pass

    @abstractmethod
    async def get_comments(self, video_url: str, count: int = 50) -> List[Dict]:
        pass

    @abstractmethod
    async def post_comment(self, video_url: str, content: str) -> bool:
        pass

    @abstractmethod
    async def reply_comment(self, comment_url: str, content: str) -> bool:
        pass

    @abstractmethod
    async def like_comment(self, comment_url: str) -> bool:
        pass

    @abstractmethod
    async def follow_user(self, user_url: str) -> bool:
        pass

    @abstractmethod
    async def send_dm(self, user_url: str, content: str) -> bool:
        pass

    @abstractmethod
    async def search_users(self, keyword: str, count: int = 20) -> List[Dict]:
        pass

    @abstractmethod
    async def get_user_profile(self, user_url: str) -> Dict:
        pass

    @abstractmethod
    async def get_user_videos(self, user_url: str, count: int = 10) -> List[Dict]:
        pass
