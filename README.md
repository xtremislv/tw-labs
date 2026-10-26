# TW-Labs Web Intel

Competitor **website and article** tracker for TechWiser. It's the sister app to the TW-Labs YouTube/Instagram dashboard, with the same look but a separate codebase, database and hosting.

**Phase 1 (this build): Article Tracker MVP**

- Add a competitor site by pasting its address. Web Intel finds its WordPress API, Google News sitemap, RSS feed and full sitemap by itself, then imports the last 30 days.
- Every 15 minutes it checks each site's fastest feed. Every 6 hours it walks the sitemap to catch anything missed.
- Every article is read once for author, category, tags, word count, H2 outline, images, YouTube embeds, affiliate links and content type (news / review / how-to / listicle / comparison / deal).
- An article is marked **Updated** only when its text actually changed, not when a site just bumps its "last modified" date. Each edit is saved with a summary such as `+120 words, 2 paragraphs changed, new sections: Price in India`.
- The **Live Feed** has filters for site, cohort, date range, New/Updated, type, category, author, word count, YouTube embed and affiliate links. It also has search (Ctrl+K), grid/list view, CSV export, shareable URLs, saved views and unread markers.
- **Article drawer:** edit history, "also covered by" other sites, outline, embeds and a "Copy brief" button.
- **Sources page:** add, pause or remove sites, assign cohorts, see feed health, run "Check now" or "Re-scan feeds", and view a log of recent runs.

Phase 2 (Site Analytics), Phase 3 (YouTube) and Phase 4 (Topic Radar and alerts) show as "coming soon" in the sidebar. See the roadmap doc.

## Run it on your computer (Windows, no Docker)

You need **Python 3.10+** and **Node 20+** (with pnpm: `npm i -g pnpm`).

**1. Backend + worker** (two terminals, both inside `backend\`):

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env          # defaults to a local SQLite file, fine for trying it
alembic upgrade head

# Optional: check what a real site exposes before adding it
python scripts\check_site.py beebom.com

uvicorn app.main:app --port 8000
```

Second terminal:

```powershell
cd backend
.venv\Scripts\activate
python -m app.worker
```

**2. Dashboard** (third terminal, project root):

```powershell
pnpm install
pnpm dev
```

Open **http://localhost:8443**, go to **Sources** and add your first site. Mark techwiser.com as "This is our site". Articles start appearing within a few minutes as the worker imports them, about one request every 2 seconds per site.

To add many sites at once, edit `backend/sites.example.json` and run `python scripts\add_sites.py sites.example.json`.

## Deploy to production (Vercel + Render)

`render.yaml` (backend + Postgres on Render, Singapore) and `vercel.json` (dashboard on Vercel, proxying `/api` to Render) are ready. Follow **DEPLOYMENT.md**. There's no login by default (the link is shared only within the team); setting `DASHBOARD_PASSWORD` on Render switches a team-password login on.

## Run it on a server instead (Docker Compose)

```bash
cp .env.example .env               # set POSTGRES_PASSWORD
docker compose up -d --build
```

The dashboard is at http://localhost:8080 and the API docs are at http://localhost:8000/docs. The stack runs Postgres, the API, the always-on worker and nginx. A $5–12/month VPS is enough. Put Cloudflare Access in front for team login.

## How it works

```
backend/app/
  discovery.py   finds a site's feeds: WP REST > news sitemap > RSS > sitemap > homepage scan
  fetcher.py     one HTTP client: 2 s per-domain delay, ETag/If-Modified-Since, robots.txt
  parsers.py     sitemap / RSS / WP JSON / homepage → candidate URLs (pure functions)
  tracker.py     poll → ingest → enrich → detect real edits (ArticleVersion)
  extract.py     page → metadata (JSON-LD → OpenGraph → trafilatura), content-type, edit diff
  worker.py      APScheduler: poll 15 min, sweep 6 h, enrich 2 min, API requests 20 s
  routers/       sites, articles (all filtering server-side), status/refresh
```

- **New vs Updated:** a moved `lastmod` or `modified` date only schedules a re-read. The re-read compares hashes of every substantial paragraph, the H2 list and the title, so pages whose timestamps change on every load don't show up as edited.
- **Edits on sites with no "modified" date** (plain RSS, news sitemaps): articles from the last 3 days are re-read every 6 hours anyway.
- **Initial 30-day import:** these articles are flagged `is_backfill`. They show in the feed under their real publish dates, but never get the "NEW" badge or count as unread.
- **Politeness:** respects robots.txt, waits at least 2 seconds between requests to a site, and stores metadata and paragraph hashes but never full article text.

## Tests

```bash
cd backend && pytest -q        # 25 tests (simulated competitor site + optional login), no network
pnpm run build                 # type-check + production build
```

## Folder notes

- `reference-tw-labs/` holds a read-only copy of the TW-Labs backend (and its original `src/`). It's the starting point for porting the YouTube module in Phase 3. Nothing imports from it.
- The original TW-Labs project folder is never modified by this project.
