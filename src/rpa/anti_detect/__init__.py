"""SuperClaw Anti-Detect Module."""
from .stealth import StealthMiddleware
from .fingerprint import FingerprintManager
from .behavior import BehaviorSimulator
from .proxy_manager import ProxyManager
from .captcha_adapter import CaptchaAdapter, TwoCaptchaAdapter

__all__ = [
    "StealthMiddleware",
    "FingerprintManager", 
    "BehaviorSimulator",
    "ProxyManager",
    "CaptchaAdapter",
    "TwoCaptchaAdapter",
]
