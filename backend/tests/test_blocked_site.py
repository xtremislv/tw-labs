"""A site that blocks every automated request (Cloudflare 403) is still
tracked through search-engine news feeds."""
from datetime import timedelta

import httpx
from sqlalchemy import select

from app import tracker
from app.discovery import discover
from app.fetcher import Fetcher
from app.models import Article, Site
from tests.fakesite import NOW

D = "destructoid.test"
RFC = (NOW - timedelta(hours=2)).strftime("%a, %d %b %Y %H:%M:%S GMT")
BING = (f'<?xml version="1.0"?><rss version="2.0"><channel><title>Bing</title>'
        f'<item><title>Metroid Prime 5 review: a return to form</title>'
        f'<link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;aid=&amp;url=https%3a%2f%2fwww.{D}%2fmetroid-prime-5-review%2f&amp;c=1&amp;mkt=en-in</link>'
        f'<pubDate>{RFC}</pubDate></item>'
        f'<item><title>Unrelated</title><link>http://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fother.test%2fx%2f</link></item>'
        f'</channel></rss>')
GOOGLE = (f'<?xml version="1.0"?><rss version="2.0"><channel><title>Google News</title>'
          f'<item><title>Zelda remake dated for March - Destructoid</title>'
          f'<link>https://news.google.com/rss/articles/CBMiABC?oc=5</link><pubDate>{RFC}</pubDate>'
          f'<source url="https://www.{D}">Destructoid</source></item></channel></rss>')


def handler(req: httpx.Request) -> httpx.Response:
    host = req.url.host
    if host.endswith(D):
        return httpx.Response(403, headers={"server": "cloudflare", "cf-mitigated": "challenge"}, text="Just a moment...")
    if host == "www.bing.com" and req.url.path == "/news/search":
        return httpx.Response(200, text=BING)
    if host == "news.google.com" and req.url.path == "/rss/search":
        return httpx.Response(200, text=GOOGLE)
    return httpx.Response(404)


def _f():
    return Fetcher(client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True))


def test_blocked_site_falls_back_to_search_feeds(db, client):
    res = discover(_f(), D)
    assert any("Cloudflare" in line for line in res.log)
    assert [s.kind for s in res.sources] == ["search", "search"]
    site = Site(domain=D, name="Destructoid", home_url=f"https://{D}/")
    db.add(site)
    db.commit()
    tracker.apply_discovery(db, site, res)
    run = tracker.poll_site(db, _f(), site)
    assert run.ok and run.items_new == 2
    arts = {a.title: a for a in db.scalars(select(Article))}
    assert set(arts) == {"Metroid Prime 5 review: a return to form", "Zelda remake dated for March"}
    assert arts["Metroid Prime 5 review: a return to form"].url.endswith("metroid-prime-5-review")
    assert arts["Zelda remake dated for March"].enrich_status == "feed_only"
    assert client.get("/api/articles").json()["total"] == 2
