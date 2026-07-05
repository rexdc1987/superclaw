"""
SuperClaw RPA - Stress Testing Tool

Launches concurrent browser instances to execute full scrape/submit workflows,
collecting success rate, latency, P95/P99, and error metrics.

Features:
    - Configurable concurrency (default 50)
    - Per-worker isolated browser + anti-detection
    - Real-time MetricsCollector integration
    - Markdown report generation

Usage::

    from rpa.pipelines.stress_test import StressTester

    tester = StressTester("https://example.com/form", concurrency=50)
    result = await tester.run(duration_seconds=300)
    print(tester.generate_report(result))
"""

from __future__ import annotations

import asyncio
import logging
import random
import statistics
import time
from dataclasses import dataclass, field
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
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class WorkerResult:
    """Result from a single worker iteration."""

    worker_id: int
    success: bool
    latency_ms: float
    error_message: str = ""
    timestamp: float = field(default_factory=time.time)
    iterations: int = 0


@dataclass
class StressTestResult:
    """Aggregated stress test results."""

    target_url: str
    concurrency: int
    duration_seconds: float
    total_requests: int
    successful_requests: int
    failed_requests: int
    captcha_count: int
    error_count: int
    success_rate: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    throughput_rps: float  # requests per second
    worker_results: list[WorkerResult] = field(default_factory=list)
    errors: dict[str, int] = field(default_factory=dict)

    @property
    def total_iterations(self) -> int:
        """Sum of all worker iterations."""
        return sum(w.iterations for w in self.worker_results)


# ---------------------------------------------------------------------------
# StressTester
# ---------------------------------------------------------------------------

class StressTester:
    """Concurrent stress tester for RPA stability validation.

    Parameters
    ----------
    target_url : str
        Target form/page URL.
    concurrency : int
        Number of concurrent workers (default 50).
    config : dict, optional
        Extra configuration (field mapping, anti-detect toggle, etc.).
    """

    def __init__(
        self,
        target_url: str,
        concurrency: int = 50,
        config: Optional[dict[str, Any]] = None,
    ) -> None:
        """Initialise the stress tester.

        Args:
            target_url: Target URL.
            concurrency: Number of concurrent workers.
            config: Optional configuration dict.
        """
        self.target_url = target_url
        self.concurrency = concurrency
        self.config: dict[str, Any] = config or {}
        self._metrics = MetricsCollector()
        self._simulator = BehaviorSimulator()
        self._playwright: Optional[Playwright] = None
        self._browser: Any = None

        # Runtime state
        self._stop_event = asyncio.Event()
        self._active_workers = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, duration_seconds: int = 300) -> StressTestResult:
        """Execute the stress test.

        Args:
            duration_seconds: Test duration in seconds.

        Returns:
            :class: with aggregated metrics.
        """
        logger.info(
            "=== Stress test START: url=%s, concurrency=%d, duration=%ds ===",
            self.target_url,
            self.concurrency,
            duration_seconds,
        )

        self._stop_event.clear()
        all_results: list[WorkerResult] = []

        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.config.get("headless", True),
            )

            # Schedule automatic stop
            asyncio.get_event_loop().call_later(
                duration_seconds, self._stop_event.set,
            )

            # Launch worker coroutines
            tasks: list[asyncio.Task[None]] = []
            for wid in range(self.concurrency):
                task = asyncio.create_task(
                    self._worker(wid, all_results),
                )
                tasks.append(task)

            self._metrics.set_active_accounts(self.concurrency)
            logger.info("Launched %d worker coroutines", self.concurrency)

            # Wait for all workers (terminated by stop_event)
            await asyncio.gather(*tasks, return_exceptions=True)

        finally:
            await self._cleanup()

        # Compile statistics
        result = self._compile_results(all_results, duration_seconds)

        logger.info(
            "=== Stress test DONE: total=%d, success_rate=%.1f%%, P95=%.0fms ===",
            result.total_requests,
            result.success_rate * 100,
            result.p95_latency_ms,
        )

        return result

    async def _worker(self, worker_id: int, results: list[WorkerResult]) -> None:
        """Single worker coroutine; loops until stop signal.

        Args:
            worker_id: Worker index.
            results: Shared result list (thread-safe in asyncio).
        """
        logger.debug("Worker %d started", worker_id)
        context: Optional[BrowserContext] = None
        page: Optional[Page] = None
        iterations = 0
        errors: dict[str, int] = {}

        try:
            context = await self._browser.new_context()
            if self.config.get("anti_detect", True):
                stealth = StealthMiddleware()
                await stealth.apply(context)

            while not self._stop_event.is_set():
                page = await context.new_page()
                t0 = time.monotonic()
                success = False
                error_msg = ""

                try:
                    # 1. Navigate to target
                    await page.goto(
                        self.target_url,
                        timeout=30_000,
                    )
                    await page.wait_for_load_state("domcontentloaded")

                    # 2. Simulate browsing
                    await self._simulate_browsing(page)

                    # 3. Fill form if field mapping provided
                    field_mapping: dict[str, str] = self.config.get(
                        "field_mapping", {},
                    )
                    if field_mapping:
                        await self._fill_form_fields(page, field_mapping)

                        # 4. Submit
                        submit_sel = self.config.get(
                            "submit_button_selector",
                            "button[type='submit'], input[type='submit']",
                        )
                        try:
                            btn = page.locator(submit_sel).first
                            await btn.wait_for(state="visible", timeout=5_000)
                            await btn.click()
                            await page.wait_for_load_state(
                                "networkidle", timeout=15_000,
                            )
                        except Exception:
                            pass  # Page may not have a submit button

                    success = True
                    iterations += 1

                except Exception as exc:
                    error_msg = str(exc)[:200]
                    error_type = type(exc).__name__
                    errors[error_type] = errors.get(error_type, 0) + 1
                    self._metrics.record_task_failure(
                        "stress_test", 0, error_type,
                    )

                finally:
                    latency = (time.monotonic() - t0) * 1000

                    if success:
                        self._metrics.record_task_success(
                            "stress_test", latency / 1000,
                        )

                    results.append(WorkerResult(
                        worker_id=worker_id,
                        success=success,
                        latency_ms=latency,
                        error_message=error_msg,
                        iterations=iterations,
                    ))

                    if page:
                        await page.close()
                        page = None

                # Brief random interval to avoid synchronization
                if not self._stop_event.is_set():
                    await asyncio.sleep(random.uniform(0.5, 2.0))

        except Exception as exc:
            logger.error("Worker %d crashed: %s", worker_id, exc)
            results.append(WorkerResult(
                worker_id=worker_id,
                success=False,
                latency_ms=0,
                error_message="Worker fatal: " + str(exc),
            ))
        finally:
            if page:
                await page.close()
            if context:
                await context.close()
            logger.debug(
                "Worker %d finished, %d iterations", worker_id, iterations,
            )

    async def _simulate_browsing(self, page: Page) -> None:
        """Simulate user browsing: scrolling, hovering, random pauses."""
        scroll_times = random.randint(1, 3)
        for _ in range(scroll_times):
            direction = random.choice(["down", "up"])
            await self._simulator.random_scroll(page, direction)
            await asyncio.sleep(random.uniform(0.3, 1.0))

        # Scroll back up
        await self._simulator.random_scroll(page, "up", (50, 200))
        await asyncio.sleep(random.uniform(0.2, 0.5))

    async def _fill_form_fields(
        self,
        page: Page,
        field_mapping: dict[str, str],
    ) -> None:
        """Fill form fields with behavior simulator (random test data)."""
        test_data = {
            "name": "Test User " + str(random.randint(1000, 9999)),
            "email": f"test{random.randint(10000, 99999)}@example.com",
            "phone": f"1{random.randint(3000000000, 9999999999)}",
            "message": "This is an automated stress test submission.",
            "address": f"{random.randint(1, 999)} Test Street",
            "company": "StressTest Corp",
            "subject": f"Inquiry #{random.randint(100, 999)}",
        }

        for key, selector in field_mapping.items():
            value = test_data.get(key, f"test_value_{random.randint(1, 9999)}")
            try:
                await self._simulator.human_like_type(
                    page, selector, str(value),
                )
                await asyncio.sleep(random.uniform(0.2, 0.8))
            except Exception as exc:
                logger.debug("Worker fill field '%s' failed: %s", key, exc)

    def _compile_results(
        self,
        worker_results: list[WorkerResult],
        duration_seconds: float,
    ) -> StressTestResult:
        """Compile worker results into StressTestResult."""
        total = len(worker_results)
        successes = sum(1 for r in worker_results if r.success)
        failures = total - successes

        latencies = [r.latency_ms for r in worker_results if r.success]
        if not latencies:
            latencies = [0.0]

        sorted_lat = sorted(latencies)
        n = len(sorted_lat)

        def percentile(p: float) -> float:
            idx = int(n * p / 100)
            return sorted_lat[min(idx, n - 1)]

        # Count error types
        error_types: dict[str, int] = {}
        for r in worker_results:
            if not r.success and r.error_message:
                key = r.error_message.split(chr(10))[0][:80]
                error_types[key] = error_types.get(key, 0) + 1

        captcha_count = sum(
            1 for r in worker_results
            if "captcha" in r.error_message.lower()
            or "CAPTCHA" in r.error_message
        )

        return StressTestResult(
            target_url=self.target_url,
            concurrency=self.concurrency,
            duration_seconds=duration_seconds,
            total_requests=total,
            successful_requests=successes,
            failed_requests=failures,
            captcha_count=captcha_count,
            error_count=failures,
            success_rate=successes / total if total > 0 else 0.0,
            avg_latency_ms=statistics.mean(latencies),
            p50_latency_ms=percentile(50),
            p95_latency_ms=percentile(95),
            p99_latency_ms=percentile(99),
            min_latency_ms=min(latencies),
            max_latency_ms=max(latencies),
            throughput_rps=total / duration_seconds if duration_seconds > 0 else 0,
            worker_results=worker_results,
            errors=error_types,
        )

    def generate_report(self, results: StressTestResult) -> str:
        """Generate a Markdown-format stress test report.

        Args:
            results: Stress test results.

        Returns:
            Markdown report string.
        """
        nl = chr(10)
        report_lines: list[str] = []

        report_lines.append("# SuperClaw Stress Test Report")
        report_lines.append("")
        report_lines.append("**Generated**: " + time.strftime("%Y-%m-%d %H:%M:%S"))
        report_lines.append("")
        report_lines.append("---")
        report_lines.append("")
        report_lines.append("## Test Summary")
        report_lines.append("")
        report_lines.append("| Metric | Value |")
        report_lines.append("|--------|-------|")
        report_lines.append(f"| Target URL |  |")
        report_lines.append(f"| Concurrency | {results.concurrency} |")
        report_lines.append(f"| Duration | {results.duration_seconds:.0f}s |")
        report_lines.append(f"| Total Requests | {results.total_requests} |")
        report_lines.append(f"| Successful | {results.successful_requests} |")
        report_lines.append(f"| Failed | {results.failed_requests} |")
        report_lines.append(f"| Success Rate | **{results.success_rate * 100:.1f}%** |")
        report_lines.append(f"| Throughput | {results.throughput_rps:.1f} req/s |")
        report_lines.append(f"| Total Iterations | {results.total_iterations} |")
        report_lines.append("")
        report_lines.append("## Latency Metrics")
        report_lines.append("")
        report_lines.append("| Percentile | Latency (ms) |")
        report_lines.append("|------------|-------------|")
        report_lines.append(f"| Min | {results.min_latency_ms:.1f} |")
        report_lines.append(f"| P50 | {results.p50_latency_ms:.1f} |")
        report_lines.append(f"| P95 | {results.p95_latency_ms:.1f} |")
        report_lines.append(f"| P99 | {results.p99_latency_ms:.1f} |")
        report_lines.append(f"| Max | {results.max_latency_ms:.1f} |")
        report_lines.append(f"| Avg | {results.avg_latency_ms:.1f} |")
        report_lines.append("")
        report_lines.append("## Error Analysis")
        report_lines.append("")

        if results.errors:
            report_lines.append("| Error Type | Count |")
            report_lines.append("|------------|-------|")
            for err_type, count in sorted(
                results.errors.items(), key=lambda x: -x[1],
            ):
                report_lines.append(f"| {err_type} | {count} |")
        else:
            report_lines.append("No errors recorded.")

        report_lines.append("")
        report_lines.append(f"**CAPTCHA triggers**: {results.captcha_count}")
        report_lines.append("")
        report_lines.append("## Performance Assessment")
        report_lines.append("")

        # Auto-grade
        grade = "FAIL"
        notes: list[str] = []

        if results.success_rate >= 0.99:
            grade = "A+"
            notes.append("Excellent success rate (>=99%)")
        elif results.success_rate >= 0.95:
            grade = "A"
            notes.append("Good success rate (>=95%)")
        elif results.success_rate >= 0.90:
            grade = "B"
            notes.append("Acceptable success rate (>=90%)")
        elif results.success_rate >= 0.80:
            grade = "C"
            notes.append("Low success rate (<90%)")
        else:
            grade = "D"
            notes.append("Critical success rate (<80%)")

        if results.p95_latency_ms < 2000:
            notes.append("Excellent P95 latency (<2s)")
        elif results.p95_latency_ms < 5000:
            notes.append("Acceptable P95 latency (<5s)")
        else:
            notes.append("High P95 latency (>=5s)")
            if grade in ("A+", "A"):
                grade = "B"

        report_lines.append(f"**Overall Grade: {grade}**")
        report_lines.append("")

        for note in notes:
            report_lines.append(f"- {note}")

        report_lines.append("")
        report_lines.append("## Recommendations")
        report_lines.append("")

        if results.success_rate < 0.95:
            report_lines.append("- Check anti-detection config; may have triggered risk controls")
        if results.p95_latency_ms > 5000:
            report_lines.append("- Check network latency and target server load")
        if results.captcha_count > 0:
            report_lines.append(
                f"- {results.captcha_count} CAPTCHA triggers detected; "
                "consider tuning behavior simulation parameters"
            )
        if results.error_count > results.total_requests * 0.1:
            report_lines.append("- High error rate; check target page stability")

        report_lines.append("")
        report_lines.append("---")
        report_lines.append("")
        report_lines.append("*Report auto-generated by SuperClaw Stress Test Engine*")

        return nl.join(report_lines)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def _cleanup(self) -> None:
        """Release browser and Playwright resources."""
        try:
            if self._browser:
                await self._browser.close()
        except Exception as exc:
            logger.debug("Browser cleanup error: %s", exc)
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception as exc:
            logger.debug("Playwright cleanup error: %s", exc)
        self._browser = None
        self._playwright = None
        self._metrics.set_active_accounts(0)
