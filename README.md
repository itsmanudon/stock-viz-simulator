# StockViz

Live market data, technical indicators, news, and a paper-trading simulator.

A Next.js + FastAPI + Postgres rewrite of the original static-HTML site.
Tag [`v1.0.0`](../../tree/v1.0.0) points at the legacy v1 source;
[`v2.0.0`](../../tree/v2.0.0) marks the cutover commit where both codebases
coexisted. The full rewrite plan lives in [`REWRITE_PLAN.md`](./REWRITE_PLAN.md).

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
- APScheduler runs in-process inside FastAPI for the daily refresh
  (`ENABLE_SCHEDULER=true` in production).
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
| Hosting     | Vercel (web) + Render (api + db)                |
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
  render.yaml          Render Blueprint (api + db)
.github/workflows/     CI: lint + typecheck + test on PR
REWRITE_PLAN.md        Phase-by-phase rewrite roadmap
```

## Local dev

Full step-by-step instructions for **macOS / Linux** and **Windows** live in
[`docs/SETUP.md`](./docs/SETUP.md). The short version:

```bash
pnpm install
uv --directory apps/api sync
cp apps/web/.env.example apps/web/.env.local        # Windows: Copy-Item
cp apps/api/.env.example apps/api/.env              # Windows: Copy-Item
pnpm db:up                                          # Postgres on :5434, Adminer on :8080
uv --directory apps/api run alembic upgrade head
uv --directory apps/api run python -m stockviz.cli seed
uv --directory apps/api run python -m stockviz.cli backfill
pnpm api:dev      # terminal 1 — FastAPI on :8000
pnpm dev:web      # terminal 2 — Next.js on :3000 (auto-bumps to next free port)
```

## Quality gates

```bash
pnpm lint                                  # biome (web) + ruff (api)
pnpm typecheck                             # tsc + pyright
uv --directory apps/api run pytest
pnpm build                                 # production build of the web app
```

GitHub Actions runs all of the above on every PR to `main` (the default branch).
The `migration` and `v2` branches are retired remnants of the rewrite — work
off `main`.

## Deployment

Full walkthrough (Vercel for web, Render Blueprint for api + db, env vars,
secrets, first-time seeding, rollback) lives in
[`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md). The short version:

- **Web → Vercel.** Import the repo, set Root Directory to `apps/web`,
  fill in env vars (`API_URL`, `NEXT_PUBLIC_API_URL`, `DATABASE_URL`,
  `AUTH_SECRET`, `AUTH_URL`, `INTERNAL_API_TOKEN`, optional Sentry). Build
  settings come from `apps/web/vercel.json`.
- **API + DB → Render.** Dashboard → New + → Blueprint → point at this
  repo. Render reads `infra/render.yaml` and provisions Postgres 16 plus
  the FastAPI web service (Docker). Fill in the `sync: false` secrets
  (`NEXTAUTH_JWT_SECRET`, `INTERNAL_API_TOKEN`, `CORS_ORIGINS`,
  `ALPHA_VANTAGE_KEY`, `NEWSDATA_KEY`, `SENTRY_DSN`), redeploy, then seed
  once via the service shell. Daily refresh runs in-process via
  APScheduler.

Build the API image locally with `docker build -t stockviz-api ./apps/api`.

## License

MIT — see [LICENSE](./LICENSE).
