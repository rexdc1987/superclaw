"""
浏览器上下文工厂

功能：为每个账号创建隔离的浏览器上下文，集成反检测、Cookie 持久化、资源限制。
"""

import asyncio
import json
import logging
import os
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ContextFactory:
    """
    浏览器上下文工厂

    Features:
    - 每个账号独立的 BrowserContext（Cookie/Storage 隔离）
    - 自动集成反检测（Fingerprint + Stealth）
    - storage_state 持久化（保存/恢复登录状态）
    - 资源限制（最大并发上下文、空闲超时回收）
    """

    def __init__(
        self,
        browser,
        storage_dir: str = "./profiles",
        max_contexts: int = 10,
        idle_timeout: float = 600.0,
    ):
        """
        Args:
            browser: Playwright Browser 实例
            storage_dir: 存储状态文件的目录
            max_contexts: 最大并发上下文数
            idle_timeout: 空闲超时（秒），超过此时间未使用的上下文会被回收
        """
        self._browser = browser
        self._storage_dir = storage_dir
        self._max_contexts = max_contexts
        self._idle_timeout = idle_timeout
        self._contexts: Dict[str, dict] = {}  # account_id -> {context, last_used, ...}
        self._lock = asyncio.Lock()
        os.makedirs(storage_dir, exist_ok=True)

        # 反检测组件（可选注入）
        self._stealth = None
        self._fingerprint_manager = None

    def set_stealth(self, stealth) -> None:
        """注入 StealthMiddleware 实例"""
        self._stealth = stealth

    def set_fingerprint_manager(self, fm) -> None:
        """注入 FingerprintManager 实例"""
        self._fingerprint_manager = fm

    def _storage_path(self, account_id: str) -> str:
        return os.path.join(self._storage_dir, f"{account_id}_state.json")

    async def create_context(
        self,
        account_id: str,
        fingerprint: dict = None,
        proxy: dict = None,
        restore_state: bool = True,
        anti_detect: bool = True,
    ):
        """
        为账号创建隔离的浏览器上下文

        Args:
            account_id: 账号 ID
            fingerprint: 指纹配置 (viewport, user_agent, locale, timezone_id 等)
            proxy: 代理配置 ({server, username, password})
            restore_state: 是否恢复已保存的登录状态
            anti_detect: 是否应用反检测措施

        Returns:
            Playwright BrowserContext
        """
        async with self._lock:
            # 检查并发限制
            if (account_id not in self._contexts
                    and len(self._contexts) >= self._max_contexts):
                # 尝试回收空闲上下文
                await self._recycle_idle()
                if len(self._contexts) >= self._max_contexts:
                    raise RuntimeError(
                        f"Max contexts ({self._max_contexts}) reached, "
                        "cannot create new context"
                    )

            # 如果已有上下文，先关闭
            if account_id in self._contexts:
                try:
                    await self._contexts[account_id]["context"].close()
                except Exception:
                    pass

        context_opts = {}

        # 应用指纹
        if fingerprint:
            for key in ("viewport", "user_agent", "locale", "timezone_id"):
                if key in fingerprint:
                    context_opts[key] = fingerprint[key]

        # 应用代理
        if proxy:
            context_opts["proxy"] = proxy

        # 恢复已保存的状态
        state_path = self._storage_path(account_id)
        if restore_state and os.path.exists(state_path):
            context_opts["storage_state"] = state_path
            logger.debug("Restoring state for %s", account_id)

        # 禁用 HTTPS 错误提示
        context_opts["ignore_https_errors"] = True

        context = await self._browser.new_context(**context_opts)

        # 集成反检测
        if anti_detect:
            await self._apply_anti_detect(context, account_id)

        # 记录上下文
        self._contexts[account_id] = {
            "context": context,
            "last_used": time.time(),
            "created_at": time.time(),
        }
        logger.info("Created context for %s (total=%d)", account_id, len(self._contexts))
        return context

    async def _apply_anti_detect(self, context, account_id: str) -> None:
        """对上下文应用反检测措施"""
        # StealthMiddleware：注入反检测 JS
        if self._stealth:
            try:
                await self._stealth.apply(context)
                logger.debug("Applied stealth for %s", account_id)
            except Exception as e:
                logger.warning("Stealth apply failed for %s: %s", account_id, e)

        # FingerprintManager：注入指纹伪装
        if self._fingerprint_manager:
            try:
                profile = self._fingerprint_manager.random_profile()
                await profile.apply_to_context(context)
                logger.debug("Applied fingerprint '%s' for %s", profile.name, account_id)
            except Exception as e:
                logger.warning("Fingerprint apply failed for %s: %s", account_id, e)

    async def get_context(self, account_id: str):
        """获取已有上下文（更新 last_used）"""
        entry = self._contexts.get(account_id)
        if entry:
            entry["last_used"] = time.time()
            return entry["context"]
        return None

    async def save_state(self, account_id: str) -> Optional[str]:
        """
        保存账号的浏览器状态（Cookie + localStorage）

        Returns:
            保存路径或 None
        """
        entry = self._contexts.get(account_id)
        if not entry:
            return None

        state_path = self._storage_path(account_id)
        try:
            state = await entry["context"].storage_state()
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            logger.info("Saved state for %s -> %s", account_id, state_path)
            return state_path
        except Exception as e:
            logger.error("Failed to save state for %s: %s", account_id, e)
            return None

    async def close_context(self, account_id: str, save: bool = True) -> None:
        """关闭并可选保存上下文"""
        if save:
            await self.save_state(account_id)

        entry = self._contexts.pop(account_id, None)
        if entry:
            try:
                await entry["context"].close()
            except Exception:
                pass
            logger.info("Closed context for %s", account_id)

    async def close_all(self, save: bool = True) -> None:
        """关闭所有上下文"""
        account_ids = list(self._contexts.keys())
        for aid in account_ids:
            await self.close_context(aid, save=save)

    async def _recycle_idle(self) -> int:
        """回收空闲超时的上下文，返回回收数量"""
        now = time.time()
        recycled = 0
        to_close = []

        for account_id, entry in self._contexts.items():
            idle_time = now - entry["last_used"]
            if idle_time > self._idle_timeout:
                to_close.append(account_id)

        for account_id in to_close:
            await self.close_context(account_id, save=True)
            recycled += 1
            logger.info("Recycled idle context: %s", account_id)

        return recycled

    def has_context(self, account_id: str) -> bool:
        return account_id in self._contexts

    @property
    def active_count(self) -> int:
        return len(self._contexts)

    def stats(self) -> Dict:
        """获取上下文工厂统计"""
        return {
            "active_contexts": self.active_count,
            "max_contexts": self._max_contexts,
            "idle_timeout": self._idle_timeout,
            "accounts": list(self._contexts.keys()),
        }
