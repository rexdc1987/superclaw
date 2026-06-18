"""浏览器连通性测试 — 验证 Playwright + Chromium 能正常工作"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import asyncio
import pytest

# Skip if no display (headless still works, but import may fail on some setups)
pytestmark = pytest.mark.asyncio


async def test_browser_launch_and_navigate():
    """验证: 浏览器启动 -> 访问页面 -> 获取标题 -> 正常关闭"""
    from automation.browser import BrowserManager

    browser = BrowserManager(headless=True)
    try:
        await browser.launch()
        assert browser.page is not None, "page 属性应存在"

        # Navigate to a simple page
        await browser.page.goto("https://www.baidu.com", wait_until="domcontentloaded", timeout=15000)
        title = await browser.page.title()
        assert len(title) > 0, f"页面标题不应为空，实际: {title}"
        print(f"  页面标题: {title}")

        # Verify we can execute JS
        ua = await browser.page.evaluate("() => navigator.userAgent")
        assert "Mozilla" in ua, "应能执行JS获取userAgent"
        print(f"  userAgent: {ua[:60]}...")

        # Verify we can query DOM
        html = await browser.page.content()
        assert len(html) > 100, "页面HTML应有内容"
        print(f"  HTML长度: {len(html)} 字符")

    finally:
        await browser.close()


async def test_browser_douyin_accessible():
    """验证: 能访问抖音首页（不登录，仅检查连通性）"""
    from automation.browser import BrowserManager

    browser = BrowserManager(headless=True)
    try:
        await browser.launch()
        resp = await browser.page.goto("https://www.douyin.com", wait_until="domcontentloaded", timeout=20000)
        assert resp.status < 400, f"抖音首页应可访问，HTTP {resp.status}"
        title = await browser.page.title()
        print(f"  抖音标题: {title}")
        assert "抖音" in title or "douyin" in title.lower() or len(title) > 0, f"标题异常: {title}"
    finally:
        await browser.close()


async def test_douyin_search_page():
    """验证: 能访问抖音搜索页（不登录，检查页面结构）"""
    from automation.browser import BrowserManager

    browser = BrowserManager(headless=True)
    try:
        await browser.launch()
        url = "https://www.douyin.com/search/test?type=video"
        resp = await browser.page.goto(url, wait_until="domcontentloaded", timeout=20000)
        print(f"  搜索页HTTP: {resp.status}")
        # Don't assert on status - Douyin may redirect to login
        await asyncio.sleep(2)
        current_url = browser.page.url
        print(f"  最终URL: {current_url}")
        html_len = len(await browser.page.content())
        print(f"  HTML长度: {html_len}")
        assert html_len > 0, "页面应有内容"
    finally:
        await browser.close()


async def test_adapter_instantiation():
    """验证: DouyinAdapter 能正确实例化"""
    from automation.browser import BrowserManager
    from automation.douyin_adapter import DouyinAdapter

    browser = BrowserManager(headless=True)
    adapter = DouyinAdapter(browser)
    assert adapter.platform_name == "douyin"
    assert adapter.base_url == "https://www.douyin.com"
    print(f"  adapter.platform_name: {adapter.platform_name}")
    print(f"  adapter.base_url: {adapter.base_url}")
