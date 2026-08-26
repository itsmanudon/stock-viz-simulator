# StockViz — deployment

How to deploy the StockViz monorepo using the source-controlled hosting
configuration. This is an operator guide, not evidence that a public URL is
currently healthy or that these hosts have been production-tested. The two
apps are configured for different hosts:

| App        | Host   | What it runs                                |
| ---------- | ------ | ------------------------------------------- |
| `apps/web` | Vercel | Next.js 16 (App Router, NextAuth v5)        |
| `apps/api` | Render | FastAPI + Postgres + in-process APScheduler |

The web app is reverse-proxied by Vercel; the API + Postgres are provisioned
together from `infra/render.yaml` as a Render Blueprint. Daily price + news
refreshes run **in-process** inside FastAPI via APScheduler
(`ENABLE_SCHEDULER=true`); there is no separate cron service in the
Blueprint; that hosting path runs APScheduler inside FastAPI.

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

Generate these once and reuse the same values on both sides.

**The web → API auth bridge uses `INTERNAL_API_TOKEN`, not NextAuth's
session secret.** The Next.js server mints a 60-second HS256 JWT signed with
`INTERNAL_API_TOKEN`; FastAPI verifies that same secret. `AUTH_SECRET` is
only for NextAuth session cookies on the web app. `NEXTAUTH_JWT_SECRET` is
unused leftover on the API (still listed in the Blueprint so existing
Render services keep the env var).

```bash
# AUTH_SECRET (NextAuth sessions on Vercel only)
openssl rand -base64 32

# INTERNAL_API_TOKEN (must be identical on Vercel and Render)
openssl rand -hex 32
```

Save these to a password manager before you start — you'll paste them into
both Render and Vercel.

## 1. Deploy the API + database to Render

Render reads `infra/render.yaml` and provisions two resources in one shot:
Postgres 16 and the `stockviz-api` web service. The Blueprint has no separate
cron resource; daily refresh runs in-process via APScheduler.

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

| Variable              | Value                                                                              |
| --------------------- | ---------------------------------------------------------------------------------- |
| `CORS_ORIGINS`        | `https://<your-vercel-domain>` (you'll know this after step 2)                     |
| `INTERNAL_API_TOKEN`  | the shared HS256 secret from “Secrets you'll generate” (must match Vercel)         |
| `NEXTAUTH_JWT_SECRET` | unused by the current auth bridge; optional on a new deploy                        |
| `ALPHA_VANTAGE_KEY`   | optional Alpha Vantage key (yfinance is primary; blank skips the AV fallback only) |
| `NEWSDATA_KEY`        | your Newsdata.io key (or leave blank to disable news ingest)                       |
| `ANTHROPIC_API_KEY`   | optional; headline sentiment scoring (leave blank to skip)                         |
| `SENTRY_DSN`          | your Sentry DSN (or leave blank)                                                   |

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

After this, the in-process APScheduler (`ENABLE_SCHEDULER=true`) keeps data
fresh. There is no separate Render cron job.

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

| Variable                                | Value                                                |
| --------------------------------------- | ---------------------------------------------------- |
| `API_URL`                               | `https://<your-api>.onrender.com`                    |
| `NEXT_PUBLIC_API_URL`                   | `https://<your-api>.onrender.com`                    |
| `DATABASE_URL`                          | the **External Database URL** from Render            |
| `INTERNAL_API_TOKEN`                    | the bearer token from step "Secrets you'll generate" |
| `AUTH_SECRET`                           | the JWT secret from step "Secrets you'll generate"   |
| `AUTH_URL`                              | `https://<your-vercel-domain>` (no trailing slash)   |
| `NEXT_PUBLIC_SENTRY_DSN`                | your Sentry browser DSN (optional)                   |
| `SENTRY_DSN`                            | your Sentry server DSN (optional)                    |
| `SENTRY_AUTH_TOKEN`                     | for source-map upload (optional)                     |
| `SENTRY_ORG`, `SENTRY_PROJECT`          | Sentry slugs (optional)                              |
| `NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE` | `0.1` (optional)                                     |

> **`DATABASE_URL` on Vercel:** the web app reads/writes the `users` table
> directly via the credentials provider's `pg` pool (see
> `apps/web/lib/db.ts`). Use Render's _External_ DB URL, not the internal one.

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
- `Invalid or expired token` / 401 on `/v1` ⇒ `INTERNAL_API_TOKEN` mismatch
  (this is the bridge JWT, not `AUTH_SECRET`).

## Ongoing operations

### Redeploys

- **Source control vs dashboards.** `infra/render.yaml` sets
  `autoDeploy: true` (Render’s Blueprint default) and pins `branch: main`.
  `apps/web/vercel.json` does not encode Vercel auto-deploy; that is a
  dashboard/Git-integration setting. Whether either host currently deploys
  on push is **owner-controlled and not verifiable from this repository**.
  Do not flip Blueprint `autoDeploy` or trigger a production rollout from a
  docs/feature PR unless the intent is to start shipping.
- Migrations apply on every Render deploy (the Dockerfile runs
  `alembic upgrade head` before starting uvicorn). Don't run migrations
  manually unless something failed.

### Daily refresh (in-process)

With `ENABLE_SCHEDULER=true`, FastAPI runs APScheduler inside the same
process. The jobs (defined in `apps/api/src/stockviz/scheduler.py`,
timezone `America/New_York`) are:

- **09:30 ET weekdays** — `dividend_credit_refresh`.
- **Hourly 10:00–16:00 ET weekdays** — `hourly_top_movers` (top-10 tickers)
  and in-app price-alert evaluation.
- **16:30 ET weekdays** — `daily_price_refresh` for every active symbol.
- **16:45 ET weekdays** — `fx_refresh` and `pending_orders_settlement`.
- **16:50 ET weekdays** — `symbol_metrics_refresh`.
- **16:55 ET weekdays** — `sentiment_aggregate_refresh`.
- **17:00 ET weekdays** — `recommendations_refresh`.
- **17:15 ET weekdays** — `portfolio_snapshots_refresh`.
- **17:30 ET weekdays** — `options_expiry_refresh`.
- **Every 4h at :15** — `news_refresh` (skipped if `NEWSDATA_KEY` is empty).

If the API instance restarts (deploy, OOM, free-tier cold-spin), the
scheduler restarts with it — no manual intervention needed.

### Adding a cron safety net (optional)

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
  plan: starter # verify current Render plan availability and pricing
  schedule: "30 21 * * 1-5" # 21:30 UTC = 16:30 ET, weekdays
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

Hosting plans and pricing change. Verify current Render and Vercel behavior
before using this optional resource; the repository does not claim a specific
price, cold-start policy, retention period, or SLA.

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
- **Database:** use the backup/restore workflow provided by the selected
  database plan; verify it and test recovery before treating the deployment
  as durable.

## Related docs

- [`SETUP.md`](./SETUP.md) — local development.
- [`KNOWN_LIMITATIONS.md`](./KNOWN_LIMITATIONS.md) — current product and ops constraints.
- [`EVENT_DRIVEN_ARCHITECTURE.md`](./EVENT_DRIVEN_ARCHITECTURE.md) — outbox and worker semantics.
- [`KUBERNETES.md`](./KUBERNETES.md) — locally validated kind/Strimzi deployment.
- [`ENGINEERING_ROADMAP.md`](./ENGINEERING_ROADMAP.md) — remaining production-hardening work.
