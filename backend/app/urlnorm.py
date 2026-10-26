"""URL canonicalisation and "is this an article?" heuristics."""
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_", "ref", "amp", "igshid", "yclid", "_ga")

# Paths that are listings / taxonomy / utility pages, never articles.
_NON_ARTICLE = re.compile(
    r"/(tag|tags|category|categories|author|authors|page|search|topic|topics|"
    r"feed|wp-json|wp-admin|wp-content|wp-includes|login|register|cart|"
    r"checkout|account|about|about-us|contact|contact-us|privacy|privacy-policy|"
    r"terms|disclaimer|advertise|careers|sitemap)(/|$)",
    re.I,
)
_STATIC_EXT = re.compile(r"\.(jpg|jpeg|png|gif|webp|svg|pdf|zip|mp4|mp3|css|js|xml|txt|ico)$", re.I)


def normalize_domain(value: str) -> str:
    """'https://www.Example.com/foo' → 'example.com'."""
    v = value.strip().lower()
    if "://" not in v:
        v = "https://" + v
    host = urlsplit(v).hostname or ""
    return host[4:] if host.startswith("www.") else host


def same_site(url: str, domain: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == domain or host.endswith("." + domain)


def canonicalize(url: str) -> str:
    """Strip tracking params, fragments, AMP suffixes and trailing slashes so
    one article never shows up under two URLs."""
    parts = urlsplit(url.strip())
    scheme = "https" if parts.scheme in ("http", "https", "") else parts.scheme
    host = (parts.hostname or "").lower()
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    path = parts.path or "/"
    path = re.sub(r"/amp/?$", "/", path)
    path = re.sub(r"\.amp(\.html)?$", r"\1", path)
    if path.startswith("/amp/"):
        path = path[4:]
    path = re.sub(r"/{2,}", "/", path)
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING_PREFIXES)
    ]
    return urlunsplit((scheme, host, path, urlencode(query), ""))


def looks_like_article(url: str, domain: str) -> bool:
    if not same_site(url, domain):
        return False
    path = urlsplit(url).path
    if path in ("", "/") or _STATIC_EXT.search(path) or _NON_ARTICLE.search(path):
        return False
    # Article slugs almost always contain a hyphenated phrase or a long
    # numeric id; bare section pages like /mobiles or /reviews don't.
    last = [seg for seg in path.split("/") if seg]
    if not last:
        return False
    slug = last[-1]
    if "-" in slug and len(slug) >= 12:
        return True
    if re.search(r"\d{5,}", path):
        return True
    return len(last) >= 2 and "-" in slug
