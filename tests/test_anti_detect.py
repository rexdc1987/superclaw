"""Unit tests for anti-detect module."""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


# === StealthMiddleware Tests ===

class TestStealthMiddleware:
    def test_stealth_args_contains_key_flags(self):
        """Stealth args should include critical anti-detection flags."""
        from src.rpa.anti_detect.stealth import StealthMiddleware
        args = StealthMiddleware.get_stealth_args()
        assert any("AutomationControlled" in a for a in args)
        assert any("disable-dev-shm-usage" in a for a in args)
        assert any("webrtc" in a.lower() for a in args)

    def test_random_user_agent_varies(self):
        """Random UA should return different values on repeated calls."""
        from src.rpa.anti_detect.stealth import StealthMiddleware
        uas = {StealthMiddleware.random_user_agent() for _ in range(20)}
        assert len(uas) >= 3, "UA generator should produce variety"

    def test_stealth_args_returns_list(self):
        """get_stealth_args should return a non-empty list of strings."""
        from src.rpa.anti_detect.stealth import StealthMiddleware
        args = StealthMiddleware.get_stealth_args()
        assert isinstance(args, list)
        assert len(args) > 0
        assert all(isinstance(a, str) for a in args)


# === FingerprintManager Tests ===

class TestFingerprintManager:
    def test_template_count(self):
        """Should have at least 5 fingerprint templates."""
        from src.rpa.anti_detect.fingerprint import FingerprintManager
        fm = FingerprintManager()
        assert fm.template_count >= 5

    def test_template_names_unique(self):
        """Template names should be unique."""
        from src.rpa.anti_detect.fingerprint import FingerprintManager
        fm = FingerprintManager()
        names = fm.list_templates()
        assert len(names) == len(set(names))

    def test_random_fingerprint_has_required_fields(self):
        """Random fingerprint should include all required fields."""
        from src.rpa.anti_detect.fingerprint import FingerprintManager
        fm = FingerprintManager()
        fp = fm.get_random_fingerprint()
        required = ["user_agent", "viewport", "platform", "languages",
                     "webgl_vendor", "webgl_renderer", "canvas_noise_seed"]
        for field in required:
            assert field in fp, f"Missing field: {field}"

    def test_random_fingerprint_varies_seed(self):
        """Canvas noise seed should differ between calls."""
        from src.rpa.anti_detect.fingerprint import FingerprintManager
        fm = FingerprintManager()
        seeds = {fm.get_random_fingerprint()["canvas_noise_seed"] for _ in range(10)}
        assert len(seeds) >= 5, "Noise seeds should be varied"

    def test_get_by_name_found(self):
        """Should retrieve template by exact name."""
        from src.rpa.anti_detect.fingerprint import FingerprintManager
        fm = FingerprintManager()
        fp = fm.get_fingerprint_by_name("Windows Chrome 126")
        assert fp is not None
        assert fp["platform"] == "Win32"

    def test_get_by_name_not_found(self):
        """Should return None for unknown name."""
        from src.rpa.anti_detect.fingerprint import FingerprintManager
        fm = FingerprintManager()
        assert fm.get_fingerprint_by_name("Nonexistent") is None

    def test_viewport_dimensions(self):
        """Viewports should have reasonable dimensions."""
        from src.rpa.anti_detect.fingerprint import FingerprintManager
        fm = FingerprintManager()
        for name in fm.list_templates():
            fp = fm.get_fingerprint_by_name(name)
            assert fp["viewport"]["width"] >= 1024
            assert fp["viewport"]["height"] >= 768


# === BehaviorSimulator Tests ===

class TestBehaviorSimulator:
    @pytest.mark.asyncio
    async def test_random_delay_range(self):
        """Random delay should respect min/max bounds (roughly)."""
        from src.rpa.anti_detect.behavior import BehaviorSimulator
        import time
        start = time.monotonic()
        await BehaviorSimulator.random_delay(50, 150)
        elapsed_ms = (time.monotonic() - start) * 1000
        assert 30 < elapsed_ms < 300  # generous bounds for CI

    @pytest.mark.asyncio
    async def test_mouse_move_points(self):
        """Mouse move should produce the expected number of intermediate points."""
        from src.rpa.anti_detect.behavior import BehaviorSimulator
        mock_page = MagicMock()
        mock_page.mouse = MagicMock()
        mock_page.mouse.move = AsyncMock()

        await BehaviorSimulator.human_mouse_move(
            mock_page, (0, 0), (100, 100), steps=10
        )
        # Should call move() exactly steps+1 times (0..steps inclusive)
        assert mock_page.mouse.move.call_count == 11


# === ProxyManager Tests ===

class TestProxyManager:
    def test_add_and_count(self):
        """Adding proxies should increase pool size."""
        from src.rpa.anti_detect.proxy_manager import ProxyManager, Proxy, ProxyProtocol
        pm = ProxyManager()
        assert pm.pool_size == 0
        pm.add_proxy(Proxy("1.2.3.4", 8080))
        assert pm.pool_size == 1
        pm.add_proxies([
            Proxy("5.6.7.8", 3128),
            Proxy("9.10.11.12", 1080, ProxyProtocol.SOCKS5),
        ])
        assert pm.pool_size == 3

    def test_remove_proxy(self):
        """Removing proxy should decrease pool size."""
        from src.rpa.anti_detect.proxy_manager import ProxyManager, Proxy
        pm = ProxyManager()
        pm.add_proxy(Proxy("1.2.3.4", 8080))
        assert pm.remove_proxy("1.2.3.4", 8080) is True
        assert pm.pool_size == 0
        assert pm.remove_proxy("nonexistent", 0) is False

    def test_get_proxy_returns_proxy(self):
        """get_proxy should return a Proxy when pool is non-empty."""
        from src.rpa.anti_detect.proxy_manager import ProxyManager, Proxy
        pm = ProxyManager()
        pm.add_proxy(Proxy("1.2.3.4", 8080))
        p = pm.get_proxy()
        assert p is not None
        assert p.host == "1.2.3.4"

    def test_get_proxy_empty_pool(self):
        """get_proxy should return None when pool is empty."""
        from src.rpa.anti_detect.proxy_manager import ProxyManager
        pm = ProxyManager()
        assert pm.get_proxy() is None

    def test_mark_failed_disables_proxy(self):
        """Proxy should become unhealthy after max_fails consecutive failures."""
        from src.rpa.anti_detect.proxy_manager import ProxyManager, Proxy
        pm = ProxyManager(max_fails=3)
        pm.add_proxy(Proxy("1.2.3.4", 8080))
        p = pm._proxies[0]
        assert p.is_healthy is True
        for _ in range(3):
            pm.mark_failed(p)
        assert p.is_healthy is False

    def test_mark_success_restores_health(self):
        """Successful request should restore proxy health."""
        from src.rpa.anti_detect.proxy_manager import ProxyManager, Proxy
        pm = ProxyManager()
        pm.add_proxy(Proxy("1.2.3.4", 8080))
        p = pm._proxies[0]
        p.is_healthy = False
        pm.mark_success(p)
        assert p.is_healthy is True

    def test_parse_proxy_url(self):
        """Should correctly parse proxy URLs."""
        from src.rpa.anti_detect.proxy_manager import ProxyManager, ProxyProtocol
        p = ProxyManager.parse_proxy_url("socks5://user:pass@10.0.0.1:1080")
        assert p.host == "10.0.0.1"
        assert p.port == 1080
        assert p.protocol == ProxyProtocol.SOCKS5
        assert p.username == "user"
        assert p.password == "pass"

    def test_proxy_url_property(self):
        """Proxy.url should format correctly."""
        from src.rpa.anti_detect.proxy_manager import Proxy, ProxyProtocol
        p = Proxy("1.2.3.4", 8080, ProxyProtocol.HTTP, "user", "pass")
        assert p.url == "http://user:pass@1.2.3.4:8080"


# === CaptchaAdapter Tests ===

class TestCaptchaAdapter:
    def test_abstract_interface(self):
        """CaptchaAdapter should not be instantiable directly."""
        from src.rpa.anti_detect.captcha_adapter import CaptchaAdapter
        with pytest.raises(TypeError):
            CaptchaAdapter()

    def test_two_captcha_init(self):
        """TwoCaptchaAdapter should store api_key and timeout."""
        from src.rpa.anti_detect.captcha_adapter import TwoCaptchaAdapter
        adapter = TwoCaptchaAdapter(api_key="test123", timeout=60)
        assert adapter._api_key == "test123"
        assert adapter._timeout == 60
