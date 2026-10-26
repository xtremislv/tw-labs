from sqlalchemy import func, select

from app import tracker
from app.discovery import discover
from app.models import Article, ArticleVersion, Site
from app.urlnorm import canonicalize
from tests.fakesite import FakeSite


def _site(db, fs: FakeSite) -> Site:
    site = Site(domain=fs.domain, name=fs.domain, home_url=f"https://{fs.domain}/")
    db.add(site)
    db.commit()
    return site


def test_discovery_finds_all_sources_in_priority_order():
    fs = FakeSite()
    res = discover(fs.fetcher(), fs.domain)
    kinds = [s.kind for s in res.sources]
    assert kinds == ["wp_rest", "news_sitemap", "rss", "sitemap", "html"]
    assert res.name == "Gadget News"
    assert res.icon_url == f"https://{fs.domain}/fav.png"


def test_discovery_without_wordpress_or_news():
    fs = FakeSite(wordpress=False, news=False)
    kinds = [s.kind for s in discover(fs.fetcher(), fs.domain).sources]
    assert kinds == ["rss", "sitemap", "html"]


def test_backfill_enrich_and_update_detection(db):
    fs = FakeSite()
    f = fs.fetcher()
    site = _site(db, fs)
    tracker.rediscover(db, f, site)
    tracker.backfill_site(db, f, site)
    arts = db.scalars(select(Article)).all()
    urls = {a.url for a in arts}
    # 4 articles inside the 30-day window; the 400-day-old one and the
    # category page are ignored.
    assert len(arts) == 4
    assert f"https://{fs.domain}/old-news-from-last-year-archive" not in urls
    assert all(a.is_backfill for a in arts)
    assert site.backfill_status == "done"

    run = tracker.enrich_pending(db, f)
    assert run.items_new == 4
    a = db.scalar(select(Article).where(Article.url.like("%galaxy-s27%")))
    assert a.enrich_status == "ok" and a.author == "Riya Sharma" and a.word_count > 100
    assert a.next_check_at is not None  # published < 3 days ago → periodic recheck

    # lastmod bumped but nothing edited → recheck runs, no version recorded
    fs.edit("galaxy-s27-ultra-launched-in-india-price-specs", bump_only=True)
    tracker.poll_site(db, f, site)
    db.refresh(a)
    assert a.enrich_status == "recheck"
    tracker.enrich_pending(db, f)
    db.refresh(a)
    assert a.update_count == 0 and a.enrich_status == "ok"

    # a real edit → Updated with a readable summary
    fs.edit("galaxy-s27-ultra-launched-in-india-price-specs",
            add_para="Update: Samsung has now confirmed that sales start on November 2 via Amazon and Samsung.com.",
            add_h2="Availability")
    tracker.poll_site(db, f, site)
    tracker.enrich_pending(db, f)
    db.refresh(a)
    assert a.update_count == 1 and a.last_updated_at is not None
    v = db.scalar(select(ArticleVersion).where(ArticleVersion.article_id == a.id))
    assert v.paragraphs_added == 1 and v.headings_added == ["Availability"]
    assert "new sections: Availability" in v.summary

    # a brand-new post via the fast source is not a backfill item
    fs.publish("oneplus-16-launch-date-confirmed-for-india", "OnePlus 16 launch date confirmed for India")
    run = tracker.poll_site(db, f, site)
    assert run.items_new == 1
    new = db.scalar(select(Article).where(Article.url.like("%oneplus-16%")))
    assert new.is_backfill is False and new.discovered_via == "wp_rest"


def test_poll_uses_etag_304(db, monkeypatch):
    from app.config import get_settings
    monkeypatch.setenv("LATEST_SITEMAPS_ON_POLL", "false")  # isolate the RSS source
    get_settings.cache_clear()
    fs = FakeSite(wordpress=False, news=False)
    f = fs.fetcher()
    site = _site(db, fs)
    tracker.rediscover(db, f, site)
    src = next(s for s in site.sources if s.kind == "rss")
    src.etag = "abc"
    db.commit()
    orig = fs.handler

    def handler(req):
        if req.headers.get("if-none-match") == "abc":
            import httpx

            return httpx.Response(304)
        return orig(req)

    fs.handler = handler
    f2 = fs.fetcher()
    run = tracker.poll_site(db, f2, site)
    get_settings.cache_clear()
    assert run.ok and run.items_processed == 0


def test_poll_falls_back_when_fast_source_breaks(db):
    fs = FakeSite()
    f = fs.fetcher()
    site = _site(db, fs)
    tracker.rediscover(db, f, site)
    fs.wordpress = False  # WP API starts returning 404
    run = tracker.poll_site(db, f, site)
    assert run.ok and run.items_processed > 0  # fell back to the news sitemap
    wp = next(s for s in site.sources if s.kind == "wp_rest")
    assert wp.consecutive_errors == 1 and "404" in wp.last_error


def test_housekeeping_drops_old_articles_and_logs(db, monkeypatch):
    from datetime import timedelta

    from app.config import get_settings
    from app.models import JobRun
    from app.timeutil import utcnow

    fs = FakeSite()
    f = fs.fetcher()
    site = _site(db, fs)
    tracker.rediscover(db, f, site)
    tracker.backfill_site(db, f, site)
    tracker.enrich_pending(db, f)
    old = db.scalar(select(Article).where(Article.url.like("%wifi%")))  # 10 days old
    db.add(ArticleVersion(article_id=old.id, summary="x"))
    db.add(JobRun(job="poll", started_at=utcnow() - timedelta(days=60)))
    db.commit()

    monkeypatch.setenv("RETENTION_DAYS", "7")
    get_settings.cache_clear()
    try:
        run = tracker.housekeeping(db)
    finally:
        get_settings.cache_clear()
    assert run.items_processed == 1
    assert db.scalar(select(Article).where(Article.url.like("%wifi%"))) is None
    assert db.scalar(select(ArticleVersion).where(ArticleVersion.article_id == old.id)) is None
    assert len(db.scalars(select(Article)).all()) == 3
    assert db.scalar(select(JobRun).where(JobRun.job == "poll", JobRun.started_at < utcnow() - timedelta(days=59))) is None


def test_latest_date_children_picks_every_child_updated_today():
    from datetime import timedelta, timezone
    from app.parsers import SitemapIndexEntry, latest_date_children
    from tests.fakesite import NOW
    ist = timezone(timedelta(hours=5, minutes=30))
    kids = [
        SitemapIndexEntry("https://x.test/post-sitemap1.xml", NOW - timedelta(days=300)),
        SitemapIndexEntry("https://x.test/post-sitemap9.xml", NOW),
        SitemapIndexEntry("https://x.test/reviews-sitemap.xml", NOW - timedelta(minutes=5)),
        SitemapIndexEntry("https://x.test/deals-sitemap.xml", NOW - timedelta(days=4)),
        SitemapIndexEntry("https://x.test/category-sitemap.xml", NOW),
        SitemapIndexEntry("https://x.test/web-story-sitemap.xml", NOW),
    ]
    got = {c.url.rsplit("/", 1)[-1] for c in latest_date_children(kids, tz=ist)}
    today = NOW.astimezone(ist).date()
    expected = {"post-sitemap9.xml"} | ({"reviews-sitemap.xml"} if (NOW - timedelta(minutes=5)).astimezone(ist).date() == today else set())
    assert got == expected
    # `since` also brings in a child changed after the previous pass
    got2 = {c.url.rsplit("/", 1)[-1] for c in latest_date_children(kids, tz=ist, since=NOW - timedelta(days=5))}
    assert "deals-sitemap.xml" in got2 and "post-sitemap1.xml" not in got2
    # no lastmod anywhere → newest-looking children
    assert latest_date_children([SitemapIndexEntry("https://x.test/post-sitemap1.xml"), SitemapIndexEntry("https://x.test/post-sitemap2.xml")], tz=ist)[0].url.endswith("2.xml")


def test_poll_catches_todays_custom_post_type_via_sitemap(db):
    fs = FakeSite()
    f = fs.fetcher()
    site = _site(db, fs)
    tracker.rediscover(db, f, site)
    tracker.backfill_site(db, f, site)
    before = db.scalar(select(func.count(Article.id)))
    # Published today as a custom post type: invisible to WP REST, RSS and
    # the news sitemap — only reviews-sitemap.xml lists it.
    fs.publish("nothing-phone-4-review-verdict", "Nothing Phone 4 review: verdict", cpt=True)
    fs.publish("oneplus-16-launch-date-confirmed", "OnePlus 16 launch date confirmed")
    run = tracker.poll_site(db, f, site)
    urls = {a.url for a in db.scalars(select(Article))}
    fs.url = lambda slug: canonicalize(f"https://{fs.domain}/{slug}/")
    assert fs.url("nothing-phone-4-review-verdict") in urls and fs.url("oneplus-16-launch-date-confirmed") in urls
    assert run.items_new == 2 and db.scalar(select(func.count(Article.id))) == before + 2
    assert "sitemaps dated" in (run.detail or "")
    cpt = db.scalar(select(Article).where(Article.url == fs.url("nothing-phone-4-review-verdict")))
    assert cpt.is_backfill is False and cpt.discovered_via == "sitemap"
    # next poll: unchanged children aren't re-read
    n_before = len([u for u in fs.requests if u.endswith("reviews-sitemap.xml")])
    run2 = tracker.poll_site(db, f, site)
    assert run2.items_new == 0
    assert len([u for u in fs.requests if u.endswith("reviews-sitemap.xml")]) == n_before
    assert "unchanged" in run2.detail


def test_slug_title():
    assert tracker.slug_title("https://x.com/best-phones-under-30000-in-india/") == "Best phones under 30000 in india"
    assert tracker.slug_title("https://x.com/news/pixel-11-launch-123456") == "Pixel 11 launch"
    assert tracker.slug_title("https://x.com/") is None


def test_sitemap_articles_visible_before_enrichment_and_coverage_report(db, client):
    fs = FakeSite()
    f = fs.fetcher()
    site = _site(db, fs)
    tracker.rediscover(db, f, site)
    tracker.backfill_site(db, f, site)
    tracker.enrich_pending(db, f, limit=100)
    fs.publish("nothing-phone-4-review-verdict", "Nothing Phone 4 review: verdict", cpt=True)
    tracker.poll_site(db, f, site)  # no enrichment yet
    items = client.get("/api/articles", params={"q": "nothing"}).json()["items"]
    assert len(items) == 1 and items[0]["title"] == "Nothing phone 4 review verdict" and items[0]["published_at"]
    # page can't be read → still in the feed
    a = db.scalar(select(Article).where(Article.url.like("%nothing-phone-4%")))
    a.enrich_status, a.last_error = "error", "HTTP 403"
    db.commit()
    assert client.get("/api/articles", params={"q": "nothing"}).json()["total"] == 1
    # coverage report: today's children, everything dated today is in the feed
    fs.publish("vivo-x300-ultra-teased-india", "Vivo X300 Ultra teased for India", cpt=True)
    rep = tracker.sitemap_coverage(db, f, site)
    names = {c["url"].rsplit("/", 1)[-1]: c for c in rep["children"]}
    assert "reviews-sitemap.xml" in names and "category-sitemap.xml" not in names
    rv = names["reviews-sitemap.xml"]
    assert rep["added_now"] >= 1 and rv["latest_day_urls"] == 2 and rv["visible"] == 2 and not rv["missing"]
