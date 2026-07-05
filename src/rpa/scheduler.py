"""
RPA 任务调度器 - Phase 1 产出
支持定时任务、任务状态机、指数退避重试、多层限流

用法示例：
    from rpa.scheduler import SuperClawScheduler
    
    scheduler = SuperClawScheduler()
    
    # 添加定时任务
    scheduler.add_cron_job('daily_cleanup', cleanup_task, hour=2, minute=0)
    
    # 提交一次性任务
    task_id = scheduler.submit_task(search_task, args=['python', 'douyin'])
    
    # 查看状态
    status = scheduler.get_task_status(task_id)
"""

import logging

import time
import random
import asyncio
from enum import Enum
from dataclasses import dataclass, field
from typing import Callable, Optional, Dict, Any, List
from datetime import datetime
from pathlib import Path

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.date import DateTrigger
    from apscheduler.jobstores.memory import MemoryJobStore
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False

logger = logging.getLogger(__name__)


# ============================================================
# 任务状态机
# ============================================================

class TaskStatus(Enum):
    """任务状态"""
    DRAFT = 'draft'
    QUEUED = 'queued'
    RUNNING = 'running'
    PAUSED = 'paused'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


# 合法的状态转换
VALID_TRANSITIONS: Dict[TaskStatus, List[TaskStatus]] = {
    TaskStatus.DRAFT:     [TaskStatus.QUEUED, TaskStatus.CANCELLED],
    TaskStatus.QUEUED:    [TaskStatus.RUNNING, TaskStatus.CANCELLED],
    TaskStatus.RUNNING:   [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.PAUSED, TaskStatus.CANCELLED],
    TaskStatus.PAUSED:    [TaskStatus.RUNNING, TaskStatus.CANCELLED],
    TaskStatus.FAILED:    [TaskStatus.QUEUED, TaskStatus.CANCELLED],  # QUEUED = 重试
    TaskStatus.COMPLETED: [],
    TaskStatus.CANCELLED: [],
}


def can_transition(from_status: TaskStatus, to_status: TaskStatus) -> bool:
    """检查状态转换是否合法"""
    return to_status in VALID_TRANSITIONS.get(from_status, [])


@dataclass
class TaskRecord:
    """任务记录"""
    task_id: str
    name: str
    status: TaskStatus = TaskStatus.DRAFT
    func_name: str = ''
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    priority: int = 50  # 0=最高, 100=最低
    
    # 重试信息
    attempt: int = 0
    max_retries: int = 3
    base_delay: float = 5.0
    max_delay: float = 300.0
    
    # 时间戳
    created_at: str = ''
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    next_retry_at: Optional[str] = None
    
    # 结果
    result: Any = None
    error: Optional[str] = None
    
    # 平台/账号信息
    platform: Optional[str] = None
    account_id: Optional[str] = None
    action_type: Optional[str] = None

    def transition_to(self, new_status: TaskStatus) -> bool:
        if can_transition(self.status, new_status):
            old = self.status
            self.status = new_status
            now = datetime.now().isoformat()
            if new_status == TaskStatus.RUNNING:
                self.started_at = now
            elif new_status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                self.completed_at = now
            logger.info(f"任务 {self.task_id}: {old.value} → {new_status.value}")
            return True
        logger.warning(f"非法状态转换: {self.status.value} → {new_status.value} (任务 {self.task_id})")
        return False


# ============================================================
# 令牌桶限流器
# ============================================================

class TokenBucket:
    """令牌桶限流器"""
    
    def __init__(self, capacity: int, refill_rate: float):
        """
        Args:
            capacity: 桶容量（最大令牌数）
            refill_rate: 每秒填充的令牌数
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()
    
    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
    
    def acquire(self) -> bool:
        self._refill()
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False
    
    async def wait(self):
        while not self.acquire():
            wait_time = (1 - self.tokens) / self.refill_rate
            await asyncio.sleep(min(wait_time, 0.1))


class RateLimitManager:
    """多层限流管理器"""
    
    # 各操作默认限流配置：(capacity, refill_rate_per_second)
    DEFAULT_LIMITS = {
        'comment': (20, 20 / 60),    # 20条/分钟
        'follow': (50, 50 / 3600),   # 50个/小时
        'dm': (20, 20 / 3600),       # 20条/小时
        'search': (10, 10 / 60),     # 10次/分钟
        'like': (30, 30 / 60),       # 30次/分钟
    }
    
    def __init__(self):
        self.global_limiter = TokenBucket(capacity=100, refill_rate=100 / 60)
        self.platform_limiters: Dict[str, TokenBucket] = {}
        self.account_limiters: Dict[str, TokenBucket] = {}
    
    def configure_platform(self, platform: str, capacity: int, refill_rate: float):
        self.platform_limiters[platform] = TokenBucket(capacity, refill_rate)
    
    async def acquire(self, account_id: str, platform: str, action_type: str) -> bool:
        """获取操作令牌，通过所有层级限流检查"""
        # 全局限流
        if not self.global_limiter.acquire():
            return False
        
        # 平台限流
        plat_limiter = self.platform_limiters.get(platform)
        if plat_limiter and not plat_limiter.acquire():
            return False
        
        # 账号+操作限流
        key = f"{account_id}:{action_type}"
        if key not in self.account_limiters:
            cap, rate = self.DEFAULT_LIMITS.get(action_type, (10, 10 / 60))
            self.account_limiters[key] = TokenBucket(capacity=cap, refill_rate=rate)
        
        return self.account_limiters[key].acquire()
    
    async def wait_for_token(self, account_id: str, platform: str, action_type: str):
        """等待直到获取令牌"""
        while not await self.acquire(account_id, platform, action_type):
            await asyncio.sleep(1)


# ============================================================
# 指数退避重试
# ============================================================

def calculate_retry_delay(attempt: int, base_delay: float = 5.0, max_delay: float = 300.0) -> float:
    """计算指数退避等待时间（含随机抖动）"""
    delay = base_delay * (2 ** attempt)
    jitter = random.uniform(0, delay * 0.1)
    return min(delay + jitter, max_delay)


# 错误分类
RETRYABLE_ERRORS = (TimeoutError, ConnectionError, OSError)
NON_RETRYABLE_ERRORS = (ValueError, PermissionError, KeyError)


# ============================================================
# 调度器主类
# ============================================================

class SuperClawScheduler:
    """
    SuperClaw 任务调度器
    
    整合：APScheduler（定时触发）+ 任务状态机 + 令牌桶限流 + 指数退避重试
    """
    
    def __init__(
        self,
        use_persistent_store: bool = True,
        db_path: str = 'data/scheduler_jobs.db',
        max_instances: int = 1,
    ):
        self.tasks: Dict[str, TaskRecord] = {}
        self.rate_limiter = RateLimitManager()
        self._task_history: Dict[str, list] = {}
        
        # APScheduler 初始化
        if HAS_APSCHEDULER:
            jobstores = {'default': MemoryJobStore()}
            if use_persistent_store:
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
                jobstores['default'] = SQLAlchemyJobStore(url=f'sqlite:///{db_path}')
            
            self.scheduler = BackgroundScheduler(
                jobstores=jobstores,
                job_defaults={
                    'coalesce': True,
                    'max_instances': max_instances,
                    'misfire_grace_time': 300
                }
            )
            self.scheduler.add_listener(self._on_job_event,
                EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED)
        else:
            self.scheduler = None
            logger.warning("APScheduler 未安装，定时调度不可用")
    
    # ---- 定时任务 ----
    
    def add_cron_job(self, job_id: str, func: Callable, name: Optional[str] = None, **cron_kwargs) -> str:
        if not self.scheduler:
            raise RuntimeError("APScheduler 未安装")
        trigger = CronTrigger(**cron_kwargs)
        self.scheduler.add_job(func=func, trigger=trigger, id=job_id, name=name or job_id, replace_existing=True)
        logger.info(f"添加 Cron 任务: {job_id}")
        return job_id
    
    def add_interval_job(self, job_id: str, func: Callable, name: Optional[str] = None, **interval_kwargs) -> str:
        if not self.scheduler:
            raise RuntimeError("APScheduler 未安装")
        trigger = IntervalTrigger(**interval_kwargs)
        self.scheduler.add_job(func=func, trigger=trigger, id=job_id, name=name or job_id, replace_existing=True)
        logger.info(f"添加 Interval 任务: {job_id}")
        return job_id
    
    def add_once_job(self, job_id: str, func: Callable, run_date: str, name: Optional[str] = None) -> str:
        if not self.scheduler:
            raise RuntimeError("APScheduler 未安装")
        trigger = DateTrigger(run_date=run_date)
        self.scheduler.add_job(func=func, trigger=trigger, id=job_id, name=name or job_id, replace_existing=True)
        logger.info(f"添加一次性任务: {job_id}")
        return job_id
    
    # ---- 一次性任务提交 ----
    
    def submit_task(
        self,
        func: Callable,
        args: tuple = (),
        kwargs: dict = None,
        name: Optional[str] = None,
        priority: int = 50,
        max_retries: int = 3,
        platform: Optional[str] = None,
        account_id: Optional[str] = None,
        action_type: Optional[str] = None,
    ) -> str:
        """提交一次性任务，返回 task_id"""
        import uuid
        task_id = f"task_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        
        record = TaskRecord(
            task_id=task_id,
            name=name or func.__name__,
            func_name=func.__name__,
            args=args,
            kwargs=kwargs or {},
            priority=priority,
            max_retries=max_retries,
            created_at=datetime.now().isoformat(),
            platform=platform,
            account_id=account_id,
            action_type=action_type,
        )
        record.transition_to(TaskStatus.QUEUED)
        self.tasks[task_id] = record
        logger.info(f"任务已提交: {task_id} ({record.name})")
        return task_id
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self.tasks.get(task_id)
        if not task:
            return None
        return {
            'task_id': task.task_id,
            'name': task.name,
            'status': task.status.value,
            'attempt': task.attempt,
            'max_retries': task.max_retries,
            'created_at': task.created_at,
            'started_at': task.started_at,
            'completed_at': task.completed_at,
            'error': task.error,
            'platform': task.platform,
            'account_id': task.account_id,
        }
    
    def cancel_task(self, task_id: str) -> bool:
        task = self.tasks.get(task_id)
        if task:
            return task.transition_to(TaskStatus.CANCELLED)
        return False
    
    def pause_task(self, task_id: str) -> bool:
        task = self.tasks.get(task_id)
        if task:
            return task.transition_to(TaskStatus.PAUSED)
        return False
    
    def resume_task(self, task_id: str) -> bool:
        task = self.tasks.get(task_id)
        if task:
            return task.transition_to(TaskStatus.RUNNING)
        return False
    
    def retry_task(self, task_id: str) -> bool:
        task = self.tasks.get(task_id)
        if task and task.status == TaskStatus.FAILED:
            return task.transition_to(TaskStatus.QUEUED)
        return False
    
    # ---- 事件监听 ----
    
    def _on_job_event(self, event):
        job_id = event.job_id
        if job_id not in self._task_history:
            self._task_history[job_id] = []
        
        if event.exception:
            record = {'status': 'error', 'timestamp': datetime.now().isoformat(), 'error': str(event.exception)}
        elif hasattr(event, 'scheduled_run_time'):
            record = {'status': 'missed', 'timestamp': datetime.now().isoformat()}
        else:
            record = {'status': 'success', 'timestamp': datetime.now().isoformat()}
        
        self._task_history[job_id].append(record)
        if len(self._task_history[job_id]) > 100:
            self._task_history[job_id] = self._task_history[job_id][-100:]
    
    # ---- 生命周期 ----
    
    def start(self):
        if self.scheduler and not self.scheduler.running:
            self.scheduler.start()
            logger.info("调度器已启动")
    
    def stop(self):
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=True)
            logger.info("调度器已停止")
    
    def list_jobs(self) -> list:
        if not self.scheduler:
            return []
        return [
            {'id': j.id, 'name': j.name, 'trigger': str(j.trigger),
             'next_run_time': str(j.next_run_time) if j.next_run_time else None}
            for j in self.scheduler.get_jobs()
        ]
    
    def list_tasks(self, status: Optional[TaskStatus] = None) -> list:
        tasks = self.tasks.values()
        if status:
            tasks = [t for t in tasks if t.status == status]
        return [
            {'task_id': t.task_id, 'name': t.name, 'status': t.status.value,
             'platform': t.platform, 'attempt': t.attempt}
            for t in tasks
        ]
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False


# ============================================================
# 使用示例
# ============================================================

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    def sample_search(keyword, platform):
        print(f"搜索: {keyword} @ {platform}")
        return {'results': 10}
    
    scheduler = SuperClawScheduler(use_persistent_store=False)
    
    # 添加定时任务
    scheduler.add_interval_job('monitor', lambda: print("监控中..."), minutes=30)
    
    # 提交一次性任务
    task_id = scheduler.submit_task(
        sample_search,
        args=('python', 'douyin'),
        name='搜索python',
        platform='douyin',
        account_id='acc_001',
        action_type='search'
    )
    
    print(f"任务ID: {task_id}")
    print(f"状态: {scheduler.get_task_status(task_id)}")
    
    # 测试状态转换
    scheduler.start()
    print(f"\n定时任务: {scheduler.list_jobs()}")
    scheduler.stop()
