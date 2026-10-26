from sqlalchemy import select

from app import tracker
from app.discovery import discover
from app.models import Article, ArticleVersion, Site
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


def test_poll_uses_etag_304(db):
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
