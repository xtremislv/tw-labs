"""The article tracker: poll → ingest → enrich → detect updates.

poll_site()       fetch the site's fast source (WP REST / news sitemap / RSS,
                  falling back down the list), ingest what it lists
sweep_site()      walk the full sitemap's recent children — catches anything
                  the fast source missed; with backfill=True it's the first
                  30-day import of a newly added site
ingest()          upsert Candidate URLs: new → Article(pending); a moved
                  lastmod on a known article → schedule a recheck
enrich_pending()  fetch + parse queued articles; on a recheck, compare with
                  the stored version and record an ArticleVersion only for a
                  real content change
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from .config import get_settings
from .discovery import PRIORITY, DiscoveryResult, discover
from .extract import compare_versions, extract_page
from .fetcher import FetchError, Fetcher
from .models import Article, ArticleVersion, JobRequest, JobRun, Site, SiteSource
from .parsers import (
    Candidate,
    choose_child_sitemaps,
    is_feed,
    latest_date_children,
    parse_feed,
    parse_homepage_links,
    parse_sitemap,
    parse_wp_posts,
)
from .timeutil import as_utc, utcnow
from .urlnorm import canonicalize, looks_like_article, same_site

log = logging.getLogger("webintel.tracker")

FAST_KINDS = ("wp_rest", "news_sitemap", "rss", "html")
IST = timezone(timedelta(hours=5, minutes=30))
# child sitemap URL → the <lastmod> it had when we last read it. Lets a poll
# skip children that haven't changed since the previous pass (in-process
# only; a restart simply re-reads today's children once).
_CHILD_SEEN: dict[str, datetime] = {}
MIN_ARTICLE_WORDS = 80


# ── job logging ────────────────────────────────────────────────────────────
@contextmanager
def job_run(db: Session, job: str, *, site_id: int | None = None, trigger: str = "schedule"):
    run = JobRun(job=job, site_id=site_id, trigger=trigger, started_at=utcnow())
    db.add(run)
    db.commit()
    try:
        yield run
        run.ok = True
    except Exception as e:  # noqa: BLE001 - recorded, then re-raised
        db.rollback()
        run.ok = False
        run.error = f"{type(e).__name__}: {e}"[:2000]
        raise
    finally:
        run.finished_at = utcnow()
        db.add(run)
        db.commit()


# ── sources ────────────────────────────────────────────────────────────────
def apply_discovery(db: Session, site: Site, result: DiscoveryResult) -> None:
    """Replace a site's sources with a fresh discovery result, keeping the
    ETag/health history of any source URL that's still present."""
    existing = {s.url: s for s in site.sources}
    keep: list[SiteSource] = []
    for f in result.sources:
        src = existing.pop(f.url, None) or SiteSource(site_id=site.id, kind=f.kind, url=f.url)
        src.kind, src.priority, src.enabled = f.kind, PRIORITY[f.kind], True
        src.last_item_count = f.item_count
        src.consecutive_errors = 0
        keep.append(src)
    for gone in existing.values():
        db.delete(gone)
    site.sources = keep
    if result.name and (not site.name or site.name == site.domain):
        site.name = result.name
    site.icon_url = result.icon_url or site.icon_url
    site.home_url = result.home_url
    db.commit()


def rediscover(db: Session, fetcher: Fetcher, site: Site, *, trigger: str = "schedule") -> DiscoveryResult:
    with job_run(db, "discover", site_id=site.id, trigger=trigger) as run:
        result = discover(fetcher, site.domain)
        apply_discovery(db, site, result)
        run.items_processed = len(result.sources)
        run.detail = "\n".join(result.log)[:8000]
    return result


def _parse_source(src: SiteSource, text: str, content: bytes, site: Site) -> list[Candidate]:
    if src.kind == "wp_rest":
        return parse_wp_posts(text)
    if src.kind == "rss":
        if not is_feed(text):
            raise ValueError("response is no longer an RSS/Atom feed")
        return parse_feed(text)
    if src.kind == "html":
        return parse_homepage_links(text, src.url, site.domain)
    doc = parse_sitemap(content or text)
    if doc.is_index:
        raise ValueError("expected a urlset, got a sitemap index")
    return doc.urls


def _fetch_source(db: Session, fetcher: Fetcher, src: SiteSource, site: Site) -> list[Candidate] | None:
    """Fetch + parse one source. Returns [] on 304 Not Modified, None on error."""
    src.last_checked_at = utcnow()
    try:
        r = fetcher.get(src.url, etag=src.etag, last_modified=src.last_modified)
        if r.not_modified:
            src.last_ok_at, src.consecutive_errors, src.last_error = utcnow(), 0, None
            return []
        if not r.ok:
            raise FetchError(f"HTTP {r.status}")
        items = _parse_source(src, r.text, r.content, site)
        src.etag = r.headers.get("etag")
        src.last_modified = r.headers.get("last-modified")
        src.last_ok_at, src.consecutive_errors, src.last_error = utcnow(), 0, None
        src.last_item_count = len(items)
        return items
    except Exception as e:  # noqa: BLE001 - any failure moves us to the next source
        src.consecutive_errors += 1
        src.last_error = f"{type(e).__name__}: {e}"[:500]
        log.warning("source %s failed: %s", src.url, src.last_error)
        return None
    finally:
        db.commit()


# ── ingest ─────────────────────────────────────────────────────────────────
def slug_title(url: str) -> str | None:
    """'https://x.com/best-phones-under-30000/' → 'Best phones under 30000'."""
    segs = [p for p in urlsplit(url).path.split("/") if p]
    if not segs:
        return None
    words = re.sub(r"\.(html?|php)$", "", segs[-1]).replace("_", "-").split("-")
    words = [w for w in words if w]
    if words and re.fullmatch(r"\d{5,}", words[-1]):
        words = words[:-1]  # trailing numeric post id
    text = " ".join(words).strip()
    return (text[:1].upper() + text[1:]) if text else None



def ingest(db: Session, site: Site, candidates: list[Candidate], *, backfill: bool) -> tuple[int, int]:
    """Upsert candidates. Returns (new_articles, rechecks_scheduled)."""
    s = get_settings()
    now = utcnow()
    cutoff = now - timedelta(days=s.backfill_days)
    by_url: dict[str, Candidate] = {}
    for c in candidates:
        if not c.url or not c.url.startswith("http"):
            continue
        canon = canonicalize(c.url)
        if c.kind in ("sitemap", "html") and not looks_like_article(canon, site.domain):
            continue
        if c.kind in ("sitemap", "news_sitemap") and not same_site(canon, site.domain):
            continue
        prev = by_url.get(canon)
        if prev is None or (c.lastmod and (prev.lastmod is None or c.lastmod > prev.lastmod)):
            by_url[canon] = c
    if not by_url:
        return 0, 0

    existing: dict[str, Article] = {}
    urls = list(by_url)
    for i in range(0, len(urls), 500):
        for a in db.scalars(select(Article).where(Article.url.in_(urls[i : i + 500]))):
            existing[a.url] = a

    new = rechecks = 0
    for canon, c in by_url.items():
        art = existing.get(canon)
        lastmod = as_utc(c.lastmod)
        if art is None:
            when = as_utc(c.published) or lastmod
            if when is not None and when < cutoff:
                continue  # older than the tracking window — not our concern
            # Sitemap entries carry no title or publish date; use the slug and
            # <lastmod> until the page is read, so the article is visible in
            # the feed right away (and stays visible if the page can't be read).
            prov_pub = as_utc(c.published) or (lastmod if c.kind == "sitemap" else None)
            art = Article(
                site_id=site.id,
                url=canon,
                title=c.title or slug_title(canon),
                published_at=prov_pub,
                source_lastmod=lastmod,
                first_seen_at=now,
                activity_at=prov_pub or now,
                is_backfill=backfill,
                discovered_via=c.kind,
                enrich_status="pending",
            )
            db.add(art)
            new += 1
            continue
        if not art.title:
            # rows added before provisional titles existed stayed hidden
            art.title = c.title or slug_title(canon)
        if art.published_at is None and art.enrich_status != "ok":
            art.published_at = as_utc(c.published) or (lastmod if c.kind == "sitemap" else None)
            if art.published_at:
                art.activity_at = art.published_at
        old = as_utc(art.source_lastmod)
        if lastmod and (old is None or lastmod > old + timedelta(minutes=1)):
            art.source_lastmod = lastmod
            if art.enrich_status in ("ok", "skipped"):
                art.enrich_status = "recheck"
                art.next_check_at = now
                rechecks += 1
    db.commit()
    return new, rechecks


# ── latest-date sitemap pass ───────────────────────────────────────────────
def latest_sitemap_pass(db: Session, fetcher: Fetcher, site: Site) -> tuple[list[Candidate], str] | None:
    """Read every child sitemap carrying the index's latest date.

    Returns (candidates, note), or None when the site has no sitemap index.
    The WP REST API only lists the "post" type and RSS only the last few
    items, so this is what catches custom post types (reviews, deals, how-tos)
    and busy days with more posts than the feed holds.
    """
    s = get_settings()
    srcs = [x for x in site.sources if x.enabled and x.kind == "sitemap"]
    if not srcs:
        return None
    src = srcs[0]
    since = as_utc(src.last_ok_at) - timedelta(minutes=30) if src.last_ok_at else None
    r = fetcher.get(src.url)
    if not r.ok:
        raise FetchError(f"sitemap index HTTP {r.status}")
    doc = parse_sitemap(r.content or r.text)
    if not doc.is_index:
        return None  # a single urlset is already covered by the 6-hourly sweep
    limit = s.latest_sitemaps_max_children
    chosen = latest_date_children(doc.children, tz=IST, since=since, limit=limit)
    cands: list[Candidate] = []
    read = skipped = 0
    for child in chosen:
        lm = as_utc(child.lastmod)
        if lm is not None and _CHILD_SEEN.get(child.url) == lm:
            skipped += 1
            continue
        try:
            cr = fetcher.get(child.url)
            if not cr.ok:
                continue
            cdoc = parse_sitemap(cr.content or cr.text)
            if cdoc.is_index:  # nested index (e.g. per-year) → same rule one level down
                for g in latest_date_children(cdoc.children, tz=IST, since=since, limit=limit):
                    gr = fetcher.get(g.url)
                    if gr.ok:
                        cands += parse_sitemap(gr.content or gr.text).urls
            else:
                cands += cdoc.urls
            read += 1
            if lm is not None:
                _CHILD_SEEN[child.url] = lm
        except Exception as e:  # noqa: BLE001 - one bad child mustn't stop the rest
            log.warning("latest sitemap %s: %s", child.url, e)
    src.last_ok_at, src.consecutive_errors, src.last_error = utcnow(), 0, None
    db.commit()
    latest = max((c.lastmod for c in chosen if c.lastmod), default=None)
    day = latest.astimezone(IST).strftime("%d %b") if latest else "no dates"
    return cands, f"sitemaps dated {day}: read {read}, unchanged {skipped}, {len(cands)} URLs"


def ingest_sitemap_candidates(db: Session, site: Site, cands: list[Candidate]) -> tuple[int, int]:
    """Ingest a latest-date pass. A child sitemap lists up to 1,000 posts, so
    entries not touched in the last 2 days are filed as backfill — they
    never show up as NEW or unread, only genuinely fresh posts do."""
    fresh_after = utcnow() - timedelta(days=2)
    fresh = [c for c in cands if c.lastmod is None or as_utc(c.lastmod) >= fresh_after]
    old = [c for c in cands if c.lastmod is not None and as_utc(c.lastmod) < fresh_after]
    n1, r1 = ingest(db, site, fresh, backfill=False)
    n2, r2 = ingest(db, site, old, backfill=True)
    return n1 + n2, r1 + r2


def sitemap_coverage(db: Session, fetcher: Fetcher, site: Site) -> dict:
    """Diagnose (and fix) one site: read every child sitemap carrying the
    index's latest date, ingest anything missing, and report per child how
    many of its latest-date URLs are tracked and visible."""
    srcs = [x for x in site.sources if x.enabled and x.kind == "sitemap"]
    if not srcs:
        return {"index_url": None, "error": "No sitemap found for this site — try “Re-scan feeds”.", "children": []}
    src = srcs[0]
    r = fetcher.get(src.url)
    if not r.ok:
        return {"index_url": src.url, "error": f"Sitemap returned HTTP {r.status}", "children": []}
    doc = parse_sitemap(r.content or r.text)
    if not doc.is_index:
        children = [(None, doc)]
        latest_day = None
    else:
        chosen = latest_date_children(doc.children, tz=IST, limit=get_settings().latest_sitemaps_max_children)
        latest = max((c.lastmod for c in chosen if c.lastmod), default=None)
        latest_day = latest.astimezone(IST).date() if latest else None
        children = []
        for c in chosen:
            try:
                cr = fetcher.get(c.url)
                children.append((c, parse_sitemap(cr.content or cr.text) if cr.ok else None))
            except Exception:  # noqa: BLE001
                children.append((c, None))
    out = []
    all_cands: list[Candidate] = []
    for entry, cdoc in children:
        row = {"url": entry.url if entry else src.url, "lastmod": entry.lastmod.isoformat() if entry and entry.lastmod else None,
               "urls": 0, "latest_day_urls": 0, "tracked": 0, "visible": 0, "missing": []}
        if cdoc is None or cdoc.is_index:
            row["error"] = "couldn't read this sitemap" if cdoc is None else "nested index (read by the poll)"
            out.append(row)
            continue
        all_cands += cdoc.urls
        day = latest_day or max((u.lastmod for u in cdoc.urls if u.lastmod), default=utcnow()).astimezone(IST).date()
        todays = [u for u in cdoc.urls if u.lastmod and u.lastmod.astimezone(IST).date() == day]
        row["urls"], row["latest_day_urls"], row["day"] = len(cdoc.urls), len(todays), day.isoformat()
        out.append((row, todays))
    # ingest first, so the report shows the state after the fix
    new, _ = ingest_sitemap_candidates(db, site, all_cands)
    final = []
    from .routers.articles import VISIBLE  # noqa: PLC0415 - avoid an import cycle at module load
    for item in out:
        if isinstance(item, dict):
            final.append(item)
            continue
        row, todays = item
        canon = {canonicalize(u.url): u.url for u in todays}
        arts = {a.url: a for a in db.scalars(select(Article).where(Article.url.in_(list(canon) or [""])))}
        for cu, raw in canon.items():
            a = arts.get(cu)
            if a is None:
                reason = "not an article URL (filtered)" if not looks_like_article(cu, site.domain) else "older than the tracking window"
                row["missing"].append({"url": raw, "reason": reason})
                continue
            row["tracked"] += 1
            vis = a.title and (a.enrich_status in VISIBLE or (a.enrich_status == "skipped" and a.discovered_via != "html"))
            if vis:
                row["visible"] += 1
            else:
                row["missing"].append({"url": raw, "reason": f"{a.enrich_status}: {a.last_error or ''}".strip(": ")})
        row["missing"] = row["missing"][:40]
        final.append(row)
    return {"index_url": src.url, "latest_day": latest_day.isoformat() if latest_day else None, "added_now": new, "children": final}


# ── poll + sweep ───────────────────────────────────────────────────────────
def poll_site(db: Session, fetcher: Fetcher, site: Site, *, trigger: str = "schedule", backfill: bool = False) -> JobRun:
    with job_run(db, "poll", site_id=site.id, trigger=trigger) as run:
        site.last_poll_at = utcnow()
        sources = [s for s in site.sources if s.enabled and s.kind in FAST_KINDS]
        sources.sort(key=lambda s: (s.consecutive_errors >= 3, s.priority))
        items = None
        for src in sources:
            items = _fetch_source(db, fetcher, src, site)
            if items is not None:
                break
        new = rech = processed = 0
        if items is not None:
            new, rech = ingest(db, site, items, backfill=backfill)
            processed = len(items)

        # Latest-date sitemap pass: every child sitemap updated today.
        sm_ok = False
        if get_settings().latest_sitemaps_on_poll and not backfill:
            try:
                res = latest_sitemap_pass(db, fetcher, site)
                if res is not None:
                    cands, note = res
                    n, rc = ingest_sitemap_candidates(db, site, cands)
                    new, rech, processed = new + n, rech + rc, processed + len(cands)
                    run.detail = note
                    sm_ok = True
            except Exception as e:  # noqa: BLE001 - the fast source result still stands
                db.rollback()
                log.warning("latest sitemap pass %s: %s", site.domain, e)
                run.detail = f"sitemap pass failed: {type(e).__name__}: {e}"[:500]

        if items is None and not sm_ok:
            site.last_error = (
                "No feeds found — the site may be blocking automated requests. Try “Re-scan feeds”."
                if not sources
                else "Every feed failed on the last check — see the sources below."
            )
            db.commit()
            if not sources:
                return run
            raise FetchError(site.last_error)
        run.items_new, run.items_updated, run.items_processed = new, rech, processed
        site.last_poll_ok_at, site.last_error = utcnow(), None
        db.commit()
    return run


def sweep_site(db: Session, fetcher: Fetcher, site: Site, *, trigger: str = "schedule", backfill: bool = False) -> JobRun:
    s = get_settings()
    with job_run(db, "backfill" if backfill else "sweep", site_id=site.id, trigger=trigger) as run:
        cutoff = utcnow() - (timedelta(days=s.backfill_days) if backfill else timedelta(days=3))
        total_new = total_rech = total_items = 0
        for src in [x for x in site.sources if x.enabled and x.kind in ("sitemap", "news_sitemap")]:
            src.last_checked_at = utcnow()
            try:
                r = fetcher.get(src.url)
                if not r.ok:
                    raise FetchError(f"HTTP {r.status}")
                doc = parse_sitemap(r.content or r.text)
                cands: list[Candidate] = []
                if doc.is_index:
                    limit = s.max_child_sitemaps_per_sweep * (3 if backfill else 1)
                    # The usual post/news children, plus every other child (any
                    # post type) changed inside the window.
                    picked = choose_child_sitemaps(doc.children, cutoff=cutoff, limit=limit)
                    picked += [c for c in latest_date_children(doc.children, tz=IST, since=cutoff, limit=s.latest_sitemaps_max_children)
                               if c.url not in {p.url for p in picked}]
                    for child in picked:
                        try:
                            cr = fetcher.get(child.url)
                            if not cr.ok:
                                continue
                            cdoc = parse_sitemap(cr.content or cr.text)
                            if cdoc.is_index:  # one more level, e.g. year → month
                                for g in choose_child_sitemaps(cdoc.children, cutoff=cutoff, limit=2):
                                    gr = fetcher.get(g.url)
                                    if gr.ok:
                                        cands += parse_sitemap(gr.content or gr.text).urls
                            else:
                                cands += cdoc.urls
                        except Exception as e:  # noqa: BLE001
                            log.warning("child sitemap %s: %s", child.url, e)
                else:
                    cands = doc.urls
                src.last_ok_at, src.consecutive_errors, src.last_error = utcnow(), 0, None
                src.last_item_count = len(cands)
                db.commit()
            except Exception as e:  # noqa: BLE001
                src.consecutive_errors += 1
                src.last_error = f"{type(e).__name__}: {e}"[:500]
                db.commit()
                continue
            n, rc = ingest(db, site, cands, backfill=backfill)
            total_new, total_rech, total_items = total_new + n, total_rech + rc, total_items + len(cands)
        run.items_new, run.items_updated, run.items_processed = total_new, total_rech, total_items
    return run


def backfill_site(db: Session, fetcher: Fetcher, site: Site, *, trigger: str = "add_site") -> None:
    site.backfill_status = "running"
    db.commit()
    try:
        if not site.sources:
            rediscover(db, fetcher, site, trigger=trigger)
        sweep_site(db, fetcher, site, trigger=trigger, backfill=True)
        try:
            poll_site(db, fetcher, site, trigger=trigger, backfill=True)
        except FetchError:
            pass
        site.backfill_status = "done"
    except Exception:
        site.backfill_status = "error"
        raise
    finally:
        db.commit()


# ── enrichment ─────────────────────────────────────────────────────────────
def _queue(db: Session, limit: int) -> list[Article]:
    s = get_settings()
    now = utcnow()
    recent = now - timedelta(days=s.recheck_recent_days)
    q = (
        select(Article)
        .join(Site)
        .where(Site.paused.is_(False))
        .where(
            or_(
                Article.enrich_status.in_(("pending", "recheck")),
                and_(
                    Article.enrich_status == "ok",
                    Article.next_check_at.is_not(None),
                    Article.next_check_at <= now,
                    Article.published_at >= recent,
                ),
            )
        )
        .where(or_(Article.next_check_at.is_(None), Article.next_check_at <= now))
        .order_by(Article.is_backfill.asc(), Article.first_seen_at.desc())
        .limit(limit * 4)
    )
    rows = list(db.scalars(q))
    # Round-robin across sites so one site's 900-article backfill can't
    # starve everyone else, and the per-domain delay overlaps.
    buckets: dict[int, list[Article]] = defaultdict(list)
    for a in rows:
        buckets[a.site_id].append(a)
    out: list[Article] = []
    while len(out) < limit and any(buckets.values()):
        for sid in list(buckets):
            if buckets[sid]:
                out.append(buckets[sid].pop(0))
                if len(out) >= limit:
                    break
    return out


def enrich_article(db: Session, fetcher: Fetcher, art: Article) -> str:
    """Fetch + parse one article. Returns 'new', 'updated', 'unchanged',
    'skipped' or 'error'."""
    s = get_settings()
    now = utcnow()
    art.last_fetched_at = now
    try:
        r = fetcher.get(art.url)
        if r.status in (404, 410):
            art.enrich_status, art.last_error, art.next_check_at = "gone", f"HTTP {r.status}", None
            db.commit()
            return "skipped"
        if not r.ok:
            raise FetchError(f"HTTP {r.status}")
        pd = extract_page(r.text, r.url)
    except Exception as e:  # noqa: BLE001
        art.enrich_attempts += 1
        art.last_error = f"{type(e).__name__}: {e}"[:500]
        art.title = art.title or slug_title(art.url)
        if art.enrich_attempts >= s.enrich_max_attempts:
            art.enrich_status = "error"
            art.next_check_at = None
        else:
            art.next_check_at = now + timedelta(minutes=10 * art.enrich_attempts)
        db.commit()
        return "error"

    if not pd.content_hash or pd.word_count < MIN_ARTICLE_WORDS:
        art.enrich_status, art.next_check_at = "skipped", None
        art.title = art.title or pd.title
        art.last_error = "not an article (too little body text)"
        db.commit()
        return "skipped"

    outcome = "new" if art.content_hash is None else "unchanged"
    if art.content_hash is not None:
        ch = compare_versions(
            old_hash=art.content_hash,
            new_hash=pd.content_hash,
            old_paras=art.paragraph_hashes,
            new_paras=pd.paragraph_hashes,
            old_headings=art.headings,
            new_headings=pd.headings,
            old_title=art.title,
            new_title=pd.title,
            old_words=art.word_count,
            new_words=pd.word_count,
        )
        if ch.is_real_change:
            db.add(
                ArticleVersion(
                    article_id=art.id,
                    seen_at=now,
                    old_title=art.title,
                    new_title=pd.title,
                    old_word_count=art.word_count,
                    new_word_count=pd.word_count,
                    paragraphs_added=ch.paragraphs_added,
                    paragraphs_removed=ch.paragraphs_removed,
                    headings_added=ch.headings_added,
                    headings_removed=ch.headings_removed,
                    summary=ch.summary,
                )
            )
            art.update_count += 1
            art.last_updated_at = now
            outcome = "updated"

    art.title = pd.title or art.title
    art.excerpt = pd.excerpt
    art.author = pd.author
    art.section = pd.section
    art.tags = pd.tags
    art.content_type = pd.content_type
    art.thumbnail_url = pd.thumbnail_url or art.thumbnail_url
    art.word_count = pd.word_count
    art.image_count = pd.image_count
    art.youtube_ids = pd.youtube_ids
    art.affiliate_link_count = pd.affiliate_link_count
    art.headings = pd.headings
    art.paragraph_hashes = pd.paragraph_hashes
    art.content_hash = pd.content_hash
    art.published_at = pd.published_at or as_utc(art.published_at) or as_utc(art.first_seen_at)
    art.modified_at = pd.modified_at
    art.activity_at = max(x for x in (as_utc(art.published_at), as_utc(art.last_updated_at)) if x is not None)
    art.enrich_status = "ok"
    art.enrich_attempts = 0
    art.last_error = None
    pub = as_utc(art.published_at)
    if pub and pub >= now - timedelta(days=s.recheck_recent_days):
        art.next_check_at = now + timedelta(hours=s.recheck_interval_hours)
    else:
        art.next_check_at = None
    db.commit()
    return outcome


def enrich_pending(db: Session, fetcher: Fetcher, *, limit: int | None = None, trigger: str = "schedule") -> JobRun:
    s = get_settings()
    with job_run(db, "enrich", trigger=trigger) as run:
        batch = _queue(db, limit or s.enrich_batch_size)
        counts: dict[str, int] = defaultdict(int)
        for art in batch:
            counts[enrich_article(db, fetcher, art)] += 1
        run.items_processed = len(batch)
        run.items_new = counts["new"]
        run.items_updated = counts["updated"]
    return run


# ── housekeeping ───────────────────────────────────────────────────────────
def repair_untitled(db: Session) -> int:
    """Give a provisional title/date to rows stored before provisional titles
    existed, so they show in the feed instead of staying hidden."""
    n = 0
    for a in db.scalars(select(Article).where(Article.title.is_(None), Article.enrich_status != "gone").limit(5000)):
        a.title = slug_title(a.url)
        if a.published_at is None and a.source_lastmod is not None:
            a.published_at = a.activity_at = as_utc(a.source_lastmod)
        n += 1
    db.commit()
    return n


def housekeeping(db: Session, *, trigger: str = "schedule") -> JobRun:
    """Keep the database small: drop old articles (RETENTION_DAYS) and old
    job logs. Runs daily; essential on the 500 MB free Supabase database."""
    s = get_settings()
    now = utcnow()
    with job_run(db, "housekeeping", trigger=trigger) as run:
        removed = 0
        if s.retention_days > 0:
            cutoff = now - timedelta(days=s.retention_days)
            last_activity = func.coalesce(Article.activity_at, Article.first_seen_at)
            ids = list(db.scalars(select(Article.id).where(last_activity < cutoff)))
            for i in range(0, len(ids), 500):
                chunk = ids[i : i + 500]
                db.execute(delete(ArticleVersion).where(ArticleVersion.article_id.in_(chunk)))
                db.execute(delete(Article).where(Article.id.in_(chunk)))
            removed = len(ids)
        log_cutoff = now - timedelta(days=s.job_log_retention_days)
        db.execute(delete(JobRun).where(JobRun.started_at < log_cutoff, JobRun.job != "heartbeat"))
        db.execute(delete(JobRequest).where(JobRequest.done_at.is_not(None), JobRequest.done_at < log_cutoff))
        db.commit()
        run.items_processed = removed
    return run
