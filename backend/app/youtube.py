"""YouTube tracking — ported from the TW-Labs dashboard, adapted to Web Intel.

Same behaviour and maths as TW-Labs:
  * walks each channel's uploads playlist (1 quota unit / page) and never uses
    search.list, then refreshes stats for every tracked video in batches of 50
    (1 unit / 50 videos);
  * overperformance = views ÷ trailing mean (and median) of the channel's
    previous 10 videos of the same format (long vs Shorts), min 3 prior videos;
  * early velocity: views captured at ~1 h / 3 h / 6 h after publish, compared
    with the same checkpoint on the channel's recent videos;
  * SponsorBlock flags sponsored / self-promo segments.

Differences: the API is called with httpx directly (no googleapiclient — lighter
on Render's free 512 MB instance), channels can be linked to a tracked website,
and community posts are scraped through an Apify actor.
"""
from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import ApiUsage, Article, Channel, CommunityPost, Video
from .timeutil import as_utc, parse_dt, utcnow

log = logging.getLogger("webintel.youtube")
API = "https://www.googleapis.com/youtube/v3"
BACKFILL_PAGES = 4
SHORT_MAX_SECONDS = 180  # YouTube Shorts can be up to 3 minutes


class YouTubeError(Exception):
    pass


# ── quota bookkeeping ──────────────────────────────────────────────────────
def quota_day(now: datetime | None = None) -> str:
    """YouTube's quota day resets at midnight Pacific; UTC-8 is close enough
    for a usage meter (and needs no time-zone database on Windows)."""
    return ((now or utcnow()) - timedelta(hours=8)).strftime("%Y-%m-%d")


def record_usage(db: Session, service: str, units: int) -> None:
    if units <= 0:
        return
    day = quota_day()
    row = db.scalar(select(ApiUsage).where(ApiUsage.day == day, ApiUsage.service == service))
    if row is None:
        row = ApiUsage(day=day, service=service, units=0)
        db.add(row)
    row.units += units
    db.commit()


def usage_today(db: Session, service: str) -> int:
    return db.scalar(select(ApiUsage.units).where(ApiUsage.day == quota_day(), ApiUsage.service == service)) or 0


# ── API client ─────────────────────────────────────────────────────────────
class YouTubeClient:
    def __init__(self, api_key: str, client: httpx.Client | None = None):
        if not api_key:
            raise YouTubeError("YOUTUBE_API_KEY is not set — add it in Render → webintel-api → Environment")
        self.key = api_key
        self.http = client or httpx.Client(timeout=30)
        self.units = 0

    def _get(self, path: str, **params) -> dict:
        params["key"] = self.key
        try:
            r = self.http.get(f"{API}/{path}", params=params)
        except httpx.HTTPError as e:
            raise YouTubeError(f"YouTube API unreachable: {e}") from e
        self.units += 1
        if r.status_code != 200:
            try:
                msg = r.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                msg = r.text[:200]
            raise YouTubeError(f"YouTube API {r.status_code}: {msg}")
        return r.json()

    def get_channel(self, *, channel_id: str | None = None, handle: str | None = None) -> dict | None:
        params = {"part": "snippet,statistics,contentDetails"}
        if channel_id:
            params["id"] = channel_id
        else:
            params["forHandle"] = handle if handle and handle.startswith("@") else f"@{handle}"
        items = self._get("channels", **params).get("items", [])
        return items[0] if items else None

    def list_upload_ids(self, playlist_id: str, *, max_pages: int) -> list[str]:
        ids: list[str] = []
        token = None
        for _ in range(max_pages):
            params = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": 50}
            if token:
                params["pageToken"] = token
            resp = self._get("playlistItems", **params)
            ids += [i["contentDetails"]["videoId"] for i in resp.get("items", [])]
            token = resp.get("nextPageToken")
            if not token:
                break
        return ids

    def get_videos(self, ids: list[str]) -> list[dict]:
        out: list[dict] = []
        for i in range(0, len(ids), 50):
            out += self._get("videos", part="snippet,statistics,contentDetails", id=",".join(ids[i : i + 50])).get("items", [])
        return out


# ── pure parsing ───────────────────────────────────────────────────────────
_DUR = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


def parse_duration(value: str) -> int:
    m = _DUR.match((value or "").strip())
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def classify_format(seconds: int) -> str:
    return "short" if 0 < seconds <= SHORT_MAX_SECONDS else "long"


def _thumb(snippet: dict) -> str | None:
    t = snippet.get("thumbnails", {})
    best = t.get("high") or t.get("medium") or t.get("default") or {}
    return best.get("url")


def parse_channel(raw: dict) -> dict:
    sn, st, cd = raw.get("snippet", {}), raw.get("statistics", {}), raw.get("contentDetails", {})
    return {
        "external_id": raw["id"],
        "name": sn.get("title", raw["id"]),
        "avatar_url": _thumb(sn),
        "subscriber_count": None if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount", 0) or 0),
        "uploads_playlist_id": cd.get("relatedPlaylists", {}).get("uploads"),
    }


def parse_video(raw: dict) -> dict:
    sn, st, cd = raw.get("snippet", {}), raw.get("statistics", {}), raw.get("contentDetails", {})
    secs = parse_duration(cd.get("duration", ""))
    return {
        "id": raw["id"],
        "title": sn.get("title") or "(untitled)",
        "thumbnail_url": _thumb(sn),
        "views": int(st.get("viewCount", 0) or 0),
        "likes": int(st["likeCount"]) if "likeCount" in st else None,
        "comments": int(st["commentCount"]) if "commentCount" in st else None,
        "published_at": datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00")),
        "duration_seconds": secs,
        "format": classify_format(secs),
    }


def resolve_input(value: str) -> tuple[str | None, str | None]:
    """'@handle', 'handle', 'UC…' id or a youtube.com URL → (channel_id, handle)."""
    v = value.strip()
    if "youtube.com" in v or "youtu.be" in v:
        v = v.split("?")[0].rstrip("/").split("/")[-1]
    if v.startswith("UC") and len(v) == 24:
        return v, None
    v = v.lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,100}", v):
        raise YouTubeError("That doesn't look like a YouTube handle, channel URL or channel ID")
    return None, "@" + v


# ── overperformance (identical maths to TW-Labs) ───────────────────────────
@dataclass
class BaselineResult:
    avg: float | None
    ratio: float | None
    median: float | None
    ratio_median: float | None


def compute_baselines(rows: list[tuple[str, str, datetime, int]], *, window: int, min_videos: int) -> dict[str, BaselineResult]:
    """rows = (id, format, published_at, views). Trailing window per format,
    never including the video itself or anything published after it."""
    out: dict[str, BaselineResult] = {}
    by_format: dict[str, list] = {}
    for r in rows:
        by_format.setdefault(r[1], []).append(r)
    for group in by_format.values():
        trailing: list[int] = []
        for vid, _fmt, _pub, views in sorted(group, key=lambda r: (r[2], r[0])):
            if len(trailing) >= min_videos:
                w = trailing[-window:]
                avg, med = sum(w) / len(w), statistics.median(w)
                out[vid] = BaselineResult(avg, views / avg if avg > 0 else None, med, views / med if med > 0 else None)
            else:
                out[vid] = BaselineResult(None, None, None, None)
            trailing.append(views)
    return out


def recompute_baselines(db: Session, channel_id: int) -> None:
    s = get_settings()
    videos = db.scalars(select(Video).where(Video.channel_id == channel_id)).all()
    res = compute_baselines(
        [(v.id, v.format, as_utc(v.published_at), v.views) for v in videos],
        window=s.baseline_window_videos,
        min_videos=s.baseline_min_videos,
    )
    for v in videos:
        r = res.get(v.id)
        v.avg_views_baseline, v.overperform_ratio = (r.avg, r.ratio) if r else (None, None)
        v.median_views_baseline, v.overperform_ratio_median = (r.median, r.ratio_median) if r else (None, None)
    # velocity ratios use the same trailing-window idea, per checkpoint
    checkpoints = s.velocity_checkpoint_hours_list
    by_format: dict[str, list[Video]] = {}
    for v in videos:
        by_format.setdefault(v.format, []).append(v)
    for group in by_format.values():
        windows: dict[int, list[int]] = {}
        for v in sorted(group, key=lambda x: (as_utc(x.published_at), x.id)):
            for h in checkpoints:
                views = getattr(v, f"h{h}_views")
                if views is None:
                    setattr(v, f"h{h}_ratio", None)
                    continue
                trailing = windows.setdefault(h, [])
                if len(trailing) >= s.baseline_min_videos:
                    w = trailing[-s.baseline_window_videos :]
                    base = sum(w) / len(w)
                    setattr(v, f"h{h}_ratio", views / base if base > 0 else None)
                else:
                    setattr(v, f"h{h}_ratio", None)
                trailing.append(views)


# ── SponsorBlock ───────────────────────────────────────────────────────────
def check_sponsors(db: Session, videos: list[Video], budget: int, http: httpx.Client | None = None) -> int:
    s = get_settings()
    if not s.sponsorblock_enabled or budget <= 0:
        return 0
    now = utcnow()
    cats = s.sponsorblock_category_list
    client = http or httpx.Client(timeout=8)
    checked = 0
    try:
        for v in videos:
            if checked >= budget:
                break
            last = as_utc(v.sponsor_checked_at)
            if last and now - last < timedelta(hours=s.sponsorblock_recheck_hours):
                continue
            try:
                r = client.get(f"{s.sponsorblock_api_base}/api/skipSegments", params={"videoID": v.id, "category": cats})
            except httpx.HTTPError:
                continue
            if r.status_code == 429:
                break
            segs = r.json() if r.status_code == 200 else []
            total = 0.0
            for seg in segs if isinstance(segs, list) else []:
                if seg.get("category") in cats:
                    a, b = (seg.get("segment") or [0, 0])[:2]
                    total += max(0.0, float(b) - float(a))
            v.has_sponsor_segment = total > 0
            v.sponsor_segment_seconds = round(total, 1) if total else None
            v.sponsor_checked_at = now
            checked += 1
    finally:
        if http is None:
            client.close()
    return checked


# ── scraping ───────────────────────────────────────────────────────────────
@dataclass
class ScrapeStats:
    channels: int = 0
    videos_new: int = 0
    videos_updated: int = 0
    units: int = 0
    errors: list[str] = field(default_factory=list)


def add_channel(db: Session, client: YouTubeClient, value: str, *, cohort: str | None, site_id: int | None) -> Channel:
    cid, handle = resolve_input(value)
    raw = client.get_channel(channel_id=cid, handle=handle)
    record_usage(db, "youtube", client.units)
    client.units = 0
    if raw is None:
        raise YouTubeError(f"No YouTube channel found for {value!r}")
    p = parse_channel(raw)
    if db.scalar(select(Channel).where(Channel.external_id == p["external_id"])):
        raise YouTubeError(f"{p['name']} is already tracked")
    ch = Channel(handle=handle or p["external_id"], cohort=cohort, site_id=site_id, **p)
    db.add(ch)
    db.commit()
    return ch


def scrape_channel(db: Session, client: YouTubeClient, ch: Channel, stats: ScrapeStats, *, sponsor_budget: list[int], sponsor_http=None) -> None:
    raw = client.get_channel(channel_id=ch.external_id)
    if raw is None:
        raise YouTubeError("channel no longer exists")
    p = parse_channel(raw)
    ch.name, ch.avatar_url, ch.subscriber_count = p["name"], p["avatar_url"], p["subscriber_count"]
    ch.uploads_playlist_id = p["uploads_playlist_id"]
    tracked = list(db.scalars(select(Video.id).where(Video.channel_id == ch.id)))
    pages = BACKFILL_PAGES if not tracked else 1
    discovered = client.list_upload_ids(ch.uploads_playlist_id, max_pages=pages) if ch.uploads_playlist_id else []
    ids = list(dict.fromkeys(discovered + tracked))
    now = utcnow()
    existing = {v.id: v for v in db.scalars(select(Video).where(Video.id.in_(ids)))} if ids else {}
    for rv in client.get_videos(ids) if ids else []:
        try:
            pv = parse_video(rv)
        except (KeyError, ValueError, TypeError) as e:
            stats.errors.append(f"skipped video {rv.get('id')}: {e}")
            continue
        v = existing.get(pv["id"])
        if v is None:
            db.add(Video(channel_id=ch.id, first_seen_at=now, updated_at=now, **pv))
            stats.videos_new += 1
        else:
            for k, val in pv.items():
                setattr(v, k, val)
            v.updated_at = now
            stats.videos_updated += 1
    db.flush()
    recompute_baselines(db, ch.id)
    newest = list(db.scalars(select(Video).where(Video.channel_id == ch.id).order_by(Video.published_at.desc()).limit(25)))
    sponsor_budget[0] -= check_sponsors(db, newest, sponsor_budget[0], sponsor_http)
    ch.last_scraped_at, ch.last_error = now, None
    db.commit()


def scrape_all(db: Session, client: YouTubeClient | None = None, *, sponsor_http=None) -> ScrapeStats:
    s = get_settings()
    stats = ScrapeStats()
    client = client or YouTubeClient(s.youtube_api_key)
    budget = [s.sponsorblock_max_checks_per_scrape]
    for ch in db.scalars(select(Channel).where(Channel.is_active.is_(True)).order_by(Channel.id)):
        try:
            scrape_channel(db, client, ch, stats, sponsor_budget=budget, sponsor_http=sponsor_http)
            stats.channels += 1
        except YouTubeError as e:
            db.rollback()
            ch.last_error = str(e)[:500]
            db.commit()
            stats.errors.append(f"{ch.name}: {e}")
            if "quota" in str(e).lower():
                break
    stats.units = client.units
    record_usage(db, "youtube", client.units)
    return stats


def capture_velocity(db: Session, client: YouTubeClient | None = None) -> int:
    """Hourly: record views for videos whose 1/3/6 h checkpoint is due."""
    s = get_settings()
    checkpoints = s.velocity_checkpoint_hours_list
    if not checkpoints:
        return 0
    now = utcnow()
    horizon = now - timedelta(hours=max(checkpoints) + s.velocity_checkpoint_grace_hours)
    due: list[tuple[Video, float]] = []
    for v in db.scalars(select(Video).where(Video.published_at >= horizon)):
        hours = (now - as_utc(v.published_at)).total_seconds() / 3600
        if any(getattr(v, f"h{h}_views") is None and h <= hours <= h + s.velocity_checkpoint_grace_hours for h in checkpoints):
            due.append((v, hours))
    if not due:
        return 0
    client = client or YouTubeClient(s.youtube_api_key)
    fresh = {r["id"]: r for r in client.get_videos([v.id for v, _ in due])}
    record_usage(db, "youtube", client.units)
    captured = 0
    channels: set[int] = set()
    for v, hours in due:
        raw = fresh.get(v.id)
        if not raw:
            continue
        views = int(raw.get("statistics", {}).get("viewCount", 0) or 0)
        v.views = max(v.views, views)
        v.velocity_checked_at = now
        for h in checkpoints:
            if getattr(v, f"h{h}_views") is None and h <= hours <= h + s.velocity_checkpoint_grace_hours:
                setattr(v, f"h{h}_views", views)
                captured += 1
        channels.add(v.channel_id)
    db.flush()
    for cid in channels:
        recompute_baselines(db, cid)
    db.commit()
    return captured


# ── community posts via Apify ──────────────────────────────────────────────
_REL = re.compile(r"(\d+)\s*(second|minute|hour|day|week|month|year)s?\s*ago", re.I)
_UNIT_HOURS = {"second": 1 / 3600, "minute": 1 / 60, "hour": 1, "day": 24, "week": 168, "month": 720, "year": 8760}


def _first(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return None


def _to_int(v) -> int | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().upper().replace(",", "")
    m = re.match(r"^([\d.]+)\s*([KMB]?)", s)
    if not m:
        return None
    n = float(m.group(1)) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2)]
    return int(n)


def normalize_post(item: dict, now: datetime) -> dict | None:
    """Tolerant to the different field names community-post actors use."""
    pid = _first(item, "postId", "id", "post_id")
    url = _first(item, "url", "postUrl", "post_url", "link")
    if not pid and url:
        m = re.search(r"/post/([A-Za-z0-9_-]+)", str(url))
        pid = m.group(1) if m else None
    if not pid:
        return None
    text = _first(item, "text", "content", "contentText", "postText", "description")
    if isinstance(text, list):
        text = " ".join(str(t.get("text", t)) if isinstance(t, dict) else str(t) for t in text)
    images = _first(item, "images", "imageUrls", "image_urls", "thumbnails", "media")
    image = _first(item, "imageUrl", "image", "thumbnail")
    if not image and isinstance(images, list) and images:
        first = images[0]
        image = first.get("url") if isinstance(first, dict) else first
    poll = _first(item, "pollOptions", "poll", "choices")
    if isinstance(poll, dict):
        poll = poll.get("choices") or poll.get("options")
    if isinstance(poll, list):
        poll = [str(p.get("text", p)) if isinstance(p, dict) else str(p) for p in poll][:10]
    video = _first(item, "videoId", "attachedVideoId", "sharedVideoId")
    if not video:
        vobj = _first(item, "video", "attachedVideo", "sharedVideo")
        if isinstance(vobj, dict):
            video = vobj.get("videoId") or vobj.get("id")
    published_text = _first(item, "publishedTimeText", "publishedTime", "published", "date", "publishedText", "time")
    published = parse_dt(_first(item, "publishedAt", "timestamp", "datePublished"))
    if published is None and isinstance(published_text, str):
        m = _REL.search(published_text)
        if m:
            published = now - timedelta(hours=int(m.group(1)) * _UNIT_HOURS[m.group(2).lower()])
        else:
            published = parse_dt(published_text)
    ptype = _first(item, "postType", "type")
    if not ptype:
        ptype = "poll" if poll else "video" if video else "image" if image else "text"
    return {
        "id": str(pid)[:80],
        "post_type": str(ptype).lower()[:20],
        "text": (str(text)[:4000] if text else None),
        "url": str(url) if url else f"https://www.youtube.com/post/{pid}",
        "image_url": str(image)[:2048] if image else None,
        "video_id": str(video)[:32] if video else None,
        "poll_options": poll if isinstance(poll, list) else None,
        "likes": _to_int(_first(item, "likes", "likeCount", "voteCount", "votes", "likesCount")),
        "comments": _to_int(_first(item, "comments", "commentCount", "commentsCount", "replyCount", "replies")),
        "published_text": str(published_text)[:80] if published_text else None,
        "published_at": published,
    }


def scrape_posts(db: Session, http: httpx.Client | None = None) -> tuple[int, list[str]]:
    s = get_settings()
    if not s.apify_api_token:
        return 0, ["APIFY_API_TOKEN not set — community posts are skipped"]
    channels = list(db.scalars(select(Channel).where(Channel.is_active.is_(True), Channel.track_posts.is_(True))))
    if not channels:
        return 0, []
    by_handle: dict[str, Channel] = {}
    for ch in channels:
        by_handle[ch.external_id.lower()] = ch
        by_handle[ch.handle.lower().lstrip("@")] = ch
    actor = s.apify_posts_actor_id.replace("/", "~")
    client = http or httpx.Client(timeout=300)
    errors: list[str] = []
    new = 0
    try:
        r = client.post(
            f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items",
            params={"token": s.apify_api_token, "timeout": 280},
            json={"urls": [f"https://www.youtube.com/channel/{c.external_id}" for c in channels],
                  "maxPostsPerChannel": s.apify_max_posts_per_channel},
        )
        if r.status_code >= 300:
            return 0, [f"Apify {r.status_code}: {r.text[:200]}"]
        items = r.json()
    except (httpx.HTTPError, ValueError) as e:
        return 0, [f"Apify request failed: {e}"]
    finally:
        if http is None:
            client.close()
    record_usage(db, "apify_posts", len(items) if isinstance(items, list) else 0)
    now = utcnow()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        keys = [str(_first(item, k) or "") for k in ("channelId", "channel_id", "authorChannelId", "channelHandle", "handle", "channelUrl", "inputUrl", "author")]
        ch = None
        for k in keys:
            k = k.lower().rstrip("/").split("/")[-1].lstrip("@")
            if k in by_handle:
                ch = by_handle[k]
                break
        if ch is None and len(channels) == 1:
            ch = channels[0]
        p = normalize_post(item, now)
        if ch is None or p is None:
            continue
        row = db.get(CommunityPost, p["id"])
        if row is None:
            db.add(CommunityPost(channel_id=ch.id, first_seen_at=now, **p))
            new += 1
        else:
            for k in ("text", "image_url", "likes", "comments", "poll_options"):
                if p[k] is not None:
                    setattr(row, k, p[k])
    for ch in channels:
        ch.posts_scraped_at = now
    db.commit()
    return new, errors


# ── cross-links: YouTube embeds inside tracked articles ────────────────────
def embed_counts(db: Session, video_ids: list[str], since_days: int = 60) -> dict[str, int]:
    """How many tracked articles embed each video (article.youtube_ids)."""
    if not video_ids:
        return {}
    wanted = set(video_ids)
    since = utcnow() - timedelta(days=since_days)
    counts: dict[str, int] = {}
    for ids in db.scalars(select(Article.youtube_ids).where(Article.first_seen_at >= since, Article.youtube_ids.is_not(None))):
        for vid in ids or []:
            if vid in wanted:
                counts[vid] = counts.get(vid, 0) + 1
    return counts


def channel_stats(db: Session) -> dict[int, dict]:
    rows = db.execute(
        select(Video.channel_id, func.count(Video.id), func.max(Video.published_at)).group_by(Video.channel_id)
    ).all()
    out = {cid: {"video_count": n, "last_published_at": last} for cid, n, last in rows}
    for cid in out:
        views = list(db.scalars(select(Video.views).where(Video.channel_id == cid).order_by(Video.published_at.desc()).limit(10)))
        out[cid]["median_views_last10"] = int(statistics.median(views)) if views else None
    return out


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
