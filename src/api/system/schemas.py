"""Schemas for the system / update endpoints."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class BuildInfoResponse(BaseModel):
    version: str = Field(description="当前版本号（读自磁盘 VERSION）")
    loaded_version: str = Field(default="", description="本进程实际加载的代码版本；与 version 不一致说明该重启了")
    code_current: bool = Field(default=True, description="服务是否正在运行已安装的最新代码")
    runtime_pid: int = Field(default=0, description="服务进程号")
    started_at: str = Field(default="", description="本进程启动时间")
    git_sha: str = Field(default="unknown", description="构建时的 git 提交")
    built_at: Optional[str] = Field(default=None, description="构建时间")
    edition: str = Field(default="server", description="发行版本")
    execution_mode: str = Field(default="api", description="当前执行模式")
    install_root: str = Field(default="", description="安装目录")
    update_repo: str = Field(default="", description="自动更新源 owner/repo，空表示未配置")


class UpdateAssetResponse(BaseModel):
    name: str = Field(description="附件文件名")
    size: int = Field(default=0, description="字节数")
    url: str = Field(default="", description="下载地址")
    sha256: str = Field(default="", description="附件旁提供的 sha256，可能为空")


class UpdateCheckResponse(BaseModel):
    configured: bool = Field(default=False, description="是否配置了更新源")
    update_available: bool = Field(default=False, description="是否有新版本")
    current_version: str = Field(default="", description="当前版本")
    latest_version: str = Field(default="", description="远端最新版本")
    notes: str = Field(default="", description="版本说明")
    published_at: str = Field(default="", description="发布时间")
    release_url: str = Field(default="", description="发行版页面地址")
    asset: Optional[UpdateAssetResponse] = Field(default=None, description="更新包附件")
    message: str = Field(default="", description="给用户看的提示")


class UpdateStatusResponse(BaseModel):
    phase: str = Field(description="idle/checking/downloading/ready/applying/failed")
    version: str = Field(default="", description="本次操作的版本号")
    progress: float = Field(default=0.0, description="下载进度 0-1")
    downloaded_bytes: int = Field(default=0)
    total_bytes: int = Field(default=0)
    message: str = Field(default="")
    error: str = Field(default="")


class UpdateActionResponse(BaseModel):
    ok: bool
    message: str
    status: UpdateStatusResponse
