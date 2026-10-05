"""API routes for the Soda Music track library."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.deps import get_db
from api.security import require_admin
from api.soda import service
from models.soda_song import SodaSong
from api.soda.schemas import (
    SodaFilterOptionsResponse,
    SodaSongListResponse,
    SodaSongPayload,
    SodaSongResponse,
    SodaSongStatsResponse,
)


router = APIRouter(prefix="/api/v1/soda", tags=["soda"])


# ====== 统计与筛选 ======

@router.get("/stats", response_model=SodaSongStatsResponse, summary="曲库概览统计")
def get_stats(db: Session = Depends(get_db)):
    return service.get_stats(db)


@router.get("/filters", response_model=SodaFilterOptionsResponse, summary="可筛选的曲风与语种")
def get_filters(db: Session = Depends(get_db)):
    return service.get_filter_options(db)


# ====== 曲目 ======

@router.get("/songs", response_model=SodaSongListResponse, summary="曲目列表")
def list_songs(
    keyword: Optional[str] = Query(default=None, max_length=100, description="按曲名/歌手/专辑/标签模糊搜索"),
    genre: Optional[str] = Query(default=None, max_length=50),
    language: Optional[str] = Query(default=None, max_length=50),
    ranked_only: bool = Query(default=False, description="仅看已上榜曲目"),
    sort: str = Query(default="rank", description="rank | heat | newest | title"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    total, items = service.list_songs(
        db,
        keyword=keyword,
        genre=genre,
        language=language,
        ranked_only=ranked_only,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [service.to_response(song) for song in items],
    }


@router.get("/songs/{song_id}", response_model=SodaSongResponse, summary="曲目详情")
def get_song(song_id: int, db: Session = Depends(get_db)):
    song = service.get_song(db, song_id)
    if not song:
        raise HTTPException(status_code=404, detail="曲目不存在")
    return service.to_response(song)


@router.post(
    "/songs",
    response_model=SodaSongResponse,
    summary="新增曲目",
    dependencies=[Depends(require_admin)],
)
def create_song(payload: SodaSongPayload, db: Session = Depends(get_db)):
    existing = (
        db.query(SodaSong)
        .filter(SodaSong.title == payload.title, SodaSong.artist == payload.artist)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="同一歌手的同名曲目已存在")
    song = service.create_song(db, payload.model_dump())
    return service.to_response(song)


@router.put(
    "/songs/{song_id}",
    response_model=SodaSongResponse,
    summary="更新曲目",
    dependencies=[Depends(require_admin)],
)
def update_song(song_id: int, payload: SodaSongPayload, db: Session = Depends(get_db)):
    song = service.get_song(db, song_id)
    if not song:
        raise HTTPException(status_code=404, detail="曲目不存在")
    song = service.update_song(db, song, payload.model_dump(exclude_unset=True))
    return service.to_response(song)


@router.delete(
    "/songs/{song_id}",
    summary="删除曲目",
    dependencies=[Depends(require_admin)],
)
def delete_song(song_id: int, db: Session = Depends(get_db)):
    song = service.get_song(db, song_id)
    if not song:
        raise HTTPException(status_code=404, detail="曲目不存在")
    service.delete_song(db, song)
    return {"message": "删除成功"}


# ====== 示例数据 ======

@router.post(
    "/seed",
    summary="导入内置示例曲目",
    dependencies=[Depends(require_admin)],
)
def seed_songs(
    reset: bool = Query(default=False, description="先清空曲库再导入"),
    db: Session = Depends(get_db),
):
    return service.seed_songs(db, reset=reset)
