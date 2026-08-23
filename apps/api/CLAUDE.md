# apps/api — agent guide

FastAPI + SQLModel + Alembic + APScheduler. Python 3.12, managed by `uv`.

## Layout

```
src/stockviz/
  main.py           create_app() — FastAPI factory, CORS, scheduler lifespan, Sentry init
  settings.py       Pydantic Settings (env-driven config + lru_cache; rewrites postgres:// → postgresql+psycopg://)
  db.py             engine + get_session dependency
  auth.py           require_user_id / UserIdDep — verifies the HS256 Bearer JWT from the Next.js server
  limiter.py        slowapi rate limiter, keyed per-user then per-IP
  scheduler.py      APScheduler jobs (see below)
  cli.py            argparse one-shot commands mirroring the scheduler jobs
  schemas.py        shared Pydantic response models
  observability.py  Sentry bootstrap (no-op without DSN)
  models/           SQLModel tables (market, portfolio, user, order, option, dividend,
                    alert, comment, recommendation, watchlist, metrics, sentiment,
                    events — outbox, consumer inbox, derived trade activity)
  events/           trade.executed contract, outbox claim/publish, Kafka wrappers,
                    derived activity applier (not imported by FastAPI startup)
  workers/          outbox_publisher and trade_activity_consumer processes
  routers/          /v1 endpoints, one file per resource — symbols, quotes, bars,
                    markets (one-call /markets summary), indicators, news,
                    recommendations, trading, orders, options, backtest,
                    screener, sentiment, leaderboard, watchlist, alerts,
                    comments, stream (SSE simulated quotes), health
  services/
    ingest/         External-API fetchers (yfinance primary, Alpha Vantage fallback, Newsdata)
    indicators/     SMA/EMA/RSI/MACD pure functions
    recommend/      The ported v1 algo
    trading/        execute, orders (pending limit/stop + derived reservations),
                    buying_power, portfolio, analytics, dividends, fx, snapshots
    options/        Black-Scholes-style pricing + option trade execution/settlement
    backtest/       engine.py — historical strategy simulation
    alerts.py       price-alert evaluation
    metrics.py      precomputed per-symbol RSI / 52w range (screener reads these)
    sentiment/      provider abstraction + store
      base.py         SentimentProvider protocol, SentimentScore/Input
      anthropic_provider.py, http_provider.py, null_provider.py
      store.py        persist scores, backfill, per-symbol rolling aggregate
migrations/         Alembic versions/
tests/              pytest, asyncio mode=auto, ~300 tests today
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
`metadata`, `ingest <tickers>`, `fx`, `metrics`, `score-sentiment`,
`sentiment-aggregate`, `recommend`, `snapshot-portfolios`, `dividends`,
`credit-dividends`, `settle-options`, `publish-outbox [--once]`,
`consume-trade-activity [--once]`.

Kafka workers (same image, different command; broker optional for the API):

```powershell
pnpm events:up   # compose profile "events" — KRaft Kafka + topic init
uv --directory apps/api run python -m stockviz.workers.outbox_publisher --once
uv --directory apps/api run python -m stockviz.workers.trade_activity_consumer --once
```

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

`scheduler.py::build_scheduler` registers eleven cron jobs (timezone
America/New_York, weekdays unless noted):

- 09:30 — `dividend_credit_refresh` (credit due dividends to portfolios)
- 10:00–16:00 hourly — `hourly_top_movers` (TOP_TICKERS_HOURLY)
- 16:30 — `daily_price_refresh` (all active symbols)
- 16:45 — `fx_refresh` and `pending_orders_settlement` (fill limit/stop orders against the new close)
- 16:50 — `symbol_metrics_refresh` (RSI / 52w range the screener reads)
- 16:55 — `sentiment_aggregate_refresh` (rolling per-symbol news sentiment)
- 17:00 — `recommendations_refresh`
- 17:15 — `portfolio_snapshots_refresh` (daily NAV snapshot per user)
- 17:30 — `options_expiry_refresh` (settle expired option positions)
- Every 4h at :15 (all days) — `news_refresh` (skipped if `NEWSDATA_KEY` empty)

Every job is wrapped in `@single_instance(...)`, which takes a Postgres
advisory lock. APScheduler runs in-process, so without it a scale-out to two
API instances double-fires every job — for order settlement and option expiry
that means filling the same order twice.

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
         ├─ news_articles ── news_sentiment   (one row per article+model)
         ├─ recommendations
         ├─ symbol_metrics      (precomputed RSI / 52w / rolling sentiment)
         └─ dividends           (declared payouts per symbol)
fx_rates                        (currency + date, USD-per-unit)
```

Gotcha: `portfolio_snapshots` hangs off **users**, not portfolios.

## Rate limiting

`limiter.py` keys on the authenticated user id where present, then the
left-most `X-Forwarded-For` hop, then the socket address; endpoints opt in with
`@limiter.limit(...)`. (Uvicorn must run with `--proxy-headers` for the
forwarded chain to be populated — the Dockerfile passes it. `get_remote_address`
alone saw only Render's proxy, making one global bucket.)

Current budget: **60/min** on the public reads
(symbols, bars, quotes, news, indicators, recommendations), **30/min**
screener, **20/min** backtest. Authenticated routers are deliberately *not*
slowapi-limited — every authed request arrives from the Next.js server, so a
per-IP limit would be one global bucket for all users. Where per-user
throttling matters, do it in the router like comments does (5 posts/min via
a DB count of recent rows). Disable the limiter with `RATELIMIT_ENABLED=0` — note that slowapi reads that
variable itself and keeps the raw string, so `limiter.py` parses it and assigns
a real bool after construction; without that, `"0"` was truthy and the switch
did nothing.

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
  filled **at the close price**, not the limit price. Pending BUYs reserve
  USD buying power (`quantity × limit_price` at the latest FX rate); pending
  SELLs reserve shares. Reservations are derived from `PENDING` rows in
  `services/trading/buying_power.py` — cancel/fill releases them. Market
  equity trades and long-option opens check **available** cash/shares, not
  raw `cash_balance` / position quantity. A fill may consume its own
  reservation (`exclude_order_id`) but not another order's. Competing
  cash writers (`apply_fill`, pending create/cancel/settle, option
  open/close/expiry, dividend credits) `SELECT … FOR UPDATE` the portfolio
  row via `lock_portfolio`, which **refreshes** the identity-map instance so
  a stale `cash_balance` cannot overwrite a concurrent debit. Cancel and
  fill re-read `order.status == PENDING` after that lock. First-portfolio
  creation serializes on the user row; `portfolios.user_id` is unique.
  Orders that trigger but fail validation (insufficient available cash/shares)
  are **cancelled** with a `cancel_reason`, never retried. Settlement takes a
  `session_date` and leaves orders pending when the latest bar predates it, so
  a failed price refresh can't fill against a stale close.
- **One fill path.** Both market orders and pending-order settlement go through
  `execute.apply_fill`, which owns the cash/position mutation. Keep it that
  way: when the two had separate copies, only one of them converted native
  currency to USD.
- **Options count toward NAV.** `compute_portfolio` marks open contracts to
  their Black-Scholes value (`options_market_value`). Without it, buying an
  option debited cash and recorded no offsetting asset.
- **Options** (`services/options/`): long-only book. Black-Scholes pricing
  with 30-day historical volatility as the IV proxy and a 5% risk-free rate;
  contracts are ×100 (`CONTRACT_MULTIPLIER`). Premiums debit the USD cash
  bucket and must honour pending-equity-BUY reservations. Option pricing is
  **not** a complete multi-currency ledger (unlike equity `apply_fill`). At
  expiry (17:30 job): ITM calls exercise into the equity book if *available*
  cash covers the strike, otherwise cash-settle intrinsic value; ITM puts
  sell *available* held shares at the strike, otherwise cash-settle; OTM
  expires worthless.

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

Each ingest service writes straight to Postgres — no CSV intermediate.
Price ingest uses **yfinance first** (no key). Alpha Vantage is attempted
only when `ALPHA_VANTAGE_KEY` is set and yfinance returned no rows. News
ingest short-circuits when `NEWSDATA_KEY` is unset. Same skip-when-unkeyed
pattern for sentiment (Anthropic) — it logs and skips when the key or
package is missing.

## Testing

`pytest -k <name>` for a focused run. Tests use an in-memory SQLite by default
where possible; routers spin up a TestClient with FastAPI's dependency overrides.
Don't introduce real-network calls in tests — mock the httpx layer.

## Sentiment

Scoring goes through a `SentimentProvider` (`services/sentiment/base.py`);
`SENTIMENT_PROVIDER` picks the implementation — `none` (default), `anthropic`,
or `http` (a standalone service). Blank resolves to `anthropic` when
`ANTHROPIC_API_KEY` is set, else `none`.

Results land in `news_sentiment`, one row per `(article_id, model)`, carrying
label + continuous score + optional confidence. `news_articles.sentiment` stays
as the denormalized "current best" label the badge reads. A provider never
raises for one document: unscorable inputs come back `None` and are stored as
NULL so `stockviz.cli score-sentiment` can retry them.

`refresh_symbol_sentiment` rolls scores into `symbol_metrics.sentiment_7d`,
which the screener filters on, the recommendation engine votes with
(`_vote_positive_sentiment`, the 7th of 7 votes), and
`GET /v1/symbols/{ticker}/sentiment` serves.

Full wire contract for the `http` provider: [`docs/SENTIMENT.md`](../../docs/SENTIMENT.md).
