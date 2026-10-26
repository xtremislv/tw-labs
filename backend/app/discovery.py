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
    "/news-sitemap.xml",
    "/sitemap-news.xml",
    "/news_sitemap.xml",
    "/sitemap_news.xml",
]


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

    # 2. Sitemaps: robots.txt first, then the common paths.
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
    found_general = False
    for sm_url in sitemap_urls:
        if sm_url in seen or len(seen) >= 10:
            continue
        seen.add(sm_url)
        try:
            r = fetcher.get(sm_url)
            if not r.ok:
                continue
            doc = parse_sitemap(r.content or r.text)
        except (FetchError, ValueError, Exception) as e:  # noqa: BLE001 - lxml raises XMLSyntaxError subclasses
            res.log.append(f"sitemap {sm_url}: {type(e).__name__}")
            continue
        if doc.is_index:
            news_children = [c for c in doc.children if "news" in c.url.rsplit("/", 1)[-1].lower()]
            for child in news_children[:2]:
                if child.url in seen:
                    continue
                seen.add(child.url)
                try:
                    cr = fetcher.get(child.url)
                    cdoc = parse_sitemap(cr.content or cr.text) if cr.ok else None
                except (FetchError, ValueError, Exception):  # noqa: BLE001
                    cdoc = None
                if cdoc and not cdoc.is_index and cdoc.is_news and cdoc.urls:
                    res.add(FoundSource("news_sitemap", child.url, len(cdoc.urls)))
            if not found_general:
                res.add(FoundSource("sitemap", sm_url, len(doc.children)))
                found_general = True
        elif doc.is_news and doc.urls:
            res.add(FoundSource("news_sitemap", sm_url, len(doc.urls)))
        elif doc.urls and not found_general:
            res.add(FoundSource("sitemap", sm_url, len(doc.urls)))
            found_general = True

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

    # 4. RSS / Atom.
    feed_urls = find_feed_links(home.text, base) if home is not None else []
    feed_urls += [base + "/feed", base + "/rss", base + "/feed/"]
    tried: set[str] = set()
    for fu in feed_urls:
        if fu.rstrip("/") in tried or len(tried) >= 4:
            continue
        tried.add(fu.rstrip("/"))
        try:
            r = fetcher.get(fu)
            if r.ok and is_feed(r.text):
                items = parse_feed(r.text)
                if items:
                    res.add(FoundSource("rss", r.url, len(items)))
                    break
        except FetchError:
            continue

    # 5. Homepage scrape fallback — always registered, used only when the
    #    feeds above fail.
    if home is not None:
        links = parse_homepage_links(home.text, base, urlsplit(base).hostname.removeprefix("www."))
        res.add(FoundSource("html", res.home_url, len(links)))

    res.sources.sort(key=lambda s: s.priority)
    return res
