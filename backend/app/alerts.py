"""Alerts (Slack / Telegram) and the daily digest.

Render's free plan blocks outgoing email ports, so alerts go to a Slack
incoming webhook and/or a Telegram bot — both plain HTTPS.

* Article rules: any-of keywords (headline, section, tags), optional sites and
  content types, optionally also on real content updates.
* Video rules: a tracked video crossing an overperformance ratio, optionally
  limited to some channels.
Each (rule, item) is sent at most once (alert_events has a unique key), and a
rule's matches from one check are batched into one message (max 10 lines).
"""
from __future__ import annotations

import html
import logging
from datetime import timedelta

import httpx
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .models import AlertEvent, AlertRule, AppState, Article, Video
from .timeutil import as_utc, utcnow

log = logging.getLogger("webintel.alerts")
IST = timedelta(hours=5, minutes=30)


# ── delivery ───────────────────────────────────────────────────────────────
def configured_destinations() -> dict[str, bool]:
    s = get_settings()
    return {"slack": bool(s.slack_webhook_url), "telegram": bool(s.telegram_bot_token and s.telegram_chat_id)}


def send(destinations: list[str], title: str, lines: list[str], http: httpx.Client | None = None) -> list[str]:
    """Send one message; returns a list of errors (empty = all delivered).
    `lines` are (text, url) pairs already formatted as 'text\turl'."""
    s = get_settings()
    errors: list[str] = []
    client = http or httpx.Client(timeout=15)
    try:
        for dest in destinations:
            try:
                if dest == "slack" and s.slack_webhook_url:
                    body = "\n".join(
                        f"• <{u}|{t.replace('<', '').replace('>', '')}>" if u else f"• {t}"
                        for t, u in (ln.split("\t", 1) if "\t" in ln else (ln, "") for ln in lines)
                    )
                    r = client.post(s.slack_webhook_url, json={"text": f"*{title}*\n{body}"})
                    if r.status_code >= 300:
                        errors.append(f"slack {r.status_code}: {r.text[:120]}")
                elif dest == "telegram" and s.telegram_bot_token and s.telegram_chat_id:
                    body = "\n".join(
                        f"• <a href=\"{html.escape(u)}\">{html.escape(t)}</a>" if u else f"• {html.escape(t)}"
                        for t, u in (ln.split("\t", 1) if "\t" in ln else (ln, "") for ln in lines)
                    )
                    r = client.post(
                        f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage",
                        json={"chat_id": s.telegram_chat_id, "text": f"<b>{html.escape(title)}</b>\n{body}",
                              "parse_mode": "HTML", "disable_web_page_preview": True},
                    )
                    if r.status_code >= 300:
                        errors.append(f"telegram {r.status_code}: {r.text[:120]}")
                elif dest in ("slack", "telegram"):
                    errors.append(f"{dest} is not configured")
            except httpx.HTTPError as e:
                errors.append(f"{dest}: {e}")
    finally:
        if http is None:
            client.close()
    return errors


# ── matching ───────────────────────────────────────────────────────────────
def _article_text(a: Article) -> str:
    return " ".join([a.title or "", a.section or "", " ".join(a.tags or [])]).lower()


def article_matches(rule: AlertRule, a: Article) -> bool:
    if rule.site_ids and a.site_id not in rule.site_ids:
        return False
    if rule.content_types and (a.content_type or "news") not in rule.content_types:
        return False
    kws = [k.strip().lower() for k in (rule.keywords or []) if k.strip()]
    if kws:
        text = _article_text(a)
        return any(k in text for k in kws)
    return True


def video_matches(rule: AlertRule, v: Video) -> bool:
    if rule.channel_ids and v.channel_id not in rule.channel_ids:
        return False
    ratio = v.overperform_ratio_median or v.overperform_ratio
    if rule.min_ratio and (ratio is None or ratio < rule.min_ratio):
        return False
    kws = [k.strip().lower() for k in (rule.keywords or []) if k.strip()]
    return not kws or any(k in (v.title or "").lower() for k in kws)


def _link(path: str) -> str:
    base = get_settings().dashboard_url.rstrip("/")
    return f"{base}{path}" if base else ""


def check_alerts(db: Session, http: httpx.Client | None = None, *, lookback_hours: int = 6) -> int:
    rules = list(db.scalars(select(AlertRule).where(AlertRule.enabled.is_(True))))
    if not rules:
        return 0
    now = utcnow()
    since = now - timedelta(hours=lookback_hours)
    fresh = list(db.scalars(
        select(Article).options(selectinload(Article.site)).where(
            Article.enrich_status == "ok",
            Article.is_backfill.is_(False),
            or_(Article.first_seen_at >= since, Article.last_updated_at >= since),
        )
    ))
    videos = list(db.scalars(
        select(Video).options(selectinload(Video.channel)).where(Video.published_at >= now - timedelta(days=3))
    ))
    sent = 0
    for rule in rules:
        hits: list[tuple[str, str]] = []  # (item_key, line)
        if rule.kind == "video":
            for v in videos:
                if video_matches(rule, v):
                    ratio = v.overperform_ratio_median or v.overperform_ratio
                    hits.append((f"video:{v.id}", f"{v.channel.name}: {v.title} ({ratio:.1f}x, {v.views:,} views)\thttps://www.youtube.com/watch?v={v.id}"))
        else:
            for a in fresh:
                if not article_matches(rule, a):
                    continue
                is_new = as_utc(a.first_seen_at) >= since
                if is_new:
                    hits.append((f"article:{a.id}", f"{a.site.name}: {a.title}\t{a.url}"))
                elif rule.include_updates and a.last_updated_at and as_utc(a.last_updated_at) >= since:
                    hits.append((f"article:{a.id}:u{a.update_count}", f"{a.site.name} updated: {a.title}\t{a.url}"))
        if not hits:
            continue
        done = set(db.scalars(select(AlertEvent.item_key).where(AlertEvent.rule_id == rule.id, AlertEvent.item_key.in_([k for k, _ in hits]))))
        todo = [(k, ln) for k, ln in hits if k not in done]
        if not todo:
            continue
        lines = [ln for _, ln in todo[:10]]
        if len(todo) > 10:
            lines.append(f"…and {len(todo) - 10} more" + (f"\t{_link('/')}" if _link('/') else ""))
        errors = send(rule.destinations or [], f"Web Intel · {rule.name}", lines, http)
        for k, _ in todo:
            db.add(AlertEvent(rule_id=rule.id, item_key=k, sent_at=now, ok=not errors, error="; ".join(errors)[:500] or None))
        rule.last_fired_at = now
        rule.fire_count += 1
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        sent += len(todo)
    return sent


# ── daily digest ───────────────────────────────────────────────────────────
def build_digest(db: Session) -> tuple[str, list[str]]:
    from .stories import build_stories  # local import keeps alerts importable without stories deps

    now = utcnow()
    since = now - timedelta(hours=24)
    new_articles = db.scalars(
        select(Article).where(Article.enrich_status == "ok", Article.is_backfill.is_(False), Article.published_at >= since)
    ).all()
    updated = db.scalars(
        select(Article).options(selectinload(Article.site)).where(Article.last_updated_at >= since).order_by(Article.update_count.desc()).limit(5)
    ).all()
    stories = build_stories(db, hours=24, min_sites=2)
    gaps = [s for s in stories if s["gap"]]
    top_videos = db.scalars(
        select(Video).options(selectinload(Video.channel)).where(Video.published_at >= now - timedelta(days=2), Video.overperform_ratio_median.is_not(None))
        .order_by(Video.overperform_ratio_median.desc()).limit(5)
    ).all()
    day = (now + IST).strftime("%a %d %b")
    lines = [f"{len(new_articles)} new articles · {len(updated)} big updates · {len(stories)} stories · {len(gaps)} gaps"]
    if stories:
        lines.append("— Top stories (sites covering) —")
        for s in stories[:5]:
            tag = " · GAP" if s["gap"] else ""
            lines.append(f"{s['site_count']} sites{tag}: {s['label']}\t{_link('/#topic-radar')}")
    if gaps:
        lines.append("— Not covered by TechWiser yet —")
        for s in gaps[:5]:
            lines.append(f"{s['label']} ({s['competitor_site_count']} sites)")
    if updated:
        lines.append("— Updated articles —")
        for a in updated:
            lines.append(f"{a.site.name}: {a.title}\t{a.url}")
    if top_videos:
        lines.append("— YouTube overperformers (48 h) —")
        for v in top_videos:
            lines.append(f"{v.channel.name}: {v.title} ({v.overperform_ratio_median:.1f}x median)\thttps://www.youtube.com/watch?v={v.id}")
    return f"Web Intel daily digest · {day}", lines


def maybe_send_digest(db: Session, http: httpx.Client | None = None, *, force: bool = False) -> bool:
    s = get_settings()
    dests = [d for d, ok in configured_destinations().items() if ok]
    if not dests or (not s.digest_enabled and not force):
        return False
    now_ist = utcnow() + IST
    today = now_ist.strftime("%Y-%m-%d")
    state = db.get(AppState, "digest_last_sent")
    due = (now_ist.hour, now_ist.minute) >= (s.digest_hour_ist, s.digest_minute_ist)
    if not force and (not due or (state and state.value == today)):
        return False
    title, lines = build_digest(db)
    errors = send(dests, title, lines, http)
    if state is None:
        state = AppState(key="digest_last_sent")
        db.add(state)
    state.value, state.updated_at = today, utcnow()
    db.commit()
    if errors:
        log.warning("digest delivery problems: %s", errors)
    return not errors


def test_destination(dest: str, http: httpx.Client | None = None) -> list[str]:
    return send([dest], "Web Intel test message", ["Alerts are connected. You'll get matching articles and videos here."], http)
