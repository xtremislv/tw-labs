from datetime import timedelta

from app import tracker
from app.models import JobRequest, Site
from app.timeutil import utcnow
from tests.fakesite import FakeSite


def _seed(db):
    fs = FakeSite()
    f = fs.fetcher()
    site = Site(domain=fs.domain, name="Gadget News", home_url=f"https://{fs.domain}/", cohort="Tech news")
    db.add(site)
    db.commit()
    tracker.rediscover(db, f, site)
    tracker.backfill_site(db, f, site)
    tracker.enrich_pending(db, f)
    return fs, f, site


def test_add_site_queues_backfill(client, db):
    r = client.post("/api/sites", json={"url": "https://www.Example.com/news", "cohort": "Tech news"})
    assert r.status_code == 201
    body = r.json()
    assert body["domain"] == "example.com" and body["health"] == "pending"
    assert db.query(JobRequest).filter_by(kind="backfill", site_id=body["id"]).count() == 1
    assert client.post("/api/sites", json={"url": "example.com"}).status_code == 409
    assert client.post("/api/sites", json={"url": "notadomain"}).status_code == 422


def test_sites_list_has_stats_and_health(client, db):
    _seed(db)
    s = client.get("/api/sites").json()[0]
    assert s["health"] == "ok" and s["fast_source"] == "wp_rest"
    assert s["articles_24h"] == 1 and s["articles_7d"] == 3  # FakeSite ages: 2 h, 30 h, 50 h, 10 d
    d = client.get(f"/api/sites/{s['id']}").json()
    assert [x["kind"] for x in d["sources"]][0] == "wp_rest"
    assert any("found wp_rest" in line for line in d["discovery_log"])


def test_feed_filters(client, db):
    fs, f, site = _seed(db)
    today = (utcnow() + timedelta(hours=5, minutes=30)).date()
    week_ago = today - timedelta(days=7)
    r = client.get("/api/articles", params={"date_from": str(week_ago), "date_to": str(today)}).json()
    assert r["total"] == 3
    titles = [a["title"] for a in r["items"]]
    assert titles[0].startswith("Galaxy S27")  # newest first
    assert client.get("/api/articles", params={"content_type": "review"}).json()["total"] == 1
    assert client.get("/api/articles", params={"q": "pixel camera"}).json()["total"] == 1
    assert client.get("/api/articles", params={"has_youtube": True}).json()["total"] == 4
    assert client.get("/api/articles", params={"cohort": "Nope"}).json()["total"] == 0
    assert client.get("/api/articles", params={"status": "updated"}).json()["total"] == 0

    fs.edit("pixel-11-review-camera-king", add_para="Update: the March patch fixed the shutter lag we complained about in this review.")
    tracker.poll_site(db, f, site)
    tracker.enrich_pending(db, f)
    up = client.get("/api/articles", params={"status": "updated"}).json()
    assert up["total"] == 1 and up["items"][0]["latest_change"].startswith("+")
    detail = client.get(f"/api/articles/{up['items'][0]['id']}").json()
    assert len(detail["versions"]) == 1 and detail["headings"]

    facets = client.get("/api/facets").json()
    assert ["news", 1] in facets["content_types"] and facets["cohorts"] == ["Tech news"]
    csv = client.get("/api/articles/export.csv").text
    assert csv.splitlines()[0].startswith("site,title,url")


def test_refresh_cooldown(client):
    assert client.post("/api/refresh").status_code == 202
    assert client.post("/api/refresh").status_code == 429


def test_status(client, db):
    _seed(db)
    st = client.get("/api/status").json()
    assert st["sites"] == 1 and st["articles_total"] == 4 and st["queue_pending"] == 0
