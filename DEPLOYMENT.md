# Deploying TW-Labs Web Intel (Vercel + Render)

The full step-by-step guide, with costs, checks and troubleshooting, is the
"TW-Labs Web Intel — Production Deployment Guide" doc. This is the short version.

```
Browser ──HTTPS──▶ Vercel (dashboard + /api/* proxy) ──▶ Render webintel-api (FastAPI + tracker, Singapore)
                                                              │                └──private──▶ Render webintel-db (Postgres 16)
                                                              └── every 15 min ──▶ competitor sites
```

| Piece | Plan | Cost/month |
|---|---|---|
| Vercel (dashboard) | Pro for company use (Hobby is non-commercial only) | $20 per developer seat |
| Render web service `webintel-api` | 0.5 CPU / 512 MB (free instances sleep → tracker would stop) | $7 |
| Render Postgres `webintel-db` | 0.1c-256mb, 1 GB disk | $6 |

## 1. GitHub
Create a **private** repo `tw-labs-web-intel`, then in this folder:
```powershell
git init; git add .; git commit -m "Web Intel phase 1"
git branch -M main
git remote add origin https://github.com/<account>/tw-labs-web-intel.git
git push -u origin main
```

## 2. Render (backend + database)
1. Add a payment card (Workspace → Billing).
2. **New → Blueprint** → connect GitHub → pick the repo. `render.yaml` creates `webintel-api` + `webintel-db` in Singapore.
3. Leave `CORS_ORIGINS` empty. **Deploy Blueprint**.
4. Logs should show `Running upgrade -> 0001`, `embedded worker started`, `Application startup complete`.
5. Check `<render-url>/healthz` → `{"ok":true}`.
6. If the URL isn't `https://webintel-api.onrender.com`, replace it in **both** `vercel.json` rewrites, commit, push.

## 3. Vercel (dashboard)
1. Add New → Project → import the repo. Keep the detected settings (Vite; `vercel.json` sets build/output/install). **No environment variables.**
2. Deploy and open the URL — the Live Feed opens directly (no login).

## 4. Go-live checks
- `<vercel-url>/healthz` OK; sidebar Tracker = **Running**.
- Add techwiser.com ("This is our site") + competitors in **Sources**; each reaches **Healthy**.
- Render database Access Control: no public IPs. Uptime monitor on `<vercel-url>/healthz`.

## Environment variables (Render → webintel-api → Environment)
`DATABASE_URL` (from Blueprint) ·
`EMBEDDED_WORKER=true` (keep `--workers 1`) · `PYTHON_VERSION=3.12.11` · tuning: see `backend/.env.example`.

## No login (by choice)
The dashboard has no login: anyone with the link can view it and add/delete sites. Share the link
only inside the team. To switch a team-password login on later, add `DASHBOARD_PASSWORD` and
`SESSION_SECRET` in Render → webintel-api → Environment — no code change needed.

## Updates & rollbacks
`git push` to `main` redeploys both. Render runs `alembic upgrade head` before switching traffic.
Roll back: Vercel → Deployments → Instant Rollback; Render → Events → Rollback (migrations are not undone).

## Free database alternative
Supabase free (Singapore): use the **Session pooler** URL (IPv4), remove the `databases:` block from
`render.yaml`, and set `DATABASE_URL` by hand. No automatic backups on the free plan.
