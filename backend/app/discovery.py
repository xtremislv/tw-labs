"""Find every machine-readable list of articles a site publishes.

Run once when a site is added (and again on "Rediscover"). Result is a set
of SiteSource rows ranked by how fresh and exact each one is:

    10  wp_rest       WordPress REST API, ordered by modified date — exact
                      publish + edit times, sees updates immediately
    20  news_sitemap  Google News sitemap — last ~48 h of articles
    30  rss           RSS / Atom feed
    60  sitemap       Full sitemap (index) — the 6-hourly backstop
    90  html          Homepage link scrape — last resort when nothing else works
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from lxml import html as lxml_html

from .fetcher import FetchError, Fetcher
from .parsers import find_feed_links, is_feed, parse_feed, parse_homepage_links, parse_sitemap, parse_wp_posts

PRIORITY = {"wp_rest": 10, "news_sitemap": 20, "rss": 30, "sitemap": 60, "html": 90}
WP_FIELDS = "_fields=link,date_gmt,modified_gmt,title"
COMMON_SITEMAPS = [
    "/sitemap_index.xml",
    "/sitemap.xml",
    "/sitemap-index.xml",
    "/wp-sitemap.xml",
    "/news-sitemap.xml",
    "/sitemap-news.xml",
    "/news_sitemap.xml",
    "/sitemap_news.xml",
]
COMMON_FEEDS = ["/feed/", "/rss", "/rss.xml", "/feed.xml", "/atom.xml", "/feeds/news/", "/feeds/mashup/", "/news/feed/"]
# Listing pages that most publishers keep (latest posts, news) — scraped for
# links like the homepage when they actually list articles.
COMMON_LISTINGS = ["/news/", "/latest/", "/latest-news/", "/news/latest/", "/category/news/", "/articles/", "/guides/"]
MAX_SITEMAPS = 4
MAX_NEWS_SITEMAPS = 3
MAX_FEEDS = 3
MAX_LISTINGS = 3


@dataclass
class FoundSource:
    kind: str
    url: str
    item_count: int = 0

    @property
    def priority(self) -> int:
        return PRIORITY[self.kind]


@dataclass
class DiscoveryResult:
    home_url: str
    name: str | None = None
    icon_url: str | None = None
    sources: list[FoundSource] = field(default_factory=list)
    log: list[str] = field(default_factory=list)

    def add(self, src: FoundSource) -> None:
        if all(s.url != src.url for s in self.sources):
            self.sources.append(src)
            self.log.append(f"found {src.kind}: {src.url} ({src.item_count} items)")


def _site_name_and_icon(page_html: str, base: str) -> tuple[str | None, str | None]:
    try:
        doc = lxml_html.fromstring(page_html)
    except (ValueError, Exception):  # noqa: BLE001
        return None, None
    name = None
    for m in doc.iter("meta"):
        if (m.get("property") or "").lower() == "og:site_name" and m.get("content"):
            name = m.get("content").strip()
            break
    if not name:
        t = doc.findtext(".//title")
        if t:
            name = " ".join(t.split()).split(" | ")[0].split(" - ")[0].strip()[:80] or None
    icon = None
    for link in doc.iter("link"):
        rel = (link.get("rel") or "").lower()
        if "icon" in rel and link.get("href"):
            icon = urljoin(base, link.get("href"))
            if "apple-touch" in rel:
                break
    return name, icon or urljoin(base, "/favicon.ico")


def discover(fetcher: Fetcher, domain: str) -> DiscoveryResult:
    base = f"https://{domain}"
    res = DiscoveryResult(home_url=base + "/")

    # 1. Homepage: real origin (www. or not), name, icon, feed links.
    home = None
    for candidate in (base + "/", f"https://www.{domain}/"):
        try:
            r = fetcher.get(candidate, check_robots=False)
            if r.ok:
                home = r
                break
        except FetchError as e:
            res.log.append(f"homepage {candidate}: {e}")
    if home is not None:
        p = urlsplit(home.url)
        base = f"{p.scheme}://{p.netloc}"
        res.home_url = base + "/"
        res.name, res.icon_url = _site_name_and_icon(home.text, base)
    else:
        res.log.append("homepage unreachable — the site may block automated requests")

    # 2. Sitemaps: every one robots.txt declares, then the common paths.
    #    Each distinct general sitemap (index or urlset) becomes a source —
    #    publishers often split posts, news and guides across several.
    sitemap_urls: list[str] = []
    try:
        rb = fetcher.get(base + "/robots.txt", check_robots=False)
        if rb.ok:
            for line in rb.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    sitemap_urls.append(line.split(":", 1)[1].strip())
    except FetchError as e:
        res.log.append(f"robots.txt: {e}")
    sitemap_urls += [base + p for p in COMMON_SITEMAPS]
    seen: set[str] = set()
    n_general = n_news = 0
    for sm_url in sitemap_urls:
        if sm_url in seen or len(seen) >= 14:
            continue
        seen.add(sm_url)
        try:
            r = fetcher.get(sm_url)
            if not r.ok:
                continue
            if r.url != sm_url and r.url in seen:
                continue  # /sitemap.xml redirecting to an index we already have
            seen.add(r.url)
            doc = parse_sitemap(r.content or r.text)
        except (FetchError, ValueError, Exception) as e:  # noqa: BLE001 - lxml raises XMLSyntaxError subclasses
            res.log.append(f"sitemap {sm_url}: {type(e).__name__}")
            continue
        if doc.is_index:
            news_children = [c for c in doc.children if "news" in c.url.rsplit("/", 1)[-1].lower()]
            for child in news_children[:MAX_NEWS_SITEMAPS]:
                if child.url in seen or n_news >= MAX_NEWS_SITEMAPS:
                    continue
                seen.add(child.url)
                try:
                    cr = fetcher.get(child.url)
                    cdoc = parse_sitemap(cr.content or cr.text) if cr.ok else None
                except (FetchError, ValueError, Exception):  # noqa: BLE001
                    cdoc = None
                if cdoc and not cdoc.is_index and cdoc.is_news and cdoc.urls:
                    res.add(FoundSource("news_sitemap", child.url, len(cdoc.urls)))
                    n_news += 1
            if n_general < MAX_SITEMAPS:
                res.add(FoundSource("sitemap", r.url, len(doc.children)))
                n_general += 1
        elif doc.is_news and doc.urls:
            if n_news < MAX_NEWS_SITEMAPS:
                res.add(FoundSource("news_sitemap", r.url, len(doc.urls)))
                n_news += 1
        elif doc.urls and n_general < MAX_SITEMAPS:
            res.add(FoundSource("sitemap", r.url, len(doc.urls)))
            n_general += 1

    # 3. WordPress REST API.
    wp_base = base + "/wp-json/wp/v2/posts"
    for query in (f"per_page=50&orderby=modified&order=desc&{WP_FIELDS}", f"per_page=50&{WP_FIELDS}"):
        try:
            r = fetcher.get(f"{wp_base}?{query}")
            if r.ok and r.text.lstrip().startswith("["):
                posts = parse_wp_posts(r.text)
                if posts:
                    res.add(FoundSource("wp_rest", f"{wp_base}?{query}", len(posts)))
                    break
        except (FetchError, ValueError, json.JSONDecodeError) as e:
            res.log.append(f"wp_rest: {type(e).__name__}")
            break

    # 4. RSS / Atom: every feed the homepage advertises, then the common
    #    paths — several feeds (news, reviews, guides) are all kept.
    feed_urls = find_feed_links(home.text, base) if home is not None else []
    feed_urls += [base + p for p in COMMON_FEEDS]
    tried: set[str] = set()
    n_feeds = 0
    for fu in feed_urls:
        key = fu.rstrip("/")
        if key in tried or len(tried) >= 10 or n_feeds >= MAX_FEEDS:
            continue
        tried.add(key)
        try:
            r = fetcher.get(fu)
            if r.ok and is_feed(r.text) and r.url.rstrip("/") not in {s.url.rstrip("/") for s in res.sources}:
                items = parse_feed(r.text)
                if items:
                    res.add(FoundSource("rss", r.url, len(items)))
                    n_feeds += 1
        except FetchError:
            continue

    # 5. Homepage + latest/news listing pages (link scrape). Always kept: they
    #    catch posts a feed or sitemap leaves out, and work on any CMS.
    if home is not None:
        domain_ = urlsplit(base).hostname.removeprefix("www.")
        links = parse_homepage_links(home.text, base, domain_)
        res.add(FoundSource("html", res.home_url, len(links)))
        n_list = 0
        for lp in COMMON_LISTINGS:
            if n_list >= MAX_LISTINGS:
                break
            try:
                r = fetcher.get(base + lp)
                if not r.ok or r.url.rstrip("/") == res.home_url.rstrip("/"):
                    continue
                found = parse_homepage_links(r.text, r.url, domain_)
                if len(found) >= 8:
                    res.add(FoundSource("html", r.url, len(found)))
                    n_list += 1
            except FetchError:
                continue

    res.sources.sort(key=lambda s: s.priority)
    return res
