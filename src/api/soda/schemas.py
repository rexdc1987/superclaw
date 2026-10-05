"""Pydantic schemas for the Soda Music library API."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class SodaSongPayload(BaseModel):
    """Write payload for creating or updating a track."""

    title: str = Field(..., min_length=1, max_length=200, description="曲名")
    artist: str = Field(default="", max_length=200, description="歌手")
    album: Optional[str] = Field(default=None, max_length=200, description="专辑")
    genre: Optional[str] = Field(default=None, max_length=50, description="曲风")
    language: Optional[str] = Field(default=None, max_length=50, description="语种")
    duration_sec: int = Field(default=0, ge=0, le=86400, description="时长(秒)")
    heat: int = Field(default=0, ge=0, description="热度值")
    rank_position: Optional[int] = Field(default=None, ge=1, le=9999, description="榜单排名")
    release_date: Optional[str] = Field(default=None, max_length=20, description="发行日期")
    tags: Optional[str] = Field(default=None, max_length=200, description="标签, 逗号分隔")
    cover_url: Optional[str] = Field(default=None, max_length=500, description="封面地址")
    remark: Optional[str] = Field(default=None, max_length=1000, description="备注")

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("曲名不能为空")
        return value

    @field_validator("artist")
    @classmethod
    def normalize_artist(cls, value: Optional[str]) -> str:
        return (value or "").strip()

    @field_validator("album", "genre", "language", "tags", "cover_url", "remark", "release_date")
    @classmethod
    def normalize_optional(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None


class SodaSongResponse(BaseModel):
    id: int
    title: str
    artist: str
    album: Optional[str] = None
    genre: Optional[str] = None
    language: Optional[str] = None
    duration_sec: int = 0
    duration_text: str = "00:00"
    heat: int = 0
    rank_position: Optional[int] = None
    release_date: Optional[str] = None
    tags: Optional[str] = None
    cover_url: Optional[str] = None
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SodaSongListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[SodaSongResponse]


class SodaSongStatsResponse(BaseModel):
    total: int
    artist_count: int
    genre_count: int
    ranked_count: int
    total_heat: int
    avg_duration_sec: int
    top_genre: Optional[str] = None


class SodaFilterOptionsResponse(BaseModel):
    genres: List[str]
    languages: List[str]
