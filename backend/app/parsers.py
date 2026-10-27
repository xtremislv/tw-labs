"""Parsers that turn a fetched sitemap / feed / API response / homepage into
a flat list of Candidate articles. Pure functions — no network, easy to test."""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime

import feedparser
from lxml import etree
from lxml import html as lxml_html

from .timeutil import parse_dt
from .urlnorm import canonicalize, looks_like_article


@dataclass
class Candidate:
    url: str
    lastmod: datetime | None = None
    published: datetime | None = None
    title: str | None = None
    kind: str = ""


@dataclass
class SitemapIndexEntry:
    url: str
    lastmod: datetime | None = None


@dataclass
class SitemapDoc:
    is_index: bool
    children: list[SitemapIndexEntry] = field(default_factory=list)
    urls: list[Candidate] = field(default_factory=list)
    is_news: bool = False


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _child_text(el, name: str) -> str | None:
    for c in el:
        if _local(c.tag) == name:
            return (c.text or "").strip() or None
    return None


def _strip_html(s: str | None) -> str | None:
    if not s:
        return s
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip() or None


def parse_sitemap(content: bytes | str) -> SitemapDoc:
    if isinstance(content, str):
        content = content.encode("utf-8", errors="replace")
    parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True, huge_tree=True)
    root = etree.fromstring(content.strip(), parser=parser)
    if root is None:
        raise ValueError("not an XML sitemap")
    rname = _local(root.tag)
    if rname == "sitemapindex":
        doc = SitemapDoc(is_index=True)
        for sm in root:
            if _local(sm.tag) != "sitemap":
                continue
            loc = _child_text(sm, "loc")
            if loc:
                doc.children.append(SitemapIndexEntry(loc, parse_dt(_child_text(sm, "lastmod"))))
        return doc
    if rname != "urlset":
        raise ValueError(f"unexpected sitemap root <{rname}>")
    doc = SitemapDoc(is_index=False)
    for u in root:
        if _local(u.tag) != "url":
            continue
        loc = _child_text(u, "loc")
        if not loc:
            continue
        cand = Candidate(url=loc, lastmod=parse_dt(_child_text(u, "lastmod")), kind="sitemap")
        for c in u:
            if _local(c.tag) == "news":
                doc.is_news = True
                cand.kind = "news_sitemap"
                cand.published = parse_dt(_child_text(c, "publication_date"))
                cand.title = _child_text(c, "title")
        doc.urls.append(cand)
    return doc


_SKIP_CHILD = re.compile(
    r"(category|categories|tag|tags|author|authors|page-sitemap|pages?[-_]?sitemap|"
    r"attachment|product|brand|web-?stor|stories|video|image|gallery|taxonom|local|"
    r"misc|static|topic)",
    re.I,
)
_PREFER_CHILD = re.compile(r"(post|article|news|story|blog)", re.I)
_DATE_IN_URL = re.compile(r"(20\d\d)[-_/]?(0[1-9]|1[0-2])(?:[-_/]?([0-3]\d))?")


def _date_key(e: SitemapIndexEntry) -> tuple:
    m = _DATE_IN_URL.search(e.url)
    d = (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)) if m else (0, 0, 0)
    lm = e.lastmod.timestamp() if e.lastmod else 0
    return (lm, d)


def choose_child_sitemaps(
    children: list[SitemapIndexEntry], *, cutoff: datetime | None, limit: int
) -> list[SitemapIndexEntry]:
    """Pick the few child sitemaps likely to hold recent articles.

    Publisher sitemap indexes often list hundreds of children (one per month
    or one per 1,000 posts) plus taxonomy ones. We drop taxonomy, prefer
    post/news children, then take the most recent by lastmod or by a date in
    the filename; with neither, the *last* entries (Yoast numbers post
    sitemaps oldest-first, so the newest posts live in the highest number).
    """
    kept = [c for c in children if not _SKIP_CHILD.search(c.url.rsplit("/", 1)[-1])]
    preferred = [c for c in kept if _PREFER_CHILD.search(c.url.rsplit("/", 1)[-1])]
    pool = preferred or kept or children
    has_signal = any(c.lastmod or _DATE_IN_URL.search(c.url) for c in pool)
    if has_signal:
        ranked = sorted(pool, key=_date_key, reverse=True)
        if cutoff is not None:
            recent = [c for c in ranked if c.lastmod is None or c.lastmod >= cutoff]
            ranked = recent or ranked[:1]
        return ranked[:limit]
    return pool[-limit:][::-1]


# Child sitemaps that never list articles (taxonomy archives, media, web
# stories). Narrower than _SKIP_CHILD on purpose: custom post types such as
# reviews-sitemap.xml or deals-sitemap.xml must be kept.
_TAXONOMY_CHILD = re.compile(
    r"(category|categories|post_tag|tag-sitemap|tags-sitemap|author|attachment|taxonom|web-?stor|image-sitemap)",
    re.I,
)


def latest_date_children(
    children: list[SitemapIndexEntry], *, tz, since: datetime | None = None, limit: int = 20
) -> list[SitemapIndexEntry]:
    """Every child sitemap updated on the most recent date in the index.

    WordPress SEO plugins (Yoast, Rank Math, AIOSEO) bump a child's <lastmod>
    when a post in it is published or edited, so every child that carries
    the index's latest date holds something new — whatever its post type.
    Children changed since `since` (the previous pass) are included too, so a
    post published just before midnight isn't skipped when the date rolls
    over. Without any lastmod the newest-looking children are used instead.
    """
    kept = [c for c in children if not _TAXONOMY_CHILD.search(c.url.rsplit("/", 1)[-1])] or children
    dated = [c for c in kept if c.lastmod]
    if not dated:
        return choose_child_sitemaps(kept, cutoff=None, limit=2)
    latest = max(c.lastmod for c in dated).astimezone(tz).date()
    picked = [c for c in dated if c.lastmod.astimezone(tz).date() == latest or (since is not None and c.lastmod >= since)]
    picked.sort(key=lambda c: c.lastmod, reverse=True)
    return picked[:limit]


def parse_feed(text: str) -> list[Candidate]:
    d = feedparser.parse(text)
    out: list[Candidate] = []
    for e in d.entries:
        link = e.get("link")
        if not link:
            continue
        published = parse_dt(e.get("published")) or parse_dt(e.get("created"))
        updated = parse_dt(e.get("updated"))
        out.append(
            Candidate(
                url=link,
                published=published or updated,
                lastmod=updated or published,
                title=_strip_html(e.get("title")),
                kind="rss",
            )
        )
    return out


def _blocked_hint(status: int, headers: dict) -> str:
    h = {k.lower(): v for k, v in headers.items()}
    if h.get("cf-mitigated") or ("cloudflare" in h.get("server", "").lower() and status in (403, 503)):
        return "blocked by Cloudflare bot protection"
    if status in (401, 403):
        return "access denied to automated requests"
    if status == 429:
        return "rate-limited"
    return f"HTTP {status}"


def parse_search_feed(text: str, domain: str) -> list[Candidate]:
    """Google News / Bing News RSS for `site:domain`. Bing wraps each link in
    a click-tracker whose url= parameter is the real article; Google's links
    stay Google redirects (they open the article in a browser)."""
    from urllib.parse import parse_qs, urlsplit

    from .urlnorm import same_site

    out: list[Candidate] = []
    for e in feedparser.parse(text).entries:
        link = e.get("link") or ""
        if "bing.com" in link and "url=" in link:
            link = (parse_qs(urlsplit(link).query).get("url") or [""])[0]
            if not same_site(link, domain):
                continue
        elif "news.google.com" in link:
            src = (e.get("source") or {}).get("href", "")
            if domain not in src:
                continue
        elif not same_site(link, domain):
            continue
        title = _strip_html(e.get("title")) or ""
        title = re.sub(r"\s+[-–|]\s+[^-–|]{2,60}$", "", title) or title  # " - Destructoid"
        pub = parse_dt(e.get("published")) or parse_dt(e.get("updated"))
        out.append(Candidate(url=link, published=pub, lastmod=pub, title=title or None, kind="search"))
    return out


def is_feed(text: str) -> bool:
    head = text.lstrip()[:500].lower()
    return head.startswith("<?xml") and ("<rss" in text[:2000].lower() or "<feed" in text[:2000].lower()) or head.startswith("<rss") or head.startswith("<feed")


def parse_wp_posts(text: str) -> list[Candidate]:
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("WordPress REST response is not a list")
    out: list[Candidate] = []
    for p in data:
        if not isinstance(p, dict) or not p.get("link"):
            continue
        title = p.get("title")
        if isinstance(title, dict):
            title = title.get("rendered")
        published = parse_dt((p.get("date_gmt") or "") + "Z" if p.get("date_gmt") else p.get("date"))
        modified = parse_dt((p.get("modified_gmt") or "") + "Z" if p.get("modified_gmt") else p.get("modified"))
        out.append(
            Candidate(url=p["link"], published=published, lastmod=modified or published, title=_strip_html(title), kind="wp_rest")
        )
    return out


def parse_homepage_links(text: str, base_url: str, domain: str, limit: int = 120) -> list[Candidate]:
    try:
        doc = lxml_html.fromstring(text)
    except (etree.ParserError, ValueError):
        return []
    doc.make_links_absolute(base_url, resolve_base_href=True)
    seen: set[str] = set()
    out: list[Candidate] = []
    for a in doc.iter("a"):
        href = a.get("href")
        if not href or not href.startswith("http"):
            continue
        canon = canonicalize(href)
        if canon in seen or not looks_like_article(canon, domain):
            continue
        seen.add(canon)
        title = " ".join(a.text_content().split()) or None
        out.append(Candidate(url=href, title=title if title and len(title) > 15 else None, kind="html"))
        if len(out) >= limit:
            break
    return out


def find_feed_links(text: str, base_url: str) -> list[str]:
    """<link rel="alternate" type="application/rss+xml"> tags on a page."""
    try:
        doc = lxml_html.fromstring(text)
    except (etree.ParserError, ValueError):
        return []
    doc.make_links_absolute(base_url, resolve_base_href=True)
    out = []
    for link in doc.iter("link"):
        rel = (link.get("rel") or "").lower()
        typ = (link.get("type") or "").lower()
        if "alternate" in rel and ("rss" in typ or "atom" in typ) and link.get("href"):
            href = link.get("href")
            if "/comments/" not in href and "comments/feed" not in href:
                out.append(href)
    return out
