"""Pydantic schemas for Hongguo comment API"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ====== 任务 ======

class TaskCreate(BaseModel):
    """创建任务请求"""
    drama_name: str = Field(..., min_length=1, max_length=200, description="搜索剧名")
    comment_mode: str = Field(default="specified", description="评论模式: random/specified")
    start_episode: int = Field(default=1, ge=1, description="起始评论集数")
    episode_interval: int = Field(default=1, ge=1, description="每隔N集评论一次")
    comment_interval_sec: int = Field(default=30, ge=1, description="评论间隔秒数")
    random_comment_count: int = Field(default=10, ge=1, description="随机评论总次数")
    random_min_interval: int = Field(default=20, ge=1, description="随机最小间隔秒")
    random_max_interval: int = Field(default=60, ge=1, description="随机最大间隔秒")
    content_source: str = Field(default="ai", description="内容来源: ai/template/mixed")
    templates: List[str] = Field(default=[], description="模板列表")


class TaskUpdate(BaseModel):
    """更新任务请求"""
    drama_name: Optional[str] = None
    comment_mode: Optional[str] = None
    start_episode: Optional[int] = None
    episode_interval: Optional[int] = None
    comment_interval_sec: Optional[int] = None
    random_comment_count: Optional[int] = None
    random_min_interval: Optional[int] = None
    random_max_interval: Optional[int] = None
    content_source: Optional[str] = None
    templates: Optional[List[str]] = None


class TaskResponse(BaseModel):
    """任务响应"""
    id: int
    drama_name: str
    comment_mode: str
    start_episode: int
    episode_interval: int
    comment_interval_sec: int
    random_comment_count: int
    random_min_interval: int
    random_max_interval: int
    content_source: str
    templates_json: str
    status: str
    current_episode: int
    total_episodes: int
    comments_sent: int
    comments_verified: int
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    duration_seconds: Optional[int]
    created_at: datetime
    updated_at: Optional[datetime]
    progress_percent: float

    class Config:
        from_attributes = True


class TaskListResponse(BaseModel):
    """任务列表响应"""
    total: int
    items: List[TaskResponse]


# ====== 评论记录 ======

class RecordResponse(BaseModel):
    """评论记录响应"""
    id: int
    task_id: int
    episode_number: int
    episode_title: Optional[str]
    comment_text: str
    generated_by: Optional[str]
    status: str
    sent_at: Optional[datetime]
    verified_at: Optional[datetime]
    screenshot_input: Optional[str]
    screenshot_sent: Optional[str]
    screenshot_verified: Optional[str]
    screenshot_input_url: Optional[str] = None
    screenshot_sent_url: Optional[str] = None
    screenshot_verified_url: Optional[str] = None
    error_message: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class RecordListResponse(BaseModel):
    """评论记录列表响应"""
    total: int
    items: List[RecordResponse]


# ====== 执行日志 ======

class LogResponse(BaseModel):
    """执行日志响应"""
    id: int
    task_id: int
    level: str
    message: str
    screenshot_path: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class LogListResponse(BaseModel):
    """执行日志列表响应"""
    total: int
    items: List[LogResponse]


# ====== 模板 ======

class TemplateCreate(BaseModel):
    """创建模板请求"""
    name: Optional[str] = None
    content: str = Field(..., min_length=1, description="模板内容")
    category: Optional[str] = None


class TemplateResponse(BaseModel):
    """模板响应"""
    id: int
    name: Optional[str]
    content: str
    category: Optional[str]
    is_default: int
    use_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class TemplateListResponse(BaseModel):
    """模板列表响应"""
    total: int
    items: List[TemplateResponse]
