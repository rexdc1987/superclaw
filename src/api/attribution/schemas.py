"""机器归属接口的请求/响应模型。

响应大多是聚合结果，字段随统计口径演进，所以只对**入参**做强校验，
返回值直接用 dict（与 `routes_hongguo` 的既有风格一致）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BindRequest(BaseModel):
    """把一台机器归属给某个账号。"""

    username: str = Field(..., min_length=1, max_length=64, description="归属账号的登录名")
    force: bool = Field(
        False,
        description="机器已有别的归属时是否强制覆盖（会写进 owner_conflict 留痕）",
    )


class BindResponse(BaseModel):
    worker_id: str
    owner_user_id: int
    owner_username: str
    forced: bool = False
    previous_owner: str = ""
    tasks_backfilled: int = 0
    bound_at: str = ""
