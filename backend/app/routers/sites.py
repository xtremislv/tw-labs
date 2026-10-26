from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import Article, JobRequest, JobRun, Site
from ..schemas import SiteCreate, SiteDetailOut, SiteOut, SiteUpdate, SourceOut
from ..timeutil import as_utc, utcnow
from ..urlnorm import normalize_domain

router = APIRouter(prefix="/api/sites", tags=["sites"])

FAST_KINDS = ("wp_rest", "news_sitemap", "rss", "html")


def _health(site: Site) -> str:
    if site.backfill_status in ("pending", "running"):
        return "pending"
    if site.backfill_status == "error":
        return "error"
    if site.paused:
        return "ok"
    ok_at = as_utc(site.last_poll_ok_at)
    if site.last_error and (ok_at is None or utcnow() - ok_at > timedelta(hours=2)):
        return "error"
    if not any(s.enabled and s.kind in FAST_KINDS and s.consecutive_errors < 3 for s in site.sources):
        return "warning"
    if any(s.consecutive_errors >= 3 for s in site.sources):
        return "warning"
    return "ok"


def _stats(db: Session) -> dict[int, dict]:
    now = utcnow()
    d1, d7 = now - timedelta(days=1), now - timedelta(days=7)
    live = Article.enrich_status.in_(("ok", "pending", "recheck", "error"))
    out: dict[int, dict] = {}
    def count(cond):
        return func.sum(case((cond, 1), else_=0))

    rows = db.execute(
        select(
            Article.site_id,
            count((Article.published_at >= d1) & live),
            count((Article.published_at >= d7) & live),
            count(Article.last_updated_at >= d7),
            func.max(Article.published_at),
            count(Article.enrich_status.in_(("pending", "recheck"))),
        ).group_by(Article.site_id)
    )
    for sid, a1, a7, u7, last, q in rows:
        out[sid] = {
            "articles_24h": a1 or 0,
            "articles_7d": a7 or 0,
            "updates_7d": u7 or 0,
            "last_article_at": last,
            "queued": q or 0,
        }
    return out


def _out(site: Site, stats: dict, cls=SiteOut, **extra):
    fast = next((s.kind for s in site.sources if s.enabled and s.kind in FAST_KINDS and s.consecutive_errors < 3), None)
    return cls.model_validate(site).model_copy(
        update={"fast_source": fast, "health": _health(site), **stats.get(site.id, {}), **extra}
    )


def _get(db: Session, site_id: int) -> Site:
    site = db.get(Site, site_id, options=[selectinload(Site.sources)])
    if site is None:
        raise HTTPException(404, "Site not found")
    return site


@router.get("", response_model=list[SiteOut])
def list_sites(db: Session = Depends(get_db)):
    sites = db.scalars(select(Site).options(selectinload(Site.sources)).order_by(Site.is_own_site.desc(), Site.name)).all()
    stats = _stats(db)
    return [_out(s, stats) for s in sites]


@router.post("", response_model=SiteOut, status_code=201)
def add_site(body: SiteCreate, db: Session = Depends(get_db)):
    domain = normalize_domain(body.url)
    if not domain or "." not in domain:
        raise HTTPException(422, "That doesn't look like a website address — try something like example.com")
    if db.scalar(select(Site).where(Site.domain == domain)):
        raise HTTPException(409, f"{domain} is already being tracked")
    site = Site(
        domain=domain,
        name=(body.name or "").strip() or domain,
        home_url=f"https://{domain}/",
        cohort=(body.cohort or "").strip() or None,
        is_own_site=body.is_own_site,
        backfill_status="pending",
    )
    db.add(site)
    db.flush()
    # Discovery + the 30-day backfill take minutes (polite 2 s gaps between
    # requests), so the worker does it; the UI polls backfill_status.
    db.add(JobRequest(kind="backfill", site_id=site.id))
    db.commit()
    db.refresh(site)
    return _out(site, {})


@router.get("/{site_id}", response_model=SiteDetailOut)
def get_site(site_id: int, db: Session = Depends(get_db)):
    site = _get(db, site_id)
    run = db.scalar(
        select(JobRun)
        .where(JobRun.site_id == site_id, JobRun.job == "discover")
        .order_by(JobRun.started_at.desc())
        .limit(1)
    )
    log = []
    if run is not None:
        log = [line for line in (run.detail or "").split("\n") if line]
        if run.error:
            log.append(run.error)
    return _out(site, _stats(db), SiteDetailOut, sources=[SourceOut.model_validate(s) for s in site.sources], discovery_log=log)


@router.patch("/{site_id}", response_model=SiteOut)
def update_site(site_id: int, body: SiteUpdate, db: Session = Depends(get_db)):
    site = _get(db, site_id)
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"]:
        site.name = data["name"].strip()
    if "cohort" in data:
        site.cohort = (data["cohort"] or "").strip() or None
    if data.get("paused") is not None:
        site.paused = data["paused"]
    if data.get("is_own_site") is not None:
        site.is_own_site = data["is_own_site"]
    db.commit()
    return _out(site, _stats(db))


@router.delete("/{site_id}", status_code=204)
def delete_site(site_id: int, db: Session = Depends(get_db)):
    site = _get(db, site_id)
    db.delete(site)
    db.commit()


@router.post("/{site_id}/rediscover", status_code=202)
def rediscover_site(site_id: int, db: Session = Depends(get_db)):
    _get(db, site_id)
    db.add(JobRequest(kind="rediscover", site_id=site_id))
    db.commit()
    return {"queued": True}


@router.post("/{site_id}/poll", status_code=202)
def poll_now(site_id: int, db: Session = Depends(get_db)):
    _get(db, site_id)
    db.add(JobRequest(kind="poll_site", site_id=site_id))
    db.commit()
    return {"queued": True}


@router.post("/{site_id}/sitemap-check")
def sitemap_check(site_id: int, db: Session = Depends(get_db)):
    """Read today's sitemaps right now, add anything missing, and report coverage."""
    from ..fetcher import Fetcher
    from ..tracker import sitemap_coverage

    site = _get(db, site_id)
    try:
        return sitemap_coverage(db, Fetcher(), site)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"{type(e).__name__}: {e}") from e
