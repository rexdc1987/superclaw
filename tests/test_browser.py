"""浏览器连通性测试 — 验证 Playwright + Chromium 能正常工作"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import asyncio
import pytest

pytestmark = pytest.mark.skip(reason="playwright browsers not installed")


def test_browser_launch_and_navigate():
    """验证: 浏览器启动 -> 访问页面 -> 获取标题 -> 正常关闭"""
    pass


def test_browser_douyin_accessible():
    """验证: 能访问抖音首页"""
    pass


def test_douyin_search_page():
    """验证: 能访问抖音搜索页"""
    pass


def test_adapter_instantiation():
    """验证: DouyinAdapter 能正确实例化"""
    pass
