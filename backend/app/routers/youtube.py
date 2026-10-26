"""/api/youtube — channels, videos (TW-Labs-style filters), community posts."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings
from ..database import get_db
from ..models import AppState, Article, Channel, CommunityPost, JobRequest, Site, Video
from ..schemas import ArticleOut
from .articles import _to_out as article_out
from ..timeutil import as_utc, utcnow
from ..youtube import YouTubeClient, YouTubeError, add_channel, channel_stats, embed_counts, usage_today

router = APIRouter(prefix="/api/youtube", tags=["youtube"])
IST = timezone(timedelta(hours=5, minutes=30))


class ChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    external_id: str
    handle: str
    name: str
    avatar_url: str | None
    subscriber_count: int | None
    cohort: str | None
    site_id: int | None
    site_name: str | None = None
    is_active: bool
    track_posts: bool
    created_at: datetime
    last_scraped_at: datetime | None
    posts_scraped_at: datetime | None
    last_error: str | None
    video_count: int = 0
    median_views_last10: int | None = None
    last_published_at: datetime | None = None


class ChannelCreate(BaseModel):
    handle: str = Field(min_length=2, max_length=200)
    cohort: str | None = Field(default=None, max_length=60)
    site_id: int | None = None


class ChannelUpdate(BaseModel):
    cohort: str | None = Field(default=None, max_length=60)
    site_id: int | None = None
    is_active: bool | None = None
    track_posts: bool | None = None
    clear_site: bool = False


class VideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    channel_id: int
    channel_name: str = ""
    channel_avatar_url: str | None = None
    title: str
    thumbnail_url: str | None
    url: str = ""
    views: int
    likes: int | None
    comments: int | None
    published_at: datetime
    duration_seconds: int
    format: str
    avg_views_baseline: float | None
    overperform_ratio: float | None
    median_views_baseline: float | None
    overperform_ratio_median: float | None
    has_sponsor_segment: bool
    sponsor_segment_seconds: float | None
    h1_views: int | None
    h1_ratio: float | None
    h3_views: int | None
    h3_ratio: float | None
    h6_views: int | None
    h6_ratio: float | None
    embedded_in: int = 0


class VideoPage(BaseModel):
    items: list[VideoOut]
    total: int
    overperform_count: int
    limit: int
    offset: int


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    channel_id: int
    channel_name: str = ""
    channel_avatar_url: str | None = None
    post_type: str | None
    text: str | None
    url: str | None
    image_url: str | None
    video_id: str | None
    poll_options: list | None
    likes: int | None
    comments: int | None
    published_text: str | None
    published_at: datetime | None
    first_seen_at: datetime


class YouTubeStatus(BaseModel):
    api_key_set: bool
    apify_set: bool
    quota_used_today: int
    quota_budget: int
    apify_posts_today: int
    channels: int
    videos: int
    posts: int
    last_scrape_at: datetime | None
    last_posts_at: datetime | None
    overperform_threshold: float


def _ch_out(ch: Channel, stats: dict) -> ChannelOut:
    return ChannelOut.model_validate(ch).model_copy(update={"site_name": ch.site.name if ch.site else None, **stats.get(ch.id, {})})


def _vid_out(v: Video, embeds: dict[str, int]) -> VideoOut:
    return VideoOut.model_validate(v).model_copy(update={
        "channel_name": v.channel.name, "channel_avatar_url": v.channel.avatar_url,
        "url": f"https://www.youtube.com/watch?v={v.id}", "embedded_in": embeds.get(v.id, 0),
    })


@router.get("/status", response_model=YouTubeStatus)
def status(db: Session = Depends(get_db)):
    s = get_settings()
    return YouTubeStatus(
        api_key_set=bool(s.youtube_api_key), apify_set=bool(s.apify_api_token),
        quota_used_today=usage_today(db, "youtube"), quota_budget=s.youtube_daily_quota_budget,
        apify_posts_today=usage_today(db, "apify_posts"),
        channels=db.scalar(select(func.count(Channel.id))) or 0,
        videos=db.scalar(select(func.count(Video.id))) or 0,
        posts=db.scalar(select(func.count(CommunityPost.id))) or 0,
        last_scrape_at=db.scalar(select(func.max(Channel.last_scraped_at))),
        last_posts_at=db.scalar(select(func.max(Channel.posts_scraped_at))),
        overperform_threshold=s.overperform_ratio_default,
    )


@router.get("/channels", response_model=list[ChannelOut])
def list_channels(db: Session = Depends(get_db)):
    stats = channel_stats(db)
    chans = db.scalars(select(Channel).options(selectinload(Channel.site)).order_by(Channel.name)).all()
    return [_ch_out(c, stats) for c in chans]


@router.post("/channels", response_model=ChannelOut, status_code=201)
def create_channel(body: ChannelCreate, db: Session = Depends(get_db)):
    if body.site_id is not None and db.get(Site, body.site_id) is None:
        raise HTTPException(422, "That site isn't tracked")
    try:
        ch = add_channel(db, YouTubeClient(get_settings().youtube_api_key), body.handle,
                         cohort=(body.cohort or "").strip() or None, site_id=body.site_id)
    except YouTubeError as e:
        raise HTTPException(422, str(e)) from e
    db.add(JobRequest(kind="youtube_channel", site_id=ch.id))  # first scrape in the background
    db.commit()
    db.refresh(ch)
    return _ch_out(ch, {})


@router.patch("/channels/{channel_id}", response_model=ChannelOut)
def update_channel(channel_id: int, body: ChannelUpdate, db: Session = Depends(get_db)):
    ch = db.get(Channel, channel_id)
    if ch is None:
        raise HTTPException(404, "Channel not found")
    data = body.model_dump(exclude_unset=True)
    if "cohort" in data:
        ch.cohort = (data["cohort"] or "").strip() or None
    if body.clear_site:
        ch.site_id = None
    elif data.get("site_id") is not None:
        if db.get(Site, data["site_id"]) is None:
            raise HTTPException(422, "That site isn't tracked")
        ch.site_id = data["site_id"]
    for k in ("is_active", "track_posts"):
        if data.get(k) is not None:
            setattr(ch, k, data[k])
    db.commit()
    db.refresh(ch)
    return _ch_out(ch, channel_stats(db))


@router.delete("/channels/{channel_id}", status_code=204)
def delete_channel(channel_id: int, db: Session = Depends(get_db)):
    ch = db.get(Channel, channel_id)
    if ch is None:
        raise HTTPException(404, "Channel not found")
    db.delete(ch)
    db.commit()


def _bounds(d_from: date | None, d_to: date | None):
    start = datetime.combine(d_from, time.min, IST).astimezone(timezone.utc) if d_from else None
    end = datetime.combine(d_to + timedelta(days=1), time.min, IST).astimezone(timezone.utc) if d_to else None
    return start, end


@router.get("/videos", response_model=VideoPage)
def list_videos(
    channels: str | None = None,
    cohort: str | None = None,
    site_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    views_threshold: int | None = Query(None, ge=0),
    format: str = Query("all", pattern="^(all|long|short)$"),
    sort_by: str = Query("ratio", pattern="^(ratio|views|date|engagement|velocity)$"),
    metric: str = Query("median", pattern="^(average|median)$"),
    has_sponsor: bool = False,
    q: str | None = Query(None, max_length=200),
    limit: int = Query(48, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    s = get_settings()
    ratio_col = Video.overperform_ratio_median if metric == "median" else Video.overperform_ratio
    stmt = select(Video).join(Channel).options(selectinload(Video.channel))
    if channels:
        ids = [int(x) for x in channels.split(",") if x.strip().isdigit()]
        if ids:
            stmt = stmt.where(Video.channel_id.in_(ids))
    if cohort:
        stmt = stmt.where(Channel.cohort == cohort)
    if site_id:
        stmt = stmt.where(Channel.site_id == site_id)
    start, end = _bounds(date_from, date_to)
    if start:
        stmt = stmt.where(Video.published_at >= start)
    if end:
        stmt = stmt.where(Video.published_at < end)
    if views_threshold:
        stmt = stmt.where(Video.views >= views_threshold)
    if format != "all":
        stmt = stmt.where(Video.format == format)
    if has_sponsor:
        stmt = stmt.where(Video.has_sponsor_segment.is_(True))
    if q:
        for term in q.split()[:6]:
            stmt = stmt.where(Video.title.ilike(f"%{term}%"))
    sub = stmt.order_by(None).subquery()
    total = db.scalar(select(func.count()).select_from(sub)) or 0
    over = db.scalar(select(func.count()).select_from(stmt.where(ratio_col >= s.overperform_ratio_default).order_by(None).subquery())) or 0
    engagement = (func.coalesce(Video.likes, 0) + func.coalesce(Video.comments, 0)) * 1.0 / case((Video.views > 0, Video.views), else_=1)
    order = {
        "ratio": [ratio_col.desc().nulls_last(), Video.published_at.desc()],
        "views": [Video.views.desc()],
        "date": [Video.published_at.desc()],
        "engagement": [engagement.desc()],
        "velocity": [func.coalesce(Video.h6_ratio, Video.h3_ratio, Video.h1_ratio).desc().nulls_last(), Video.published_at.desc()],
    }[sort_by]
    rows = list(db.scalars(stmt.order_by(*order).limit(limit).offset(offset)))
    embeds = embed_counts(db, [v.id for v in rows])
    return VideoPage(items=[_vid_out(v, embeds) for v in rows], total=total, overperform_count=over, limit=limit, offset=offset)


@router.get("/posts", response_model=list[PostOut])
def list_posts(
    channels: str | None = None,
    days: int = Query(30, ge=1, le=365),
    q: str | None = Query(None, max_length=200),
    limit: int = Query(60, ge=1, le=200),
    db: Session = Depends(get_db),
):
    since = utcnow() - timedelta(days=days)
    stmt = select(CommunityPost).options(selectinload(CommunityPost.channel)).where(
        func.coalesce(CommunityPost.published_at, CommunityPost.first_seen_at) >= since
    )
    if channels:
        ids = [int(x) for x in channels.split(",") if x.strip().isdigit()]
        if ids:
            stmt = stmt.where(CommunityPost.channel_id.in_(ids))
    if q:
        stmt = stmt.where(CommunityPost.text.ilike(f"%{q}%"))
    rows = db.scalars(stmt.order_by(func.coalesce(CommunityPost.published_at, CommunityPost.first_seen_at).desc()).limit(limit))
    return [PostOut.model_validate(p).model_copy(update={"channel_name": p.channel.name, "channel_avatar_url": p.channel.avatar_url}) for p in rows]


@router.get("/videos/by-ids", response_model=list[VideoOut])
def videos_by_ids(ids: str, db: Session = Depends(get_db)):
    """Tracked videos among the given YouTube ids (used by the article drawer)."""
    wanted = [x for x in ids.split(",") if x][:30]
    rows = db.scalars(select(Video).options(selectinload(Video.channel)).where(Video.id.in_(wanted)))
    return [_vid_out(v, {}) for v in rows]


@router.get("/videos/{video_id}/articles", response_model=list[ArticleOut])
def video_articles(video_id: str, db: Session = Depends(get_db)):
    """Tracked articles (last 60 days) that embed this video."""
    since = utcnow() - timedelta(days=60)
    rows = db.scalars(
        select(Article).options(selectinload(Article.site))
        .where(Article.first_seen_at >= since, Article.youtube_ids.is_not(None))
        .order_by(Article.first_seen_at.desc())
    )
    return [article_out(a) for a in rows if video_id in (a.youtube_ids or [])][:50]


@router.post("/refresh", status_code=202)
def refresh(posts: bool = False, db: Session = Depends(get_db)):
    s = get_settings()
    if not s.youtube_api_key:
        raise HTTPException(422, "Add YOUTUBE_API_KEY on Render first")
    state = db.get(AppState, "youtube_manual_refresh")
    now = utcnow()
    if state and state.updated_at and (now - as_utc(state.updated_at)).total_seconds() < s.manual_youtube_cooldown_seconds:
        wait = int(s.manual_youtube_cooldown_seconds - (now - as_utc(state.updated_at)).total_seconds())
        raise HTTPException(429, f"YouTube was refreshed moments ago — try again in {wait} s")
    if state is None:
        state = AppState(key="youtube_manual_refresh")
        db.add(state)
    state.updated_at = now
    db.add(JobRequest(kind="youtube_posts" if posts else "youtube_all"))
    db.commit()
    return {"queued": True}
