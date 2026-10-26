"""Try Web Intel's discovery + parsing against a real site, without touching
the database. Use it to see what a competitor exposes before adding it, or to
debug a site that shows "Check sources".

    python scripts/check_site.py beebom.com
    python scripts/check_site.py 91mobiles.com --articles 3
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.discovery import discover  # noqa: E402
from app.extract import extract_page  # noqa: E402
from app.fetcher import Fetcher  # noqa: E402
from app.parsers import is_feed, parse_feed, parse_homepage_links, parse_sitemap, parse_wp_posts  # noqa: E402
from app.urlnorm import normalize_domain  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("site")
    ap.add_argument("--articles", type=int, default=2, help="how many articles to fetch and parse")
    args = ap.parse_args()
    domain = normalize_domain(args.site)
    f = Fetcher()
    print(f"\n== Discovering feeds for {domain} (2 s between requests, ~30 s) ==")
    res = discover(f, domain)
    print(f"Name: {res.name}   Home: {res.home_url}   Icon: {res.icon_url}")
    for line in res.log:
        print("  ·", line)
    if not res.sources:
        print("\nNo sources found. The site may block automated requests from this network.")
        return
    print("\nSources (fastest first):")
    for s in res.sources:
        print(f"  [{s.priority:>2}] {s.kind:<13} {s.url}")

    fast = next((s for s in res.sources if s.kind in ("wp_rest", "news_sitemap", "rss", "html")), None)
    if fast is None:
        return
    r = f.get(fast.url)
    if fast.kind == "wp_rest":
        items = parse_wp_posts(r.text)
    elif fast.kind == "rss" and is_feed(r.text):
        items = parse_feed(r.text)
    elif fast.kind == "html":
        items = parse_homepage_links(r.text, fast.url, domain)
    else:
        items = parse_sitemap(r.content or r.text).urls
    print(f"\nLatest from the fast source ({fast.kind}): {len(items)} items")
    for c in items[:8]:
        print(f"  {c.published or c.lastmod or '':<26} {c.title or ''}\n    {c.url}")

    for c in items[: args.articles]:
        print(f"\n== Parsing {c.url} ==")
        page = f.get(c.url)
        if not page.ok:
            print("  HTTP", page.status)
            continue
        pd = extract_page(page.text, page.url)
        for k in ("title", "author", "section", "content_type", "published_at", "modified_at", "word_count",
                  "image_count", "youtube_ids", "affiliate_link_count", "thumbnail_url"):
            print(f"  {k:<21} {getattr(pd, k)}")
        print(f"  {'headings':<21} {pd.headings[:6]}")
        print(f"  {'tags':<21} {pd.tags[:8]}")


if __name__ == "__main__":
    main()
