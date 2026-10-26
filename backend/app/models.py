"""Database tables for the Web Intel article tracker.

Site            one competitor website (or techwiser.com itself, is_own_site)
SiteSource      one discovered feed for a site: news sitemap, sitemap, RSS,
                WordPress REST, or a homepage-scrape fallback
Article         one article URL (canonicalised) and its latest metadata
ArticleVersion  one row per *real* content change detected on an article
JobRun          log of every worker job run (feeds the Sources health page)
JobRequest      small queue the API uses to ask the worker to do something
                now (add site → discover + backfill, "Refresh now")
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from .database import Base
from .timeutil import as_utc, utcnow


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend. Postgres already does
    this; SQLite (dev/tests) hands back naive values, which the browser would
    misread as local time."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001
        return as_utc(value)

    def process_result_value(self, value, dialect):  # noqa: ANN001
        return as_utc(value)


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    home_url: Mapped[str] = mapped_column(String(1024))
    cohort: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_own_site: Mapped[bool] = mapped_column(Boolean, default=False)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    icon_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # pending → running → done | error. The first sitemap sweep of a new
    # site is a backfill; its articles are marked is_backfill so the feed's
    # "New" badge and alerts don't fire for 30 days of old posts at once.
    backfill_status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_poll_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_poll_ok_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    sources: Mapped[list[SiteSource]] = relationship(
        back_populates="site", cascade="all, delete-orphan", order_by="SiteSource.priority"
    )


class SiteSource(Base):
    __tablename__ = "site_sources"
    __table_args__ = (UniqueConstraint("site_id", "url", name="uq_site_source_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    # wp_rest | news_sitemap | rss | sitemap | html
    kind: Mapped[str] = mapped_column(String(20))
    url: Mapped[str] = mapped_column(String(1024))
    # Lower = polled first. The fastest working source is the "fast source"
    # (polled every 15 min); the sitemap is the backstop (every 6 h).
    priority: Mapped[int] = mapped_column(Integer, default=50)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    etag: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_ok_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_item_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consecutive_errors: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    site: Mapped[Site] = relationship(back_populates="sources")


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (
        Index("ix_articles_site_published", "site_id", "published_at"),
        Index("ix_articles_activity", "activity_at"),
        Index("ix_articles_enrich", "enrich_status", "next_check_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True)

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    section: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    youtube_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    affiliate_link_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    headings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Short hashes of each substantial paragraph — lets us say "3 paragraphs
    # changed" on an update without storing anyone's full article text.
    paragraph_hashes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    modified_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # The lastmod/modified value the feed last reported — a change here is
    # what triggers a recheck, but only a content change counts as Updated.
    source_lastmod: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    update_count: Mapped[int] = mapped_column(Integer, default=0)
    # max(published_at, last_updated_at) — what the Live Feed sorts by.
    activity_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    is_backfill: Mapped[bool] = mapped_column(Boolean, default=False)
    discovered_via: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Own-site benchmark (techwiser.com only): last 28 days from Search
    # Console + GA4, refreshed daily when those integrations are configured.
    own_clicks_28d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    own_impressions_28d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    own_position: Mapped[float | None] = mapped_column(Float, nullable=True)
    own_views_28d: Mapped[int | None] = mapped_column(Integer, nullable=True)
    own_metrics_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    # pending → ok | error ; "recheck" = fetch again and compare
    enrich_status: Mapped[str] = mapped_column(String(20), default="pending")
    enrich_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    next_check_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    site: Mapped[Site] = relationship()
    versions: Mapped[list[ArticleVersion]] = relationship(
        back_populates="article", cascade="all, delete-orphan", order_by="ArticleVersion.seen_at.desc()"
    )


class ArticleVersion(Base):
    __tablename__ = "article_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True)
    seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    old_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    old_word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paragraphs_added: Mapped[int] = mapped_column(Integer, default=0)
    paragraphs_removed: Mapped[int] = mapped_column(Integer, default=0)
    headings_added: Mapped[list | None] = mapped_column(JSON, nullable=True)
    headings_removed: Mapped[list | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")

    article: Mapped[Article] = relationship(back_populates="versions")


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job: Mapped[str] = mapped_column(String(50), index=True)
    site_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    items_new: Mapped[int] = mapped_column(Integer, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, default=0)
    items_processed: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Free-text notes, e.g. the discovery log ("found rss: …").
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger: Mapped[str] = mapped_column(String(20), default="schedule")


class JobRequest(Base):
    __tablename__ = "job_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # backfill | poll_all | poll_site | rediscover
    kind: Mapped[str] = mapped_column(String(30))
    site_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    picked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


# ═══ Phase 3 — YouTube (ported from TW-Labs, adapted) ══════════════════════
class Channel(Base):
    """A tracked YouTube channel, optionally linked to a tracked website."""

    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # UC… id once resolved
    handle: Mapped[str] = mapped_column(String(120))  # as typed, e.g. @beebomco
    name: Mapped[str] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    subscriber_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    uploads_playlist_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cohort: Mapped[str | None] = mapped_column(String(100), nullable=True)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    track_posts: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_scraped_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    posts_scraped_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    site: Mapped[Site | None] = relationship()
    videos: Mapped[list[Video]] = relationship(back_populates="channel", cascade="all, delete-orphan")


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (Index("ix_videos_channel_published", "channel_id", "published_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # YouTube video id
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    views: Mapped[int] = mapped_column(BigInteger, default=0)
    likes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comments: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    published_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    format: Mapped[str] = mapped_column(String(8))  # long | short
    # Trailing per-(channel, format) baselines — same maths as TW-Labs.
    avg_views_baseline: Mapped[float | None] = mapped_column(Float, nullable=True)
    overperform_ratio: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    median_views_baseline: Mapped[float | None] = mapped_column(Float, nullable=True)
    overperform_ratio_median: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    # SponsorBlock
    has_sponsor_segment: Mapped[bool] = mapped_column(Boolean, default=False)
    sponsor_segment_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    sponsor_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # Early-velocity checkpoints (views at ~1 h / 3 h / 6 h after publish)
    h1_views: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    h1_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    h3_views: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    h3_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    h6_views: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    h6_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    velocity_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    channel: Mapped[Channel] = relationship(back_populates="videos")


class CommunityPost(Base):
    __tablename__ = "community_posts"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    post_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # text | image | poll | video
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    video_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    poll_options: Mapped[list | None] = mapped_column(JSON, nullable=True)
    likes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comments: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    published_text: Mapped[str | None] = mapped_column(String(80), nullable=True)  # "2 days ago" as YouTube shows it
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)  # estimated
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)

    channel: Mapped[Channel] = relationship()


class ApiUsage(Base):
    """Daily quota/credit spend per external service (YouTube units, Apify runs)."""

    __tablename__ = "api_usage"
    __table_args__ = (UniqueConstraint("day", "service", name="uq_api_usage_day_service"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD (Pacific time for YouTube's quota day)
    service: Mapped[str] = mapped_column(String(30))
    units: Mapped[int] = mapped_column(Integer, default=0)


# ═══ Phase 4 — Shortlist, alerts, state ═══════════════════════════════════
class ShortlistItem(Base):
    __tablename__ = "shortlist_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # article | story | video | post | idea
    ref_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)  # site / channel name
    status: Mapped[str] = mapped_column(String(20), default="idea")  # idea | assigned | in_progress | published | dropped
    owner: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20), default="article")  # article | video
    keywords: Mapped[list | None] = mapped_column(JSON, nullable=True)  # any-of, case-insensitive
    site_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    channel_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    content_types: Mapped[list | None] = mapped_column(JSON, nullable=True)
    include_updates: Mapped[bool] = mapped_column(Boolean, default=False)
    min_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)  # video rules
    destinations: Mapped[list] = mapped_column(JSON, default=list)  # ["slack", "telegram"]
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_fired_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    fire_count: Mapped[int] = mapped_column(Integer, default=0)


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (UniqueConstraint("rule_id", "item_key", name="uq_alert_rule_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("alert_rules.id", ondelete="CASCADE"), index=True)
    item_key: Mapped[str] = mapped_column(String(120))  # "article:123" / "article:123:u2" / "video:abc"
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AppState(Base):
    """Tiny key/value store (last digest sent, last benchmark sync, …)."""

    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
