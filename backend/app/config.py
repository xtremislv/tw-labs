"""Runtime settings, read from environment variables / backend/.env.

Every value has a working default for local development, so `uvicorn` and
`python -m app.worker` start with nothing configured except DATABASE_URL.
"""
from functools import lru_cache
from urllib.parse import quote, unquote

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./dev.db"

    # ── Production / security ────────────────────────────────────────────
    # OPTIONAL team password. Unset (the default) = no login screen; anyone
    # with the link can use the dashboard. Set it to turn the login back on:
    # every /api route except /api/auth/* then needs a signed session cookie
    # (see app/auth.py).
    dashboard_password: str = ""
    # Signs session cookies. Any long random string; changing it logs
    # everyone out.
    session_secret: str = ""
    session_days: int = 30
    # Run the scheduler inside the API process (one Render service instead
    # of an API + a separate background worker). Only with ONE uvicorn worker.
    embedded_worker: bool = False
    cors_origins: str = "http://localhost:5173,http://localhost:4173,http://localhost:8443"
    workspace_name: str = "TechWiser Web Competitors"

    # ── Crawling ─────────────────────────────────────────────────────────
    # Many publisher sites (Cloudflare, Akamai) reject obviously non-browser
    # user agents outright, so the default looks like a browser but still
    # names this tool at the end so a site admin reading logs can tell what
    # it is.
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 TWLabsWebIntel/1.0"
    )
    request_timeout_seconds: float = 20.0
    # Minimum gap between two requests to the same domain.
    per_domain_delay_seconds: float = 2.0
    respect_robots_txt: bool = True

    # ── Tracking ─────────────────────────────────────────────────────────
    # How far back the first sitemap sweep of a newly added site reaches.
    backfill_days: int = 30
    # Max sitemap child files read per sweep (date-partitioned sitemaps can
    # have hundreds; we only want the recent ones).
    max_child_sitemaps_per_sweep: int = 4
    # Every poll also reads each child sitemap in the site's sitemap index
    # that was updated on the latest date (catches every post type that
    # WordPress publishes today, not just what the REST/RSS feed lists).
    latest_sitemaps_on_poll: bool = True
    latest_sitemaps_max_children: int = 20
    # Max articles fetched + parsed per enrichment pass (across all sites).
    enrich_batch_size: int = 60
    enrich_max_attempts: int = 3
    # Recent articles are re-fetched on this cadence to catch edits on sites
    # whose feeds don't expose a modified date.
    recheck_recent_days: int = 3
    recheck_interval_hours: int = 6

    # ── Worker schedule (minutes) ────────────────────────────────────────
    fast_poll_minutes: int = 15
    sitemap_sweep_minutes: int = 360
    enrich_minutes: int = 2
    job_request_poll_seconds: int = 20

    # ── Storage housekeeping (daily) ──────────────────────────────────────
    # Delete articles with no activity for this many days (0 = keep forever).
    # The free Supabase database is 500 MB; ~180 days keeps 20 sites well
    # inside it.
    retention_days: int = 0
    job_log_retention_days: int = 30

    # ── Database connection pool ─────────────────────────────────────────
    # Kept small: Supabase's free shared pooler allows few connections.
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # ── Phase 3: YouTube (same maths as TW-Labs) ─────────────────────────
    youtube_api_key: str = ""
    youtube_daily_quota_budget: int = 10000
    # Daily full scrape (IST clock time) + hourly early-velocity checks.
    youtube_scrape_hour_ist: int = 6
    youtube_scrape_minute_ist: int = 0
    baseline_window_videos: int = 10
    baseline_min_videos: int = 3
    overperform_ratio_default: float = 2.0
    velocity_checkpoints_hours: str = "1,3,6"
    velocity_checkpoint_grace_hours: float = 2.0
    sponsorblock_enabled: bool = True
    sponsorblock_api_base: str = "https://sponsor.ajay.app"
    sponsorblock_categories: str = "sponsor,selfpromo,exclusive_access"
    sponsorblock_recheck_hours: int = 24
    sponsorblock_max_checks_per_scrape: int = 40
    manual_youtube_cooldown_seconds: int = 300
    # Community posts via an Apify actor (pay-per-post on your Apify account).
    apify_api_token: str = ""
    apify_posts_actor_id: str = "lurkapi/youtube-community-posts-scraper"
    apify_max_posts_per_channel: int = 10
    posts_scrape_hour_ist: int = 7

    # ── Phase 4: alerts, digest, benchmark ───────────────────────────────
    slack_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    alerts_check_minutes: int = 5
    digest_enabled: bool = True
    digest_hour_ist: int = 9
    digest_minute_ist: int = 30
    # Public dashboard address, used for links inside alerts and the digest.
    dashboard_url: str = ""
    # Own-site benchmark (optional): a Google service-account JSON (the whole
    # file's contents) that has been added as a user on the Search Console
    # property and the GA4 property.
    google_service_account_json: str = ""
    gsc_site_url: str = ""  # e.g. "sc-domain:techwiser.com" or "https://techwiser.com/"
    ga4_property_id: str = ""  # numeric, e.g. "123456789"

    # Cooldown for the dashboard's "Refresh now" button.
    manual_refresh_cooldown_seconds: int = 120

    @property
    def velocity_checkpoint_hours_list(self) -> list[int]:
        return [int(x) for x in self.velocity_checkpoints_hours.split(",") if x.strip().isdigit() and int(x) in (1, 3, 6)]

    @property
    def sponsorblock_category_list(self) -> list[str]:
        return [c.strip() for c in self.sponsorblock_categories.split(",") if c.strip()]

    @property
    def sqlalchemy_url(self) -> str:
        """Render/Neon/Supabase hand out postgres:// or postgresql:// URLs;
        SQLAlchemy needs the driver named (postgresql+psycopg://)."""
        url = _escape_password(self.database_url.strip())
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


def _escape_password(url: str) -> str:
    """Percent-encode a password pasted raw into a database URL.

    Supabase generates passwords that can contain @ # / : ? and similar. Pasted
    as-is, "postgresql://user:pa@ss@host/db" makes the driver think the host is
    "ss@host". The host part never contains "@", so everything up to the LAST
    "@" is user:password; we encode the password unless it's already encoded.
    """
    if "://" not in url or url.startswith("sqlite"):
        return url
    scheme, rest = url.split("://", 1)
    at = rest.rfind("@")
    if at == -1:
        return url
    userinfo, hostpart = rest[:at], rest[at + 1 :]
    user, sep, password = userinfo.partition(":")
    if not sep or not password:
        return url
    if unquote(password) != password:  # already percent-encoded
        return url
    return f"{scheme}://{user}:{quote(password, safe='')}@{hostpart}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
