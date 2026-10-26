from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    url: str
    priority: int
    enabled: bool
    last_checked_at: datetime | None
    last_ok_at: datetime | None
    last_item_count: int | None
    consecutive_errors: int
    last_error: str | None


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    domain: str
    name: str
    home_url: str
    cohort: str | None
    is_own_site: bool
    paused: bool
    icon_url: str | None
    backfill_status: str
    created_at: datetime
    last_poll_at: datetime | None
    last_poll_ok_at: datetime | None
    last_error: str | None
    fast_source: str | None = None
    health: str = "ok"  # ok | warning | error | pending
    articles_24h: int = 0
    articles_7d: int = 0
    updates_7d: int = 0
    last_article_at: datetime | None = None
    queued: int = 0


class SiteDetailOut(SiteOut):
    sources: list[SourceOut] = []
    discovery_log: list[str] = []


class SiteCreate(BaseModel):
    url: str = Field(min_length=3, max_length=300)
    name: str | None = Field(default=None, max_length=120)
    cohort: str | None = Field(default=None, max_length=60)
    is_own_site: bool = False


class SiteUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    cohort: str | None = Field(default=None, max_length=60)
    paused: bool | None = None
    is_own_site: bool | None = None


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    seen_at: datetime
    old_title: str | None
    new_title: str | None
    old_word_count: int | None
    new_word_count: int | None
    paragraphs_added: int
    paragraphs_removed: int
    headings_added: list[str] | None
    headings_removed: list[str] | None
    summary: str


class ArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    site_id: int
    site_name: str = ""
    site_domain: str = ""
    site_icon_url: str | None = None
    url: str
    title: str | None
    excerpt: str | None
    author: str | None
    section: str | None
    tags: list[str] | None
    content_type: str | None
    thumbnail_url: str | None
    word_count: int | None
    image_count: int | None
    youtube_ids: list[str] | None
    affiliate_link_count: int | None
    published_at: datetime | None
    modified_at: datetime | None
    first_seen_at: datetime
    last_updated_at: datetime | None
    update_count: int
    activity_at: datetime | None
    is_backfill: bool
    discovered_via: str | None
    enrich_status: str
    latest_change: str | None = None
    own_clicks_28d: int | None = None
    own_impressions_28d: int | None = None
    own_position: float | None = None
    own_views_28d: int | None = None


class ArticleDetailOut(ArticleOut):
    headings: list[str] | None = None
    versions: list[VersionOut] = []
    also_covered_by: list["ArticleOut"] = []


class ArticlePage(BaseModel):
    items: list[ArticleOut]
    total: int
    limit: int
    offset: int


class Facets(BaseModel):
    content_types: list[tuple[str, int]]
    sections: list[tuple[str, int]]
    authors: list[tuple[str, int]]
    cohorts: list[str]


class JobRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    job: str
    site_id: int | None
    started_at: datetime
    finished_at: datetime | None
    items_new: int
    items_updated: int
    items_processed: int
    ok: bool | None
    error: str | None
    trigger: str


class SystemStatus(BaseModel):
    workspace_name: str
    sites: int
    articles_total: int
    articles_24h: int
    updates_24h: int
    queue_pending: int
    last_poll_at: datetime | None
    worker_alive: bool
    recent_runs: list[JobRunOut]
