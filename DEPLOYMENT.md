# Deploying TW-Labs Web Intel for free (Render + Supabase)

The full step-by-step guide, with checks and troubleshooting, is the
"TW-Labs Web Intel — Production Deployment Guide" doc. This is the short version.

```
Browser ──▶ Render static site "webintel" (dashboard; forwards /api/*) ──▶ Render "webintel-api" (FREE; API + tracker)
                                                                               │        └──▶ Supabase Postgres (FREE, Singapore)
cron-job.org ── GET /healthz every 10 min (keeps the free API awake) ──────────┘        └──▶ competitor sites every 15 min
```

| Piece | Where | Cost |
|---|---|---|
| Dashboard | Render static site | Free |
| API + tracker | Render web service, free instance, Singapore | Free (750 h/month covers one service 24/7) |
| Database | Supabase free project, Singapore, 500 MB | Free |
| Keep-awake ping | cron-job.org | Free |

Why not Vercel Hobby: Vercel's Hobby plan is non-commercial only, and Vercel counts any site built by a
paid employee as commercial. `vercel.json` stays in the repo for if you move to Vercel Pro later.

## 1. GitHub
Private repo `tw-labs-web-intel`, then in this folder:
```powershell
git init; git add .; git commit -m "Web Intel phase 1"
git branch -M main
git remote add origin https://github.com/<account>/tw-labs-web-intel.git
git push -u origin main
```

## 2. Supabase (database)
1. supabase.com → New project → region **Southeast Asia (Singapore)** → set a database password
   (letters and digits only avoids URL-escaping trouble).
2. Project → **Connect** → copy the **Session pooler** URI (port 5432, host `…pooler.supabase.com`).
   Not "Direct connection" — that's IPv6, which Render can't reach.
3. Put your password in place of `[YOUR-PASSWORD]` and add `?sslmode=require` at the end.

## 3. Render (backend + dashboard)
1. **New → Blueprint** → connect GitHub → pick the repo (`render.yaml`, no card needed).
2. Paste the Supabase URL as `DATABASE_URL`. **Deploy Blueprint**.
3. `webintel-api` logs: `Running upgrade -> 0001`, `embedded worker started`, `Application startup complete`.
4. `https://webintel-api.onrender.com/healthz` → `{"ok":true}`. If Render gave the API a different URL,
   fix the two `destination:` lines under `webintel` in `render.yaml`, commit, push.
5. Open the `webintel` static site URL → the Live Feed.

## 4. Keep the API awake (required on the free plan)
cron-job.org → free account → Create cronjob → URL `https://<api-url>/healthz` → every **10 minutes** →
enable "notify on failure". Without this the API sleeps after 15 minutes and tracking stops.

## 5. Go-live checks
- Static site URL opens the Live Feed; sidebar Tracker = **Running** after ~2 minutes.
- Add techwiser.com ("This is our site") + competitors in **Sources**; each reaches **Healthy**.
- cron-job.org history shows successful 200 responses every 10 minutes.

## Free-plan limits to know
- No login: anyone with the link can use it. Share it only inside the team.
- Render may restart the free API at any time; tracking resumes on its own within a minute.
- No Render Shell on free; bulk-add sites from your PC: set `DATABASE_URL` to the Supabase URL in
  `backend/.env`, then `python scripts\add_sites.py sites.example.json`.
- Supabase free has no automatic backups and 500 MB. `RETENTION_DAYS=180` deletes articles older than
  6 months daily to stay well under it. Export a backup monthly (guide → Backups).
- If the free API ever runs out of the 750 monthly hours (only if you add other free services), it's
  suspended until the 1st.

## Upgrading to paid later (~$13/month, always on, backups)
Use `render.paid.yaml` (rename it to `render.yaml`) — see the guide's upgrade section.
