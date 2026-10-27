"""A non-WordPress publisher (like GameSpot / TheGamer / Destructoid) that
splits its content across several feeds, sitemaps and listing pages. Each
article below is visible through exactly ONE of those methods — the tracker
must find all of them."""
from datetime import timedelta

import httpx
from sqlalchemy import select

from app import tracker
from app.discovery import discover
from app.fetcher import Fetcher
from app.models import Article, Site
from tests.fakesite import NOW, iso

D = "gamehub.test"
ARTS = {
    "feed-news": "zelda-remake-release-date-announced",
    "feed-reviews": "metroid-prime-5-review-verdict",
    "nested-sitemap": "best-builds-for-elden-ring-nightreign",
    "plain-sitemap": "roblox-clover-rpg-codes-october",
    "listing-page": "gta-6-trailer-3-breakdown-details",
    "homepage": "switch-3-price-leak-rumour-roundup",
}


def _rss(slug, title):
    return (f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title><item><title>{title}</title>'
            f'<link>https://{D}/{slug}/</link><pubDate>{NOW.strftime("%a, %d %b %Y %H:%M:%S +0000")}</pubDate></item></channel></rss>')


def _urlset(*slugs):
    body = "".join(f"<url><loc>https://{D}/{s}/</loc><lastmod>{iso(NOW)}</lastmod></url>" for s in slugs)
    return f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'


def _index(*kids):
    body = "".join(f"<sitemap><loc>https://{D}/{k}</loc><lastmod>{iso(lm)}</lastmod></sitemap>" for k, lm in kids)
    return f'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</sitemapindex>'


def _page(title):
    paras = "".join(f"<p>Paragraph {i} of {title} with enough words to count as article body text for sure.</p>" for i in range(8))
    return f"<html><head><title>{title}</title></head><body><article><h1>{title}</h1>{paras}</article></body></html>"


def handler(req: httpx.Request) -> httpx.Response:
    p = req.url.path
    routes = {
        "/robots.txt": (f"User-agent: *\nSitemap: https://{D}/sitemaps/index.xml\nSitemap: https://{D}/sitemaps/guides.xml\n", "text"),
        "/": (f'<html><head><link rel="alternate" type="application/rss+xml" href="https://{D}/feeds/news/">'
              f'<link rel="alternate" type="application/rss+xml" href="https://{D}/feeds/reviews/"></head><body>'
              f'<a href="https://{D}/{ARTS["homepage"]}/">Switch 3 price leak rumour roundup</a></body></html>', "html"),
        "/feeds/news/": (_rss(ARTS["feed-news"], "Zelda remake release date announced"), "text"),
        "/feeds/reviews/": (_rss(ARTS["feed-reviews"], "Metroid Prime 5 review"), "text"),
        # index → year index → month urlset (3 levels)
        "/sitemaps/index.xml": (_index(("sitemaps/2026.xml", NOW), ("sitemaps/2025.xml", NOW - timedelta(days=300))), "text"),
        "/sitemaps/2026.xml": (_index(("sitemaps/2026-10.xml", NOW), ("sitemaps/2026-09.xml", NOW - timedelta(days=30))), "text"),
        "/sitemaps/2026-10.xml": (_urlset(ARTS["nested-sitemap"]), "text"),
        "/sitemaps/guides.xml": (_urlset(ARTS["plain-sitemap"]), "text"),
        "/news/": ("<html><body>" + "".join(
            f'<a href="https://{D}/{s}/">{s.replace("-", " ")}</a>'
            for s in [ARTS["listing-page"]] + [f"older-story-number-{i}-from-the-news-archive" for i in range(9)]) + "</body></html>", "html"),
    }
    if p in routes:
        body, kind = routes[p]
        return httpx.Response(200, html=body) if kind == "html" else httpx.Response(200, text=body)
    slug = p.strip("/")
    if slug in ARTS.values() or slug.startswith("older-story"):
        return httpx.Response(200, html=_page(slug.replace("-", " ").title()))
    return httpx.Response(404)


def _fetcher():
    return Fetcher(client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))


def test_discovery_registers_every_feed_sitemap_and_listing_page():
    res = discover(_fetcher(), D)
    got = {(s.kind, s.url.replace(f"https://{D}", "")) for s in res.sources}
    assert ("rss", "/feeds/news/") in got and ("rss", "/feeds/reviews/") in got
    assert ("sitemap", "/sitemaps/index.xml") in got and ("sitemap", "/sitemaps/guides.xml") in got
    assert ("html", "/") in got and ("html", "/news/") in got


def test_poll_merges_every_method(db):
    f = _fetcher()
    site = Site(domain=D, name="GameHub", home_url=f"https://{D}/")
    db.add(site)
    db.commit()
    tracker.rediscover(db, f, site)
    run = tracker.poll_site(db, f, site)
    urls = {a.url for a in db.scalars(select(Article))}
    for how, slug in ARTS.items():
        assert any(slug in u for u in urls), f"missed the article only visible via {how}"
    assert "rss" in run.detail and "html" in run.detail and "sitemaps dated" in run.detail
    # a repeat poll re-reads nothing that hasn't changed and adds nothing
    assert tracker.poll_site(db, f, site).items_new == 0
