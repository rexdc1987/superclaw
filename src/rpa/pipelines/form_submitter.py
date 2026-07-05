"""
SuperClaw RPA - 表单自动提交管道

提供批量表单提交能力，集成反检测浏览器、行为模拟、多账号轮换和验证码检测。

Features:
    - 反检测浏览器上下文（StealthMiddleware + FingerprintManager）
    - 人类行为模拟（BehaviorSimulator: 变速打字、贝塞尔鼠标轨迹）
    - 多账号轮换（每个账号提交N个后自动休息）
    - CAPTCHA / 账号封禁检测
    - Prometheus 指标采集（MetricsCollector）

Usage::

    from rpa.pipelines.form_submitter import FormSubmitter

    config = {
        "field_mapping": {
            "name":  "#input-name",
            "email": "#input-email",
        },
    }
    submitter = FormSubmitter(config)
    results = await submitter.submit_batch(form_url, data_list, account_pool)
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from rpa.anti_detect.behavior import BehaviorSimulator
from rpa.anti_detect.stealth import StealthMiddleware
from rpa.monitoring.metrics import MetricsCollector

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 公共数据结构
# ---------------------------------------------------------------------------

class SubmitStatus(str, Enum):
    """单次表单提交的可能结果。"""

    SUCCESS = "success"
    FAILED = "failed"
    CAPTCHA = "captcha"
    TIMEOUT = "timeout"
    ACCOUNT_BLOCKED = "account_blocked"


@dataclass
class SubmitResult:
    """单次表单提交结果。"""

    status: SubmitStatus
    data: dict[str, Any] = field(default_factory=dict)
    account_id: str = ""
    error_message: str = ""
    latency_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """序列化为普通 dict，便于 JSON 导出。"""
        return {
            "status": self.status.value,
            "data": self.data,
            "account_id": self.account_id,
            "error_message": self.error_message,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# 默认配置
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG: dict[str, Any] = {
    "submissions_per_account": 5,        # 每个账号提交 N 次后轮换
    "rest_between_accounts_sec": 10.0,   # 轮换时休息秒数
    "typing_delay_ms_range": (50, 180),  # 按键延迟范围
    "pause_between_fields_ms": (300, 1200),
    "submit_timeout_ms": 30_000,
    "success_indicators": [
        "thank you", "success", "submitted", "successfully",
        "成功", "提交成功", "谢谢",
    ],
    "failure_indicators": ["error", "failed", "失败", "错误"],
    "captcha_indicators": [
        "captcha", "recaptcha", "验证码", "robot", "我不是机器人",
    ],
    "max_retries": 2,
    "field_mapping": {},  # {logical_name: css_selector}
    "submit_button_selector": "button[type='submit'], input[type='submit']",
    "anti_detect": True,
    "headless": False,
}


# ---------------------------------------------------------------------------
# FormSubmitter
# ---------------------------------------------------------------------------

class FormSubmitter:
    """批量表单自动提交器，集成反检测与多账号轮换。

    Parameters
    ----------
    config : dict
        配置字典，未提供的键使用 _DEFAULT_CONFIG 补全。
    """

    def __init__(self, config: dict[str, Any]) -> None:
        """初始化提交器。

        Args:
            config: 配置字典。支持的键见 _DEFAULT_CONFIG。
        """
        self.config: dict[str, Any] = {**_DEFAULT_CONFIG, **config}
        self._metrics = MetricsCollector()
        self._simulator = BehaviorSimulator()
        self._playwright: Optional[Playwright] = None
        self._browser: Any = None

        self._submissions_count: int = 0
        self._current_account_idx: int = 0

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    async def submit_batch(
        self,
        form_url: str,
        data_list: list[dict[str, Any]],
        account_pool: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """批量提交表单数据，自动轮换账号。

        Args:
            form_url: 目标表单 URL。
            data_list: 待提交数据列表，每个 dict 包含
                {field_name: value} 键值对，key 为 field_mapping
                中的逻辑名。
            account_pool: 账号池，每个 dict 至少包含 id 或
                username 键，可含 cookies / proxy 等。

        Returns:
            提交结果列表（dict 序列化后的 SubmitResult）。
        """
        if not data_list:
            logger.warning("submit_batch: data_list 为空")
            return []

        if not account_pool:
            raise ValueError("account_pool 必须包含至少一个账号")

        results: list[dict[str, Any]] = []
        per_account: int = int(self.config["submissions_per_account"])
        rest_sec: float = float(self.config["rest_between_accounts_sec"])

        try:
            self._playwright = await async_playwright().start()
            await self._init_browser()

            for idx, data_entry in enumerate(data_list):
                # --- 账号轮换逻辑 ---
                if idx > 0 and idx % per_account == 0:
                    logger.info(
                        "账号轮换: 休息 %.1fs 后切换...", rest_sec,
                    )
                    await asyncio.sleep(rest_sec)
                    self._current_account_idx += 1

                account = account_pool[
                    self._current_account_idx % len(account_pool)
                ]

                result = await self._submit_single(form_url, data_entry, account)
                results.append(result.to_dict())

                # 记录 Prometheus 指标
                if result.status == SubmitStatus.SUCCESS:
                    self._metrics.record_task_success(
                        "form_submit", result.latency_ms / 1000,
                    )
                elif result.status == SubmitStatus.CAPTCHA:
                    self._metrics.record_captcha()
                    self._metrics.record_task_failure(
                        "form_submit", result.latency_ms / 1000, "captcha",
                    )
                else:
                    self._metrics.record_task_failure(
                        "form_submit", result.latency_ms / 1000,
                        result.status.value,
                    )

                self._submissions_count += 1
                logger.info(
                    "[%d/%d] status=%s  account=%s  latency=%.0fms",
                    idx + 1,
                    len(data_list),
                    result.status.value,
                    result.account_id,
                    result.latency_ms,
                )

        finally:
            await self._cleanup()

        return results

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _init_browser(self) -> None:
        """启动反检测（或普通）Chromium 浏览器。"""
        assert self._playwright is not None
        headless: bool = bool(self.config.get("headless", False))

        if self.config["anti_detect"]:
            self._browser = await self._playwright.chromium.launch(
                headless=headless,
            )
            logger.info("反检测浏览器已启动 (headless=%s)", headless)
        else:
            self._browser = await self._playwright.chromium.launch(
                headless=headless,
            )
            logger.info("普通 Chromium 已启动 (headless=%s)", headless)

    async def _create_context(self, account: dict[str, Any]) -> BrowserContext:
        """创建浏览器上下文，注入反检测脚本。

        Args:
            account: 账号信息，可含 user_agent / viewport 等。

        Returns:
            Playwright BrowserContext。
        """
        context_options: dict[str, Any] = {}

        if account.get("user_agent"):
            context_options["user_agent"] = account["user_agent"]

        if account.get("viewport"):
            context_options["viewport"] = account["viewport"]

        if account.get("locale"):
            context_options["locale"] = account["locale"]

        context = await self._browser.new_context(**context_options)

        # 注入反检测脚本
        if self.config["anti_detect"]:
            stealth = StealthMiddleware()
            await stealth.apply(context)

        # 如果账号有 cookies，注入
        if account.get("cookies"):
            await context.add_cookies(account["cookies"])

        return context

    async def _submit_single(
        self,
        form_url: str,
        data: dict[str, Any],
        account: dict[str, Any],
    ) -> SubmitResult:
        """打开上下文，填写表单，提交并返回结果。"""
        account_id = str(
            account.get("id", account.get("username", "unknown")),
        )
        t0 = time.monotonic()
        retries: int = int(self.config.get("max_retries", 2))

        for attempt in range(retries + 1):
            context: Optional[BrowserContext] = None
            page: Optional[Page] = None
            try:
                context = await self._create_context(account)
                page = await context.new_page()

                # 导航到表单页
                await page.goto(
                    form_url, timeout=self.config["submit_timeout_ms"],
                )
                await page.wait_for_load_state("domcontentloaded")

                # 随机浏览行为（模拟真人先看看页面）
                await asyncio.sleep(random.uniform(0.5, 1.5))

                # 填写表单
                field_mapping: dict[str, str] = self.config["field_mapping"]
                await self._fill_form(page, field_mapping, data)

                # 提交并验证
                raw = await self._submit_and_verify(page)

                latency = (time.monotonic() - t0) * 1000
                status_val = raw.get("status", SubmitStatus.FAILED.value)
                if isinstance(status_val, SubmitStatus):
                    status_val = status_val.value

                return SubmitResult(
                    status=SubmitStatus(status_val),
                    data=raw,
                    account_id=account_id,
                    error_message=raw.get("error", ""),
                    latency_ms=latency,
                )

            except Exception as exc:
                logger.warning(
                    "第 %d/%d 次尝试失败 (account=%s): %s",
                    attempt + 1,
                    retries + 1,
                    account_id,
                    exc,
                )
                if attempt == retries:
                    latency = (time.monotonic() - t0) * 1000
                    return SubmitResult(
                        status=SubmitStatus.FAILED,
                        account_id=account_id,
                        error_message=str(exc),
                        latency_ms=latency,
                    )
                await asyncio.sleep(random.uniform(1, 3))

            finally:
                if page:
                    await page.close()
                if context:
                    await context.close()

        # 不应到达此处；满足类型检查
        return SubmitResult(status=SubmitStatus.FAILED, account_id=account_id)

    async def _fill_form(
        self,
        page: Page,
        field_mapping: dict[str, str],
        data: dict[str, Any],
    ) -> None:
        """按字段映射填写表单，使用变速打字和随机停顿。

        Args:
            page: 已加载表单的 Playwright Page。
            field_mapping: 逻辑字段名到 CSS 选择器的映射，
                如 {"name": "#input-name"}。
            data: 要填写的键值对。
        """
        pause_range: tuple[int, int] = self.config["pause_between_fields_ms"]

        for key, selector in field_mapping.items():
            value = data.get(key)
            if value is None:
                logger.debug("跳过字段 '%s' -- 无数据", key)
                continue

            try:
                # 使用 BehaviorSimulator 的变速打字
                # human_like_type(page, selector, text) 会先 click 再逐字输入
                await self._simulator.human_like_type(
                    page, selector, str(value),
                )

                # 字段间随机停顿
                await asyncio.sleep(random.randint(*pause_range) / 1000.0)
                logger.debug("已填写字段 '%s' (%s)", key, selector)

            except Exception as exc:
                logger.warning(
                    "填写字段 '%s' (selector=%s) 失败: %s",
                    key, selector, exc,
                )

    async def _submit_and_verify(self, page: Page) -> dict[str, Any]:
        """点击提交按钮并检测结果（成功 / 失败 / 验证码）。

        Returns:
            {"status": str, "raw_text": str, "error": str}
        """
        submit_sel: str = self.config["submit_button_selector"]
        success_kws = [s.lower() for s in self.config["success_indicators"]]
        failure_kws = [s.lower() for s in self.config["failure_indicators"]]
        captcha_kws = [s.lower() for s in self.config["captcha_indicators"]]
        block_kws = ["blocked", "banned", "suspended", "封禁", "暂停"]

        try:
            # 定位并点击提交按钮
            submit_btn = page.locator(submit_sel).first
            await submit_btn.wait_for(state="visible", timeout=5_000)

            # 点击前模拟鼠标移动到按钮
            box = await submit_btn.bounding_box()
            if box:
                start_x = random.uniform(100, 400)
                start_y = random.uniform(100, 400)
                end_x = box["x"] + box["width"] / 2 + random.uniform(-3, 3)
                end_y = box["y"] + box["height"] / 2 + random.uniform(-3, 3)
                await self._simulator.human_like_mouse_move(
                    page, (start_x, start_y), (end_x, end_y),
                )
                await asyncio.sleep(random.uniform(0.05, 0.15))

            await submit_btn.click()

            # 等待页面响应
            await page.wait_for_load_state(
                "networkidle", timeout=self.config["submit_timeout_ms"],
            )
            await asyncio.sleep(random.uniform(1.0, 2.5))

            # 获取页面文本用于关键词检测
            body_text: str = (await page.inner_text("body")).lower()
            snippet = body_text[:500]

            # 1. 验证码检测（最高优先级）
            if any(kw in body_text for kw in captcha_kws):
                logger.warning("检测到验证码")
                return {
                    "status": SubmitStatus.CAPTCHA.value,
                    "raw_text": snippet,
                    "error": "检测到验证码",
                }

            # 2. 账号封禁
            if any(kw in body_text for kw in block_kws):
                return {
                    "status": SubmitStatus.ACCOUNT_BLOCKED.value,
                    "raw_text": snippet,
                    "error": "账号疑似被封禁",
                }

            # 3. 成功关键词
            if any(kw in body_text for kw in success_kws):
                return {
                    "status": SubmitStatus.SUCCESS.value,
                    "raw_text": snippet,
                    "error": "",
                }

            # 4. URL 跳转检测（重定向到感谢页面）
            cur = page.url.lower()
            if any(kw in cur for kw in ("thank", "success", "confirm")):
                return {
                    "status": SubmitStatus.SUCCESS.value,
                    "raw_text": snippet,
                    "error": "",
                }

            # 5. 明确的失败关键词
            if any(kw in body_text for kw in failure_kws):
                return {
                    "status": SubmitStatus.FAILED.value,
                    "raw_text": snippet,
                    "error": "页面包含失败关键词",
                }

            # 6. 无法确定
            return {
                "status": SubmitStatus.FAILED.value,
                "raw_text": snippet,
                "error": "无法确定提交结果",
            }

        except Exception as exc:
            logger.error("提交/验证错误: %s", exc)
            return {
                "status": SubmitStatus.TIMEOUT.value,
                "raw_text": "",
                "error": str(exc),
            }

    async def _cleanup(self) -> None:
        """释放浏览器和 Playwright 资源。"""
        try:
            if self._browser:
                await self._browser.close()
        except Exception as exc:
            logger.debug("浏览器关闭错误: %s", exc)
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception as exc:
            logger.debug("Playwright 关闭错误: %s", exc)
        self._browser = None
        self._playwright = None
