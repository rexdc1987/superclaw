"""Scheduler - daily reset and maintenance tasks"""
import threading
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class Scheduler:
    """Background scheduler for periodic tasks"""

    def __init__(self):
        self._running = False
        self._thread = None

    def start(self):
        """Start the scheduler in background thread"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("Scheduler started")

    def stop(self):
        self._running = False
        logger.info("Scheduler stopped")

    def _run(self):
        last_reset_date = None
        while self._running:
            now = datetime.now()
            # Reset daily counters once per calendar day (not tied to hour=0)
            if last_reset_date != now.date():
                try:
                    from services.account_service import AccountService
                    AccountService().reset_daily_counters()
                    last_reset_date = now.date()
                    logger.info(f"Daily counters reset at {now}")
                except Exception as e:
                    logger.error(f"Daily reset failed: {e}")

            time.sleep(60)  # Check every minute


# Global scheduler instance
_scheduler = None


def get_scheduler():
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler
