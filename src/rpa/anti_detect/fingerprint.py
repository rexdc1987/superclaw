"""Fingerprint configuration manager - device template library."""
from __future__ import annotations
import random
import hashlib
from typing import Dict, Any, Optional, List


# Device fingerprint templates
_TEMPLATES: List[Dict[str, Any]] = [
    {
        "name": "Windows Chrome 126",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "viewport": {"width": 1920, "height": 1080},
        "platform": "Win32",
        "languages": ["en-US", "en"],
        "webgl_vendor": "Google Inc. (NVIDIA)",
        "webgl_renderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)",
        "hardware_concurrency": 12,
        "device_memory": 16,
        "canvas_noise_seed": "a1b2c3d4e5",
    },
    {
        "name": "Windows Chrome 125",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "viewport": {"width": 1536, "height": 864},
        "platform": "Win32",
        "languages": ["zh-CN", "zh", "en"],
        "webgl_vendor": "Google Inc. (Intel)",
        "webgl_renderer": "ANGLE (Intel, Intel(R) UHD Graphics 770 Direct3D11 vs_5_0 ps_5_0)",
        "hardware_concurrency": 8,
        "device_memory": 8,
        "canvas_noise_seed": "f6g7h8i9j0",
    },
    {
        "name": "Mac Safari 17",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        "viewport": {"width": 1440, "height": 900},
        "platform": "MacIntel",
        "languages": ["en-US", "en"],
        "webgl_vendor": "Apple",
        "webgl_renderer": "Apple M2",
        "hardware_concurrency": 8,
        "device_memory": 16,
        "canvas_noise_seed": "k1l2m3n4o5",
    },
    {
        "name": "Linux Firefox 128",
        "user_agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
        "viewport": {"width": 1920, "height": 1080},
        "platform": "Linux x86_64",
        "languages": ["en-US", "en"],
        "webgl_vendor": "NVIDIA Corporation",
        "webgl_renderer": "NVIDIA GeForce GTX 1660/PCIe/SSE2",
        "hardware_concurrency": 6,
        "device_memory": 8,
        "canvas_noise_seed": "p6q7r8s9t0",
    },
    {
        "name": "Windows Edge 126",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
        "viewport": {"width": 2560, "height": 1440},
        "platform": "Win32",
        "languages": ["en-US", "en"],
        "webgl_vendor": "Google Inc. (AMD)",
        "webgl_renderer": "ANGLE (AMD, AMD Radeon RX 6700 XT Direct3D11 vs_5_0 ps_5_0)",
        "hardware_concurrency": 16,
        "device_memory": 32,
        "canvas_noise_seed": "u1v2w3x4y5",
    },
]


class FingerprintManager:
    """Manage browser fingerprint templates and injection."""

    def __init__(self, templates: Optional[List[Dict[str, Any]]] = None):
        self._templates = templates or _TEMPLATES

    @property
    def template_count(self) -> int:
        return len(self._templates)

    def get_random_fingerprint(self) -> Dict[str, Any]:
        """Return a random fingerprint template with fresh noise seed."""
        fp = dict(random.choice(self._templates))
        fp["canvas_noise_seed"] = hashlib.md5(
            str(random.random()).encode()
        ).hexdigest()[:10]
        return fp

    def get_fingerprint_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Return a specific template by name."""
        for t in self._templates:
            if t["name"] == name:
                return dict(t)
        return None

    def list_templates(self) -> List[str]:
        """Return list of available template names."""
        return [t["name"] for t in self._templates]

    @staticmethod
    async def apply_fingerprint(page, fingerprint: Dict[str, Any]) -> None:
        """Inject fingerprint overrides into a Playwright page.

        Args:
            page: Playwright Page instance.
            fingerprint: Fingerprint dict from get_random_fingerprint().
        """
        js = """
        const fp = %s;
        // Navigator overrides
        Object.defineProperty(navigator, 'platform', { get: () => fp.platform });
        Object.defineProperty(navigator, 'languages', { get: () => fp.languages });
        Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => fp.hardwareConcurrency });
        Object.defineProperty(navigator, 'deviceMemory', { get: () => fp.deviceMemory });

        // WebGL overrides
        const getParameter = WebGLRenderingContext.prototype.getParameter;
        WebGLRenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) return fp.webglVendor;
            if (parameter === 37446) return fp.webglRenderer;
            return getParameter.apply(this, arguments);
        };

        // Canvas noise injection
        const toDataURL = HTMLCanvasElement.prototype.toDataURL;
        const seed = parseInt(fp.canvasNoiseSeed, 16) || 0;
        HTMLCanvasElement.prototype.toDataURL = function(type) {
            const ctx = this.getContext('2d');
            if (ctx) {
                const imageData = ctx.getImageData(0, 0, Math.min(this.width, 4), Math.min(this.height, 4));
                for (let i = 0; i < imageData.data.length; i += 4) {
                    imageData.data[i] = (imageData.data[i] + (seed % 3) - 1) & 0xff;
                }
                ctx.putImageData(imageData, 0, 0);
            }
            return toDataURL.apply(this, arguments);
        };
        """ % str({
            "platform": fingerprint.get("platform", "Win32"),
            "languages": fingerprint.get("languages", ["en-US"]),
            "hardwareConcurrency": fingerprint.get("hardware_concurrency", 8),
            "deviceMemory": fingerprint.get("device_memory", 8),
            "webglVendor": fingerprint.get("webgl_vendor", ""),
            "webglRenderer": fingerprint.get("webgl_renderer", ""),
            "canvasNoiseSeed": fingerprint.get("canvas_noise_seed", "0"),
        })
        await page.add_init_script(js)
