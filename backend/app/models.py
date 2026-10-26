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
    Boolean,
    DateTime,
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
