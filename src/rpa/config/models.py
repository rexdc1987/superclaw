"""
配置模型定义

基于 Pydantic BaseModel 的分层配置校验。
"""

from typing import Dict, List
from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    """应用基础配置"""
    name: str = "SuperClaw"
    version: str = "0.1.0"
    env: str = Field("production", pattern="^(development|staging|production)$")
    debug: bool = False
    log_level: str = Field("INFO", pattern="^(DEBUG|INFO|WARNING|ERROR)$")


class SchedulerConfig(BaseModel):
    """调度器配置"""
    max_instances: int = Field(1, ge=1, le=10)
    misfire_grace_time: int = Field(300, ge=0)
    persistent_store: bool = True
    db_path: str = "data/scheduler_jobs.db"


class QueueConfig(BaseModel):
    """队列配置"""
    type: str = Field("asyncio", pattern="^(asyncio|redis)$")
    redis_url: str = "redis://localhost:6379/0"
    max_workers: int = Field(5, ge=1, le=100)
    task_timeout: int = Field(600, ge=1)


class RateLimitItemConfig(BaseModel):
    """单个限流配置"""
    capacity: int = Field(..., ge=1)
    refill_rate: float = Field(..., gt=0)


class RateLimitConfig(BaseModel):
    """限流配置"""
    global_capacity: int = Field(100, ge=1)
    global_refill_rate: float = Field(1.67, gt=0)
    platforms: Dict[str, RateLimitItemConfig] = Field(default_factory=dict)
    actions: Dict[str, RateLimitItemConfig] = Field(default_factory=dict)


class RetryConfig(BaseModel):
    """重试配置"""
    max_retries: int = Field(3, ge=0, le=10)
    base_delay: float = Field(5.0, gt=0)
    max_delay: float = Field(300.0, gt=0)
    retryable_errors: List[str] = Field(default_factory=lambda: [
        "TimeoutError", "ConnectionError", "OSError"
    ])


class DatabaseConfig(BaseModel):
    """数据库配置"""
    url: str = "sqlite:///data/superclaw.db"
    echo: bool = False


class MonitoringConfig(BaseModel):
    """监控配置"""
    enabled: bool = True
    metrics_port: int = Field(9090, ge=1024, le=65535)
    alert_channel: str = "feishu"


class AccountsConfig(BaseModel):
    """账号配置"""
    strategy: str = Field("round_robin", pattern="^(round_robin|health_first|random|least_used)$")
    cooldown_seconds: int = Field(300, ge=0)
    max_consecutive_fails: int = Field(3, ge=1)


class SuperClawConfig(BaseModel):
    """SuperClaw 根配置"""
    app: AppConfig = Field(default_factory=AppConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    queue: QueueConfig = Field(default_factory=QueueConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    accounts: AccountsConfig = Field(default_factory=AccountsConfig)
