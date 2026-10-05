"""Business logic for the Soda Music track library."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from models.soda_song import SodaSong


SORT_OPTIONS = {
    "rank": (SodaSong.rank_position.is_(None), SodaSong.rank_position.asc(), SodaSong.heat.desc()),
    "heat": (SodaSong.heat.desc(), SodaSong.id.asc()),
    "newest": (SodaSong.id.desc(),),
    "title": (SodaSong.title.asc(), SodaSong.id.asc()),
}


SEED_SONGS: List[Dict[str, Any]] = [
    {"title": "罗刹海市", "artist": "刀郎", "album": "山歌寥哉", "genre": "民谣", "language": "国语",
     "duration_sec": 265, "heat": 986000, "rank_position": 1, "release_date": "2023-07-19", "tags": "爆款,热议"},
    {"title": "向云端", "artist": "小霞", "album": "向云端", "genre": "流行", "language": "国语",
     "duration_sec": 232, "heat": 874000, "rank_position": 2, "release_date": "2023-06-02", "tags": "治愈,合唱"},
    {"title": "乌梅子酱", "artist": "李荣浩", "album": "纵横四海", "genre": "流行", "language": "国语",
     "duration_sec": 218, "heat": 812000, "rank_position": 3, "release_date": "2022-12-21", "tags": "甜歌,短视频"},
    {"title": "孤勇者", "artist": "陈奕迅", "album": "孤勇者", "genre": "流行", "language": "国语",
     "duration_sec": 262, "heat": 796000, "rank_position": 4, "release_date": "2021-11-08", "tags": "影视OST,热血"},
    {"title": "可能", "artist": "程响", "album": "可能", "genre": "流行", "language": "国语",
     "duration_sec": 245, "heat": 752000, "rank_position": 5, "release_date": "2021-12-10", "tags": "翻唱,治愈"},
    {"title": "起风了", "artist": "买辣椒也用券", "album": "起风了", "genre": "民谣", "language": "国语",
     "duration_sec": 311, "heat": 731000, "rank_position": 6, "release_date": "2017-05-12", "tags": "翻唱,经典"},
    {"title": "大鱼", "artist": "周深", "album": "大鱼海棠", "genre": "古风", "language": "国语",
     "duration_sec": 313, "heat": 698000, "rank_position": 7, "release_date": "2016-06-23", "tags": "影视OST,空灵"},
    {"title": "光年之外", "artist": "邓紫棋", "album": "光年之外", "genre": "流行", "language": "国语",
     "duration_sec": 235, "heat": 664000, "rank_position": 8, "release_date": "2016-12-23", "tags": "影视OST,高音"},
    {"title": "夜曲", "artist": "周杰伦", "album": "十一月的萧邦", "genre": "R&B", "language": "国语",
     "duration_sec": 227, "heat": 641000, "rank_position": 9, "release_date": "2005-11-01", "tags": "经典,怀旧"},
    {"title": "晴天", "artist": "周杰伦", "album": "叶惠美", "genre": "流行", "language": "国语",
     "duration_sec": 269, "heat": 628000, "rank_position": 10, "release_date": "2003-07-31", "tags": "经典,青春"},
    {"title": "海阔天空", "artist": "Beyond", "album": "乐与怒", "genre": "摇滚", "language": "粤语",
     "duration_sec": 326, "heat": 597000, "rank_position": 11, "release_date": "1993-05-01", "tags": "经典,励志"},
    {"title": "富士山下", "artist": "陈奕迅", "album": "What's Going On...?", "genre": "流行", "language": "粤语",
     "duration_sec": 258, "heat": 566000, "rank_position": 12, "release_date": "2006-11-23", "tags": "经典,粤语情歌"},
    {"title": "漠河舞厅", "artist": "柳爽", "album": "1st.星球", "genre": "民谣", "language": "国语",
     "duration_sec": 276, "heat": 543000, "rank_position": 13, "release_date": "2021-04-25", "tags": "故事感,翻红"},
    {"title": "成都", "artist": "赵雷", "album": "无法长大", "genre": "民谣", "language": "国语",
     "duration_sec": 328, "heat": 519000, "rank_position": 14, "release_date": "2016-12-21", "tags": "城市,巡演必唱"},
    {"title": "易燃易爆炸", "artist": "陈粒", "album": "如也", "genre": "民谣", "language": "国语",
     "duration_sec": 258, "heat": 487000, "rank_position": 15, "release_date": "2015-02-02", "tags": "独立音乐,张力"},
    {"title": "挪威的森林", "artist": "伍佰", "album": "爱情的尽头", "genre": "摇滚", "language": "国语",
     "duration_sec": 344, "heat": 452000, "rank_position": 16, "release_date": "1996-06-01", "tags": "经典,摇滚"},
    {"title": "后来", "artist": "刘若英", "album": "我等你", "genre": "流行", "language": "国语",
     "duration_sec": 313, "heat": 428000, "rank_position": 17, "release_date": "1999-12-01", "tags": "经典,大合唱"},
    {"title": "野狼disco", "artist": "宝石Gem", "album": "野狼disco", "genre": "说唱", "language": "国语",
     "duration_sec": 293, "heat": 396000, "rank_position": 18, "release_date": "2019-09-02", "tags": "说唱,复古"},
    {"title": "白月光与朱砂痣", "artist": "大籽", "album": "白月光与朱砂痣", "genre": "流行", "language": "国语",
     "duration_sec": 227, "heat": 361000, "rank_position": 19, "release_date": "2020-08-10", "tags": "短视频,翻唱多"},
    {"title": "云与海", "artist": "阿YueYue", "album": "云与海", "genre": "古风", "language": "国语",
     "duration_sec": 245, "heat": 334000, "rank_position": 20, "release_date": "2020-05-20", "tags": "古风,翻唱"},
    {"title": "精卫", "artist": "曾舜晞", "album": "精卫", "genre": "古风", "language": "国语",
     "duration_sec": 251, "heat": 128000, "rank_position": None, "release_date": "2023-03-15", "tags": "潜力曲"},
    {"title": "雪 distance", "artist": "刘思鉴", "album": "雪 distance", "genre": "电子", "language": "国语",
     "duration_sec": 214, "heat": 96000, "rank_position": None, "release_date": "2022-11-18", "tags": "电子,氛围"},
    {"title": "晚安", "artist": "颜人中", "album": "晚安", "genre": "流行", "language": "国语",
     "duration_sec": 236, "heat": 87000, "rank_position": None, "release_date": "2019-11-22", "tags": "深夜,翻唱"},
]


def to_response(song: SodaSong) -> Dict[str, Any]:
    """Serialize a track into the API response shape."""
    total = max(0, int(song.duration_sec or 0))
    return {
        "id": song.id,
        "title": song.title,
        "artist": song.artist or "",
        "album": song.album,
        "genre": song.genre,
        "language": song.language,
        "duration_sec": total,
        "duration_text": "{:02d}:{:02d}".format(total // 60, total % 60),
        "heat": int(song.heat or 0),
        "rank_position": song.rank_position,
        "release_date": song.release_date,
        "tags": song.tags,
        "cover_url": song.cover_url,
        "remark": song.remark,
        "created_at": song.created_at,
        "updated_at": song.updated_at,
    }


def list_songs(
    db: Session,
    *,
    keyword: Optional[str] = None,
    genre: Optional[str] = None,
    language: Optional[str] = None,
    ranked_only: bool = False,
    sort: str = "rank",
    page: int = 1,
    page_size: int = 20,
) -> Tuple[int, List[SodaSong]]:
    """Return (total, page items) for the filtered track list."""
    query = db.query(SodaSong)

    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                SodaSong.title.like(like),
                SodaSong.artist.like(like),
                SodaSong.album.like(like),
                SodaSong.tags.like(like),
            )
        )
    if genre:
        query = query.filter(SodaSong.genre == genre)
    if language:
        query = query.filter(SodaSong.language == language)
    if ranked_only:
        query = query.filter(SodaSong.rank_position.isnot(None))

    total = query.count()
    order_by = SORT_OPTIONS.get(sort) or SORT_OPTIONS["rank"]
    page = max(1, int(page))
    page_size = min(200, max(1, int(page_size)))
    items = (
        query.order_by(*order_by)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return total, items


def get_song(db: Session, song_id: int) -> Optional[SodaSong]:
    return db.query(SodaSong).filter(SodaSong.id == int(song_id)).first()


def create_song(db: Session, payload: Dict[str, Any]) -> SodaSong:
    song = SodaSong(**payload)
    db.add(song)
    db.commit()
    db.refresh(song)
    return song


def update_song(db: Session, song: SodaSong, payload: Dict[str, Any]) -> SodaSong:
    for field, value in payload.items():
        setattr(song, field, value)
    db.commit()
    db.refresh(song)
    return song


def delete_song(db: Session, song: SodaSong) -> None:
    db.delete(song)
    db.commit()


def get_stats(db: Session) -> Dict[str, Any]:
    total = int(db.query(func.count(SodaSong.id)).scalar() or 0)
    artist_count = int(db.query(func.count(func.distinct(SodaSong.artist))).scalar() or 0)
    genre_count = int(
        db.query(func.count(func.distinct(SodaSong.genre)))
        .filter(SodaSong.genre.isnot(None))
        .scalar()
        or 0
    )
    ranked_count = int(
        db.query(func.count(SodaSong.id)).filter(SodaSong.rank_position.isnot(None)).scalar() or 0
    )
    total_heat = int(db.query(func.coalesce(func.sum(SodaSong.heat), 0)).scalar() or 0)
    avg_duration = int(db.query(func.coalesce(func.avg(SodaSong.duration_sec), 0)).scalar() or 0)

    top_row = (
        db.query(SodaSong.genre, func.count(SodaSong.id).label("total"))
        .filter(SodaSong.genre.isnot(None))
        .group_by(SodaSong.genre)
        .order_by(func.count(SodaSong.id).desc(), SodaSong.genre.asc())
        .first()
    )
    return {
        "total": total,
        "artist_count": artist_count,
        "genre_count": genre_count,
        "ranked_count": ranked_count,
        "total_heat": total_heat,
        "avg_duration_sec": avg_duration,
        "top_genre": top_row[0] if top_row else None,
    }


def get_filter_options(db: Session) -> Dict[str, List[str]]:
    genres = [
        row[0]
        for row in db.query(SodaSong.genre)
        .filter(SodaSong.genre.isnot(None))
        .distinct()
        .order_by(SodaSong.genre.asc())
        .all()
    ]
    languages = [
        row[0]
        for row in db.query(SodaSong.language)
        .filter(SodaSong.language.isnot(None))
        .distinct()
        .order_by(SodaSong.language.asc())
        .all()
    ]
    return {"genres": genres, "languages": languages}


def seed_songs(db: Session, *, reset: bool = False) -> Dict[str, int]:
    """Import the bundled sample tracks. Idempotent on (title, artist)."""
    removed = 0
    if reset:
        removed = int(db.query(SodaSong).delete() or 0)
        db.commit()

    existing = {(row.title, row.artist) for row in db.query(SodaSong.title, SodaSong.artist).all()}
    created = 0
    for item in SEED_SONGS:
        if (item["title"], item["artist"]) in existing:
            continue
        db.add(SodaSong(**item))
        created += 1
    if created:
        db.commit()

    total = int(db.query(func.count(SodaSong.id)).scalar() or 0)
    return {"created": created, "removed": removed, "skipped": len(SEED_SONGS) - created, "total": total}
