"""Topic Radar: group recent headlines from different sites into "stories".

Deliberately lightweight (no ML model, so it fits Render's free 512 MB):

1. Tokenise each headline; drop stop-words and generic tech words.
2. Weight every token by rarity across the window (IDF), so "s27", "pixel",
   "11a" count far more than "phone" or "launch".
3. Candidates only come from shared rare or model-like tokens (inverted
   index), so a week of ~5,000 headlines clusters in well under a second.
4. Two headlines join the same story when they were published within 48 h of
   each other and their shared tokens carry at least 55% of the lighter
   headline's weight, including at least one model-like token (2+ characters
   with a digit, e.g. "s27", "11a", "18") or two rare words.
5. Headlines naming different brands (Pixel vs iPhone) never merge, and each
   headline is compared with a story's first few articles only (no chaining).
   A story with no techwiser.com article is a **gap**.
"""
from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from .models import Article, Channel, Site, Video
from .timeutil import as_utc, utcnow

STOP = set("""
a an and are as at be been but by can do does for from get gets got has have how i in into is it its just know
latest more most new news now of on or our out over own price prices rs inr review reviews launched launch launches
launching official officially specs specifications features feature should so than that the their them then there
these this those to top up vs versus was we what when where which who why will with without you your here all
best buy deal deals sale offer offers off discount check out full list every first look hands-on video watch
india indian global update updates updated report reports reportedly leak leaks leaked teased tease tips
revealed reveal ahead date details detail confirmed confirms coming soon available availability know
""".split())
_TOKEN = re.compile(r"[a-z0-9][a-z0-9+]*")
MIN_SHARE = 0.55
WINDOW_PAIR_HOURS = 48
_cache: dict[tuple, tuple[float, list]] = {}


def tokens(title: str | None) -> set[str]:
    out = set()
    for t in _TOKEN.findall((title or "").lower().replace("’", "'")):
        if t in STOP or (len(t) < 3 and not any(c.isdigit() for c in t)):
            continue
        out.add(t)
    return out


@dataclass
class StoryArticle:
    article: Article
    toks: set[str]
    when: datetime


@dataclass
class Story:
    key: str
    label: str
    members: list[StoryArticle] = field(default_factory=list)
    top_terms: list[str] = field(default_factory=list)

    @property
    def sites(self) -> set[int]:
        return {m.article.site_id for m in self.members}

    @property
    def first_at(self) -> datetime:
        return min(m.when for m in self.members)

    @property
    def last_at(self) -> datetime:
        return max(m.when for m in self.members)



# Brand words, folded to one name per company. Two headlines that each name a
# brand, but no brand in common, are never the same story ("Pixel 11" news vs
# "iPhone 11" news) — the commonest false merge in tech headlines.
_BRANDS = {
    "samsung": "samsung", "galaxy": "samsung", "apple": "apple", "iphone": "apple", "ipad": "apple",
    "macbook": "apple", "ios": "apple", "watchos": "apple", "macos": "apple", "airpods": "apple",
    "google": "google", "pixel": "google", "android": "google", "gemini": "google", "oneplus": "oneplus",
    "xiaomi": "xiaomi", "redmi": "xiaomi", "poco": "xiaomi", "hyperos": "xiaomi", "vivo": "vivo", "iqoo": "vivo",
    "oppo": "oppo", "coloros": "oppo", "realme": "realme", "nothing": "nothing", "cmf": "nothing",
    "motorola": "motorola", "moto": "motorola", "nokia": "nokia", "honor": "honor", "huawei": "huawei",
    "asus": "asus", "rog": "asus", "zenfone": "asus", "lenovo": "lenovo", "legion": "lenovo", "infinix": "infinix",
    "tecno": "tecno", "itel": "itel", "lava": "lava", "sony": "sony", "playstation": "sony", "ps5": "sony",
    "boat": "boat", "noise": "noise", "jbl": "jbl", "dell": "dell", "alienware": "dell", "acer": "acer",
    "msi": "msi", "qualcomm": "qualcomm", "snapdragon": "qualcomm", "mediatek": "mediatek", "dimensity": "mediatek",
    "intel": "intel", "amd": "amd", "ryzen": "amd", "nvidia": "nvidia", "geforce": "nvidia", "rtx": "nvidia",
    "microsoft": "microsoft", "windows": "microsoft", "xbox": "microsoft", "copilot": "microsoft",
    "whatsapp": "meta", "instagram": "meta", "facebook": "meta", "meta": "meta", "jio": "jio", "airtel": "airtel",
    "bsnl": "bsnl", "netflix": "netflix", "amazon": "amazon", "alexa": "amazon", "kindle": "amazon",
    "flipkart": "flipkart", "tesla": "tesla", "openai": "openai", "chatgpt": "openai", "anthropic": "anthropic",
    "claude": "anthropic", "garmin": "garmin", "fitbit": "google", "lg": "lg", "tcl": "tcl", "hisense": "hisense",
}
LEADERS = 3  # a headline is compared with a story's first few articles only


def brands_of(toks: set[str]) -> set[str]:
    return {_BRANDS[t] for t in toks if t in _BRANDS}


def _similar(a: StoryArticle, b: StoryArticle, idf: dict[str, float], df: dict[str, int], rare_cut: int,
             wa: float, wb: float) -> float:
    if abs(a.when - b.when) > timedelta(hours=WINDOW_PAIR_HOURS):
        return 0.0
    ba, bb = brands_of(a.toks), brands_of(b.toks)
    if ba and bb and not (ba & bb):
        return 0.0
    shared = a.toks & b.toks
    # A model number alone ("18", "14a") isn't enough — at least two shared
    # terms, one of them model-like (2+ chars with a digit) or two rare words.
    strong = [t for t in shared if len(t) >= 2 and any(c.isdigit() for c in t)]
    rare = [t for t in shared if df[t] <= rare_cut]
    if len(shared) < 2 or not (strong or len(rare) >= 2):
        return 0.0
    return sum(idf[t] for t in shared) / min(wa, wb)


def cluster(items: list[StoryArticle]) -> list[list[int]]:
    """Leader clustering in time order: each headline joins the story whose
    first few articles it matches best, else starts a new story. Comparing
    against a story's leaders (not any member) stops A~B~C chains from
    merging unrelated headlines."""
    n = len(items)
    if n == 0:
        return []
    df: dict[str, int] = {}
    for it in items:
        for t in it.toks:
            df[t] = df.get(t, 0) + 1
    idf = {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}
    # Tokens in more than ~3% of headlines (min 10) are too common to find
    # candidate stories on their own; they still count towards the score.
    rare_cut = max(10, int(n * 0.03))
    weight = [sum(idf[t] for t in it.toks) or 1.0 for it in items]
    order = sorted(range(n), key=lambda i: items[i].when)
    stories: list[list[int]] = []
    index: dict[str, set[int]] = {}  # rare token -> story ids whose leaders contain it
    for i in order:
        it = items[i]
        cands: set[int] = set()
        for t in it.toks:
            if df[t] <= rare_cut or any(c.isdigit() for c in t):
                cands |= index.get(t, set())
        best, best_score = None, MIN_SHARE
        for sid in cands:
            score = max(_similar(it, items[j], idf, df, rare_cut, weight[i], weight[j]) for j in stories[sid][:LEADERS])
            if score >= best_score:
                best, best_score = sid, score
        if best is None:
            best = len(stories)
            stories.append([])
        stories[best].append(i)
        if len(stories[best]) <= LEADERS:
            for t in it.toks:
                index.setdefault(t, set()).add(best)
    # Second pass: a headline processed before the articles that would have
    # linked it to a story (e.g. a site that published first, in different
    # words) gets one more try against every story's leaders.
    for sid, members in enumerate(stories):
        if len(members) != 1:
            continue
        i = members[0]
        it = items[i]
        cands: set[int] = set()
        for t in it.toks:
            if df[t] <= rare_cut or any(c.isdigit() for c in t):
                cands |= index.get(t, set())
        best, best_score = None, MIN_SHARE
        for other in cands - {sid}:
            if len(stories[other]) < 2:
                continue
            score = max(_similar(it, items[j], idf, df, rare_cut, weight[i], weight[j]) for j in stories[other][:LEADERS])
            if score >= best_score:
                best, best_score = other, score
        if best is not None:
            stories[best].append(i)
            stories[sid] = []
    return [st for st in stories if st]


def _label(members: list[StoryArticle]) -> tuple[str, list[str]]:
    counts: dict[str, int] = {}
    for m in members:
        for t in m.toks:
            counts[t] = counts.get(t, 0) + 1
    common = [t for t, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])) if c >= max(2, len(members) // 2)]
    # the headline sharing the most common terms reads best as the label
    best = max(members, key=lambda m: (len(m.toks & set(common)), -len(m.article.title or "")))
    return best.article.title or "", common[:6]


def build_stories(db: Session, *, hours: int = 48, min_sites: int = 2, cohort: str | None = None) -> list[dict]:
    key = (hours, min_sites, cohort)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 120:
        return hit[1]
    since = utcnow() - timedelta(hours=hours)
    q = (
        select(Article)
        .join(Site)
        .options(selectinload(Article.site))
        .where(
            Article.enrich_status.in_(("ok", "pending", "recheck")),
            Article.title.is_not(None),
            or_(Article.published_at >= since, Article.first_seen_at >= since),
            Site.paused.is_(False),
        )
    )
    if cohort:
        q = q.where(or_(Site.cohort == cohort, Site.is_own_site.is_(True)))
    items: list[StoryArticle] = []
    for a in db.scalars(q):
        toks = tokens(a.title)
        if len(toks) >= 2:
            items.append(StoryArticle(a, toks, as_utc(a.published_at) or as_utc(a.first_seen_at)))
    own_sites = set(db.scalars(select(Site.id).where(Site.is_own_site.is_(True))))
    stories: list[dict] = []
    for group in cluster(items):
        members = [items[i] for i in group]
        site_ids = {m.article.site_id for m in members}
        competitor_sites = site_ids - own_sites
        if len(site_ids) < min_sites:
            continue
        label, terms = _label(members)
        members.sort(key=lambda m: m.when)
        first = members[0].when
        # time for the story to reach its 3rd site ("spread speed")
        reach: list[datetime] = []
        seen_sites: set[int] = set()
        for m in members:
            if m.article.site_id not in seen_sites:
                seen_sites.add(m.article.site_id)
                reach.append(m.when)
        hours_to_3 = (reach[2] - reach[0]).total_seconds() / 3600 if len(reach) >= 3 else None
        covered_by_us = bool(site_ids & own_sites)
        age_h = max(1.0, (utcnow() - first).total_seconds() / 3600)
        score = len(competitor_sites) * 10 + len(members) + 24 / age_h
        stories.append({
            "key": f"{members[0].article.id}-{len(members)}",
            "label": label,
            "terms": terms,
            "site_count": len(site_ids),
            "competitor_site_count": len(competitor_sites),
            "article_count": len(members),
            "first_at": first,
            "last_at": members[-1].when,
            "hours_to_3_sites": round(hours_to_3, 1) if hours_to_3 is not None else None,
            "covered_by_us": covered_by_us if own_sites else None,
            "gap": (not covered_by_us) if own_sites else None,
            "score": round(score, 2),
            "article_ids": [m.article.id for m in members],
            "sites": sorted({(m.article.site.id, m.article.site.name, m.article.site.icon_url, m.article.site.is_own_site) for m in members}, key=lambda s: s[1]),
        })
    stories.sort(key=lambda s: -s["score"])
    _cache[key] = (time.time(), stories)
    return stories


def related_videos(db: Session, terms: list[str], since: datetime, limit: int = 6) -> list[Video]:
    """Tracked YouTube videos whose titles share the story's key terms."""
    strong = [t for t in terms if len(t) >= 2 and any(c.isdigit() for c in t)] or terms[:2]
    if not strong:
        return []
    cands = db.scalars(
        select(Video).join(Channel).options(selectinload(Video.channel)).where(Video.published_at >= since - timedelta(days=1))
    )
    out = []
    for v in cands:
        vt = tokens(v.title)
        if all(t in vt for t in strong[:2]) and len(vt & set(terms)) >= min(2, len(terms)):
            out.append(v)
    out.sort(key=lambda v: -(v.views or 0))
    return out[:limit]


def clear_cache() -> None:
    _cache.clear()
