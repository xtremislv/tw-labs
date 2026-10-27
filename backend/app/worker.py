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
from datetime import timedelta

from sqlalchemy import func, select

from .config import get_settings
from .database import SessionLocal
from .fetcher import Fetcher
from .models import JobRequest, JobRun, Site
from .timeutil import as_utc, utcnow
from . import alerts, benchmark, tracker, youtube

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
    repair_untitled()


DISCOVERY_VERSION = "3"  # bump when discover() learns new methods


def rediscover_one_due() -> None:
    """Re-run discovery for the one site that most needs it."""
    from .models import AppState

    with SessionLocal() as db:
        for site in _active_sites(db):
            key = f"discovery_v:{site.id}"
            st = db.get(AppState, key)
            last = db.scalar(select(func.max(JobRun.started_at)).where(JobRun.site_id == site.id, JobRun.job == "discover"))
            stale = last is None or utcnow() - as_utc(last) > timedelta(days=7)
            if (st is None or st.value != DISCOVERY_VERSION) or stale:
                try:
                    tracker.rediscover(db, _fetcher(), site)
                except Exception as e:  # noqa: BLE001
                    db.rollback()
                    log.warning("rediscover %s failed: %s", site.domain, e)
                st = db.get(AppState, key) or AppState(key=key)
                st.value = DISCOVERY_VERSION
                db.add(st)
                db.commit()
                return  # one site per run keeps the free instance responsive


def repair_untitled() -> None:
    try:
        with SessionLocal() as db:
            n = tracker.repair_untitled(db)
            if n:
                log.info("gave provisional titles to %s hidden articles", n)
    except Exception as e:  # noqa: BLE001 - never block start-up
        log.warning("repair_untitled failed: %s", e)


# ── Phase 3: YouTube ───────────────────────────────────────────────────────
def youtube_scrape() -> None:
    if not get_settings().youtube_api_key:
        return
    with SessionLocal() as db:
        with tracker.job_run(db, "youtube") as run:
            st = youtube.scrape_all(db)
            run.items_new, run.items_updated, run.items_processed = st.videos_new, st.videos_updated, st.channels
            run.detail = f"{st.units} quota units" + ("; " + "; ".join(st.errors[:5]) if st.errors else "")


def youtube_velocity() -> None:
    if not get_settings().youtube_api_key:
        return
    with SessionLocal() as db:
        try:
            youtube.capture_velocity(db)
        except youtube.YouTubeError as e:
            log.warning("velocity check failed: %s", e)


def youtube_posts() -> None:
    if not get_settings().apify_api_token:
        return
    with SessionLocal() as db:
        with tracker.job_run(db, "posts") as run:
            new, errors = youtube.scrape_posts(db)
            run.items_new = new
            run.detail = "; ".join(errors)[:2000] or None


def youtube_one_channel(channel_id: int) -> None:
    from .models import Channel

    with SessionLocal() as db:
        ch = db.get(Channel, channel_id)
        if ch is None:
            return
        with tracker.job_run(db, "youtube", trigger="add_channel") as run:
            client = youtube.YouTubeClient(get_settings().youtube_api_key)
            st = youtube.ScrapeStats()
            youtube.scrape_channel(db, client, ch, st, sponsor_budget=[get_settings().sponsorblock_max_checks_per_scrape])
            youtube.record_usage(db, "youtube", client.units)
            run.items_new, run.items_processed = st.videos_new, 1


# ── Phase 4: alerts, digest, benchmark ─────────────────────────────────────
def alerts_check() -> None:
    with SessionLocal() as db:
        try:
            alerts.check_alerts(db)
            alerts.maybe_send_digest(db)
        except Exception as e:  # noqa: BLE001 - alert delivery must never kill the scheduler
            log.warning("alerts check failed: %s", e)


def benchmark_sync() -> None:
    if not any(benchmark.configured().values()):
        return
    with SessionLocal() as db:
        try:
            benchmark.sync(db)
        except Exception as e:  # noqa: BLE001
            log.warning("benchmark sync failed: %s", e)


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
                elif req.kind == "youtube_all":
                    youtube_scrape()
                elif req.kind == "youtube_posts":
                    youtube_posts()
                elif req.kind == "youtube_channel":  # site_id holds the channel id here
                    youtube_one_channel(req.site_id)
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
    # One-off, ~1 min after start: titles for rows saved without one.
    sched.add_job(repair_untitled, "date", run_date=utcnow() + timedelta(seconds=60), id="repair")
    # Re-scan each site's feeds/sitemaps/listing pages: weekly, and once
    # after an update that adds discovery methods. One site at a time.
    sched.add_job(rediscover_one_due, "interval", minutes=10, id="rediscover", next_run_time=utcnow() + timedelta(minutes=3))
    # IST has no daylight saving, so IST clock times convert to fixed UTC ones
    # (and no time-zone database is needed, which Windows lacks).
    yh, ym = _ist_to_utc(s.youtube_scrape_hour_ist, s.youtube_scrape_minute_ist)
    sched.add_job(youtube_scrape, "cron", hour=yh, minute=ym, id="youtube")
    sched.add_job(youtube_velocity, "interval", minutes=60, id="velocity")
    ph, pm = _ist_to_utc(s.posts_scrape_hour_ist, 0)
    sched.add_job(youtube_posts, "cron", hour=ph, minute=pm, id="posts")
    sched.add_job(alerts_check, "interval", minutes=s.alerts_check_minutes, id="alerts")
    sched.add_job(benchmark_sync, "cron", hour=0, minute=45, id="benchmark")  # 06:15 IST
    return sched


def _ist_to_utc(hour: int, minute: int) -> tuple[int, int]:
    total = (hour * 60 + minute - 330) % (24 * 60)
    return total // 60, total % 60


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
