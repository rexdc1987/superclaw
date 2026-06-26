"""Core stealth middleware - WebDriver flag hiding, CDP injection, UA spoofing."""
from __future__ import annotations
import random
from typing import List, Dict, Optional

# Common desktop user agents
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]

# JavaScript to inject before page load
_STEALTH_JS = """
// Hide webdriver flag
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Fake plugins array
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
        ];
        plugins.length = 3;
        return plugins;
    }
});

// Override permissions query
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) =>
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters);

// Fix chrome.runtime
window.chrome = window.chrome || {};
window.chrome.runtime = window.chrome.runtime || {};

// Override language consistency
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

// Prevent iframe contentWindow detection
try {
    const frame = document.createElement('iframe');
    frame.style.display = 'none';
    document.body.appendChild(frame);
    const contentWindow = frame.contentWindow;
    Object.defineProperty(contentWindow.navigator, 'webdriver', { get: () => undefined });
    document.body.removeChild(frame);
} catch(e) {}
"""


class StealthMiddleware:
    """Apply anti-detection measures to Playwright browser contexts."""

    @staticmethod
    def get_stealth_args() -> List[str]:
        """Return Chromium launch arguments for stealth mode."""
        return [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions-file-access-check",
            "--disable-webrtc-multiple-routes",
            "--disable-webrtc-hw-encoding",
            "--disable-webrtc-hw-decoding",
            "--enforce-webrtc-ip-permission-check",
            "--webrtc-ip-handling-policy=disable_non_proxied_udp",
        ]

    @staticmethod
    def random_user_agent() -> str:
        """Return a random desktop user agent string."""
        return random.choice(_USER_AGENTS)

    async def apply(self, context) -> None:
        """Instance method - inject stealth scripts into the context.

        Delegates to apply_stealth. Provided so adapters can call
        self._stealth.apply(context) without caring about static vs instance.
        """
        await self.apply_stealth(context)

    @staticmethod
    async def apply_stealth(context) -> None:
        """Inject stealth scripts into every new page of the context.

        Args:
            context: Playwright BrowserContext instance.
        """
        await context.add_init_script(_STEALTH_JS)

    @staticmethod
    def get_stealth_headers() -> Dict[str, str]:
        """Return additional headers to mimic a real browser."""
        return {
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "sec-ch-ua": '"Chromium";v="126", "Not.A/Brand";v="8", "Google Chrome";v="126"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }
