# StockViz

Live market data, technical indicators, news, and a paper-trading simulator.

The v2 rewrite (this branch / `migration`) is a Next.js + FastAPI + Postgres stack
that replaced the original static-HTML site. The legacy site is tagged
[`v1.0.0`](../../tree/v1.0.0). The full rewrite plan lives in
[`REWRITE_PLAN.md`](./REWRITE_PLAN.md).

## What it does

- **Markets** — sortable table of every tracked symbol with inline sparklines.
- **Ticker detail** — OHLCV candlesticks (lightweight-charts), SMA/EMA/RSI/MACD overlays, related news.
- **Compare** — normalized price chart for multiple tickers side-by-side.
- **News** — paginated company-news feed from Newsdata.io, cached in Postgres.
- **Recommendations** — daily-scored buy candidates with rationale, ported from the v1 algo.
- **Paper trading** — per-user portfolio with cash balance, positions, trade history, P&L.

## Architecture

```
┌────────────────┐         ┌─────────────────────┐         ┌─────────────┐
│  Browser       │  HTTPS  │  Next.js (Vercel)   │  HTTPS  │   FastAPI   │
│  React + RSC   │ ──────▶ │  - App Router       │ ──────▶ │  (Render)   │
└────────────────┘         │  - NextAuth v5      │         │  + APScheduler
                           │  - server-only API  │         └──────┬──────┘
                           │    client w/ token  │                │
                           └─────────┬───────────┘                │
                                     │                            │
                                     │     ┌──────────────────────┘
                                     ▼     ▼
                              ┌─────────────────┐         ┌──────────────────┐
                              │  Postgres 16    │         │  Alpha Vantage   │
                              │  (Render DB)    │         │  yfinance        │
                              │  - users        │         │  Newsdata.io     │
                              │  - symbols      │         └──────────────────┘
                              │  - price_bars   │
                              │  - portfolios   │
                              │  - trades       │
                              └─────────────────┘
```

- The Next.js server-only API client attaches `Authorization: Bearer <INTERNAL_API_TOKEN>` +
  `X-User-Id: <session.userId>` for authenticated `/v1` calls. The browser never sees the token.
- APScheduler runs in-process inside FastAPI for the daily refresh; a Render cron job re-runs
  the ingest nightly as a safety net.
- Sentry collects errors from both the web and api (gated on `SENTRY_DSN`).

## Stack

| Layer       | Choice                                          |
| ----------- | ----------------------------------------------- |
| Web         | Next.js 16 (App Router), React 19, TS, Tailwind v4, shadcn/ui |
| Auth        | NextAuth v5 (credentials provider, bcrypt)      |
| Charts      | lightweight-charts (TradingView)                |
| API         | FastAPI, SQLModel, Alembic, APScheduler         |
| DB          | Postgres 16                                     |
| Ingestion   | Alpha Vantage (primary) + yfinance (fallback) + Newsdata.io |
| Hosting     | Vercel (web) + Render (api + db + cron)         |
| Monitoring  | Sentry                                          |
| Tooling     | pnpm + uv, biome + ruff, pyright + tsc          |

## Repo layout

```
apps/
  web/                 Next.js frontend
    app/               App Router routes
    components/        shadcn/ui + custom (chart, trade form, etc.)
    lib/               server-only API client, auth helpers
    auth.ts            NextAuth v5 setup
    sentry.*.config.ts Sentry init for each runtime
  api/                 FastAPI backend
    src/stockviz/
      routers/         /v1 endpoints (symbols, bars, trades, ...)
      services/        ingest, recommend, indicators, trading
      models/          SQLModel tables
      scheduler.py     APScheduler jobs
    migrations/        Alembic
    tests/             pytest
    Dockerfile         Production image (uv + uvicorn)
infra/
  docker-compose.yml   Local Postgres + Adminer
  render.yaml          Render Blueprint (api + db + cron)
.github/workflows/     CI: lint + typecheck + test on PR
REWRITE_PLAN.md        Phase-by-phase rewrite roadmap
```

## Local dev

### Prereqs

- Node.js 22+ ([nvm-windows](https://github.com/coreybutler/nvm-windows); see `.nvmrc`)
- pnpm 11+ (`npm install -g pnpm`)
- Python 3.12+ via [uv](https://docs.astral.sh/uv/) (`winget install --id=astral-sh.uv`)
- Docker Desktop

### Setup

```powershell
# 1. install deps
pnpm install
uv --directory apps/api sync

# 2. env files
Copy-Item apps/web/.env.example apps/web/.env.local
Copy-Item apps/api/.env.example apps/api/.env

# 3. boot Postgres + Adminer
pnpm db:up

# 4. apply migrations + seed
uv --directory apps/api run alembic upgrade head
uv --directory apps/api run python -m stockviz.cli seed
uv --directory apps/api run python -m stockviz.cli backfill

# 5. two terminals
pnpm api:dev      # FastAPI on http://127.0.0.1:8000
pnpm dev:web      # Next.js on http://localhost:3000
```

Open <http://localhost:3000>. OpenAPI docs at <http://127.0.0.1:8000/docs>.
Adminer at <http://localhost:8080> (server: `postgres`, user/pass/db: `stockviz`/`stockviz_dev`/`stockviz`).

### Ports

| Service       | Port |
| ------------- | ---- |
| Web (Next.js) | 3000 |
| API (FastAPI) | 8000 |
| Postgres      | 5434 |
| Adminer       | 8080 |

Postgres is on **5434** to avoid clashing with a native install or other Docker projects.

## Quality gates

```powershell
pnpm lint        # biome (web) + ruff (api)
pnpm typecheck   # tsc + pyright
uv --directory apps/api run pytest
pnpm build       # production build of the web app
```

GitHub Actions runs all of the above on every PR to `main`, `migration`, and `v2`.

## Deployment

### Vercel (web)

1. Import the repo into Vercel. Set **Root Directory** to `apps/web`.
2. Set env vars in **Project Settings → Environment Variables**:
   - `API_URL=https://<your-render-service>.onrender.com`
   - `NEXT_PUBLIC_API_URL=https://<your-render-service>.onrender.com`
   - `DATABASE_URL=<Render Postgres external URL>`
   - `INTERNAL_API_TOKEN=<random 32+ char string, same as Render>`
   - `AUTH_SECRET=<openssl rand -base64 32>`
   - `AUTH_URL=https://<your-vercel-domain>`
   - `NEXT_PUBLIC_SENTRY_DSN`, `SENTRY_DSN`, `SENTRY_AUTH_TOKEN`, `SENTRY_ORG`, `SENTRY_PROJECT` (all optional)
3. Deploy. Vercel picks up `apps/web/vercel.json` for build settings.

### Render (api + db + cron)

1. **Dashboard → New + → Blueprint**, point at this repo. Render reads `infra/render.yaml`
   and provisions Postgres + the API web service + the nightly cron job.
2. After the first deploy, fill in the `sync: false` env vars in the dashboard:
   `NEXTAUTH_JWT_SECRET` (same as the web's `AUTH_SECRET`), `INTERNAL_API_TOKEN` (same as web),
   `ALPHA_VANTAGE_KEY`, `NEWSDATA_KEY`, `SENTRY_DSN`, `CORS_ORIGINS=https://<vercel-domain>`.
3. Trigger a redeploy. The container runs `alembic upgrade head` before starting `uvicorn`.
4. SSH into the service shell (or `render shell stockviz-api`) and seed once:
   `python -m stockviz.cli seed && python -m stockviz.cli backfill && python -m stockviz.cli metadata`.

The Dockerfile lives at `apps/api/Dockerfile`. To build locally:

```powershell
docker build -t stockviz-api ./apps/api
```

## License

MIT — see [LICENSE](./LICENSE).
