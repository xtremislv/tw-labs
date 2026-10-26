from datetime import timedelta

import pytest
from sqlalchemy import select

from app import alerts, benchmark
from app.config import get_settings
from app.models import AlertEvent, AlertRule, Article, Site
from app.stories import build_stories, clear_cache, tokens
from app.timeutil import utcnow
from tests.fakeyt import FakeYouTube


def _site(db, domain, own=False, cohort="Tech news"):
    s = Site(domain=domain, name=domain.split(".")[0].title(), home_url=f"https://{domain}/", cohort=cohort,
             is_own_site=own, backfill_status="done")
    db.add(s)
    db.commit()
    return s


def _art(db, site, title, hours_ago, **kw):
    now = utcnow()
    a = Article(site_id=site.id, url=f"https://{site.domain}/{abs(hash(title)) % 10**8}-{hours_ago}", title=title,
                published_at=now - timedelta(hours=hours_ago), first_seen_at=now - timedelta(hours=hours_ago),
                activity_at=now - timedelta(hours=hours_ago), enrich_status="ok", is_backfill=False, content_type="news", **kw)
    db.add(a)
    db.commit()
    return a


@pytest.fixture
def newsroom(db):
    clear_cache()
    a, b, c, tw = _site(db, "alpha.test"), _site(db, "beta.test"), _site(db, "gamma.test"), _site(db, "techwiser.test", own=True, cohort=None)
    _art(db, a, "Samsung Galaxy S27 Ultra launched in India: price, specs, availability", 3)
    _art(db, b, "Galaxy S27 Ultra price in India announced, sale starts November 2", 5)
    _art(db, c, "Samsung Galaxy S27 Ultra hands-on: first impressions", 8)
    _art(db, a, "Pixel 11a review: the budget camera champ", 4)
    _art(db, tw, "Pixel 11a review: best camera under Rs 40,000?", 6)
    _art(db, b, "Pixel 11a gets a big camera update", 10)
    _art(db, c, "How to fix Wi-Fi not working on Android", 2)
    _art(db, b, "iOS 27 beta 3 brings new lock screen widgets", 7)
    return {"a": a, "b": b, "c": c, "tw": tw}


def test_tokens_drop_generic_words():
    assert tokens("Samsung Galaxy S27 Ultra launched in India: price, specs") == {"samsung", "galaxy", "s27", "ultra"}


def test_stories_cluster_and_flag_gaps(db, newsroom):
    stories = build_stories(db, hours=48, min_sites=2)
    labels = {s["label"]: s for s in stories}
    s27 = next(s for s in stories if "s27" in s["terms"])
    pixel = next(s for s in stories if "11a" in s["terms"])
    assert s27["site_count"] == 3 and s27["gap"] is True and s27["covered_by_us"] is False
    assert pixel["site_count"] == 3 and pixel["gap"] is False
    assert s27["hours_to_3_sites"] == 5.0
    assert not any("wi-fi" in l.lower() for l in labels)  # single-site stories are dropped
    assert stories[0]["score"] >= stories[-1]["score"]


def test_radar_and_shortlist_api(client, db, newsroom):
    r = client.get("/api/radar", params={"hours": 48}).json()
    assert r["total"] == 2 and r["gaps"] == 1 and r["own_site_configured"]
    gap = next(s for s in r["stories"] if s["gap"])
    assert len(gap["articles"]) == 3 and {s["name"] for s in gap["sites"]} == {"Alpha", "Beta", "Gamma"}
    assert client.get("/api/radar", params={"gaps_only": True}).json()["total"] == 1
    assert client.get("/api/radar", params={"q": "pixel"}).json()["total"] == 1

    item = client.post("/api/shortlist", json={"kind": "story", "ref_id": gap["key"], "title": gap["label"], "source": "3 sites"}).json()
    assert item["status"] == "idea"
    again = client.post("/api/shortlist", json={"kind": "story", "ref_id": gap["key"], "title": gap["label"]}).json()
    assert again["id"] == item["id"]  # no duplicates
    upd = client.patch(f"/api/shortlist/{item['id']}", json={"status": "assigned", "owner": "Atri", "notes": "Do a short"}).json()
    assert upd["status"] == "assigned" and upd["owner"] == "Atri"
    assert client.patch(f"/api/shortlist/{item['id']}", json={"status": "bogus"}).status_code == 422
    from app.stories import clear_cache as cc
    cc()
    assert next(s for s in client.get("/api/radar").json()["stories"] if s["gap"])["shortlisted"] is True
    assert client.delete(f"/api/shortlist/{item['id']}").status_code == 204
    assert client.get("/api/shortlist").json() == []


@pytest.fixture
def channels(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/X")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100200")
    monkeypatch.setenv("DIGEST_HOUR_IST", "0")
    monkeypatch.setenv("DIGEST_MINUTE_IST", "0")
    get_settings.cache_clear()
    yield FakeYouTube()
    get_settings.cache_clear()


def test_alert_rules_fire_once_and_digest(client, db, newsroom, channels):
    fy = channels
    # rule created via API primes existing matches so it doesn't flood
    r = client.post("/api/alerts/rules", json={"name": "Galaxy", "keywords": ["galaxy s27"], "destinations": ["slack", "telegram"]}).json()
    assert db.scalar(select(AlertEvent).where(AlertEvent.rule_id == r["id"])) is not None
    assert alerts.check_alerts(db, http=fy.http()) == 0

    # a new matching article arrives → one batched message per destination
    _art(db, newsroom["c"], "Galaxy S27 Ultra vs iPhone 18 Pro Max camera test", 0)
    assert alerts.check_alerts(db, http=fy.http()) == 1
    slack = [x for x in fy.requests if x.startswith("SLACK:")]
    tg = [x for x in fy.requests if x.startswith("TELEGRAM:")]
    assert len(slack) == 1 and "Galaxy S27 Ultra vs iPhone" in slack[0] and len(tg) == 1
    assert alerts.check_alerts(db, http=fy.http()) == 0  # never twice
    rule = db.get(AlertRule, r["id"])
    assert rule.fire_count == 1 and rule.last_fired_at

    # non-matching article doesn't fire; site filter works
    _art(db, newsroom["a"], "OnePlus 16 teased", 0)
    db.add(AlertRule(name="Beta only", site_ids=[newsroom["b"].id], destinations=["slack"]))
    db.commit()
    _art(db, newsroom["b"], "Beta publishes something", 0)
    _art(db, newsroom["a"], "Alpha publishes something", 0)
    assert alerts.check_alerts(db, http=fy.http()) == 2  # beta's 2 fresh articles (prior + new one at 0 h)? see below
    # digest: due (00:00 IST configured), sends once per day
    assert alerts.maybe_send_digest(db, http=fy.http()) is True
    assert alerts.maybe_send_digest(db, http=fy.http()) is False
    title, lines = alerts.build_digest(db)
    assert "digest" in title.lower() and any("GAP" in ln for ln in lines)

    integ = client.get("/api/integrations").json()
    assert integ["slack"] and integ["telegram"] and integ["digest_last_sent"]
    prev = client.get("/api/digest/preview").json()
    assert prev["lines"] and "\t" not in "".join(prev["lines"])


def test_rule_validation(client):
    assert client.post("/api/alerts/rules", json={"name": "x", "kind": "nope"}).status_code == 422
    v = client.post("/api/alerts/rules", json={"name": "Hits", "kind": "video", "destinations": ["slack", "email"]}).json()
    assert v["min_ratio"] == 2.0 and v["destinations"] == ["slack"]
    assert client.put(f"/api/alerts/rules/{v['id']}", json={"name": "Hits 3x", "kind": "video", "min_ratio": 3}).json()["min_ratio"] == 3
    assert client.delete(f"/api/alerts/rules/{v['id']}").status_code == 204


def test_benchmark_sync_matches_own_articles(db, newsroom, monkeypatch):
    import httpx

    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "{}")
    monkeypatch.setenv("GSC_SITE_URL", "sc-domain:techwiser.test")
    monkeypatch.setenv("GA4_PROPERTY_ID", "123")
    get_settings.cache_clear()
    own = db.scalar(select(Article).where(Article.site_id == newsroom["tw"].id))
    path = "/" + own.url.split("/", 3)[3]

    def handler(req):
        if "searchAnalytics" in str(req.url):
            assert req.headers["authorization"] == "Bearer tok"
            return httpx.Response(200, json={"rows": [{"keys": [f"https://techwiser.test{path}/"], "clicks": 120, "impressions": 4000, "position": 6.24}]})
        if "runReport" in str(req.url):
            return httpx.Response(200, json={"rows": [{"dimensionValues": [{"value": path}], "metricValues": [{"value": "2500"}]}]})
        return httpx.Response(404)

    try:
        res = benchmark.sync(db, token="tok", http=httpx.Client(transport=httpx.MockTransport(handler)))
    finally:
        get_settings.cache_clear()
    db.refresh(own)
    assert res["matched"] == 1 and own.own_clicks_28d == 120 and own.own_views_28d == 2500 and own.own_position == 6.2
