"""
Social Media Content Collector Pipeline

端到端社媒内容采集管道，整合反检测、代理轮换、行为模拟、多平台适配器。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import BrowserContext, Page, async_playwright

from rpa.anti_detect.stealth import StealthMiddleware
from rpa.anti_detect.proxy_manager import ProxyPool
from rpa.anti_detect.behavior import BehaviorSimulator
from rpa.anti_detect.fingerprint import FingerprintManager
from rpa.anti_detect.captcha_adapter import CaptchaAdapter
from rpa.monitoring.metrics import MetricsCollector
from rpa.monitoring.alert_engine import AlertEngine

logger = logging.getLogger(__name__)

PLATFORM_ADAPTERS = {
    "douyin": "automation.douyin_adapter.DouyinAdapter",
    "xiaohongshu": "automation.xiaohongshu_adapter.XiaohongshuAdapter",
    "bilibili": "automation.bilibili_adapter.BilibiliAdapter",
    "kuaishou": "automation.kuaishou_adapter.KuaishouAdapter",
}


def _import_adapter(platform: str):
    import importlib
    path = PLATFORM_ADAPTERS[platform]
    module_path, cls_name = path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, cls_name)


class SocialMediaCollector:
    """端到端社媒内容采集器，整合反检测+代理+行为模拟+监控。"""

    def __init__(self, config: dict) -> None:
        self.config = config
        self._stealth = StealthMiddleware(config.get("anti_detect", {}))
        self._proxy_pool = ProxyPool(config.get("proxy", {}))
        self._behavior = BehaviorSimulator(config.get("behavior", {}))
        self._fingerprint = FingerprintManager(config.get("fingerprint", {}))
        self._captcha = CaptchaAdapter(config.get("captcha", {}))
        self._metrics = MetricsCollector()
        self._alert_engine = AlertEngine()
        self._adapters = {}
        self._playwright = None
        self._browser = None
        retry_cfg = config.get("retry", {})
        self._max_retries = retry_cfg.get("max_retries", 3)
        self._backoff = retry_cfg.get("backoff", 2.0)
        logger.info("SocialMediaCollector initialized")

    async def collect(self, platform: str, keywords: list[str], max_items: int = 100) -> list[dict]:
        """执行完整采集流程。"""
        if platform not in PLATFORM_ADAPTERS:
            raise ValueError(f"Unsupported platform: {platform}")

        run_id = uuid.uuid4().hex[:12]
        start_time = time.monotonic()
        logger.info("[%s] Starting collection: platform=%s, keywords=%s", run_id, platform, keywords)
        self._metrics.record("collection_start", {"platform": platform, "run_id": run_id})

        proxy = await self._proxy_pool.get_proxy()
        context = None

        try:
            context = await self._setup_browser(proxy=proxy)
            page = await context.new_page()
            raw_results = await self._retry_collect(page, platform, keywords, max_items)

            try:
                from services.filter_service import FilterService
                cleaned = FilterService(self.config.get("filter", {})).filter(raw_results)
            except ImportError:
                cleaned = raw_results

            output_dir = self.config.get("output_dir", "./output")
            await self._save_results(cleaned, output_dir)

            elapsed = time.monotonic() - start_time
            self._metrics.record("collection_complete", {
                "platform": platform, "count": len(cleaned), "elapsed": round(elapsed, 2)
            })
            logger.info("[%s] Done: %d items in %.2fs", run_id, len(cleaned), elapsed)
            return cleaned

        except Exception as exc:
            elapsed = time.monotonic() - start_time
            self._metrics.record("collection_error", {"platform": platform, "error": str(exc)})
            await self._alert_engine.trigger(level="error", title=f"Collection failed: {platform}", message=str(exc))
            raise RuntimeError(f"Collection failed: {exc}") from exc
        finally:
            if context:
                await context.close()
            await self._proxy_pool.release_proxy(proxy)

    async def _setup_browser(self, proxy: Optional[dict] = None) -> BrowserContext:
        """创建反检测浏览器上下文。"""
        if self._playwright is None:
            self._playwright = await async_playwright().start()

        browser_cfg = self.config.get("browser", {})
        fp = self._fingerprint.get_fingerprint()
        args = browser_cfg.get("args", []) + self._stealth.get_launch_args()

        browser = await self._playwright.chromium.launch(
            headless=browser_cfg.get("headless", True), args=args
        )

        ctx_kwargs = {
            "viewport": fp.get("viewport", {"width": 1920, "height": 1080}),
            "user_agent": fp.get("user_agent", ""),
            "locale": fp.get("locale", "zh-CN"),
            "timezone_id": fp.get("timezone", "Asia/Shanghai"),
        }
        if proxy:
            ctx_kwargs["proxy"] = {"server": proxy["server"], "username": proxy.get("username"), "password": proxy.get("password")}

        context = await browser.new_context(**ctx_kwargs)
        await self._stealth.apply_to_context(context)
        fp_scripts = self._fingerprint.get_injection_scripts()
        if fp_scripts:
            await context.add_init_script(fp_scripts)
        return context

    async def _collect_platform(self, page: Page, platform: str, keywords: list[str]) -> list[dict]:
        """调用平台适配器采集。"""
        adapter = _import_adapter(platform)(config=self.config.get("platforms", {}).get(platform, {}))
        results = []
        for kw in keywords:
            await self._behavior.pre_search_delay(page)
            try:
                items = await adapter.search(page, kw)
                results.extend(items)
            except Exception as exc:
                if await self._captcha.try_resolve(page):
                    items = await adapter.search(page, kw)
                    results.extend(items)
            await self._behavior.inter_search_delay(page)
            await self._behavior.random_scroll(page)
        return results

    async def _save_results(self, results: list[dict], output_dir: str) -> None:
        """保存结果为 JSON。"""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        fp = out / f"collection_{ts}_{uuid.uuid4().hex[:8]}.json"
        fp.write_text(json.dumps({"items": results}, ensure_ascii=False, indent=2), encoding="utf-8")
        self._metrics.record("results_saved", {"path": str(fp), "count": len(results)})

    async def _retry_collect(self, page: Page, platform: str, keywords: list[str], max_items: int) -> list[dict]:
        """带重试的采集。"""
        last_exc = None
        for attempt in range(1, self._max_retries + 1):
            try:
                results = await self._collect_platform(page, platform, keywords)
                return results[:max_items]
            except Exception as exc:
                last_exc = exc
                await asyncio.sleep(self._backoff * attempt)
        raise RuntimeError(f"All retries failed: {last_exc}") from last_exc

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def __aenter__(self):
        return self
    async def __aexit__(self, *exc):
        await self.close()
