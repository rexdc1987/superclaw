"""Behavior simulation engine - human-like mouse, typing, scrolling."""
from __future__ import annotations
import asyncio
import math
import random
from typing import Tuple, Optional


class BehaviorSimulator:
    """Simulate human-like interactions on Playwright pages."""

    @staticmethod
    async def random_delay(min_ms: int = 100, max_ms: int = 500) -> None:
        """Sleep for a random duration between min_ms and max_ms milliseconds."""
        await asyncio.sleep(random.uniform(min_ms / 1000, max_ms / 1000))

    @staticmethod
    async def human_mouse_move(
        page,
        start: Tuple[float, float],
        end: Tuple[float, float],
        steps: int = 15,
    ) -> None:
        """Move mouse from start to end using cubic Bezier curve with jitter.

        Args:
            page: Playwright Page instance.
            start: (x, y) starting position.
            end: (x, y) ending position.
            steps: Number of intermediate points (more = smoother).
        """
        # Generate random control points for Bezier curve
        cp1 = (
            start[0] + random.uniform(-80, 80),
            start[1] + random.uniform(-80, 80),
        )
        cp2 = (
            end[0] + random.uniform(-80, 80),
            end[1] + random.uniform(-80, 80),
        )

        for i in range(steps + 1):
            t = i / steps
            # Cubic Bezier interpolation
            x = (
                (1 - t) ** 3 * start[0]
                + 3 * (1 - t) ** 2 * t * cp1[0]
                + 3 * (1 - t) * t ** 2 * cp2[0]
                + t ** 3 * end[0]
            )
            y = (
                (1 - t) ** 3 * start[1]
                + 3 * (1 - t) ** 2 * t * cp1[1]
                + 3 * (1 - t) * t ** 2 * cp2[1]
                + t ** 3 * end[1]
            )
            # Add micro-jitter
            x += random.uniform(-1.5, 1.5)
            y += random.uniform(-1.5, 1.5)
            await page.mouse.move(x, y)
            # Variable speed: slower at start/end, faster in middle
            speed_factor = 0.5 + math.sin(t * math.pi) * 0.5
            delay = random.uniform(0.008, 0.025) * (1.5 - speed_factor)
            await asyncio.sleep(delay)

    @staticmethod
    async def human_type(
        page,
        selector: str,
        text: str,
        wpm: int = 80,
    ) -> None:
        """Type text with human-like variable speed.

        Args:
            page: Playwright Page instance.
            selector: CSS selector for the input field.
            text: Text to type.
            wpm: Approximate words per minute (affects delay).
        """
        # Base delay per character (chars_per_minute ~= wpm * 5)
        base_delay = 60.0 / (wpm * 5)
        element = page.locator(selector)
        await element.click()
        await asyncio.sleep(random.uniform(0.1, 0.3))

        for i, char in enumerate(text):
            # Normal distribution around base delay
            delay = max(0.02, random.gauss(base_delay, base_delay * 0.4))
            # Occasional longer pause (thinking)
            if random.random() < 0.05:
                delay += random.uniform(0.3, 0.8)
            await page.keyboard.type(char, delay=int(delay * 1000))

    @staticmethod
    async def human_scroll(
        page,
        direction: str = "down",
        distance: int = 300,
    ) -> None:
        """Scroll page with human-like variable speed and pauses.

        Args:
            page: Playwright Page instance.
            direction: 'up' or 'down'.
            distance: Approximate pixel distance to scroll.
        """
        sign = -1 if direction == "up" else 1
        scrolled = 0
        while scrolled < distance:
            chunk = random.randint(50, 150)
            await page.mouse.wheel(0, sign * chunk)
            scrolled += chunk
            # Variable pause between scroll chunks
            await asyncio.sleep(random.uniform(0.05, 0.25))
            # Occasional longer pause
            if random.random() < 0.15:
                await asyncio.sleep(random.uniform(0.3, 1.0))

    @staticmethod
    async def human_click(page, selector: str, offset_range: int = 4) -> None:
        """Click an element with random offset from center.

        Args:
            page: Playwright Page instance.
            selector: CSS selector for target element.
            offset_range: Max pixel offset from center (±).
        """
        element = page.locator(selector)
        box = await element.bounding_box()
        if not box:
            await element.click()
            return

        # Target near center with random offset
        x = box["x"] + box["width"] / 2 + random.uniform(-offset_range, offset_range)
        y = box["y"] + box["height"] / 2 + random.uniform(-offset_range, offset_range)

        # Move mouse first (with Bezier curve)
        await BehaviorSimulator.human_mouse_move(
            page,
            (x - random.uniform(50, 200), y - random.uniform(50, 200)),
            (x, y),
            steps=random.randint(8, 20),
        )
        await asyncio.sleep(random.uniform(0.05, 0.15))
        await page.mouse.click(x, y)
