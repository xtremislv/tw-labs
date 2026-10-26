# TW-Labs Web Intel

Competitor **website and article** tracker for TechWiser. It's the sister app to the TW-Labs YouTube/Instagram dashboard, with the same look but a separate codebase, database and hosting.

**Phase 1: Article Tracker**

- Add a competitor site by pasting its address. Web Intel finds its WordPress API, Google News sitemap, RSS feed and full sitemap by itself, then imports the last 30 days.
- Every 15 minutes it checks each site's fastest feed **and** opens the sitemap index, reads every child sitemap carrying the latest date (posts, reviews, deals — any post type) and takes every article in them. Every 6 hours it walks the wider sitemap to catch anything missed.
- Every article is read once for author, category, tags, word count, H2 outline, images, YouTube embeds, affiliate links and content type (news / review / how-to / listicle / comparison / deal).
- An article is marked **Updated** only when its text actually changed, not when a site just bumps its "last modified" date. Each edit is saved with a summary such as `+120 words, 2 paragraphs changed, new sections: Price in India`.
- The **Live Feed** has filters for site, cohort, date range, New/Updated, type, category, author, word count, YouTube embed and affiliate links. It also has search (Ctrl+K), grid/list view, CSV export, shareable URLs, saved views and unread markers.
- **Article drawer:** edit history, "also covered by" other sites, outline, embeds and a "Copy brief" button.
- **Sources page:** add, pause or remove sites, assign cohorts, see feed health, run "Check now" or "Re-scan feeds", and view a log of recent runs.

**Phase 3: YouTube** (the TW-Labs tracker, ported)

- Add a competitor channel by @handle, URL or channel id, and optionally link it to its website.
- Each video is compared with the channel's trailing average and median (last 10 videos of the same format), so a **2.0x** badge means twice the usual views. Long-form and Shorts never mix.
- **Velocity:** views captured 1, 3 and 6 hours after upload, against the channel's usual pace at the same age.
- **SponsorBlock** flags sponsored segments. A Sponsored filter chip works like TW-Labs.
- Same filters as TW-Labs: channels, date range, min views, format, Avg/Median, sort by overperformance, views, newest, engagement or early velocity, grid/list.
- **Embed matching:** each video shows how many tracked articles embed it; the article drawer shows tracked videos with their stats.
- **Community posts** (text, polls, images) via Apify, once a day.
- Uses about 3 API units per channel per day out of the free 10,000.

**Phase 4: Topic Radar, Shortlist and Alerts**

- **Topic Radar** groups headlines from different sites about the same story (no AI service needed). Each story shows how many sites covered it, how fast it spread, related videos on tracked channels, and a red **GAP** badge when techwiser.com hasn't covered it.
- **Shortlist:** a board (Ideas → Assigned → In progress → Published) for stories, videos, posts and articles picked with the ☆ button. Owner and notes on each card.
- **Alerts:** rules by keyword, site, content type, channel or overperformance ratio, sent to Slack and/or Telegram every 5 minutes. A daily digest goes out at 09:30 IST.
- **Benchmark (optional):** 28-day Search Console clicks/impressions/position and GA4 views for techwiser.com articles, shown in the article drawer.

Phase 2 (Site Analytics) is still marked "coming soon" in the sidebar.

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

## Deploy to production (free: Render + Supabase)

`render.yaml` deploys everything on Render's free plan: the API + tracker as a free web service, and the dashboard as a free static site that forwards `/api` to it. The database is a free Supabase project. A free cron-job.org ping keeps the API awake. Follow **DEPLOYMENT.md**. There is no login by default; setting `DASHBOARD_PASSWORD` turns one on. `render.paid.yaml` (about $13/month, always on, Render Postgres) and `vercel.json` (Vercel Pro) are there for upgrading later.

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
  youtube.py     YouTube Data API (httpx), baselines, velocity, SponsorBlock, Apify posts
  stories.py     Topic Radar: groups headlines into stories (IDF terms + brand guard)
  alerts.py      alert rules → Slack / Telegram, daily digest
  benchmark.py   Search Console + GA4 for our own site (service account)
  worker.py      APScheduler: poll 15 min, sweep 6 h, enrich 2 min, YouTube 06:00 IST,
                 velocity hourly, posts 07:00 IST, alerts 5 min, digest 09:30 IST
  routers/       sites, articles, youtube, insights (radar, shortlist, alerts), status
```

- **New vs Updated:** a moved `lastmod` or `modified` date only schedules a re-read. The re-read compares hashes of every substantial paragraph, the H2 list and the title, so pages whose timestamps change on every load don't show up as edited.
- **Edits on sites with no "modified" date** (plain RSS, news sitemaps): articles from the last 3 days are re-read every 6 hours anyway.
- **Initial 30-day import:** these articles are flagged `is_backfill`. They show in the feed under their real publish dates, but never get the "NEW" badge or count as unread.
- **Politeness:** respects robots.txt, waits at least 2 seconds between requests to a site, and stores metadata and paragraph hashes but never full article text.

## Tests

```bash
cd backend && pytest -q        # 40 tests (simulated sites, YouTube, Apify, Slack, Telegram), no network
pnpm run build                 # type-check + production build
```

## Folder notes

- `reference-tw-labs/` holds a read-only copy of the TW-Labs backend (and its original `src/`), used as the reference for the YouTube port. Nothing imports from it.
- The original TW-Labs project folder is never modified by this project.
