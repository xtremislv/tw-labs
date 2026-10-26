"""Turn one fetched article page into structured metadata.

Order of trust for each field: the page's own JSON-LD (Article / NewsArticle
schema, which publishers maintain for Google) → OpenGraph / article:* meta
tags → trafilatura's own metadata guesses. Body text comes from trafilatura
and is only used to count words and hash paragraphs; it isn't stored.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime

import extruct
import trafilatura
from lxml import etree
from lxml import html as lxml_html

from .timeutil import parse_dt

ARTICLE_TYPES = {
    "article", "newsarticle", "blogposting", "reportagenewsarticle", "review",
    "techarticle", "analysisnewsarticle", "howto", "liveblogposting", "opinionnewsarticle",
}

_YT_ID = re.compile(r"(?:youtube(?:-nocookie)?\.com/(?:embed/|watch\?v=|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})")
_AFFILIATE = re.compile(
    r"(amzn\.to/|amazon\.(in|com)/.*[?&]tag=|flipkart\.com/.*[?&]affid=|fkrt\.(it|cc|co)/|"
    r"ekaro\.in|linksredirect\.com|clnk\.in|bitli\.in|inr\.deals|go\.skimresources|"
    r"tatacliq\.com/.*utm_source=affiliate|croma\.com/.*affiliate)",
    re.I,
)
_MIN_PARA_CHARS = 60


@dataclass
class PageData:
    title: str | None = None
    excerpt: str | None = None
    author: str | None = None
    section: str | None = None
    tags: list[str] = field(default_factory=list)
    thumbnail_url: str | None = None
    published_at: datetime | None = None
    modified_at: datetime | None = None
    word_count: int = 0
    image_count: int = 0
    youtube_ids: list[str] = field(default_factory=list)
    affiliate_link_count: int = 0
    headings: list[str] = field(default_factory=list)
    paragraph_hashes: list[str] = field(default_factory=list)
    content_hash: str | None = None
    content_type: str = "news"
    canonical_url: str | None = None


# ── helpers ────────────────────────────────────────────────────────────────
def _flatten_jsonld(items) -> list[dict]:
    out: list[dict] = []
    stack = list(items if isinstance(items, list) else [items])
    while stack:
        it = stack.pop(0)
        if isinstance(it, list):
            stack.extend(it)
        elif isinstance(it, dict):
            if "@graph" in it:
                stack.extend(it["@graph"] if isinstance(it["@graph"], list) else [it["@graph"]])
            out.append(it)
    return out


def _types(obj: dict) -> set[str]:
    t = obj.get("@type")
    if isinstance(t, str):
        return {t.lower()}
    if isinstance(t, list):
        return {str(x).lower() for x in t}
    return set()


def _name(v) -> str | None:
    if isinstance(v, str):
        return v.strip() or None
    if isinstance(v, dict):
        return _name(v.get("name"))
    if isinstance(v, list):
        names = [n for n in (_name(x) for x in v) if n]
        return ", ".join(dict.fromkeys(names)) or None
    return None


def _image(v) -> str | None:
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return v.get("url") or v.get("contentUrl")
    if isinstance(v, list) and v:
        return _image(v[0])
    return None


def _keywords(v) -> list[str]:
    if isinstance(v, str):
        return [k.strip() for k in v.split(",") if k.strip()]
    if isinstance(v, list):
        return [str(k).strip() for k in v if str(k).strip()]
    return []


def _norm_para(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip().lower()


def _short_hash(t: str) -> str:
    return hashlib.sha1(t.encode("utf-8")).hexdigest()[:12]


def classify_content_type(title: str | None, url: str) -> str:
    t = f" {(title or '').lower()} "
    u = url.lower()
    if re.search(r"\bvs\.?\b|\bversus\b", t) or "-vs-" in u:
        return "comparison"
    if re.search(r"\b(deal|deals|offer|offers|discount|price cut|price drop|sale|coupon|lowest price)\b", t) and not re.search(r"\breview\b", t):
        return "deal"
    if re.search(r"\breview\b|\bhands[- ]on\b|\bfirst impressions?\b|\blong[- ]term\b", t) or "/review" in u:
        return "review"
    if re.search(r"\bhow to\b|\bhow-to\b|\bways to\b|\bfix\b|\bguide\b|\bstep[- ]by[- ]step\b|\btips\b|\btricks\b|\bexplained\b|\bwhat is\b", t):
        return "how-to"
    if re.search(r"^\s*(top\s+)?\d{1,3}\s|\bbest\b|\btop \d+\b", t):
        return "listicle"
    return "news"


# ── main entry point ───────────────────────────────────────────────────────
def extract_page(html_text: str, url: str) -> PageData:
    pd = PageData()

    # 1. Structured data
    try:
        meta = extruct.extract(html_text, base_url=url, syntaxes=["json-ld", "opengraph"], uniform=True, errors="ignore")
    except Exception:  # noqa: BLE001 - extruct can raise many parser errors
        meta = {"json-ld": [], "opengraph": []}
    ld_article = None
    for obj in _flatten_jsonld(meta.get("json-ld") or []):
        if _types(obj) & ARTICLE_TYPES:
            ld_article = obj
            break
    og: dict = {}
    for o in meta.get("opengraph") or []:
        og.update({k: v for k, v in o.items() if isinstance(v, (str, list))})

    if ld_article:
        pd.title = _name(ld_article.get("headline")) or _name(ld_article.get("name"))
        pd.author = _name(ld_article.get("author"))
        pd.section = _name(ld_article.get("articleSection"))
        pd.tags = _keywords(ld_article.get("keywords"))
        pd.thumbnail_url = _image(ld_article.get("image")) or _image(ld_article.get("thumbnailUrl"))
        pd.published_at = parse_dt(ld_article.get("datePublished"))
        pd.modified_at = parse_dt(ld_article.get("dateModified"))
        pd.excerpt = _name(ld_article.get("description"))

    pd.title = pd.title or _name(og.get("og:title"))
    pd.thumbnail_url = pd.thumbnail_url or _image(og.get("og:image"))
    pd.excerpt = pd.excerpt or _name(og.get("og:description"))
    pd.published_at = pd.published_at or parse_dt(og.get("article:published_time"))
    pd.modified_at = pd.modified_at or parse_dt(og.get("article:modified_time")) or parse_dt(og.get("og:updated_time"))
    pd.section = pd.section or _name(og.get("article:section"))
    if not pd.tags:
        tag = og.get("article:tag")
        pd.tags = _keywords(tag) if isinstance(tag, (str, list)) else []

    # 2. Trafilatura metadata as a last resort
    tmeta = None
    try:
        tmeta = trafilatura.extract_metadata(html_text, default_url=url)
    except Exception:  # noqa: BLE001
        pass
    if tmeta is not None:
        pd.title = pd.title or tmeta.title
        pd.author = pd.author or tmeta.author
        pd.published_at = pd.published_at or parse_dt(tmeta.date)
        pd.excerpt = pd.excerpt or tmeta.description
        if not pd.tags and tmeta.tags:
            pd.tags = list(tmeta.tags)
        if not pd.section and tmeta.categories:
            pd.section = tmeta.categories[0]
        pd.canonical_url = tmeta.url

    # 3. Main text → words, paragraph hashes, content hash
    body = None
    try:
        body = trafilatura.extract(
            html_text, url=url, include_comments=False, include_tables=True, favor_precision=True
        )
    except Exception:  # noqa: BLE001
        pass
    if body:
        paras = [_norm_para(p) for p in body.split("\n")]
        paras = [p for p in paras if len(p) >= _MIN_PARA_CHARS]
        pd.paragraph_hashes = [_short_hash(p) for p in paras]
        pd.word_count = len(body.split())
        pd.content_hash = hashlib.sha256("\n".join(paras).encode("utf-8")).hexdigest()
        if not pd.excerpt and paras:
            pd.excerpt = body.strip().split("\n")[0][:300]

    # 4. DOM-level signals inside the article body
    try:
        doc = lxml_html.fromstring(html_text)
        scope = doc.xpath("//article") or doc.xpath("//main") or [doc]
        art = max(scope, key=lambda e: len(e.text_content()))
        pd.headings = [h for h in (" ".join(x.text_content().split()) for x in art.iter("h2")) if h][:40]
        pd.image_count = sum(1 for _ in art.iter("img"))
        srcs = [el.get("src") or el.get("data-src") or "" for el in art.iter("iframe")]
        srcs += [el.get("href") or "" for el in art.iter("a")]
        srcs += [el.get("videoid") or "" for el in art.iter("lite-youtube")]
        ids: list[str] = []
        for s in srcs:
            m = _YT_ID.search(s)
            if m:
                ids.append(m.group(1))
        ids += [el.get("videoid") for el in art.iter("lite-youtube") if el.get("videoid")]
        pd.youtube_ids = list(dict.fromkeys(ids))[:20]
        pd.affiliate_link_count = sum(1 for a in art.iter("a") if _AFFILIATE.search(a.get("href") or ""))
        if not pd.title:
            t = doc.findtext(".//title")
            pd.title = " ".join(t.split()) if t else None
    except (etree.ParserError, ValueError):
        pass

    if pd.excerpt:
        pd.excerpt = " ".join(pd.excerpt.split())[:400]
    if pd.author and len(pd.author) > 200:
        pd.author = pd.author[:200]
    pd.tags = list(dict.fromkeys(t for t in pd.tags if len(t) < 80))[:25]
    pd.content_type = classify_content_type(pd.title, url)
    return pd


@dataclass
class ChangeSummary:
    is_real_change: bool
    paragraphs_added: int = 0
    paragraphs_removed: int = 0
    headings_added: list[str] = field(default_factory=list)
    headings_removed: list[str] = field(default_factory=list)
    title_changed: bool = False
    word_delta: int = 0
    summary: str = ""


def compare_versions(
    *,
    old_hash: str | None,
    new_hash: str | None,
    old_paras: list[str] | None,
    new_paras: list[str] | None,
    old_headings: list[str] | None,
    new_headings: list[str] | None,
    old_title: str | None,
    new_title: str | None,
    old_words: int | None,
    new_words: int | None,
) -> ChangeSummary:
    """Decide whether a re-fetch is a *real* edit and describe it.

    A bumped lastmod alone isn't an update. We need the paragraph set or the
    title to have actually changed. Paragraphs under 60 chars are ignored
    when hashing (bylines, "Updated 5 min ago", share counts), which keeps
    dynamic page chrome from counting as an edit.
    """
    if not old_hash or not new_hash:
        return ChangeSummary(False)
    title_changed = bool(old_title and new_title and old_title.strip() != new_title.strip())
    if old_hash == new_hash and not title_changed:
        return ChangeSummary(False)
    o, n = set(old_paras or []), set(new_paras or [])
    added, removed = len(n - o), len(o - n)
    h_old, h_new = old_headings or [], new_headings or []
    h_added = [h for h in h_new if h not in h_old]
    h_removed = [h for h in h_old if h not in h_new]
    if not (added or removed or title_changed or h_added or h_removed):
        return ChangeSummary(False)
    delta = (new_words or 0) - (old_words or 0)
    parts = []
    if title_changed:
        parts.append("title changed")
    if delta:
        parts.append(f"{delta:+d} words")
    changed = max(added, removed)
    if changed:
        parts.append(f"{changed} paragraph{'s' if changed != 1 else ''} changed")
    if h_added:
        parts.append("new sections: " + "; ".join(h_added[:3]))
    if h_removed:
        parts.append("removed sections: " + "; ".join(h_removed[:3]))
    return ChangeSummary(
        True, added, removed, h_added, h_removed, title_changed, delta, ", ".join(parts) or "content edited"
    )
