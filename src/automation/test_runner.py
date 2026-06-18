"""Automation test runner"""
import asyncio
import logging
from datetime import datetime
from typing import Dict, List
from automation.browser import BrowserManager
from automation.douyin_adapter import DouyinAdapter

logger = logging.getLogger(__name__)


class AutomationTestRunner:
    """Run automation tests for platform adapters"""

    def __init__(self, headless=True):
        self.headless = headless
        self.browser = BrowserManager(headless=headless)
        self.adapter = None

    async def setup(self, platform="douyin", profile_path=None):
        """Initialize browser and adapter"""
        await self.browser.launch(profile_path)
        if platform == "douyin":
            self.adapter = DouyinAdapter(self.browser)
        else:
            raise ValueError(f"Unsupported platform: {platform}")
        logger.info(f"Automation test ready for {platform}")

    async def test_login(self, account=None) -> Dict:
        """Test login check"""
        result = {"test": "login", "passed": False, "details": ""}
        try:
            logged_in = await self.adapter.login(account)
            result["passed"] = True
            result["details"] = f"Login status: {logged_in}"
            if logged_in:
                result["status"] = "logged_in"
            else:
                result["status"] = "not_logged_in"
        except Exception as e:
            result["details"] = str(e)
        return result

    async def test_search(self, keyword="test", video_count=3) -> Dict:
        """Test keyword search"""
        result = {"test": "search", "passed": False, "details": "", "videos": []}
        try:
            videos = await self.adapter.search_keyword(keyword, video_count)
            result["passed"] = len(videos) > 0
            result["videos"] = videos
            result["details"] = f"Found {len(videos)} videos for '{keyword}'"
        except Exception as e:
            result["details"] = str(e)
        return result

    async def test_get_comments(self, video_url, count=10) -> Dict:
        """Test comment extraction"""
        result = {"test": "get_comments", "passed": False, "details": "", "comments": []}
        try:
            comments = await self.adapter.get_comments(video_url, count)
            result["passed"] = len(comments) > 0
            result["comments"] = comments
            result["details"] = f"Found {len(comments)} comments"
        except Exception as e:
            result["details"] = str(e)
        return result

    async def run_all_tests(self, keyword="test") -> List[Dict]:
        """Run all automation tests"""
        results = []
        logger.info("Starting automation test suite...")

        # Test 1: Login
        login_result = await self.test_login()
        results.append(login_result)
        logger.info(f"Login test: {login_result['details']}")

        # Test 2: Search (only if logged in)
        if login_result.get("status") == "logged_in":
            search_result = await self.test_search(keyword)
            results.append(search_result)
            logger.info(f"Search test: {search_result['details']}")

            # Test 3: Get comments (only if videos found)
            if search_result.get("videos"):
                video_url = search_result["videos"][0].get("video_url", "")
                if video_url:
                    comment_result = await self.test_get_comments(video_url)
                    results.append(comment_result)
                    logger.info(f"Comment test: {comment_result['details']}")

        return results

    async def cleanup(self):
        """Close browser"""
        await self.browser.close()
        logger.info("Automation test cleanup done")


async def run_automation_tests(headless=True, keyword="test"):
    """Main entry point for automation tests"""
    runner = AutomationTestRunner(headless=headless)
    try:
        await runner.setup(platform="douyin")
        results = await runner.run_all_tests(keyword)
        return results
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = asyncio.run(run_automation_tests(headless=True))
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"[{status}] {r['test']}: {r['details']}")
