"""Own-site benchmark: real Search Console + GA4 numbers for techwiser.com.

Optional. Needs a Google Cloud service account (free) whose e-mail address is
added as a user on the Search Console property (Restricted is enough) and on
the GA4 property (Viewer). Paste the service account's whole JSON key into
GOOGLE_SERVICE_ACCOUNT_JSON, plus GSC_SITE_URL and/or GA4_PROPERTY_ID.

Runs daily: last 28 days of clicks / impressions / average position per page
(Search Console) and page views per page path (GA4), written onto the
matching own-site articles so they show real numbers next to competitors.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from urllib.parse import quote, urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AppState, Article, Site
from .timeutil import utcnow
from .urlnorm import canonicalize

log = logging.getLogger("webintel.benchmark")
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly", "https://www.googleapis.com/auth/analytics.readonly"]


class BenchmarkError(Exception):
    pass


def configured() -> dict[str, bool]:
    s = get_settings()
    has_key = bool(s.google_service_account_json.strip())
    return {"search_console": has_key and bool(s.gsc_site_url), "ga4": has_key and bool(s.ga4_property_id)}


def _token() -> str:
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    try:
        info = json.loads(get_settings().google_service_account_json)
    except ValueError as e:
        raise BenchmarkError("GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON — paste the whole key file") from e
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    creds.refresh(Request())
    return creds.token


def _path(url: str) -> str:
    p = urlsplit(url).path or "/"
    return p.rstrip("/") or "/"


def fetch_gsc(token: str, http: httpx.Client) -> dict[str, tuple[int, int, float]]:
    s = get_settings()
    end = date.today() - timedelta(days=2)  # Search Console lags ~2 days
    body = {"startDate": str(end - timedelta(days=27)), "endDate": str(end), "dimensions": ["page"], "rowLimit": 25000}
    r = http.post(
        f"https://www.googleapis.com/webmasters/v3/sites/{quote(s.gsc_site_url, safe='')}/searchAnalytics/query",
        headers={"Authorization": f"Bearer {token}"}, json=body,
    )
    if r.status_code != 200:
        raise BenchmarkError(f"Search Console {r.status_code}: {r.text[:200]}")
    out = {}
    for row in r.json().get("rows", []):
        out[_path(row["keys"][0])] = (int(row.get("clicks", 0)), int(row.get("impressions", 0)), float(row.get("position", 0)))
    return out


def fetch_ga4(token: str, http: httpx.Client) -> dict[str, int]:
    s = get_settings()
    body = {"dateRanges": [{"startDate": "28daysAgo", "endDate": "yesterday"}], "dimensions": [{"name": "pagePath"}],
            "metrics": [{"name": "screenPageViews"}], "limit": 25000}
    r = http.post(
        f"https://analyticsdata.googleapis.com/v1beta/properties/{s.ga4_property_id}:runReport",
        headers={"Authorization": f"Bearer {token}"}, json=body,
    )
    if r.status_code != 200:
        raise BenchmarkError(f"GA4 {r.status_code}: {r.text[:200]}")
    out: dict[str, int] = {}
    for row in r.json().get("rows", []):
        path = _path(row["dimensionValues"][0]["value"])
        out[path] = out.get(path, 0) + int(row["metricValues"][0]["value"])
    return out


def sync(db: Session, *, token: str | None = None, http: httpx.Client | None = None) -> dict:
    conf = configured()
    if not any(conf.values()):
        return {"skipped": "not configured"}
    own = list(db.scalars(select(Site.id).where(Site.is_own_site.is_(True))))
    if not own:
        return {"skipped": "no site is marked as our site"}
    client = http or httpx.Client(timeout=60)
    try:
        tok = token or _token()
        gsc = fetch_gsc(tok, client) if conf["search_console"] else {}
        ga = fetch_ga4(tok, client) if conf["ga4"] else {}
    finally:
        if http is None:
            client.close()
    now = utcnow()
    matched = 0
    for a in db.scalars(select(Article).where(Article.site_id.in_(own))):
        path = _path(canonicalize(a.url))
        g = gsc.get(path)
        v = ga.get(path)
        if g is None and v is None:
            continue
        if g:
            a.own_clicks_28d, a.own_impressions_28d, a.own_position = g[0], g[1], round(g[2], 1)
        if v is not None:
            a.own_views_28d = v
        a.own_metrics_at = now
        matched += 1
    state = db.get(AppState, "benchmark_last_sync") or AppState(key="benchmark_last_sync")
    state.value = json.dumps({"at": now.isoformat(), "matched": matched, "gsc_pages": len(gsc), "ga4_pages": len(ga)})
    state.updated_at = now
    db.add(state)
    db.commit()
    return {"matched": matched, "gsc_pages": len(gsc), "ga4_pages": len(ga)}
