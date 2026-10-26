"""The Live Feed API. All filtering happens here, server-side."""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import Article, ArticleVersion, Site
from ..schemas import ArticleDetailOut, ArticleOut, ArticlePage, Facets, VersionOut
from ..timeutil import utcnow

router = APIRouter(prefix="/api", tags=["articles"])

VISIBLE = ("ok", "pending", "recheck", "error")


def _visible():
    """Everything a feed or sitemap listed. 'error' = the page couldn't be
    read (blocked, timeout) — still a real article, shown with its slug title.
    'skipped' (too little text) is hidden only for homepage-scan finds, which
    can be non-article pages; anything a feed or sitemap listed is a post."""
    return or_(Article.enrich_status.in_(VISIBLE),
               and_(Article.enrich_status == "skipped", Article.discovered_via != "html"))
IST = timezone(timedelta(hours=5, minutes=30))
_STOP = set(
    "a an and are as at be by for from has have how in is it its new of on or the this to vs with what why "
    "will your you launched launch india price review best top know here all more get now than".split()
)


def _day_bounds(d_from: date | None, d_to: date | None) -> tuple[datetime | None, datetime | None]:
    """Dates from the UI are IST calendar days (the team is in India)."""
    start = datetime.combine(d_from, time.min, IST).astimezone(timezone.utc) if d_from else None
    end = datetime.combine(d_to + timedelta(days=1), time.min, IST).astimezone(timezone.utc) if d_to else None
    return start, end


def _filtered(
    *,
    sites: str | None,
    cohort: str | None,
    date_from: date | None,
    date_to: date | None,
    status: str,
    content_type: str | None,
    section: str | None,
    author: str | None,
    q: str | None,
    min_words: int | None,
    has_youtube: bool,
    has_affiliate: bool,
):
    stmt = select(Article).join(Site).where(_visible(), Article.title.is_not(None))
    if sites:
        ids = [int(x) for x in sites.split(",") if x.strip().isdigit()]
        if ids:
            stmt = stmt.where(Article.site_id.in_(ids))
    if cohort:
        stmt = stmt.where(Site.cohort == cohort)
    start, end = _day_bounds(date_from, date_to)

    def in_range(col):
        conds = [col.is_not(None)]
        if start:
            conds.append(col >= start)
        if end:
            conds.append(col < end)
        return and_(*conds)

    if status == "new":
        stmt = stmt.where(in_range(Article.published_at))
    elif status == "updated":
        stmt = stmt.where(Article.update_count > 0, in_range(Article.last_updated_at))
    else:
        stmt = stmt.where(or_(in_range(Article.published_at), in_range(Article.last_updated_at)))
    if content_type:
        stmt = stmt.where(Article.content_type.in_(content_type.split(",")))
    if section:
        stmt = stmt.where(Article.section == section)
    if author:
        stmt = stmt.where(Article.author == author)
    if min_words:
        stmt = stmt.where(Article.word_count >= min_words)
    if has_affiliate:
        stmt = stmt.where(Article.affiliate_link_count > 0)
    if q:
        for term in [t for t in re.split(r"\s+", q.strip()) if t][:6]:
            like = f"%{term}%"
            stmt = stmt.where(or_(Article.title.ilike(like), Article.excerpt.ilike(like), Article.section.ilike(like)))
    return stmt


def _to_out(a: Article, latest: dict[int, str] | None = None) -> ArticleOut:
    return ArticleOut.model_validate(a).model_copy(
        update={
            "site_name": a.site.name,
            "site_domain": a.site.domain,
            "site_icon_url": a.site.icon_url,
            "latest_change": (latest or {}).get(a.id),
        }
    )


def _latest_changes(db: Session, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    sub = (
        select(ArticleVersion.article_id, func.max(ArticleVersion.id).label("vid"))
        .where(ArticleVersion.article_id.in_(ids))
        .group_by(ArticleVersion.article_id)
        .subquery()
    )
    rows = db.execute(select(ArticleVersion.article_id, ArticleVersion.summary).join(sub, ArticleVersion.id == sub.c.vid))
    return {aid: summary for aid, summary in rows}


def _common_params(
    sites: str | None = None,
    cohort: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status: str = Query("all", pattern="^(all|new|updated)$"),
    content_type: str | None = None,
    section: str | None = None,
    author: str | None = None,
    q: str | None = Query(None, max_length=200),
    min_words: int | None = Query(None, ge=0, le=100000),
    has_youtube: bool = False,
    has_affiliate: bool = False,
) -> dict:
    return locals()


def _sorted(stmt, sort: str, status: str):
    if sort == "words":
        return stmt.order_by(Article.word_count.desc().nulls_last(), Article.id.desc())
    if sort == "most_updated":
        return stmt.order_by(Article.update_count.desc(), Article.last_updated_at.desc().nulls_last())
    if status == "new":
        return stmt.order_by(Article.published_at.desc().nulls_last(), Article.id.desc())
    if status == "updated":
        return stmt.order_by(Article.last_updated_at.desc().nulls_last(), Article.id.desc())
    return stmt.order_by(Article.activity_at.desc().nulls_last(), Article.id.desc())


def _apply_youtube(rows: list[Article], params: dict) -> list[Article]:
    if params.get("has_youtube"):
        return [a for a in rows if a.youtube_ids]
    return rows


@router.get("/articles", response_model=ArticlePage)
def list_articles(
    params: dict = Depends(_common_params),
    sort: str = Query("newest", pattern="^(newest|words|most_updated)$"),
    limit: int = Query(48, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = _filtered(**params).options(selectinload(Article.site))
    if params["has_youtube"]:
        # JSON-array emptiness isn't portable SQL; filter in Python on a
        # bounded window instead (fine at our scale: a few thousand rows).
        rows = _apply_youtube(list(db.scalars(_sorted(stmt, sort, params["status"]).limit(5000))), params)
        total, page = len(rows), rows[offset : offset + limit]
    else:
        total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
        page = list(db.scalars(_sorted(stmt, sort, params["status"]).limit(limit).offset(offset)))
    latest = _latest_changes(db, [a.id for a in page if a.update_count])
    return ArticlePage(items=[_to_out(a, latest) for a in page], total=total, limit=limit, offset=offset)


@router.get("/articles/export.csv")
def export_csv(
    params: dict = Depends(_common_params),
    sort: str = Query("newest", pattern="^(newest|words|most_updated)$"),
    db: Session = Depends(get_db),
):
    stmt = _sorted(_filtered(**params).options(selectinload(Article.site)), sort, params["status"]).limit(5000)
    rows = _apply_youtube(list(db.scalars(stmt)), params)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["site", "title", "url", "author", "section", "type", "words", "published (IST)", "last updated (IST)", "updates"])
    for a in rows:
        fmt = lambda d: d.astimezone(IST).strftime("%Y-%m-%d %H:%M") if d else ""  # noqa: E731
        w.writerow([a.site.name, a.title, a.url, a.author or "", a.section or "", a.content_type or "", a.word_count or "",
                    fmt(a.published_at), fmt(a.last_updated_at), a.update_count])
    buf.seek(0)
    name = f"web-intel-{utcnow().astimezone(IST):%Y%m%d-%H%M}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _tokens(title: str | None) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    return {w for w in words if w not in _STOP and (len(w) > 2 or w.isdigit())}


@router.get("/articles/{article_id}", response_model=ArticleDetailOut)
def get_article(article_id: int, db: Session = Depends(get_db)):
    a = db.get(Article, article_id, options=[selectinload(Article.site), selectinload(Article.versions)])
    if a is None:
        raise HTTPException(404, "Article not found")
    # "Also covered by": other sites' articles within ±48 h sharing most of
    # this headline's distinctive words. A stand-in until Topic Radar's
    # proper clustering lands in Phase 4.
    also: list[ArticleOut] = []
    mine = _tokens(a.title)
    if a.published_at and len(mine) >= 2:
        window = select(Article).options(selectinload(Article.site)).where(
            Article.site_id != a.site_id,
            Article.enrich_status.in_(VISIBLE),
            Article.published_at >= a.published_at - timedelta(hours=48),
            Article.published_at <= a.published_at + timedelta(hours=48),
        ).limit(2000)
        scored = []
        for other in db.scalars(window):
            theirs = _tokens(other.title)
            if not theirs:
                continue
            overlap = len(mine & theirs) / min(len(mine), len(theirs))
            if overlap >= 0.6 and len(mine & theirs) >= 2:
                scored.append((overlap, other))
        scored.sort(key=lambda t: -t[0])
        also = [_to_out(o) for _, o in scored[:8]]
    base = _to_out(a, _latest_changes(db, [a.id]))
    return ArticleDetailOut(
        **base.model_dump(),
        headings=a.headings,
        versions=[VersionOut.model_validate(v) for v in a.versions],
        also_covered_by=also,
    )


@router.get("/facets", response_model=Facets)
def facets(sites: str | None = None, db: Session = Depends(get_db)):
    since = utcnow() - timedelta(days=30)
    base = [Article.enrich_status == "ok", Article.published_at >= since]
    if sites:
        ids = [int(x) for x in sites.split(",") if x.strip().isdigit()]
        if ids:
            base.append(Article.site_id.in_(ids))

    def top(col, n):
        rows = db.execute(
            select(col, func.count()).where(*base, col.is_not(None)).group_by(col).order_by(func.count().desc()).limit(n)
        )
        return [(v, c) for v, c in rows if v]

    cohorts = [c for (c,) in db.execute(select(Site.cohort).where(Site.cohort.is_not(None)).distinct().order_by(Site.cohort))]
    return Facets(content_types=top(Article.content_type, 10), sections=top(Article.section, 40),
                  authors=top(Article.author, 60), cohorts=cohorts)
