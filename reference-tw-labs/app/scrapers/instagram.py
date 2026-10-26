"""
Instagram scraper, via an Apify Actor rather than talking to Instagram
directly.

Why Apify and not a raw scraper: Instagram has no free official API that
lets a third party pull an arbitrary public competitor's posts (the
official Graph API only exposes accounts you administer, behind app
review). Community scrapers (instaloader, playwright-based scripts) work
but are fragile — Instagram aggressively rate-limits and IP-bans scraper
traffic, so they need proxies and constant maintenance to stay working.
Apify runs managed actors that handle that anti-blocking layer for you, in
exchange for metered usage (the free plan includes $5/month of usage
credit — see PRODUCTION_ROADMAP.md for what that buys).

Same split as scrapers/youtube.py: ``ApifyInstagramClient`` is the only
thing that talks to the network; ``normalize_instagram_item`` is a pure
function tests can feed realistic sample JSON without any credentials.

One call per channel per run: ``fetch_profile_posts`` re-fetches the
account's most recent ``apify_max_posts_per_channel`` timeline items
(default 10 — the same size as the overperformance baseline's trailing
``baseline_window_videos`` window) and every item in that batch is
upserted, so a reel that was already tracked gets its view/like/comment
counts refreshed to their current values, not just newly-discovered reels.
That's what keeps the median/mean baseline from going stale: not a second
Apify call, but this one being re-run several times a day.

(An earlier version of this scraper made a second, targeted call —
``fetch_posts_by_url`` — to re-fetch specific already-tracked reels that
had aged out of the discovery batch, e.g. on an account that posts a lot
of photos between reels. That's gone: it doubled the Apify usage on every
run to guard against a gap that a frequent single-call refresh already
closes in practice. The trade-off is real but deliberate — if a channel's
photo-to-reel ratio is high enough to push a reel past the last
``apify_max_posts_per_channel`` posts before the next refresh runs, that
reel's baseline will lag until it re-enters the window. Raise
``APIFY_MAX_POSTS_PER_CHANNEL`` for a channel like that if it becomes a
problem.)

IMPORTANT — Apify actor output schemas are not standardized across actors
and change when actor authors update them. ``normalize_instagram_item``
below is written against the commonly-used ``apify/instagram-scraper`` and
``apify/instagram-reel-scraper`` field names (it tries several known aliases
per field). If you rent a different actor, open one dataset item in the
Apify console, compare its keys to the aliases below, and extend the
``_first_present`` lookups — that's the one place this integration is
actor-specific.

Pinned posts vs. chronological order: Instagram lets an account pin up to
3 posts to the top of its profile grid, and several Apify Instagram actors
(this one included, per its own issue tracker — e.g. "Scraper Fetches
Pinned Posts Instead of Recent Posts in Chronological Order" on
apify/instagram-scraper, and "Returning Older Posts Outside Of Date" on
apify/instagram-post-scraper) return those pinned posts first regardless
of how old they are. With a small ``resultsLimit``, that can crowd out
genuinely recent posts before ``scrape_channel`` ever sees them —
``PINNED_POST_PADDING`` below is the fix: ask the actor for a few more
posts than needed, then sort by real publish time and keep only the
newest ``apify_max_posts_per_channel`` locally.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any

from apify_client import ApifyClient
from sqlalchemy.orm import Session

from app.error_safety import safe_error_message
from app.formatting import initials_from_name, normalize_handle
from app.models import Channel, Video
from app.overperformance import recompute_and_store_channel_baselines

logger = logging.getLogger(__name__)

# apify_client's ActorClient.call() "waits indefinitely, unless the wait_secs
# argument is provided" (its own docstring) — a stuck or heavily-throttled
# actor run (Instagram rate-limiting the actor's own scraping, a bad actor
# build, etc.) would otherwise hang this call, and everything after it in
# the same scrape run, forever rather than surfacing as the per-channel
# error scrape_channel below already knows how to handle. Apify's own free
# actors typically finish a single-profile run in well under a minute, so
# five minutes is generous headroom rather than a tight budget.
APIFY_RUN_WAIT_SECS = 300

# See this module's docstring ("Pinned posts vs. chronological order") — the
# actor can return up to Instagram's max of 3 pinned posts ahead of genuinely
# recent ones. scrape_channel asks for apify_max_posts_per_channel + this
# padding, then sorts locally and drops back down to apify_max_posts_per_channel,
# so pinned-but-old items lose their seat to real recent ones instead of
# occupying it.
PINNED_POST_PADDING = 3


class ApifyInstagramClient:
    def __init__(self, api_token: str, actor_id: str):
        if not api_token:
            raise ValueError("APIFY_API_TOKEN is not set — see backend/.env.example")
        self._client = ApifyClient(api_token)
        self.actor_id = actor_id
        self.runs_started = 0

    def _run_and_collect(self, run_input: dict[str, Any]) -> list[dict]:
        """
        Starts the configured actor and blocks until it finishes or
        ``APIFY_RUN_WAIT_SECS`` elapses, then returns its dataset items.
        Raises (a plain ``RuntimeError``, not whatever internal shape Apify
        used) if the run didn't reach a successful terminal state — a run
        that's still ``RUNNING`` when the wait bound is hit would otherwise
        have an incomplete (or entirely empty) dataset read as if it were
        the channel's real, complete result. The caller (scrape_channel)
        turns any exception raised here into a per-channel error instead of
        aborting the whole batch.
        """
        run = self._client.actor(self.actor_id).call(run_input=run_input, wait_secs=APIFY_RUN_WAIT_SECS)
        self.runs_started += 1
        status = run.get("status") if run else None
        if status != "SUCCEEDED":
            raise RuntimeError(
                f"Apify actor run did not complete successfully within {APIFY_RUN_WAIT_SECS}s "
                f"(status: {status or 'unknown'})."
            )
        dataset_id = run["defaultDatasetId"]
        return list(self._client.dataset(dataset_id).iterate_items())

    def fetch_profile_posts(self, username: str, *, max_posts: int) -> list[dict]:
        """
        Runs the configured actor for one username and returns its dataset
        items. Raises whatever ``_run_and_collect`` raises on a failed or
        timed-out run — the caller (scrape_channel) turns that into a
        per-channel error instead of aborting the whole batch.
        """
        run_input: dict[str, Any] = {
            "directUrls": [f"https://www.instagram.com/{username}/"],
            "resultsType": "posts",
            "resultsLimit": max_posts,
        }
        return self._run_and_collect(run_input)


# ── Pure parsing ─────────────────────────────────────────────────────────────


def _first_present(item: dict, *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return default


def normalize_instagram_item(raw: dict, *, channel_id: str) -> dict | None:
    """
    Normalize one Apify dataset item into the app's Video shape. Returns
    None for an item that isn't actually a video/reel (a plain photo post
    has no meaningful "views" metric to track for overperformance) — photo
    carousels are skipped rather than force-fit into the schema.
    """
    post_id = _first_present(raw, "id", "shortCode", "pk")
    if not post_id:
        return None

    is_video = bool(_first_present(raw, "isVideo", "videoUrl", "videoDuration", default=False)) or _first_present(
        raw, "type", "productType", default=""
    ) in ("Video", "clips", "reel")
    if not is_video:
        return None

    views = _first_present(raw, "videoPlayCount", "videoViewCount", "playCount", "viewCount", default=None)
    if views is None:
        # Some actors only expose likes+comments for older posts; treat the
        # video as untracked-for-views rather than fabricating a number.
        return None

    timestamp = _first_present(raw, "timestamp", "takenAt", "takenAtTimestamp")
    published_at = _parse_instagram_timestamp(timestamp)

    caption = _first_present(raw, "caption", "text", "title", default="(no caption)")
    title = caption.splitlines()[0][:200] if caption else "(no caption)"

    shortcode = _first_present(raw, "shortCode", "code", default=post_id)
    duration = _first_present(raw, "videoDuration", default=0) or 0

    return {
        "id": f"instagram:{post_id}",
        "channel_id": channel_id,
        "platform": "instagram",
        "title": title,
        "thumbnail_url": _first_present(raw, "displayUrl", "thumbnailUrl", "thumbnailSrc"),
        "external_url": _safe_external_url(
            _first_present(raw, "url", default=None), f"https://www.instagram.com/p/{shortcode}/"
        ),
        "views": int(views),
        "likes": _int_or_none(_first_present(raw, "likesCount", "likes")),
        "comments": _int_or_none(_first_present(raw, "commentsCount", "comments")),
        "published_at": published_at,
        "duration_seconds": int(float(duration)) if duration else 0,
        "format": "reel",
    }


def _safe_external_url(raw_url: Any, fallback: str) -> str:
    """Only ever store an http(s) URL as Video.external_url — this value is
    later rendered as a clickable ``<a href>`` on the dashboard's video card
    (see src/App.tsx's VideoCard) with no further validation on that end.
    ``raw_url`` comes straight off a rented Apify actor's output, whose
    schema "is not standardized... and changes when actor authors update
    them" (this module's docstring) — a misbehaving or compromised actor
    returning something like a ``javascript:`` URI in its ``url`` field
    would otherwise become a stored-XSS payload the moment a teammate
    clicks that video. Anything that isn't a plain http(s) URL falls back
    to the same canonical post URL already used when the actor omits a
    ``url`` field entirely, so this changes behavior only for input that
    was never a valid link to begin with.
    """
    if isinstance(raw_url, str) and raw_url.strip().lower().startswith(("http://", "https://")):
        return raw_url
    return fallback


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_instagram_timestamp(value: Any) -> dt.date:
    if value is None:
        return dt.date.today()
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc).date()
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return dt.date.today()


def _item_recency_key(raw: dict) -> float:
    """
    Best-effort epoch-seconds for sorting *raw* actor items newest-first —
    used only to counteract pinned/out-of-order results (see
    PINNED_POST_PADDING and this module's docstring), separate from
    _parse_instagram_timestamp's job of picking a display date for storage.

    The two intentionally disagree on how to handle a missing/unparsable
    timestamp: _parse_instagram_timestamp defaults to today so a real video
    with a missing date doesn't get lost or mis-sorted once stored, but this
    function defaults to the epoch (oldest possible) so a timestamp-less item
    sorts to the back and is the first thing dropped by the padding trim
    below — for *this* purpose, "we can't tell how old it is" should lose
    its slot to a confirmed-recent item, not risk taking one from it.
    """
    value = _first_present(raw, "timestamp", "takenAt", "takenAtTimestamp")
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def parse_profile_meta(items: list[dict]) -> dict:
    """Best-effort profile info (name/followers) lifted off the first item,
    since most Instagram actors embed the profile owner on every post."""
    if not items:
        return {}
    first = items[0]
    owner = first.get("ownerFullName") or first.get("fullName") or first.get("username") or ""
    followers = _first_present(first, "followersCount", "ownerFollowersCount")
    return {
        "name": owner or None,
        "avatar_initials": initials_from_name(owner) if owner else None,
        "subscriber_count": _int_or_none(followers),
    }


# ── Orchestration ────────────────────────────────────────────────────────────


@dataclass
class ChannelScrapeStats:
    videos_upserted: int = 0
    runs_started: int = 0
    errors: list[str] = field(default_factory=list)


def scrape_channel(client: ApifyInstagramClient, db: Session, channel: Channel, *, settings) -> ChannelScrapeStats:
    stats = ChannelScrapeStats()
    username = normalize_handle(channel.external_id, "instagram")

    try:
        items = client.fetch_profile_posts(
            username, max_posts=settings.apify_max_posts_per_channel + PINNED_POST_PADDING
        )
    except Exception as exc:  # noqa: BLE001 — a single channel's actor failure shouldn't kill the batch
        stats.errors.append(f"Apify run failed for @{username}: {safe_error_message(exc)}")
        stats.runs_started = client.runs_started
        return stats

    # Sort newest-first by *real* publish time and trim back down to
    # apify_max_posts_per_channel — cancels out the padding requested above,
    # so a pinned-but-old post the actor put first ends up at the back of
    # this list and is what gets dropped, not a genuinely recent post that
    # never got a chance to be included.
    items = sorted(items, key=_item_recency_key, reverse=True)[: settings.apify_max_posts_per_channel]

    meta = parse_profile_meta(items)
    if meta.get("name"):
        channel.name = meta["name"]
    if meta.get("avatar_initials"):
        channel.avatar_initials = meta["avatar_initials"]
    if meta.get("subscriber_count") is not None:
        channel.subscriber_count = meta["subscriber_count"]

    discovered_ids: set[str] = set()
    for raw_item in items:
        parsed = normalize_instagram_item(raw_item, channel_id=channel.id)
        if parsed is None:
            continue
        discovered_ids.add(parsed["id"])
        existing = db.get(Video, parsed["id"])
        if existing is None:
            db.add(Video(**parsed))
        else:
            for key, value in parsed.items():
                setattr(existing, key, value)
        stats.videos_upserted += 1

    if items and not discovered_ids:
        # The actor returned something but normalize_instagram_item recognized
        # none of it as a video/reel — almost always means its output schema
        # has drifted from the field-name aliases _first_present looks for
        # (see this module's docstring), not that the account genuinely
        # posted zero reels. Without this, a scrape run still reports
        # "success" with videos_upserted=0 and nothing else distinguishes
        # that from "this channel just hasn't posted anything new today",
        # even though PRODUCTION_ROADMAP.md's own troubleshooting section
        # promises that GET /api/scrape/runs' errorMessage is where a schema
        # shift like this shows up.
        stats.errors.append(
            f"Apify returned {len(items)} post(s) for @{username} but none were recognized as videos/reels — "
            "the actor's output schema may have changed (see backend/README.md's Instagram troubleshooting notes)."
        )

    db.flush()
    recompute_and_store_channel_baselines(db, channel.id, settings)
    stats.runs_started = client.runs_started
    return stats
