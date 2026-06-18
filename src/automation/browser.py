"""Browser manager for Playwright automation"""
from playwright.async_api import async_playwright


class BrowserManager:
    def __init__(self, headless=False):
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def launch(self, user_data_dir=None):
        """Launch browser (alias compatible with test_runner/e2e)"""
        self.playwright = await async_playwright().start()
        if user_data_dir:
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir, headless=self.headless)
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        else:
            self.browser = await self.playwright.chromium.launch(headless=self.headless)
            self.context = await self.browser.new_context()
            self.page = await self.context.new_page()
        return self

    async def start(self):
        """Launch browser (no persistent context)"""
        return await self.launch()

    async def new_context(self, user_data_dir=None):
        """Create a new browser context"""
        if user_data_dir:
            return await self.playwright.chromium.launch_persistent_context(
                user_data_dir, headless=self.headless)
        if not self.browser:
            self.browser = await self.playwright.chromium.launch(headless=self.headless)
        return await self.browser.new_context()

    async def close(self):
        """Close all browser resources"""
        if self.page:
            try:
                await self.page.close()
            except Exception:
                pass
        if self.context:
            try:
                await self.context.close()
            except Exception:
                pass
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                pass

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit — always close resources"""
        await self.close()
        return False
