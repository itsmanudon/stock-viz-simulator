# StockViz

Live market data, technical indicators, news, and a paper-trading simulator.

A Next.js + FastAPI + Postgres rewrite of the original static-HTML site.
Tag [`v1.0.0`](../../tree/v1.0.0) points at the legacy v1 source;
[`v2.0.0`](../../tree/v2.0.0) marks the cutover commit where both codebases
coexisted. The rewrite plan ([`REWRITE_PLAN.md`](./REWRITE_PLAN.md)) is
**historical** — all seven phases shipped. A recruiter-honest list of what
ships vs what is still unfinished is in
[`docs/RESUME_GAPS.md`](./docs/RESUME_GAPS.md).

There is no public live URL in this repository. Intended hosts are Vercel
(web) and Render (API + DB); dashboard auto-deploys are currently **off**.

## What it does

- **Markets** — sortable table of tracked symbols with inline sparklines.
- **Ticker detail** — OHLCV candlesticks (lightweight-charts), SMA/EMA/RSI/MACD overlays, related news and comments.
- **Compare** — normalized price chart for multiple tickers side-by-side.
- **News** — paginated company-news feed from Newsdata.io, cached in Postgres.
- **Recommendations** — daily-scored buy candidates (six price/volume votes plus an optional news-sentiment vote).
- **Screener / backtest / leaderboard** — filter the universe, run a historical strategy, rank public portfolios.
- **Paper trading** — per-user portfolio with cash, equity and long-only option positions, pending limit/stop orders, trade history, P&L, dividends, and FX conversion to USD.
- **Watchlist and in-app price alerts** — alerts evaluate hourly on weekdays; there is no email/push.
- **Auth** — email/password (bcrypt) plus optional Google OAuth (needs `GOOGLE_CLIENT_*`).

The header “live” price badge is a simulated random walk off the last cached
close, not a real-time exchange feed. Headline sentiment scoring is off
unless `ANTHROPIC_API_KEY` or `SENTIMENT_PROVIDER=http` is configured.

## Architecture

```
┌────────────────┐         ┌─────────────────────┐         ┌─────────────┐
│  Browser       │  HTTPS  │  Next.js (Vercel)   │  HTTPS  │   FastAPI   │
│  React + RSC   │ ──────▶ │  - App Router       │ ──────▶ │  (Render)   │
└────────────────┘         │  - NextAuth v5      │         │  + APScheduler
                           │  - server-only API  │         └──────┬──────┘
                           │    client (JWT)     │                │
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

- The Next.js server mints a short-lived HS256 JWT (`{ sub: "<user.id>" }`,
  60 s) signed with `INTERNAL_API_TOKEN` and sends it as
  `Authorization: Bearer <jwt>` on authenticated `/v1` calls. The browser
  never sees the token. FastAPI verifies the signature in
  `auth.py::require_user_id`.
- APScheduler runs in-process inside FastAPI for the daily refresh
  (`ENABLE_SCHEDULER=true` in production).
- Sentry collects errors from both the web and api (gated on `SENTRY_DSN`).

## Stack

| Layer       | Choice                                          |
| ----------- | ----------------------------------------------- |
| Web         | Next.js 16 (App Router), React 19, TS, Tailwind v4, shadcn/ui |
| Auth        | NextAuth v5 (credentials + optional Google OAuth, bcrypt) |
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
    app/               App Router routes (markets, stocks, screener, backtest, …)
    components/        shadcn/ui + custom (chart, trade form, etc.)
    lib/               server-only API client, auth helpers
    tests/             Vitest unit tests + Playwright e2e
    auth.ts            NextAuth v5 setup
    sentry.*.config.ts Sentry init for each runtime
  api/                 FastAPI backend
    src/stockviz/
      routers/         /v1 endpoints (symbols, bars, trades, options, …)
      services/        ingest, recommend, indicators, trading, sentiment
      models/          SQLModel tables
      scheduler.py     APScheduler jobs
    migrations/        Alembic
    tests/             pytest
    seed-data/         companies.json + price CSVs for backfill
    Dockerfile         Production image (uv + uvicorn)
infra/
  docker-compose.yml   Local Postgres + Adminer
  render.yaml          Render Blueprint (api + db)
.github/workflows/     CI: lint, typecheck, tests, audit, Docker, e2e
docs/RESUME_GAPS.md    Honest shipped-vs-claimed / next-work list
REWRITE_PLAN.md        Historical phase-by-phase rewrite plan
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

`seed` without `backfill` leaves the markets table empty (symbols, no bars).
Google sign-in needs `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`; email
signup works without them.

## Quality gates

```bash
pnpm lint                                  # biome (web) + ruff (api)
pnpm typecheck                             # tsc + pyright
pnpm --filter @stockviz/web test           # Vitest
uv --directory apps/api run pytest
pnpm build                                 # production build of the web app
```

GitHub Actions runs the above plus `pnpm audit` / `pip-audit`, an API Docker
build, `alembic check`, and Playwright e2e on every push and PR to **`dev`**
and **`main`**.

Work off **`dev`**. Open feature PRs into `dev`, not `main`. `main` is the
release branch. The `migration` and `v2` branches are retired remnants of
the rewrite.

## Deployment

Full walkthrough (Vercel for web, Render Blueprint for api + db, env vars,
secrets, first-time seeding, rollback) lives in
[`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md). The short version:

> **Note:** auto-deployments are currently **disabled** in the Vercel and
> Render dashboards. `dev` is merged into `main` freely as changes land —
> no milestone gate. `infra/render.yaml` still has `autoDeploy: true` (the
> Blueprint default); re-enable deploys in the dashboards when you want
> production to follow `main`. The instructions below apply when
> deployments are turned back on.

- **Web → Vercel.** Import the repo, set Root Directory to `apps/web`,
  fill in env vars (`API_URL`, `NEXT_PUBLIC_API_URL`, `DATABASE_URL`,
  `AUTH_SECRET`, `AUTH_URL`, `INTERNAL_API_TOKEN`, optional Sentry). Build
  settings come from `apps/web/vercel.json`.
- **API + DB → Render.** Dashboard → New + → Blueprint → point at this
  repo. Render reads `infra/render.yaml` and provisions Postgres 16 plus
  the FastAPI web service (Docker). Fill in the `sync: false` secrets
  (`INTERNAL_API_TOKEN` must match Vercel, `CORS_ORIGINS`,
  `ALPHA_VANTAGE_KEY`, `NEWSDATA_KEY`, optional `ANTHROPIC_API_KEY` /
  `SENTRY_DSN`), redeploy, then seed once via the service shell. Daily
  refresh runs in-process via APScheduler.

Build the API image locally with `docker build -t stockviz-api ./apps/api`.

## License

MIT — see [LICENSE](./LICENSE).
