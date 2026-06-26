"""Captcha solving adapter - pluggable multi-provider support."""
from __future__ import annotations
import asyncio
import abc
import base64
from typing import Optional


class CaptchaAdapter(abc.ABC):
    """Abstract base class for captcha solving adapters."""

    @abc.abstractmethod
    async def solve_image(self, image_bytes: bytes) -> str:
        """Solve a captcha from image bytes.

        Args:
            image_bytes: Raw captcha image data.

        Returns:
            The solved captcha text.
        """
        ...

    @abc.abstractmethod
    async def solve_recaptcha(self, sitekey: str, page_url: str) -> str:
        """Solve reCAPTCHA v2 invisible/checkbox.

        Args:
            sitekey: The reCAPTCHA site key from the page.
            page_url: The URL of the page containing the captcha.

        Returns:
            The g-recaptcha-response token.
        """
        ...

    @abc.abstractmethod
    async def solve_hcaptcha(self, sitekey: str, page_url: str) -> str:
        """Solve hCaptcha.

        Args:
            sitekey: The hCaptcha site key.
            page_url: The URL of the page.

        Returns:
            The captcha response token.
        """
        ...


class TwoCaptchaAdapter(CaptchaAdapter):
    """Adapter for 2Captcha API (https://2captcha.com)."""

    BASE_URL = "https://2captcha.com"

    def __init__(self, api_key: str, timeout: int = 120):
        self._api_key = api_key
        self._timeout = timeout

    async def _post_task(self, **params) -> str:
        """Submit a captcha task and wait for result."""
        import aiohttp

        params["key"] = self._api_key
        params["json"] = 1

        async with aiohttp.ClientSession() as session:
            # Submit task
            async with session.post(
                f"{self.BASE_URL}/in.php",
                data=params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()
                if data.get("status") != 1:
                    raise RuntimeError(f"2Captcha submit failed: {data.get('request', 'unknown')}")
                task_id = data["request"]

            # Poll for result
            deadline = asyncio.get_event_loop().time() + self._timeout
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(5)
                async with session.get(
                    f"{self.BASE_URL}/res.php",
                    params={"key": self._api_key, "action": "get", "id": task_id, "json": 1},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    result = await resp.json()
                    if result.get("status") == 1:
                        return result["request"]
                    if result.get("request") != "CAPCHA_NOT_READY":
                        raise RuntimeError(f"2Captcha error: {result.get('request')}")

            raise TimeoutError(f"2Captcha timed out after {self._timeout}s")

    async def solve_image(self, image_bytes: bytes) -> str:
        """Solve image captcha via 2Captcha."""
        b64 = base64.b64encode(image_bytes).decode()
        return await self._post_task(
            method="base64",
            body=b64,
        )

    async def solve_recaptcha(self, sitekey: str, page_url: str) -> str:
        """Solve reCAPTCHA v2 via 2Captcha."""
        return await self._post_task(
            method="userrecaptcha",
            googlekey=sitekey,
            pageurl=page_url,
        )

    async def solve_hcaptcha(self, sitekey: str, page_url: str) -> str:
        """Solve hCaptcha via 2Captcha."""
        return await self._post_task(
            method="hcaptcha",
            sitekey=sitekey,
            pageurl=page_url,
        )
