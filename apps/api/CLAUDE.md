# apps/api — agent guide

FastAPI + SQLModel + Alembic + APScheduler. Python 3.12, managed by `uv`.

## Layout

```
src/stockviz/
  main.py           create_app() — FastAPI factory, CORS, scheduler lifespan, Sentry init
  settings.py       Pydantic Settings (env-driven config + lru_cache)
  db.py             engine + get_session dependency
  auth.py           require_user_id — verifies X-Internal-Token + X-User-Id (server-to-server bridge)
  scheduler.py      APScheduler jobs (daily prices, hourly top movers, news, recs)
  cli.py            argparse one-shot commands (seed, backfill, metadata, ingest, recommend)
  observability.py  Sentry bootstrap (no-op without DSN)
  models/           SQLModel tables (market, portfolio, user, recommendation, watchlist)
  routers/          /v1 endpoints (one file per resource)
  services/
    ingest/         External-API fetchers (Alpha Vantage, yfinance, Newsdata)
    indicators/     SMA/EMA/RSI/MACD pure functions
    recommend/      The ported v1 algo
    trading/        Paper-trade execution + portfolio aggregation
migrations/         Alembic versions/
tests/              pytest, asyncio mode=auto, 64 tests today
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

`scheduler.py::build_scheduler` registers four cron jobs (timezone America/New_York):

- 16:30 weekdays — `daily_price_refresh` (all active symbols)
- Hourly 10:00–16:00 weekdays — `hourly_top_movers` (TOP_TICKERS_HOURLY)
- Every 4h at :15 — `news_refresh` (skipped if `NEWSDATA_KEY` empty)
- 17:00 weekdays — `recommendations_refresh`

**Off by default.** `ENABLE_SCHEDULER=false` so pytest / CLI / local dev don't
fire jobs. Render flips it on. The Render cron service is a separate safety
net that re-runs the same logic via `python -m stockviz.cli`.

## Auth bridge

`auth.py::require_user_id` is the FastAPI dependency. Header contract is
documented in the module docstring and matched on the Next.js side in
`apps/web/lib/api/server.ts`. Don't expose any new authenticated endpoint
without depending on `UserIdDep`.

## Migrations

`alembic revision --autogenerate -m "<msg>"` then review the generated file —
SQLModel's metadata isn't always perfect with relationship/index detection.
Apply with `alembic upgrade head`. The post-write hook runs `ruff format` on
new revisions (configured in `alembic.ini`).

## Ingestion contract

Each ingest service writes straight to Postgres — no CSV intermediate. They
short-circuit (with a log line) when their API key is unset, so jobs are
safe to run unconfigured.

## Testing

`pytest -k <name>` for a focused run. Tests use an in-memory SQLite by default
where possible; routers spin up a TestClient with FastAPI's dependency overrides.
Don't introduce real-network calls in tests — mock the httpx layer.
