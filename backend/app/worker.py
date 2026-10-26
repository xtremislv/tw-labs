"""The background worker — run as its own process:  python -m app.worker

Schedules (see config.py):
  every 15 min   poll each site's fast source
  every 6 h      sweep each site's sitemap (backstop)
  every 2 min    enrich queued articles (fetch, parse, detect updates)
  every 20 s     pick up requests from the API (add site, refresh now, …)
"""
from __future__ import annotations

import logging
import signal
import sys

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import select

from .config import get_settings
from .database import SessionLocal
from .fetcher import Fetcher
from .models import JobRequest, JobRun, Site
from .timeutil import utcnow
from . import tracker

log = logging.getLogger("webintel.worker")
fetcher: Fetcher | None = None


def _fetcher() -> Fetcher:
    global fetcher
    if fetcher is None:
        fetcher = Fetcher()
    return fetcher


def _active_sites(db) -> list[Site]:
    return list(
        db.scalars(select(Site).where(Site.paused.is_(False), Site.backfill_status.in_(("done", "error"))).order_by(Site.id))
    )


def heartbeat() -> None:
    with SessionLocal() as db:
        hb = db.scalar(select(JobRun).where(JobRun.job == "heartbeat"))
        if hb is None:
            hb = JobRun(job="heartbeat", ok=True)
            db.add(hb)
        hb.started_at = hb.finished_at = utcnow()
        db.commit()


def poll_all(trigger: str = "schedule") -> None:
    with SessionLocal() as db:
        for site in _active_sites(db):
            try:
                tracker.poll_site(db, _fetcher(), site, trigger=trigger)
            except Exception as e:  # noqa: BLE001 - one bad site must not stop the rest
                log.warning("poll %s failed: %s", site.domain, e)


def sweep_all() -> None:
    with SessionLocal() as db:
        for site in _active_sites(db):
            try:
                tracker.sweep_site(db, _fetcher(), site)
            except Exception as e:  # noqa: BLE001
                log.warning("sweep %s failed: %s", site.domain, e)


def enrich() -> None:
    heartbeat()
    with SessionLocal() as db:
        if tracker._queue(db, 1):
            tracker.enrich_pending(db, _fetcher())


def housekeeping() -> None:
    with SessionLocal() as db:
        tracker.housekeeping(db)


def process_requests() -> None:
    heartbeat()
    with SessionLocal() as db:
        while True:
            req = db.scalar(select(JobRequest).where(JobRequest.picked_at.is_(None)).order_by(JobRequest.id).limit(1))
            if req is None:
                return
            req.picked_at = utcnow()
            db.commit()
            try:
                site = db.get(Site, req.site_id) if req.site_id else None
                if req.kind == "poll_all":
                    poll_all(trigger="manual")
                elif site is None:
                    raise ValueError("site no longer exists")
                elif req.kind == "backfill":
                    tracker.backfill_site(db, _fetcher(), site)  # discovers first if needed
                elif req.kind == "rediscover":
                    tracker.rediscover(db, _fetcher(), site, trigger="manual")
                elif req.kind == "poll_site":
                    tracker.poll_site(db, _fetcher(), site, trigger="manual")
            except Exception as e:  # noqa: BLE001
                db.rollback()
                req.error = f"{type(e).__name__}: {e}"[:1000]
                log.warning("request %s failed: %s", req.kind, req.error)
            req.done_at = utcnow()
            db.add(req)
            db.commit()


def build_scheduler(cls: type[BaseScheduler]) -> BaseScheduler:
    s = get_settings()
    # Explicit UTC: APScheduler otherwise asks tzlocal for the machine zone,
    # which fails on legacy names like "Asia/Calcutta". Intervals don't care.
    sched = cls(
        timezone="UTC",
        executors={"default": ThreadPoolExecutor(3)},
        job_defaults={"coalesce": True, "max_instances": 1},
    )
    sched.add_job(process_requests, "interval", seconds=s.job_request_poll_seconds, id="requests", next_run_time=utcnow())
    sched.add_job(poll_all, "interval", minutes=s.fast_poll_minutes, id="poll")
    sched.add_job(sweep_all, "interval", minutes=s.sitemap_sweep_minutes, id="sweep")
    sched.add_job(enrich, "interval", minutes=s.enrich_minutes, id="enrich", next_run_time=utcnow())
    sched.add_job(housekeeping, "interval", hours=24, id="housekeeping")
    return sched


def start_embedded() -> BaseScheduler:
    """Run the worker inside the API process (EMBEDDED_WORKER=true)."""
    sched = build_scheduler(BackgroundScheduler)
    sched.start()
    log.info("embedded worker started inside the API process")
    return sched


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = get_settings()
    sched = build_scheduler(BlockingScheduler)

    def _stop(*_):
        log.info("shutting down")
        sched.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    log.info("worker started: poll every %s min, sweep every %s min", s.fast_poll_minutes, s.sitemap_sweep_minutes)
    sched.start()


if __name__ == "__main__":
    main()
