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

## Data model — the load-bearing relationships

```
users ─┬─ portfolios ─┬─ positions           (qty + native-currency avg_cost)
       │              ├─ trades               (fill history)
       │              ├─ pending_orders       (limit / stop_loss / take_profit)
       │              ├─ options_positions    (also carries user_id)
       │              └─ portfolio_dividends  (credited payouts)
       ├─ portfolio_snapshots   (daily NAV — powers leaderboard + equity curve)
       ├─ watchlists ── watchlist_items
       ├─ alerts
       └─ comments              (parent_id self-FK = one level of replies)

symbols ─┬─ price_bars          (EOD OHLCV; everything prices off the latest 1d close)
         ├─ news_articles       (+ AI sentiment column)
         ├─ recommendations
         └─ dividends           (declared payouts per symbol)
fx_rates                        (currency + date, USD-per-unit)
```

Gotcha: `portfolio_snapshots` hangs off **users**, not portfolios.

## Rate limiting

`limiter.py` wires slowapi keyed on client IP; endpoints opt in with
`@limiter.limit(...)`. Current budget: **60/min** on the public reads
(symbols, bars, quotes, news, indicators, recommendations), **30/min**
screener, **20/min** backtest. Authenticated routers are deliberately *not*
slowapi-limited — every authed request arrives from the Next.js server, so a
per-IP limit would be one global bucket for all users. Where per-user
throttling matters, do it in the router like comments does (5 posts/min via
a DB count of recent rows). Disable the limiter with `RATELIMIT_ENABLED=0`.

## Trading domain rules

Everything prices off the **latest `1d` close** in `price_bars` — there are no
intraday fills anywhere in the app:

- New portfolios start with **$100,000** cash (`DEFAULT_STARTING_CASH`,
  `services/trading/execute.py`), auto-created on the first `/v1/portfolio`
  call via `ensure_default_portfolio` (idempotent).
- **Market orders** fill immediately at the latest close. Buys recompute the
  position's weighted-average `avg_cost`; sells never touch `avg_cost`, and a
  position sold to zero is **deleted**, not kept at qty 0.
- **Cash is always USD.** Trade rows store price/quantity in the symbol's
  native currency; the cash debit/credit converts at the latest FX rate
  (`services/trading/fx.py` — rates are USD-per-unit, forward-filled over
  weekends/holidays). A missing rate is a hard `NoFxRateError` on market
  orders.
- **Pending orders** (`services/trading/orders.py`): `limit` (buy triggers at
  close ≤ limit, sell at close ≥), `stop_loss`/`take_profit` (sell-only;
  close ≤ / ≥ trigger). Checked once per day by the 16:45 settlement job and
  filled **at the close price**, not the limit price. Orders that trigger but
  fail validation (insufficient cash/shares) are **cancelled**, never retried.
- **Options** (`services/options/`): long-only book. Black-Scholes pricing
  with 30-day historical volatility as the IV proxy and a 5% risk-free rate;
  contracts are ×100 (`CONTRACT_MULTIPLIER`). At expiry (17:30 job): ITM
  calls exercise into the equity book if cash covers the strike, otherwise
  cash-settle intrinsic value; ITM puts sell held shares at the strike,
  otherwise cash-settle; OTM expires worthless.

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
