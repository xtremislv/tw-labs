"""An in-memory competitor website for tests: robots.txt, a sitemap index
with taxonomy + post + news children, an RSS feed, the WordPress REST API,
and article pages whose content and lastmod the test can change."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx

from app.fetcher import Fetcher

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


class FakeSite:
    def __init__(self, domain="gadgetnews.test", *, wordpress=True, news=True, rss=True):
        self.domain = domain
        self.wordpress, self.news, self.rss = wordpress, news, rss
        self.requests: list[str] = []
        self.articles: dict[str, dict] = {}
        for i, (slug, title, hours) in enumerate(
            [
                ("galaxy-s27-ultra-launched-in-india-price-specs", "Galaxy S27 Ultra launched in India: price, specs", 2),
                ("best-phones-under-30000-in-india", "Best phones under 30000 in India", 30),
                ("pixel-11-review-camera-king", "Pixel 11 review: camera king", 50),
                ("how-to-fix-wifi-not-working-on-android", "How to fix Wi-Fi not working on Android", 24 * 10),
                ("old-news-from-last-year-archive", "Old news from last year", 24 * 400),
            ]
        ):
            self.articles[slug] = {
                "title": title,
                "published": NOW - timedelta(hours=hours),
                "modified": NOW - timedelta(hours=hours),
                "paras": [f"Paragraph {j} of {title} with enough words to count as body text for the extractor to keep it around." for j in range(8)],
                "h2": ["Specifications", "Price in India"],
            }

    # ── helpers for tests ───────────────────────────────────────────────
    def url(self, slug: str) -> str:
        return f"https://{self.domain}/{slug}/"

    def edit(self, slug: str, *, add_para: str | None = None, title: str | None = None, bump_only=False, add_h2=None):
        a = self.articles[slug]
        a["modified"] = max(a["modified"], NOW) + timedelta(minutes=10)
        if bump_only:
            return
        if add_para:
            a["paras"].append(add_para)
        if title:
            a["title"] = title
        if add_h2:
            a["h2"].append(add_h2)

    def publish(self, slug: str, title: str, *, cpt: bool = False):
        """cpt=True: a custom post type (e.g. a review) that WordPress lists
        only in reviews-sitemap.xml — not in the REST API, RSS or news sitemap."""
        self.articles[slug] = {
            "cpt": cpt,
            "title": title,
            "published": NOW,
            "modified": NOW,
            "paras": [f"Fresh story body line {j} about {title} with enough words to be counted properly." for j in range(10)],
            "h2": ["What's new"],
        }

    def posts(self):
        return {k: v for k, v in self.articles.items() if not v.get("cpt")}

    def cpts(self):
        return {k: v for k, v in self.articles.items() if v.get("cpt")}

    # ── HTTP handler ────────────────────────────────────────────────────
    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        path = request.url.path
        host = request.url.host
        if host != self.domain:
            return httpx.Response(404)
        if path == "/robots.txt":
            return httpx.Response(200, text=f"User-agent: *\nDisallow: /wp-admin/\nSitemap: https://{self.domain}/sitemap_index.xml\n")
        if path == "/":
            return httpx.Response(200, html=(
                f'<html><head><title>Gadget News | Tech</title><meta property="og:site_name" content="Gadget News">'
                f'<link rel="icon" href="/fav.png">'
                + (f'<link rel="alternate" type="application/rss+xml" href="https://{self.domain}/feed/">' if self.rss else "")
                + "</head><body>"
                + "".join(f'<a href="{self.url(s)}">{a["title"]}</a>' for s, a in self.articles.items())
                + '<a href="/category/mobiles/">Mobiles</a></body></html>'
            ))
        if path == "/sitemap_index.xml":
            kids = ["category-sitemap.xml", "post-sitemap1.xml", "post-sitemap2.xml", "reviews-sitemap.xml"] + (["news-sitemap.xml"] if self.news else [])
            def lm(k):
                if k == "post-sitemap1.xml":
                    return NOW - timedelta(days=400)
                if k == "reviews-sitemap.xml":
                    return max((a["modified"] for a in self.cpts().values()), default=NOW - timedelta(days=30))
                if k == "post-sitemap2.xml":
                    return max(a["modified"] for a in self.posts().values())
                return NOW
            body = "".join(f"<sitemap><loc>https://{self.domain}/{k}</loc><lastmod>{iso(lm(k))}</lastmod></sitemap>" for k in kids)
            return httpx.Response(200, text=f'<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</sitemapindex>')
        if path in ("/post-sitemap2.xml", "/reviews-sitemap.xml"):
            src = self.posts() if path == "/post-sitemap2.xml" else self.cpts()
            body = "".join(f"<url><loc>{self.url(s)}</loc><lastmod>{iso(a['modified'])}</lastmod></url>" for s, a in src.items())
            return httpx.Response(200, text=f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>')
        if path in ("/post-sitemap1.xml", "/category-sitemap.xml"):
            return httpx.Response(200, text=f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://{self.domain}/category/mobiles/</loc></url></urlset>')
        if path == "/news-sitemap.xml" and self.news:
            recent = [(s, a) for s, a in self.posts().items() if NOW - a["published"] < timedelta(hours=48)]
            body = "".join(
                f"<url><loc>{self.url(s)}</loc><news:news><news:publication><news:name>GN</news:name><news:language>en</news:language></news:publication>"
                f"<news:publication_date>{iso(a['published'])}</news:publication_date><news:title>{a['title']}</news:title></news:news></url>"
                for s, a in recent
            )
            return httpx.Response(200, text=f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">{body}</urlset>')
        if path.rstrip("/") == "/feed" and self.rss:
            items = "".join(
                f"<item><title>{a['title']}</title><link>{self.url(s)}</link><pubDate>{a['published'].strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item>"
                for s, a in self.posts().items()
            )
            return httpx.Response(200, text=f'<?xml version="1.0"?><rss version="2.0"><channel><title>GN</title>{items}</channel></rss>')
        if path == "/wp-json/wp/v2/posts":
            if not self.wordpress:
                return httpx.Response(404, json={"code": "rest_no_route"})
            posts = sorted(self.posts().items(), key=lambda kv: kv[1]["modified"], reverse=True)
            return httpx.Response(200, text=json.dumps([
                {"link": self.url(s), "date_gmt": a["published"].strftime("%Y-%m-%dT%H:%M:%S"),
                 "modified_gmt": a["modified"].strftime("%Y-%m-%dT%H:%M:%S"), "title": {"rendered": a["title"].replace("&", "&#038;")}}
                for s, a in posts
            ]))
        slug = path.strip("/")
        if slug in self.articles:
            a = self.articles[slug]
            ld = {"@context": "https://schema.org", "@graph": [{"@type": "WebPage"}, {
                "@type": "NewsArticle", "headline": a["title"], "datePublished": iso(a["published"]),
                "dateModified": iso(a["modified"]), "author": {"@type": "Person", "name": "Riya Sharma"},
                "articleSection": "Mobiles", "keywords": "samsung, android", "image": {"url": f"https://{self.domain}/img/{slug}.jpg"},
                "description": f"Summary of {a['title']}"}]}
            body = "".join(f"<h2>{h}</h2>" for h in a["h2"]) + "".join(f"<p>{p}</p>" for p in a["paras"])
            body += '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe><a href="https://amzn.to/abc">Buy</a><img src="/x.jpg">'
            return httpx.Response(200, html=(
                f'<html><head><title>{a["title"]}</title><script type="application/ld+json">{json.dumps(ld)}</script></head>'
                f'<body><nav>Menu Home Phones Laptops</nav><article><h1>{a["title"]}</h1>{body}</article><footer>© GN</footer></body></html>'
            ))
        return httpx.Response(404, text="not found")

    def fetcher(self) -> Fetcher:
        return Fetcher(client=httpx.Client(transport=httpx.MockTransport(self.handler), follow_redirects=True))
