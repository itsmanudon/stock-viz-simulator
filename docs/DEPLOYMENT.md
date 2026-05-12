# StockViz — deployment

Production deploy of the StockViz monorepo. The two apps deploy to **different
hosts**:

| App           | Host    | What it runs                                       |
| ------------- | ------- | -------------------------------------------------- |
| `apps/web`    | Vercel  | Next.js 16 (App Router, NextAuth v5)               |
| `apps/api`    | Render  | FastAPI + Postgres + in-process APScheduler        |

The web app is reverse-proxied by Vercel; the API + Postgres are provisioned
together from `infra/render.yaml` as a Render Blueprint. Daily price + news
refreshes run **in-process** inside FastAPI via APScheduler
(`ENABLE_SCHEDULER=true`); there is no separate cron service in the
Blueprint because Render no longer offers a free plan for cron jobs.

```
Browser ──HTTPS──▶ Vercel (apps/web) ──HTTPS──▶ Render (apps/api) ──▶ Render Postgres
                                                       │
                                                       └─ APScheduler (in-process)
```

## Prerequisites

- A GitHub repo with this code pushed to `main` (Vercel and Render both pull from GitHub).
- A [Vercel](https://vercel.com) account.
- A [Render](https://render.com) account.
- Optional: an [Alpha Vantage](https://www.alphavantage.co/) key and a
  [Newsdata.io](https://newsdata.io/) key. Without them, ingest jobs run but
  short-circuit cleanly — the app still works, just with stale market data.
- Optional: a [Sentry](https://sentry.io) project for error monitoring.

## Secrets you'll generate up front

Generate these once and reuse the same values on both sides. **`AUTH_SECRET`
(web) and `NEXTAUTH_JWT_SECRET` (api) must be byte-identical** — the web app
signs JWTs with this, the API verifies them.

```bash
# AUTH_SECRET / NEXTAUTH_JWT_SECRET (same value)
openssl rand -base64 32

# INTERNAL_API_TOKEN (shared bearer for server-to-server)
openssl rand -hex 32
```

Save these to a password manager before you start — you'll paste them into
both Render and Vercel.

## 1. Deploy the API + database to Render

Render reads `infra/render.yaml` and provisions two resources in one shot:
Postgres 16 and the `stockviz-api` web service. (No separate cron job —
Render dropped the free cron plan; the daily refresh runs in-process via
APScheduler instead. See **Adding a cron safety net** below if you want to
re-introduce one on a paid plan.)

### 1a. Create the Blueprint

1. Render dashboard → **New + → Blueprint**.
2. Connect your GitHub account and select the StockViz repo.
3. Render parses `infra/render.yaml` and shows a preview. Confirm.

> **Note:** `infra/render.yaml` pins the deploy source via `repo:` and
> `branch: main`. If your fork lives at a different URL, edit those two
> values before importing the Blueprint.

After this step Render has created the resources but the API will fail to boot
because the `sync: false` env vars are still empty. Fix that next.

### 1b. Fill in the API env vars

Dashboard → **stockviz-api → Environment**. Set:

| Variable                | Value                                                              |
| ----------------------- | ------------------------------------------------------------------ |
| `CORS_ORIGINS`          | `https://<your-vercel-domain>` (you'll know this after step 2)     |
| `NEXTAUTH_JWT_SECRET`   | the `AUTH_SECRET` you generated above                              |
| `INTERNAL_API_TOKEN`    | the bearer token you generated above                               |
| `ALPHA_VANTAGE_KEY`     | your Alpha Vantage key (or leave blank to disable price ingest)    |
| `NEWSDATA_KEY`          | your Newsdata.io key (or leave blank to disable news ingest)       |
| `SENTRY_DSN`            | your Sentry DSN (or leave blank)                                   |

`DATABASE_URL`, `ENVIRONMENT`, `DEBUG`, and `ENABLE_SCHEDULER` are pinned by
the Blueprint; don't override them. `ENABLE_SCHEDULER=true` is what turns on
the in-process APScheduler — leave it on in production.

### 1c. Trigger a redeploy

Dashboard → **stockviz-api → Manual Deploy → Deploy latest commit**. The
Docker image runs `alembic upgrade head` before starting uvicorn (see
`apps/api/Dockerfile:48`), so migrations apply automatically on every deploy.

Once the deploy goes green, hit `https://<your-api>.onrender.com/health` —
should return `{"status": "ok"}`. OpenAPI docs at `/docs`.

### 1d. Seed the database (one-time)

The API boots with an empty `symbols` table. Open a shell into the service:

```bash
# Render dashboard → stockviz-api → Shell, or:
render shell stockviz-api
```

Inside the container:

```bash
python -m stockviz.cli seed       # populates the symbol list
python -m stockviz.cli backfill   # CSV → DB historical bars (slow, one-time)
python -m stockviz.cli metadata   # fills name / sector / industry per symbol
```

After this, the nightly cron and in-process scheduler keep data fresh.

## 2. Deploy the web app to Vercel

### 2a. Import the project

1. Vercel dashboard → **Add New → Project**.
2. Select the same GitHub repo.
3. **Root Directory:** `apps/web` (critical — Vercel needs this to find the
   right `vercel.json` and run the workspace-aware build).
4. **Framework Preset:** Next.js (auto-detected).

Build settings come from `apps/web/vercel.json` — don't override them. The
build command runs from the monorepo root and uses pnpm workspace filters.

### 2b. Set env vars

Vercel dashboard → **Project Settings → Environment Variables**. Add all of
these for **Production** (and **Preview**, if you want preview deploys to
work):

| Variable                              | Value                                                |
| ------------------------------------- | ---------------------------------------------------- |
| `API_URL`                             | `https://<your-api>.onrender.com`                    |
| `NEXT_PUBLIC_API_URL`                 | `https://<your-api>.onrender.com`                    |
| `DATABASE_URL`                        | the **External Database URL** from Render            |
| `INTERNAL_API_TOKEN`                  | the bearer token from step "Secrets you'll generate" |
| `AUTH_SECRET`                         | the JWT secret from step "Secrets you'll generate"   |
| `AUTH_URL`                            | `https://<your-vercel-domain>` (no trailing slash)   |
| `NEXT_PUBLIC_SENTRY_DSN`              | your Sentry browser DSN (optional)                   |
| `SENTRY_DSN`                          | your Sentry server DSN (optional)                    |
| `SENTRY_AUTH_TOKEN`                   | for source-map upload (optional)                     |
| `SENTRY_ORG`, `SENTRY_PROJECT`        | Sentry slugs (optional)                              |
| `NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE` | `0.1` (optional)                                   |

> **`DATABASE_URL` on Vercel:** the web app reads/writes the `users` table
> directly via the credentials provider's `pg` pool (see
> `apps/web/lib/db.ts`). Use Render's *External* DB URL, not the internal one.

> **`AUTH_URL` is required in production.** Unlike dev (where NextAuth
> derives it from the request host), production needs an explicit value so
> sign-in callbacks resolve correctly.

### 2c. Deploy

Click **Deploy**. First build takes ~3–5 min (pnpm install + Next.js build +
optional Sentry source-map upload).

### 2d. Connect the two

Once Vercel gives you a domain:

1. Go back to **Render → stockviz-api → Environment** and set
   `CORS_ORIGINS=https://<your-vercel-domain>`. Save → redeploy.
2. If you set up a custom domain on Vercel, update `AUTH_URL` and
   `CORS_ORIGINS` to match.

## 3. Verify

1. Open `https://<your-vercel-domain>`. Markets table should populate.
2. `/signup` → create an account → land on `/portfolio`. Should show
   `$100,000` cash and zero positions (the API auto-creates the default
   portfolio on first read).
3. Place a paper trade at `/trade`. It should appear in `/trades`.
4. Open `https://<your-api>.onrender.com/health` — `{"status":"ok"}`.
5. Open `/docs` on the API — Swagger UI should load.

If `/portfolio` 500s or hangs, check `Render → stockviz-api → Logs`:
- `INVALID_INTERNAL_TOKEN` ⇒ `INTERNAL_API_TOKEN` mismatch between Vercel and Render.
- `Cross-Origin Request Blocked` ⇒ `CORS_ORIGINS` doesn't match the Vercel domain.
- `JWT decode failed` ⇒ `AUTH_SECRET` ≠ `NEXTAUTH_JWT_SECRET`.

## Ongoing operations

### Redeploys

- Both Vercel and Render have `autoDeploy: true` from `main`. Push to `main`
  → both rebuild automatically.
- Migrations apply on every Render deploy (the Dockerfile runs
  `alembic upgrade head` before starting uvicorn). Don't run migrations
  manually unless something failed.

### Daily refresh (in-process)

With `ENABLE_SCHEDULER=true`, FastAPI runs APScheduler inside the same
process. The jobs (defined in `apps/api/src/stockviz/scheduler.py`) are:

- **16:30 ET weekdays** — `daily_price_refresh` for every active symbol.
- **Hourly 10:00–16:00 ET weekdays** — `hourly_top_movers`.
- **Every 4h at :15** — `news_refresh` (skipped if `NEWSDATA_KEY` is empty).
- **17:00 ET weekdays** — `recommendations_refresh`.

If the API instance restarts (deploy, OOM, free-tier cold-spin), the
scheduler restarts with it — no manual intervention needed.

### Adding a cron safety net (optional, paid)

Render's in-process scheduler is fine in practice but stops firing if the
service goes down for the whole window. For extra safety, append a cron
service to `infra/render.yaml`:

```yaml
  - type: cron
    name: stockviz-nightly-refresh
    runtime: docker
    repo: <your repo URL>
    branch: main
    rootDir: apps/api
    dockerfilePath: apps/api/Dockerfile
    plan: starter   # NOT free — Render removed the free cron tier
    schedule: "30 21 * * 1-5"   # 21:30 UTC = 16:30 ET, weekdays
    dockerCommand: sh -c "python -m stockviz.cli ingest AAPL MSFT GOOGL && python -m stockviz.cli recommend"
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: stockviz-postgres
          property: connectionString
      - key: ALPHA_VANTAGE_KEY
        sync: false
      - key: SENTRY_DSN
        sync: false
```

Cost is per-run on Starter — a single nightly invocation is in the
~$1/month range.

### Scaling beyond the free tier

Both Render's Postgres-free and web-service-free plans spin down after
inactivity (~15 min cold start). For real use:
- Upgrade the API service to Starter or higher to avoid cold starts.
- Upgrade Postgres so it doesn't expire after 90 days.
- Vercel's Hobby tier is fine for personal projects; upgrade to Pro if you
  need preview deploys without API rate limits.

## Building the API image locally

Useful for debugging the production setup before pushing:

```bash
docker build -t stockviz-api ./apps/api
docker run --rm -p 8000:8000 \
  -e DATABASE_URL="<your local postgres url>" \
  -e INTERNAL_API_TOKEN="dev-internal-token-change-me" \
  -e NEXTAUTH_JWT_SECRET="dev-secret-change-me" \
  stockviz-api
```

## Rolling back

- **Vercel:** dashboard → Deployments → pick a previous green deploy →
  **Promote to Production**. Instant rollback (no rebuild).
- **Render:** dashboard → stockviz-api → Deploys → pick a previous deploy
  → **Rollback**. Requires the Docker image to be cached; if not, redeploy
  from a previous commit on `main`.
- **Database:** Render's free Postgres has daily backups. Restore from
  dashboard → stockviz-postgres → Backups.

## Related docs

- [`SETUP.md`](./SETUP.md) — local development.
- [`../REWRITE_PLAN.md`](../REWRITE_PLAN.md) — phase-by-phase rewrite history.
- [`../apps/api/CLAUDE.md`](../apps/api/CLAUDE.md) — API internals.
- [`../apps/web/CLAUDE.md`](../apps/web/CLAUDE.md) — web internals.
