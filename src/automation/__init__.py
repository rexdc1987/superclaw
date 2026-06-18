"""Platform adapter factory"""
from automation.platform_base import BasePlatformAdapter


def get_adapter(platform: str, browser_manager) -> BasePlatformAdapter:
    """Get platform adapter by name"""
    if platform == "douyin":
        from automation.douyin_adapter import DouyinAdapter
        return DouyinAdapter(browser_manager)
    elif platform == "xiaohongshu":
        from automation.xiaohongshu_adapter import XiaohongshuAdapter
        return XiaohongshuAdapter(browser_manager)
    elif platform == "kuaishou":
        from automation.kuaishou_adapter import KuaishouAdapter
        return KuaishouAdapter(browser_manager)
    elif platform == "bilibili":
        from automation.bilibili_adapter import BilibiliAdapter
        return BilibiliAdapter(browser_manager)
    else:
        raise ValueError(f"Unsupported platform: {platform}")
