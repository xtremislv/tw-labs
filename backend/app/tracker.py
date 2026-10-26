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
from collections import defaultdict
from contextlib import contextmanager
from datetime import timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .config import get_settings
from .discovery import PRIORITY, DiscoveryResult, discover
from .extract import compare_versions, extract_page
from .fetcher import FetchError, Fetcher
from .models import Article, ArticleVersion, JobRun, Site, SiteSource
from .parsers import (
    Candidate,
    choose_child_sitemaps,
    is_feed,
    parse_feed,
    parse_homepage_links,
    parse_sitemap,
    parse_wp_posts,
)
from .timeutil import as_utc, utcnow
from .urlnorm import canonicalize, looks_like_article, same_site

log = logging.getLogger("webintel.tracker")

FAST_KINDS = ("wp_rest", "news_sitemap", "rss", "html")
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
            art = Article(
                site_id=site.id,
                url=canon,
                title=c.title,
                published_at=as_utc(c.published),
                source_lastmod=lastmod,
                first_seen_at=now,
                activity_at=as_utc(c.published) or now,
                is_backfill=backfill,
                discovered_via=c.kind,
                enrich_status="pending",
            )
            db.add(art)
            new += 1
            continue
        if not art.title and c.title:
            art.title = c.title
        old = as_utc(art.source_lastmod)
        if lastmod and (old is None or lastmod > old + timedelta(minutes=1)):
            art.source_lastmod = lastmod
            if art.enrich_status in ("ok", "skipped"):
                art.enrich_status = "recheck"
                art.next_check_at = now
                rechecks += 1
    db.commit()
    return new, rechecks


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
        if items is None:
            site.last_error = (
                "No feeds found — the site may be blocking automated requests. Try “Re-scan feeds”."
                if not sources
                else "Every feed failed on the last check — see the sources below."
            )
            db.commit()
            if not sources:
                return run
            raise FetchError(site.last_error)
        new, rech = ingest(db, site, items, backfill=backfill)
        run.items_new, run.items_updated, run.items_processed = new, rech, len(items)
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
                    for child in choose_child_sitemaps(doc.children, cutoff=cutoff, limit=limit):
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
