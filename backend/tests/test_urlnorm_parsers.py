from datetime import timedelta

from app.extract import classify_content_type
from app.parsers import SitemapIndexEntry, choose_child_sitemaps, parse_feed, parse_sitemap, parse_wp_posts
from app.timeutil import parse_dt, utcnow
from app.urlnorm import canonicalize, looks_like_article, normalize_domain


def test_normalize_domain():
    assert normalize_domain("https://www.Beebom.com/foo") == "beebom.com"
    assert normalize_domain("91mobiles.com") == "91mobiles.com"


def test_canonicalize_strips_tracking_amp_and_slash():
    assert canonicalize("http://x.com/a-b-c/amp/?utm_source=tw&id=3#top") == "https://x.com/a-b-c?id=3"
    assert canonicalize("https://x.com/amp/a-b-c/") == "https://x.com/a-b-c"


def test_looks_like_article():
    d = "x.com"
    assert looks_like_article("https://x.com/galaxy-s27-ultra-review", d)
    assert looks_like_article("https://x.com/news/1234567", d)
    assert not looks_like_article("https://x.com/category/mobiles", d)
    assert not looks_like_article("https://x.com/author/riya", d)
    assert not looks_like_article("https://x.com/", d)
    assert not looks_like_article("https://other.com/galaxy-s27-ultra-review", d)
    assert not looks_like_article("https://x.com/wp-content/uploads/a-big-image.jpg", d)


def test_parse_sitemap_news_and_index():
    news = parse_sitemap(
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">'
        b"<url><loc>https://x.com/a-b-c-d</loc><news:news><news:publication_date>2026-10-25T10:00:00+05:30</news:publication_date>"
        b"<news:title>Hello &amp; bye</news:title></news:news></url></urlset>"
    )
    assert news.is_news and news.urls[0].title == "Hello & bye"
    assert news.urls[0].published.hour == 4  # converted to UTC
    idx = parse_sitemap('<?xml version="1.0"?><sitemapindex><sitemap><loc>https://x.com/s1.xml</loc></sitemap></sitemapindex>')
    assert idx.is_index and idx.children[0].url == "https://x.com/s1.xml"


def test_choose_child_sitemaps_prefers_recent_posts():
    now = utcnow()
    kids = [
        SitemapIndexEntry("https://x.com/category-sitemap.xml", now),
        SitemapIndexEntry("https://x.com/post-sitemap1.xml", now - timedelta(days=500)),
        SitemapIndexEntry("https://x.com/post-sitemap2.xml", now),
        SitemapIndexEntry("https://x.com/page-sitemap.xml", now),
    ]
    got = choose_child_sitemaps(kids, cutoff=now - timedelta(days=30), limit=4)
    assert [g.url for g in got] == ["https://x.com/post-sitemap2.xml"]
    # No lastmod anywhere: Yoast numbering puts the newest posts last.
    plain = [SitemapIndexEntry(f"https://x.com/post-sitemap{i}.xml") for i in range(1, 9)]
    assert choose_child_sitemaps(plain, cutoff=None, limit=2)[0].url.endswith("post-sitemap8.xml")
    # Date-partitioned names.
    dated = [SitemapIndexEntry(f"https://x.com/sitemap-2026-{m:02d}.xml") for m in range(1, 11)]
    assert choose_child_sitemaps(dated, cutoff=None, limit=1)[0].url.endswith("2026-10.xml")


def test_parse_feed_and_wp():
    items = parse_feed('<rss version="2.0"><channel><item><title>A &lt;b&gt;x&lt;/b&gt;</title><link>https://x.com/a-b-c</link>'
                       "<pubDate>Sun, 25 Oct 2026 10:00:00 +0000</pubDate></item></channel></rss>")
    assert items[0].url == "https://x.com/a-b-c" and items[0].published is not None
    wp = parse_wp_posts('[{"link":"https://x.com/p-q-r","date_gmt":"2026-10-25T10:00:00","modified_gmt":"2026-10-26T01:00:00","title":{"rendered":"Tips &#038; tricks"}}]')
    assert wp[0].title == "Tips & tricks" and wp[0].lastmod > wp[0].published


def test_parse_dt_rejects_bogus():
    assert parse_dt("0000-00-00 00:00:00") is None
    assert parse_dt("1970-01-01") is None
    assert parse_dt("not a date") is None
    assert parse_dt("2099-01-01") is None


def test_classify_content_type():
    assert classify_content_type("iPhone 18 vs Galaxy S27: which to buy", "u") == "comparison"
    assert classify_content_type("Pixel 11 review: camera king", "u") == "review"
    assert classify_content_type("How to fix Wi-Fi on Android", "u") == "how-to"
    assert classify_content_type("10 best phones under 20000", "u") == "listicle"
    assert classify_content_type("iPhone 17 gets Rs 10,000 price cut on Flipkart", "u") == "deal"
    assert classify_content_type("OnePlus 15 launched in India", "u") == "news"
