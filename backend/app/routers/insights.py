"""Phase 4 APIs: Topic Radar, Shortlist, alert rules, digest, integrations."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import alerts, benchmark
from ..config import get_settings
from ..database import get_db
from ..models import AlertEvent, AlertRule, AppState, Article, ShortlistItem, Site
from ..stories import build_stories, related_videos
from ..timeutil import utcnow
from .articles import _to_out
from ..schemas import ArticleOut

router = APIRouter(prefix="/api", tags=["insights"])


# ── Topic Radar ────────────────────────────────────────────────────────────
class StoryVideo(BaseModel):
    id: str
    title: str
    channel_name: str
    views: int
    ratio: float | None
    published_at: datetime
    thumbnail_url: str | None


class StorySite(BaseModel):
    id: int
    name: str
    icon_url: str | None
    is_own_site: bool


class StoryOut(BaseModel):
    key: str
    label: str
    terms: list[str]
    site_count: int
    competitor_site_count: int
    article_count: int
    first_at: datetime
    last_at: datetime
    hours_to_3_sites: float | None
    covered_by_us: bool | None
    gap: bool | None
    score: float
    sites: list[StorySite]
    articles: list[ArticleOut] = []
    videos: list[StoryVideo] = []
    shortlisted: bool = False


class RadarOut(BaseModel):
    stories: list[StoryOut]
    total: int
    gaps: int
    own_site_configured: bool
    window_hours: int


@router.get("/radar", response_model=RadarOut)
def radar(
    hours: int = Query(48, ge=6, le=24 * 14),
    min_sites: int = Query(2, ge=2, le=10),
    gaps_only: bool = False,
    cohort: str | None = None,
    q: str | None = Query(None, max_length=100),
    limit: int = Query(40, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stories = build_stories(db, hours=hours, min_sites=min_sites, cohort=cohort)
    own_configured = bool(db.scalar(select(func.count(Site.id)).where(Site.is_own_site.is_(True))))
    gaps = sum(1 for s in stories if s["gap"])
    if gaps_only:
        stories = [s for s in stories if s["gap"]]
    if q:
        ql = q.lower()
        stories = [s for s in stories if ql in s["label"].lower() or any(ql in t for t in s["terms"])]
    total = len(stories)
    page = stories[:limit]
    ids = [i for s in page for i in s["article_ids"]]
    arts = {a.id: a for a in db.scalars(select(Article).options(selectinload(Article.site)).where(Article.id.in_(ids)))} if ids else {}
    listed = set(db.scalars(select(ShortlistItem.ref_id).where(ShortlistItem.kind == "story")))
    since = utcnow() - timedelta(hours=hours)
    out: list[StoryOut] = []
    for s in page:
        vids = related_videos(db, s["terms"], since)
        out.append(StoryOut(
            **{k: v for k, v in s.items() if k not in ("article_ids", "sites")},
            sites=[StorySite(id=i, name=n, icon_url=ic, is_own_site=o) for i, n, ic, o in s["sites"]],
            articles=[_to_out(arts[i]) for i in s["article_ids"] if i in arts],
            videos=[StoryVideo(id=v.id, title=v.title, channel_name=v.channel.name, views=v.views,
                               ratio=v.overperform_ratio_median, published_at=v.published_at, thumbnail_url=v.thumbnail_url) for v in vids],
            shortlisted=s["key"] in listed,
        ))
    return RadarOut(stories=out, total=total, gaps=gaps, own_site_configured=own_configured, window_hours=hours)


# ── Shortlist ──────────────────────────────────────────────────────────────
STATUSES = ("idea", "assigned", "in_progress", "published", "dropped")


class ShortlistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    ref_id: str | None
    title: str
    url: str | None
    source: str | None
    status: str
    owner: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class ShortlistCreate(BaseModel):
    kind: str = Field(pattern="^(article|story|video|post|idea)$")
    ref_id: str | None = Field(default=None, max_length=80)
    title: str = Field(min_length=1, max_length=500)
    url: str | None = Field(default=None, max_length=2048)
    source: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=4000)
    owner: str | None = Field(default=None, max_length=80)


class ShortlistUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(idea|assigned|in_progress|published|dropped)$")
    owner: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=4000)
    title: str | None = Field(default=None, min_length=1, max_length=500)


@router.get("/shortlist", response_model=list[ShortlistOut])
def shortlist(db: Session = Depends(get_db)):
    return [ShortlistOut.model_validate(i) for i in db.scalars(select(ShortlistItem).order_by(ShortlistItem.updated_at.desc()))]


@router.post("/shortlist", response_model=ShortlistOut, status_code=201)
def add_shortlist(body: ShortlistCreate, db: Session = Depends(get_db)):
    if body.ref_id:
        dup = db.scalar(select(ShortlistItem).where(ShortlistItem.kind == body.kind, ShortlistItem.ref_id == body.ref_id))
        if dup:
            return ShortlistOut.model_validate(dup)
    item = ShortlistItem(**body.model_dump(), created_at=utcnow(), updated_at=utcnow())
    db.add(item)
    db.commit()
    db.refresh(item)
    return ShortlistOut.model_validate(item)


@router.patch("/shortlist/{item_id}", response_model=ShortlistOut)
def update_shortlist(item_id: int, body: ShortlistUpdate, db: Session = Depends(get_db)):
    item = db.get(ShortlistItem, item_id)
    if item is None:
        raise HTTPException(404, "Not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(item, k, (v.strip() or None) if isinstance(v, str) and k in ("owner", "notes") else v)
    item.updated_at = utcnow()
    db.commit()
    return ShortlistOut.model_validate(item)


@router.delete("/shortlist/{item_id}", status_code=204)
def delete_shortlist(item_id: int, db: Session = Depends(get_db)):
    item = db.get(ShortlistItem, item_id)
    if item is not None:
        db.delete(item)
        db.commit()


# ── Alerts ─────────────────────────────────────────────────────────────────
class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    kind: str
    keywords: list[str] | None
    site_ids: list[int] | None
    channel_ids: list[int] | None
    content_types: list[str] | None
    include_updates: bool
    min_ratio: float | None
    destinations: list[str]
    enabled: bool
    created_at: datetime
    last_fired_at: datetime | None
    fire_count: int


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field("article", pattern="^(article|video)$")
    keywords: list[str] = Field(default_factory=list, max_length=30)
    site_ids: list[int] = Field(default_factory=list)
    channel_ids: list[int] = Field(default_factory=list)
    content_types: list[str] = Field(default_factory=list)
    include_updates: bool = False
    min_ratio: float | None = Field(default=None, ge=0, le=100)
    destinations: list[str] = Field(default_factory=lambda: ["slack"])
    enabled: bool = True


def _clean_rule(body: RuleIn) -> dict:
    d = body.model_dump()
    d["keywords"] = [k.strip() for k in d["keywords"] if k.strip()][:30] or None
    d["site_ids"] = d["site_ids"] or None
    d["channel_ids"] = d["channel_ids"] or None
    d["content_types"] = d["content_types"] or None
    d["destinations"] = [x for x in d["destinations"] if x in ("slack", "telegram")]
    if d["kind"] == "video" and not d["min_ratio"]:
        d["min_ratio"] = get_settings().overperform_ratio_default
    return d


@router.get("/alerts/rules", response_model=list[RuleOut])
def rules(db: Session = Depends(get_db)):
    return [RuleOut.model_validate(r) for r in db.scalars(select(AlertRule).order_by(AlertRule.created_at))]


@router.post("/alerts/rules", response_model=RuleOut, status_code=201)
def create_rule(body: RuleIn, db: Session = Depends(get_db)):
    rule = AlertRule(**_clean_rule(body), created_at=utcnow())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    # Mark what already matches as "seen" so a new rule doesn't flood the
    # channel with the last few hours of articles.
    _prime(db, rule)
    return RuleOut.model_validate(rule)


def _prime(db: Session, rule: AlertRule) -> None:
    from ..alerts import article_matches, video_matches
    from ..models import Video

    since = utcnow() - timedelta(hours=6)
    keys: list[str] = []
    if rule.kind == "video":
        keys = [f"video:{v.id}" for v in db.scalars(select(Video).where(Video.published_at >= utcnow() - timedelta(days=3))) if video_matches(rule, v)]
    else:
        for a in db.scalars(select(Article).where(Article.first_seen_at >= since)):
            if article_matches(rule, a):
                keys.append(f"article:{a.id}")
                if a.update_count:
                    keys.append(f"article:{a.id}:u{a.update_count}")
    for k in keys:
        db.add(AlertEvent(rule_id=rule.id, item_key=k, ok=True, error="baseline at rule creation"))
    db.commit()


@router.put("/alerts/rules/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: int, body: RuleIn, db: Session = Depends(get_db)):
    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(404, "Rule not found")
    for k, v in _clean_rule(body).items():
        setattr(rule, k, v)
    db.commit()
    return RuleOut.model_validate(rule)


@router.delete("/alerts/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(AlertRule, rule_id)
    if rule is not None:
        db.delete(rule)
        db.commit()


class Integrations(BaseModel):
    slack: bool
    telegram: bool
    youtube: bool
    apify: bool
    search_console: bool
    ga4: bool
    digest_enabled: bool
    digest_time_ist: str
    digest_last_sent: str | None
    benchmark_last_sync: dict | None
    dashboard_url: str


@router.get("/integrations", response_model=Integrations)
def integrations(db: Session = Depends(get_db)):
    s = get_settings()
    d = alerts.configured_destinations()
    b = benchmark.configured()
    last = db.get(AppState, "digest_last_sent")
    bsync = db.get(AppState, "benchmark_last_sync")
    return Integrations(
        slack=d["slack"], telegram=d["telegram"], youtube=bool(s.youtube_api_key), apify=bool(s.apify_api_token),
        search_console=b["search_console"], ga4=b["ga4"], digest_enabled=s.digest_enabled,
        digest_time_ist=f"{s.digest_hour_ist:02d}:{s.digest_minute_ist:02d}",
        digest_last_sent=last.value if last else None,
        benchmark_last_sync=json.loads(bsync.value) if bsync and bsync.value else None,
        dashboard_url=s.dashboard_url,
    )


@router.post("/alerts/test")
def test_alert(dest: str = Query(pattern="^(slack|telegram)$")):
    errors = alerts.test_destination(dest)
    if errors:
        raise HTTPException(502, "; ".join(errors))
    return {"ok": True}


@router.get("/digest/preview")
def digest_preview(db: Session = Depends(get_db)):
    title, lines = alerts.build_digest(db)
    return {"title": title, "lines": [ln.split("\t")[0] for ln in lines]}


@router.post("/digest/send")
def digest_send(db: Session = Depends(get_db)):
    if not any(alerts.configured_destinations().values()):
        raise HTTPException(422, "Set SLACK_WEBHOOK_URL or TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID on Render first")
    ok = alerts.maybe_send_digest(db, force=True)
    if not ok:
        raise HTTPException(502, "The digest couldn't be delivered — check the webhook / bot settings")
    return {"ok": True}


@router.post("/benchmark/sync")
def benchmark_sync(db: Session = Depends(get_db)):
    try:
        return benchmark.sync(db)
    except benchmark.BenchmarkError as e:
        raise HTTPException(502, str(e)) from e
