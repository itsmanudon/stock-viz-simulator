# apps/api — agent guide

FastAPI + SQLModel + Alembic + APScheduler. Python 3.12, managed by `uv`.

## Layout

```
src/stockviz/
  main.py           create_app() — FastAPI factory, CORS, scheduler lifespan, Sentry init
  settings.py       Pydantic Settings (env-driven config + lru_cache; rewrites postgres:// → postgresql+psycopg://)
  db.py             engine + get_session dependency
  auth.py           require_user_id / UserIdDep — verifies the HS256 Bearer JWT from the Next.js server
  limiter.py        slowapi rate limiter (disable with RATELIMIT_ENABLED=0)
  scheduler.py      APScheduler jobs (see below)
  cli.py            argparse one-shot commands mirroring the scheduler jobs
  schemas.py        shared Pydantic response models
  observability.py  Sentry bootstrap (no-op without DSN)
  models/           SQLModel tables (market, portfolio, user, order, option, dividend,
                    alert, comment, recommendation, watchlist)
  routers/          /v1 endpoints, one file per resource — symbols, quotes, bars,
                    indicators, news, recommendations, trading, orders, options,
                    backtest, screener, leaderboard, watchlist, alerts, comments,
                    stream (SSE simulated live quotes), health
  services/
    ingest/         External-API fetchers (Alpha Vantage, yfinance, Newsdata)
    indicators/     SMA/EMA/RSI/MACD pure functions
    recommend/      The ported v1 algo
    trading/        execute, orders (pending limit/stop), portfolio, analytics,
                    dividends, fx, snapshots
    options/        Black-Scholes-style pricing + option trade execution/settlement
    backtest/       engine.py — historical strategy simulation
    alerts.py       price-alert evaluation
    sentiment.py    Anthropic-based news sentiment (no-ops if key/package absent)
migrations/         Alembic versions/
tests/              pytest, asyncio mode=auto, ~230 tests today
Dockerfile          Multi-stage build with uv → uvicorn at runtime
alembic.ini         prepend_sys_path=src so alembic can import stockviz.*
```

## Running

```powershell
uv --directory apps/api sync                          # install deps from uv.lock
uv --directory apps/api run alembic upgrade head      # apply migrations
uv --directory apps/api run python -m stockviz.cli seed
uv --directory apps/api run python -m stockviz.cli backfill   # one-time, CSV → DB
pnpm api:dev                                          # uvicorn --reload on :8000
```

OpenAPI docs at `/docs` when running. Health at `/health`.

CLI subcommands (`python -m stockviz.cli <cmd>`): `seed`, `backfill`,
`metadata`, `ingest <tickers>`, `fx`, `recommend`, `snapshot-portfolios`,
`dividends`, `credit-dividends`, `settle-options`.

## Quality gates

```powershell
uv --directory apps/api run ruff check .
uv --directory apps/api run ruff format --check .
uv --directory apps/api run pyright
uv --directory apps/api run pytest
```

All run in CI. Ruff selects `E W F I B C4 UP RUF SIM`; `E501` is off (formatter
owns line length). Pyright is `basic`.

## Scheduler

`scheduler.py::build_scheduler` registers nine cron jobs (timezone
America/New_York, weekdays unless noted):

- 09:30 — `dividend_credit_refresh` (credit due dividends to portfolios)
- 10:00–16:00 hourly — `hourly_top_movers` (TOP_TICKERS_HOURLY)
- 16:30 — `daily_price_refresh` (all active symbols)
- 16:45 — `fx_refresh` and `pending_orders_settlement` (fill limit/stop orders against the new close)
- 17:00 — `recommendations_refresh`
- 17:15 — `portfolio_snapshots_refresh` (daily NAV snapshot per user)
- 17:30 — `options_expiry_refresh` (settle expired option positions)
- Every 4h at :15 (all days) — `news_refresh` (skipped if `NEWSDATA_KEY` empty)

**Off by default.** `ENABLE_SCHEDULER=false` so pytest / CLI / local dev don't
fire jobs. Render flips it on. Each job has a matching `stockviz.cli`
subcommand for manual re-runs (there is no separate Render cron service).

## Auth bridge

`auth.py::require_user_id` verifies an `Authorization: Bearer <JWT>` header —
an HS256 token with `{ sub: "<user.id>" }` and 60 s expiry, signed with
`INTERNAL_API_TOKEN`. The Next.js side mints it in `apps/web/lib/api/server.ts`.
Don't expose any new authenticated endpoint without depending on `UserIdDep`.

## Migrations

`alembic revision --autogenerate -m "<msg>"` then review the generated file —
SQLModel's metadata isn't always perfect with relationship/index detection.
Apply with `alembic upgrade head`. The post-write hook runs `ruff format` on
new revisions (configured in `alembic.ini`). If parallel branches each added a
revision you'll get **multiple heads** — resolve with
`alembic merge heads -m "merge heads"` (it has happened before).

## Ingestion contract

Each ingest service writes straight to Postgres — no CSV intermediate. They
short-circuit (with a log line) when their API key is unset, so jobs are
safe to run unconfigured. Same pattern for `sentiment.py` (Anthropic) — it
logs and skips when the key or package is missing.

## Testing

`pytest -k <name>` for a focused run. Tests use an in-memory SQLite by default
where possible; routers spin up a TestClient with FastAPI's dependency overrides.
Don't introduce real-network calls in tests — mock the httpx layer.
