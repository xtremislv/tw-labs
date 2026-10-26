from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import Article, JobRequest, JobRun, Site
from ..schemas import JobRunOut, SystemStatus
from ..timeutil import as_utc, utcnow

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/status", response_model=SystemStatus)
def status(db: Session = Depends(get_db)):
    now = utcnow()
    d1 = now - timedelta(days=1)
    visible = Article.enrich_status.in_(("ok", "pending", "recheck", "error"))
    runs = db.scalars(select(JobRun).where(JobRun.job != "heartbeat").order_by(JobRun.started_at.desc()).limit(25)).all()
    last_poll = db.scalar(select(func.max(JobRun.started_at)).where(JobRun.job == "poll"))
    heartbeat = db.scalar(select(func.max(JobRun.started_at)))
    return SystemStatus(
        workspace_name=get_settings().workspace_name,
        sites=db.scalar(select(func.count(Site.id))) or 0,
        articles_total=db.scalar(select(func.count(Article.id)).where(visible)) or 0,
        articles_24h=db.scalar(select(func.count(Article.id)).where(visible, Article.published_at >= d1)) or 0,
        updates_24h=db.scalar(select(func.count(Article.id)).where(Article.last_updated_at >= d1)) or 0,
        queue_pending=db.scalar(select(func.count(Article.id)).where(Article.enrich_status.in_(("pending", "recheck")))) or 0,
        last_poll_at=last_poll,
        # The worker runs an enrich pass every couple of minutes, so no job
        # run for 20 minutes means it's down.
        worker_alive=bool(heartbeat and now - as_utc(heartbeat) < timedelta(minutes=20)),
        recent_runs=[JobRunOut.model_validate(r) for r in runs],
    )


@router.get("/jobs", response_model=list[JobRunOut])
def jobs(site_id: int | None = None, limit: int = 50, db: Session = Depends(get_db)):
    q = select(JobRun).where(JobRun.job != "heartbeat").order_by(JobRun.started_at.desc()).limit(min(limit, 200))
    if site_id is not None:
        q = q.where(JobRun.site_id == site_id)
    return [JobRunOut.model_validate(r) for r in db.scalars(q)]


@router.post("/refresh", status_code=202)
def refresh_all(db: Session = Depends(get_db)):
    """The dashboard's Refresh button. No API key (the browser can't keep a
    secret); a cooldown stops repeated clicks from hammering competitor
    sites instead."""
    cooldown = get_settings().manual_refresh_cooldown_seconds
    last = db.scalar(select(func.max(JobRequest.created_at)).where(JobRequest.kind == "poll_all"))
    if last and (utcnow() - as_utc(last)).total_seconds() < cooldown:
        wait = int(cooldown - (utcnow() - as_utc(last)).total_seconds())
        raise HTTPException(429, f"Refreshed moments ago — try again in {wait} s")
    db.add(JobRequest(kind="poll_all"))
    db.commit()
    return {"queued": True}
