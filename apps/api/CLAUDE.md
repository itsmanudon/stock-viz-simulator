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
  scheduler.py      APScheduler jobs (see below) — also run as a dedicated process
  cli.py            argparse one-shot commands mirroring the scheduler jobs;
                    `earnings` refreshes the idempotent yfinance calendar;
                    `news` is the manual twin of the news-ingest worker —
                    it builds the same `news.refresh.requested` envelope the
                    scheduler enqueues and calls the consumer's own
                    `process_payload`, so provider I/O, de-dup, the inbox
                    receipt and the `news.article.ingested` fan-out are the
                    worker's code and not a second copy
                    (+ `run-scheduler` for the Kubernetes singleton)
  schemas.py        shared Pydantic response models
  observability.py  Sentry bootstrap (no-op without DSN)
  models/           SQLModel tables (market, portfolio, user, order, option, dividend,
                    earnings, alert, comment, recommendation, watchlist, metrics, sentiment,
                    events — outbox, consumer inbox, derived trade activity,
                    execution — SimulatedExecution provenance,
                    replay — ReplaySession / ReplayPosition / ReplayFill /
                    ReplayJournal)
  events/           versioned contracts (trades/market/news), outbox/inbox,
                    dispatcher, domain handlers, Kafka producer wrappers
                    (not imported by FastAPI startup)
  workers/          outbox_publisher, scheduler (dedicated APScheduler process),
                    plus trade-activity, market ingest/analytics, news
                    ingest/sentiment, and sentiment-aggregate consumers
  benchmarks/       Kafka consumer-group scaling experiment (not domain logic).
                    Runs isolate by seek-to-end + run_id; throughput is
                    min(produced_at)→max(consumed_at), not collector wall-clock.
  routers/          /v1 endpoints, one file per resource — symbols, quotes, bars,
                    markets (one-call /markets summary), indicators, news,
                    recommendations, trading, orders, options, backtest,
                    screener, sentiment, leaderboard, watchlist, alerts,
                    comments, earnings, stream (SSE simulated quotes), replay
                    (isolated ReplaySession), health
                    (`GET /live` liveness, `GET /health` readiness + DB)
  services/
    ingest/         External-API fetchers (yfinance primary, Alpha Vantage fallback, Newsdata);
                    earnings ingestion is available through `stockviz earnings`
    indicators/     SMA/EMA/RSI/MACD pure functions
    recommend/      7-vote scorer; API now returns structured votes + rationale
    trading/        execute, orders (pending limit/stop + derived reservations),
                    simulation_adapter (PriceBar / PendingOrder → kernel types),
                    execution_provenance (SimulatedExecution writer),
                    buying_power, portfolio, analytics, dividends, fx, snapshots
    simulation/     pure deterministic execution kernel + profile registry +
                    SimulationClock. Live MARKET and pending equity fills call
                    evaluate_order with LIVE_PAPER_EXECUTION_PROFILE; apply_fill
                    remains the ledger; SimulatedExecution snapshots the
                    FillDecision. See docs/SIMULATION.md
    replay/         isolated ReplaySession book (SIM-05). Frozen ticker/range,
                    next-bar SimulationClock, server-owned PriceBar snapshots.
                    ReplayFill is isolated from Trade / apply_fill / Kafka.
                    SIM-07 forensics.py reconstructs episodes/MAE/MFE;
                    journal.py persists the first-fill-locked thesis.
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
Dockerfile          Multi-stage build with uv. Default CMD is
                    `alembic upgrade head && uvicorn` (Render). Kubernetes
                    overrides the command per workload so API replicas do
                    not migrate or run the scheduler.
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

OpenAPI docs at `/docs` when running. Liveness at `/live` (no I/O).
Readiness at `/health` (Postgres; 503 if down). Kubernetes probes those
separately; Render still uses `/health` as `healthCheckPath`.

CLI subcommands (`python -m stockviz.cli <cmd>`): `seed`, `backfill`,
`metadata`, `ingest <tickers>`, `ingest-quarantine [--ticker T] [--release ID ...]`,
`news [tickers]`, `fx`, `metrics`,
`score-sentiment`, `sentiment-aggregate`, `recommend`, `snapshot-portfolios`,
`dividends`, `credit-dividends`, `settle-options`, `run-scheduler`,
`publish-outbox [--once]`,
`consume-trade-activity [--once]`, `consume-market-ingest [--once]`,
`consume-market-analytics [--once]`, `consume-news-ingest [--once]`,
`consume-news-sentiment [--once]`, `consume-sentiment-aggregate [--once]`.

Kafka workers (same image, different command; broker optional for the API):

```powershell
pnpm events:up   # compose profile "events" — KRaft Kafka + topic init
pnpm events:publisher
pnpm events:market-ingest
pnpm events:news-ingest
# also: events:market-analytics, events:news-sentiment, events:sentiment-aggregate
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
- 10:00–16:00 hourly — `hourly_top_movers` (enqueue `market.refresh.requested`
  for `TOP_TICKERS_HOURLY`; alerts run in the analytics worker)
- 16:30 — `daily_price_refresh` (enqueue `market.refresh.requested` for every
  active symbol; no provider I/O in-process)
- 16:45 — `fx_refresh` and `pending_orders_settlement` (fill limit/stop orders against the new close)
- 16:50 — `symbol_metrics_refresh` (RSI / 52w range the screener reads)
- 16:55 — `sentiment_aggregate_refresh` (rolling per-symbol news sentiment)
- 17:00 — `recommendations_refresh`
- 17:15 — `portfolio_snapshots_refresh` (daily NAV snapshot per user)
- 17:30 — `options_expiry_refresh` (settle expired option positions)
- Every 4h at :15 (all days) — `news_refresh` (enqueue `news.refresh.requested`;
  skipped if `NEWSDATA_KEY` empty; sentiment is a Kafka worker)

`symbol_metrics_refresh` and `sentiment_aggregate_refresh` remain
full-universe **reconciliation** jobs. Kafka consumers are the incremental
path. Pending orders, options, dividends, FX, snapshots, and recommendations
stay on APScheduler.

Every job is wrapped in `@single_instance(...)`, which takes a Postgres
advisory lock. APScheduler runs in-process, so without it a scale-out to two
API instances double-fires every job — for order settlement and option expiry
that means filling the same order twice.

**Off by default.** `ENABLE_SCHEDULER=false` so pytest / CLI / local dev /
horizontally scaled API pods don't fire jobs. Render flips it on (in-process
inside FastAPI). Kubernetes keeps the flag false on API pods and runs
`python -m stockviz.workers.scheduler` as a 1-replica Deployment
(`python -m stockviz.cli run-scheduler` is the CLI twin). Advisory locks
remain defense-in-depth. Each job has a matching `stockviz.cli` subcommand
for manual re-runs (there is no separate Render cron service).

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
- **Execution kernel.** `services/simulation.evaluate_order` is a pure
  function. All live equity paper fills — MARKET (`execute_trade`) and
  pending LIMIT / STOP_LOSS / TAKE_PROFIT (`settle_pending_orders`) — call
  it with `LIVE_PAPER_EXECUTION_PROFILE` (`LEGACY_CLOSE`) and pass
  `decision.fill_price` into `apply_fill`. The same `FillDecision` is
  snapshotted as `SimulatedExecution` in the same transaction (SIM-04).
  Historical pre-SIM-04 trades may have no provenance. `get_execution_profile`
  looks up versioned profiles; unknown pairs fail with no fallback.
  `GET /v1/trades/{id}/execution` exposes provenance; `TradeOut` and
  `trade.executed.v1` are unchanged. The simulation package must stay free
  of Session, FX, settings, Kafka, and wall-clock reads. `SimulationClock`
  is constructed with an explicit instant. Account failures stay in the
  trading layer. Shared adapters live in
  `services/trading/simulation_adapter.py`. Live `observed_at` /
  `evaluated_at` is evaluation / settlement time, not `PriceBar.ts`.
- **Replay sessions** (`services/replay/`, `/v1/replay/...`): isolated
  cash/positions over a frozen ticker/`start_at`/`end_at` 1d range.
  `current_at` is the currently observable stored bar. `POST .../advance`
  moves to the next stored bar under `SELECT … FOR UPDATE`. Market and
  history never return bars after `current_at`. `GET .../summary` marks
  positions at the current replay close. `GET .../availability` returns the
  stored 1d range for the launcher. List rows omit positions (no N+1).
  Orders take intent only; fill price is the current bar close. USD
  symbols only. Cancel is manual; exhausting `end_at` marks `completed`.
  No delete endpoint; child rows cascade if a session row is removed.
  Replay Lab UI is `/replay` (SIM-06). MARKET-only in the UI.
  `GET .../forensics` is derived (episodes, MAE/MFE vs active weighted
  entry using stored daily high/low, same-symbol buy-and-hold excess,
  one-ticker concentration). Horizon is `current_at` (cancelled the
  same; completed through frozen `end_at`). `GET`/`PUT .../journal`
  stores thesis/invalidation/expected bars/confidence; those fields
  lock after the first fill (`409`); reflection stays editable.
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
only when `ALPHA_VANTAGE_KEY` is set and yfinance returned no rows. Massive is
private/nonpersistent shadow only: `MASSIVE_SHADOW_ENABLED=true` requires
`MASSIVE_API_KEY`, and candidate bars never enter persistence, events, or APIs.
An explicit `NEWS_PROVIDER=newsdata` requires `NEWSDATA_KEY`; an explicit
Anthropic/HTTP sentiment provider similarly requires its credential/endpoint.
Blank selections retain legacy key-based resolution. `stockviz.cli news` also
exits 2 rather than silently ingesting nothing.

`upsert_bars` writes in chunks of `UPSERT_CHUNK_ROWS` (1000). `price_bars`
binds 11 parameters per row, including provider provenance plus generic
adjustment/session semantics, and a full-history yfinance fetch is ~11k bars —
one multi-row INSERT of that size exceeds Postgres' 65535 parameter ceiling,
which made `stockviz.cli ingest` fail outright against Postgres.

Canonical volume is `Decimal`, but persisted volume remains `BIGINT` until a
private live Massive run establishes the required fixed scale. Fractional
values are rejected, never rounded. See
[`docs/MARKET_DATA.md`](../../docs/MARKET_DATA.md).

**Plausibility screening (F-011).** `upsert_bars` is the single choke point
for every price-bar write. Before writing it runs
`services/ingest/screening.py::screen_bar` on each bar: structurally
impossible bars (non-positive/non-finite price, `low > open|close` or
`open|close > high`, negative volume) are **rejected** with a `WARNING`;
bars with an implausible intrabar range or day-over-day move (>60%, both
tunable constants) are **quarantined** into `price_bar_quarantine`
(`QuarantinedPriceBar`) instead of `price_bars`. Nothing prices off the
quarantine table. Release a held bar with
`stockviz ingest-quarantine --release <id>`. The Kafka handler
(`persist_market_refresh`) screens too, and emits `market.bars.refreshed`
counts/close from accepted bars only. Any new write path must go through
`upsert_bars` or `screen_bars` + `write_accepted_bars`, never a raw
`PriceBar` insert. See
[market-data semantics](../../docs/database/market-data.md#plausibility-screening).

The newsdata.io query string is the **company name**, resolved by
`scheduler.company_name_map()`: `symbols.name` from the database, with
`seed-data/companies.json` layered on top. The seed file is not shipped in
the API image, and before the database layer existed the query silently
degraded to the bare ticker ("AMZN" rather than "Amazon.com Inc.").

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
