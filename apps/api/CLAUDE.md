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
                    ReplayJournal, aegis — read-only Aegis News copies)
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
                    experiments (saved backtests, Phase 5.4),
                    screener, sentiment, leaderboard, watchlist, alerts,
                    comments, earnings, stream (SSE simulated quotes), replay
                    (isolated ReplaySession), health
                    (`GET /live` liveness, `GET /health` readiness + DB)
  services/
    ingest/         External-API fetchers (yfinance primary, Alpha Vantage fallback, Newsdata);
                    earnings ingestion is available through `stockviz earnings`
    indicators/     engine.py (Phase 6.1): one OHLCV indicator registry
                    (about 20: SMA, EMA, WMA, VWAP, Supertrend, ADX, RSI,
                    MACD, Stochastic, CCI, ROC, Williams %R, Bollinger, ATR,
                    HV, Donchian, Keltner, OBV, MFI, A/D, relative volume),
                    each with a lookback; `/v1/symbols/{t}/indicators`
                    loads that many bars before the window and returns only
                    the window (audit RS-1); `/v1/indicators/catalog` lists
                    them. `compute.py`'s `compute_rsi` delegates to the
                    engine, so the screener, backtests and chart share one
                    RSI. `symbol_metrics` 52-week range = high/low of the
                    last 252 sessions (RS-14)
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
    backtest/       engine.py — historical strategy simulation. Since Phase
                    5.2 (SIM-08) fills come from the kernel and book in the
                    shared SimLedger. 5.3: `fill_rule` picks the profile
                    (`next_open` v1, the API default: next bar's open;
                    `next_close` = `legacy_close`); `spread_bps` and
                    `slippage_bps` are a kernel `CostModel` that moves the
                    fill price against the trader; `commission_bps` and
                    `fee_schedule` (`services/simulation/fees.py`: `none`,
                    `us_equity_2026` = SEC $20.60/M and FINRA TAF on sales;
                    5.6: `in_delivery_nse_2026` / `in_delivery_bse_2026` =
                    STT, exchange charge, SEBI, stamp, GST, DP per Zerodha's
                    page read 12 Nov 2026; a schedule's currency must match
                    the symbol's, else 400)
                    are fees per fill, listed per trade. Live trading passes
                    no cost model and stays on `legacy_close`. The router loads warm-up bars before
                    `from` (SMA: long window + 1; RSI: 250) that signals see
                    but nothing trades on, and the equity curve and benchmark
                    start at `from` (SR-3). Responses carry `currency`
                    (SR-11), `price_basis` (or `mixed`) and `return_mode`;
                    `return_mode: "total"` credits dividends to shares held
                    into each ex-date, strategy and benchmark alike (SR-7)
    alerts.py       price-alert evaluation
    metrics.py      precomputed per-symbol snapshot the screener reads: RSI,
                    52-week range, and (Phase 6.2) SMA 50/200, ATR %,
                    20-day volatility, 20-day average volume
    screener.py     Phase 6.2 `run_screen`: SQL filters on the snapshot joined
                    to symbol and instrument (market = country, exchange =
                    MIC, currency), momentum for every candidate BEFORE the
                    limit (audit RS-5), sort with missing values last, page.
                    Serves `GET /v1/screener` (paged, total) and the old
                    `GET /v1/symbols/screen` list. `/v1/screens` (authed)
                    saves named screens as the screener URL's query string.
                    Phase 6.5: the snapshot carries valuation as of the
                    run (P/E, P/B, P/S, EV/EBITDA, dividend yield, market
                    cap in USD, net margin, ROE, debt/equity, revenue
                    growth), each a `<column>_min`/`_max` filter and a sort
    markets/        calendar.py — exchange calendars and completed sessions (Phase 4.1)
    aegis/          Aegis News read sync (Phase 2): contract.py (lenient
                    feed models), token.py (EdDSA feed:read token), client.py
                    (the one client: timeouts, bounded retries), sync.py
                    (run_sync), read.py (documents_for_ticker)
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
uv --directory apps/api run python -m stockviz.cli backfill   # one-time, CSV → DB (--replace reloads)
pnpm api:dev                                          # uvicorn --reload on :8000
```

OpenAPI docs at `/docs` when running. Liveness at `/live` (no I/O).
Readiness at `/health` (Postgres; 503 if down). Kubernetes probes those
separately; Render still uses `/health` as `healthCheckPath`.

CLI subcommands (`python -m stockviz.cli <cmd>`): `seed`, `backfill`,
`metadata`, `ingest <tickers>`, `ingest-quarantine [--ticker T] [--release ID ...]`,
`news [tickers]`, `fx`, `metrics`, `fundamentals [--source yfinance|edgar]`,
`score-sentiment`, `sentiment-aggregate`, `recommend`, `snapshot-portfolios`,
`dividends`, `credit-dividends`, `settle-options`, `run-scheduler`,
`prune-events [--days N] [--include-unpublished]`, `aegis-sync [--max-pages N]`,
`settle-orders [--session-date YYYY-MM-DD]`, `evaluate-alerts`, `revalidate-web`,
`publish-outbox [--once]`,
`consume-trade-activity [--once]`, `consume-market-ingest [--once]`,
`consume-market-analytics [--once]`, `consume-news-ingest [--once]`,
`consume-news-sentiment [--once]`, `consume-sentiment-aggregate [--once]`.

**Pending orders and alerts when hosted (audits P0-1, P0-2).** The Railway
cron has no scheduler, so `settle-orders` and `evaluate-alerts` run in its
chain after `fx` and before `snapshot-portfolios`, against
`latest_completed_session()` (`services/ingest/bar_semantics.py`).

**Which session is complete (audit MD-3, Phase 4.1).** Exchange calendars
(`services/markets/calendar.py`, the only module importing
`exchange_calendars`) decide it: a venue's session is complete 45 minutes
after that venue's close, early closes included, and weekends and the venue's
holidays are skipped. `latest_completed_session(now, venue)` defaults to New
York (`XNYS`), which dates the nightly jobs, so the 22:00 UTC cron stores and
settles the day's own session and, on a US holiday, the session before. Bars
are filtered by their own venue (`venue_for_ticker`, from the Yahoo suffix
until instruments carry a venue: `.L` XLON, `.DE` XETR, `.TO` XTSE, `.T` XTKS,
`.NS`/`.BO` XBOM, which shares NSE's holidays). `ingest` judges each ticker
against its venue's session. Option expiry uses the last New York session on
or before expiry. Outside a calendar's range (XBOM ends 2026-12-31 in the
pinned package) the weekday rule applies and a warning is logged.

**A daily bar's date is its venue's date (Phase 4.1b).** yfinance labels a
daily bar with midnight in the venue's time zone, and `fetch_yfinance_daily`
takes that date as it is. Do not convert it to New York: before 12 Nov 2026 it
did, and every bar east of New York was stored a day early (Monday's session
under Sunday). `stockviz.cli redate-bars` (dry run; `--apply` to act) repairs
stored history: per affected ticker it fetches yfinance again and, in one
transaction, swaps the `yfinance` daily rows and their quarantine rows. Other
sources (`bulk_*`, `v1_csv`) are kept; a ticker yfinance returns nothing for is
skipped. Run it once after the fix is deployed (`services/ingest/redate.py`).

**Dividends (audit LG-12, #66).** `credit_due_dividends` credits every
uncredited ex-date on or before the run date (a missed night or a missing FX
rate is paid by the next run), only for ex-dates after the portfolio opened,
from the holding at the close before the ex-date: the current position with
trades dated (New York) on or after the ex-date undone. FX is the rate on or
before the ex-date. `portfolio_dividends` uniqueness stops double payment.

**Splits rebase the ledger once (Phase 4.2, #65).** Stored closes are
yfinance's split-adjusted series, rewritten every night, so a split divides
every old close by its ratio. `stockviz.cli corporate-actions` (after
`ingest`, before `fx` and `settle-orders` in the cron) records splits for the
tickers the ledger touches (`corporate_actions`, from `yfinance.splits`) and,
once the ex-date bar is complete on the venue, rebases each user in one
transaction (`services/corporate_actions/apply.py`): shares bought before the
cut-off and still held times r with the total cost kept; pending orders, live
alerts and open options made before the cut-off scaled likewise (options
carry `shares_per_contract`, 100 until a split changes it; value and
exercise read it, never `CONTRACT_MULTIPLIER`). Trade rows stay as filled.
`corporate_action_applications` (unique per action and user) makes it run
once. Old splits change nothing because no ledger row predates them. The
Alpha Vantage fallback is unadjusted, so `upsert_bars` lets it add only days
newer than the newest stored daily bar (audit MD-5). Replay sessions read
the same rescaled bars and are not rebased.

**A night leaves a record (audits OP-5, OP-3, OP-15).** `cli.main` writes a
`job_runs` row (`models/job_run.py`) for each command in `RECORDED_JOBS`:
`running`, then `succeeded`, `failed` (any other exit code, or an exception,
whose text is kept) or `skipped` (exit 2). Recording never changes a job's
result. `/health` adds `newest_bar`, `last_job_success_at` and `failing_jobs`
(jobs whose latest run failed); its status still depends on the database
only. The CLI starts Sentry when `SENTRY_DSN` is set. The cron refreshes the
earnings calendar nightly and symbol metadata on Mondays (both yfinance).
`tests/test_cron_chain.py` runs the real chain from `railway.ts` through the
CLI at a frozen 22:00 UTC (SQLite, and scratch PostgreSQL when
`DATABASE_URL` is one); `tests/test_migration_round_trip.py` runs the
Alembic chain up, down past this week's migrations, and up.

**Snapshots and returns (audits LG-1, LG-2, SR-4, SR-5).** Snapshots are
dated by the session their prices come from (`latest_completed_session`), not
the run date. `portfolios.opening_nav` holds the starting value for good:
analytics measure the total return from it to the **live** valuation (none
before two snapshots), drawdown runs opening → snapshots → live, and the
leaderboard measures from it. The first snapshot is not the opening: the
nightly job overwrites it if the user traded that day. The annualised return
uses calendar days over 365. Sharpe uses only returns between snapshots one
session apart (`MAX_SESSION_GAP_DAYS`) and needs `MIN_SHARPE_RETURNS` (20).

**Refresh failures are failures (audit MD-4).** `ingest` judges success by
each ticker's newest stored bar, not row counts (the full history is upserted
nightly): it exits 1 if a ticker raised (the rest still run) or if no ticker
reached the expected session, and only reports single tickers that are
behind (their market may have been closed). `fx` exits 1 when a currency gets
no rates; `dividends` exits 1 when a fetch failed. In the cron each failure
sets the exit code without stopping later steps.

**Alert rules (Phase 7.1, audit RS-8).** `alerts` rows are rules with a
`kind`: `price` (close above/below `target_price`, or `params.move_pct`, a
session move either way) and `technical` (`params`: a registry `indicator`,
`op` above/below, and `value` or `compare_to`, e.g. `close` vs `sma_200`;
`.output` names one of several outputs). `services/alerts/rules.py`
validates and words them; `services/alerts/engine.py::evaluate_pending_alerts`
judges each active rule once per new daily bar (the cron's `evaluate-alerts`
and the analytics worker both call it). A rule fires when its condition goes
from false to true; never judged before, it takes its starting state from the
newest bar known at `armed_at` (`known_at_arming`, the LG-5 rule; tests that
seed old bars turn it off in `conftest.py`, `@pytest.mark.placement_guard`
turns it back on). Session-move rules fire on each qualifying bar. `once`
rules stop after firing; `every_cross` rules wait `cooldown_sessions` bars.
Each firing is an `alert_events` row (bar date, observed value, threshold,
message) with a unique `dedupe_key` (`<rule>:<bar date>`), so a rerun writes
nothing twice. API: `GET /v1/alerts/events`, `GET /v1/alerts/{id}/events`,
`POST /v1/alerts/{id}/rearm`, `PATCH /v1/alerts/{id}` (pause). Split rebasing
scales price levels only. Migration `8ced30212d40`; existing alerts are
armed from their creation time.

**Web cache after the night (audit RS-9, Phase 6.6).** The cron's last step
is `revalidate-web`: it posts to `WEB_REVALIDATE_URL` with header
`X-StockViz-Revalidate`, an HMAC-SHA256 of `stockviz-revalidate-v1` under
`INTERNAL_API_TOKEN` (`cli.revalidate_key`; the web checks the same in
`lib/revalidate-key.ts`). Exit 2 when the URL is unset, 1 when the web
answers 401/403, 0 otherwise: an unreachable or sleeping web holds no cache.

**Watchlist rows carry their sparkline (audit RS-12, Phase 6.6).**
`WatchlistItemOut.closes` holds the last 30 daily closes, oldest first, read
for every row in one `recent_bars` query; the list and add endpoints both
use `_items_out`.

**Fundamentals, point in time (Phase 6.3).** `fundamental_facts` holds one
row per reported figure (`models/fundamentals.py`), append-only: a changed or
restated value is a new row with a later `available_at`, and
`services/fundamentals/store.py::facts_as_of` returns the version known on a
date, preferring EDGAR over yfinance for the same period. Concepts are
normalised (`concepts.py`, `MAPPING_VERSION`), outflows stored positive.
`stockviz.cli fundamentals [--source yfinance|edgar] [tickers]` (recorded
job; Fridays in the cron): yfinance for every active equity, dated by fetch
day and `point_in_time = false`; EDGAR (US equities, filing-date
`available_at`) only with `SEC_USER_AGENT`, else exit 2. The owner sets that
contact before release, so until then fundamentals are yfinance only.
`GET /v1/symbols/{t}/fundamentals?period=annual|quarter&as_of=` returns a
statement table with `sources` and `point_in_time`.

**Valuation (Phase 6.4).** `services/fundamentals/valuation.py::valuation`
computes multiples and metrics as known on a date: point-in-time facts plus
that day's close, the price converted into the reporting currency at that
day's FX when they differ (INFY.NS reports in USD, trades in INR). TTM is
four consecutive quarters, else the latest year (`basis`). A metric with
missing or meaningless inputs is null with a `reason` ("loss", "no shares
outstanding"); ROIC is pre-tax and labelled so; no forward P/E (no estimate
source). `GET /v1/symbols/{t}/valuation?as_of=` and
`/valuation/history?metric=pe&years=5` (month-end values, each as known
then, with the latest's percentile).

**Experiment registry (Phase 5.4).** `/v1/experiments` (authed):
`POST /runs` takes the same body as `POST /v1/backtest` (under `backtest`),
runs it through `services/backtest/run.py::execute_backtest` (the code the
public endpoint uses) and stores in `experiment_runs` the request, kernel
profile, fee schedule, code version (`RAILWAY_GIT_COMMIT_SHA`, else
`unknown`), a SHA-256 **dataset fingerprint** of every bar (ts, OHLC, basis)
and dividend read, warm-up included, and the full result. `POST
/runs/{id}/rerun` (`services/backtest/registry.py`) returns `identical`,
`different` (same data, different result: the code changed; the differing
fields are listed) or `data_changed` (the fingerprint moved, nothing
compared). Runs are private, capped at 500 a user. `experiments` group runs
under a name and hypothesis. `tests/test_experiment_registry.py` pins the
acceptance: a saved run reruns identically and equals the public endpoint.
Phase 5.5 adds `POST /walk-forward` and `POST /sweep`
(`services/backtest/walkforward.py`): rolling windows (default 3-year
in-sample, 1-year out-of-sample, yearly steps); each in-sample period picks
the best grid setting by Sharpe or return, the next period scores it with the
capital carried over, and the stitched out-of-sample curve is the result. A
sweep ranks every setting over the range and records how many were tried.
Grids are capped at 50 (default: 15 SMA or 16 RSI settings). Bars load once
and runs are in memory: 50 settings over ten years took 1.9 s locally, so
these run in the request. Both are stored as runs (`kind` `walk_forward` /
`sweep`) and rerun like single runs.

**Event table retention (audit OP-11).** Nothing else deletes from
`outbox_events` or `consumer_inbox`. `prune-events` deletes published outbox
rows and inbox receipts older than 30 days; `--include-unpublished` also
deletes old unsent rows, for hosts where no publisher runs. The Railway cron
runs it with that flag and sets `EVENTS_OUTBOX_ENABLED=false`, which makes the
news ingest skip its `news.article.ingested` fan-out (nothing would publish it). It also deletes
sign-in counters (`auth_rate_limits`, written by the web server's
`lib/rate-limit.ts`; audit OP-8) whose window ended more than a day ago.

**Aegis News sync (Phase 2).** `aegis-sync` copies the Aegis feed
(`GET /api/v1/feed/documents`) and the whole mapping list
(`GET /api/v1/assets/mappings`) into the `aegis_*` tables. Pages read those
tables and never call Aegis. Contract: `docs/contracts/aegis-read-v1.md` in
the workspace repository and `aegis-news/docs/feed.md`. Rules:

- StockViz mints its own 10-minute `feed:read` service token per run
  (`AEGIS_SERVICE_TOKEN_KEY`, an Ed25519 PEM; claims as Aegis's
  `mint_service_token`). Without URL, key, issuer and audience the command
  exits 2, and the cron chain skips it. Hosted, Aegis has no public domain:
  the cron reaches `http://aegis-api.railway.internal:8000`, and only the key
  is set out of band (Doppler `stock-viz-simulator/prd`, key id
  `stockviz-sync-2026-11`).
- Each feed page commits with the cursor after it (`aegis_sync_state`), so a
  run that dies resumes there and a rerun changes nothing. Every run leaves a
  row in `aegis_sync_runs` (`running`, `succeeded` or `failed` with the error).
- A bundle replaces the document's analyses, entities and events (it is the
  latest signed run). A tombstone (`withdrawal`) deletes the document.
- No article text is stored. Order and filter by `available_at`, never
  `published_at` (empty for GDELT; audit AG-12). Analyses keep provider,
  model name, version and the raw label, `mixed` included (AG-4).
- Tickers join locally: document -> `aegis_document_entities` ->
  `aegis_mappings` with `scheme='provider_id'` and
  `identifier='stockviz:<TICKER>'` (`services/aegis/read.py`), so a mapping
  seeded later links documents already held (AG-2).
- Tests use recorded responses in `tests/fixtures/aegis/`, validated against
  Aegis's own models; see the README there before changing them.
- **Readers (Phase 2 task 5).** `/v1/news`, `/v1/symbols/{ticker}/news` and
  `/v1/symbols/{ticker}/sentiment` read the `aegis_*` tables, not
  `news_articles`. `/v1/news` lists only documents linked to a StockViz
  symbol. `symbol_metrics.sentiment_7d` (the 7th signals vote and the
  screener's sentiment filter) is written by `refresh_aegis_sentiment`, run at
  the end of every `aegis-sync` (also after a failed sync) and by the
  `sentiment-aggregate` CLI and scheduler job (audit AG-14). The legacy
  `news`, `score-sentiment` and `sentiment-aggregate` steps are off the
  Railway cron; the legacy tables stay until the Aegis path is verified. The
  Kafka sentiment-aggregate consumer (events lab only) still writes the
  legacy aggregate: retiring the news workers is Phase 2 task 7.
- **Signals maximum (audit SR-9).** Each stored vote carries `available`; the
  sentiment vote is unavailable when no scored Aegis news falls in the week.
  `RecommendationOut.max_score` counts available votes (7, or 6). The pass
  threshold stays 4.

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

**The web server is exempt (audit RS-6, option 1, owner's pick 12 Nov
2026).** Its server-side calls come over Railway's private network with no
forwarded address, so they all shared one bucket. They now carry
`X-StockViz-Web: <HMAC-SHA256 of a fixed label under INTERNAL_API_TOKEN>`
(`web_server_key()`), and `limiter.py` skips every limit for a request that
carries the right value. The web limits each visitor by address instead
(`apps/web/lib/visitor-limit.ts`). Browser calls (option quotes, backtest
runs) reach the API without the header and stay limited here. The exemption
overrides slowapi's private `_check_request_limit`, because its request
filters receive no request; `tests/test_rate_limit_web_server.py` pins it.

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
- **Rupee accounts (Phase 4.8).** `PUT /v1/portfolio/base-currency`
  (`services/trading/account.py`) restarts a **fresh** account in USD
  ($100,000) or INR (₹1 crore, `STARTING_CASH`): no trades, orders, options,
  positions, dividends or foreign cash, else 409. It restates the opening
  NAV and the account's snapshots and sets the display currency to match.
  `PortfolioOut` carries `base_currency` and `base_currency_locked`.
- **Market orders** fill immediately at the latest close. Buys recompute the
  position's weighted-average `avg_cost`; sells never touch `avg_cost`, and a
  position sold to zero is **deleted**, not kept at qty 0.
  A market order is refused (409, `StaleMarketData`) when the symbol's newest
  close is from an earlier day than the newest close of any active symbol in
  its currency (#67): one ticker whose refresh failed cannot trade at a stale
  price, while weekends and holidays move every peer together. A refresh that
  failed for a whole market is not caught until exchange calendars (Phase 4).
- **Client order keys (#67, LG-10).** `POST /v1/trades` and `POST /v1/orders`
  take an optional `client_order_id` (1-64 of `A-Z a-z 0-9 _ -`), unique per
  portfolio. A repeat with the same order returns the first trade or order
  (201, same body); the same key for a different order is a 409
  (`ClientOrderIdConflict`). The lookup runs under the portfolio lock. The web
  review (`components/order-review.tsx`) makes one key each time it opens.
  Option opens take the same key (`POST /v1/options/trade`, `action: open`;
  `OptionOrderConflict`); the option ticket makes one after hydration and a
  new one after each buy. A close is safe to repeat without one: the second
  finds the contract closed.
- **Database backstops (audit LG-11).** Correctness rests on the portfolio
  lock, but the database also refuses what no writer should produce: one
  `positions` row per (portfolio, ticker), position quantity > 0 and
  `avg_cost` >= 0, `cash_balance` >= 0, trade, pending-order and option
  amounts positive (migration `5d1b8e2c4a77`). `tests/test_pg_concurrency.py`
  races each writer pair on PostgreSQL: buy reservations, sells, an option
  closed twice, cancel against settle, dividend credit twice, and one client
  key sent twice.
- **Cash is in the account's base currency** (USD, or INR since Phase 4.8).
  Trade rows store price/quantity in the symbol's native currency, and
  `trades.fx_rate` is base units per native unit: `fx.fill_rate_to_base` /
  `fx.base_rate` divide the stored USD-per-unit rates through the USD pivot
  (both legs must pass the MD-7 age check). Reservations
  (`buy_reservation`), realized P&L, snapshots (NAV in the base) and the
  journal are in the base; `TradeOut` adds `base_currency` and `total_base`,
  and `total_usd` is the base amount at the latest rate. A missing rate is a
  hard `NoFxRateError` on market orders. Option premiums are USD: an INR
  account spends USD cash first and converts the shortfall from rupees
  (`fx_conversions`), and option proceeds land in its USD balance; the
  journal counts an INR account's option closes as unavailable.
- **Pending orders** (`services/trading/orders.py`): `limit` (buy triggers at
  close ≤ limit, sell at close ≥), `stop_loss`/`take_profit` (sell-only;
  close ≤ / ≥ trigger). Checked once per day by the 16:45 settlement job and
  filled **at the close price**, not the limit price. Pending BUYs reserve
  base-currency buying power (`quantity × limit_price` at the latest FX rate); pending
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
  a failed price refresh can't fill against a stale close. An order fills only
  on a session that closed **after** it was placed (LG-5; tests that seed old
  bars turn this off through a `conftest.py` fixture, and LG-5's own tests opt
  back in with `@pytest.mark.placement_guard`). Each order commits on its own
  (LG-4). An order unfilled `ORDER_MAX_AGE_DAYS` (30) after placement becomes
  `expired` and releases its reservation (LG-6). Order inputs go through
  `services/trading/bounds.py::check_amount`: finite, positive, at most 6
  decimals, capped (LG-9).
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
  moves to the next stored bar under `SELECT … FOR UPDATE`; with
  `?expected_current_at=` (the web sends it) a repeated request after the
  session moved on changes nothing (audit SR-10). Market and
  history never return bars after `current_at`. `GET .../summary` marks
  positions at the current replay close. `GET .../availability` returns the
  stored 1d range for the launcher. List rows omit positions (no N+1).
  Orders take intent only; fill price is the current bar close. USD
  symbols only. Cancel is manual. Reaching the last bar keeps the session
  active, so that bar can be traded; advancing from it marks `completed`
  (the web's "Finish replay"). Cash and positions go through the shared
  `services/simulation/ledger.py::SimLedger` (Phase 5.1), whose arithmetic
  `tests/test_sim_ledger.py` holds equal to `apply_fill`; the backtester
  moves onto it in 5.2. `stockviz.cli benchmark-kernel` measures kernel +
  ledger throughput (about 140k fills/s locally; `test_kernel_benchmark.py`
  keeps a 10k floor).
  No delete endpoint; child rows cascade if a session row is removed.
  Replay Lab UI is `/replay` (SIM-06). MARKET-only in the UI.
  `GET .../forensics` is derived (episodes, MAE/MFE vs active weighted
  entry using stored daily high/low, same-symbol buy-and-hold excess,
  one-ticker concentration). MAE/MFE count a bar's range only for shares
  held before its fills (fills are at the close), and measure from the
  ledger's average cost, as does the episode entry (audits SR-2, SR-6).
  Horizon is `current_at` (cancelled the
  same; completed through frozen `end_at`). `GET`/`PUT .../journal`
  stores thesis/invalidation/expected bars/confidence; those fields
  lock after the first fill (`409`); reflection stays editable.
- **Options count toward NAV.** `compute_portfolio` marks open contracts to
  their Black-Scholes value (`options_market_value`). Without it, buying an
  option debited cash and recorded no offsetting asset.
- **Incomplete valuations say so (audit LG-13).** `compute_portfolio` still
  values a holding without a close and an unpriceable option at 0, and adds an
  amount without an FX rate unconverted, but each shortcut becomes a
  `ValuationWarning` (`no_close`, `no_option_price`, `no_fx_rate`), returned
  as `PortfolioOut.valuation_warnings`. The nightly snapshot refuses an
  incomplete valuation (`IncompleteValuation`, logged, not a job failure) and
  keeps the last good NAV, so a missing price never enters the equity curve,
  returns or leaderboard as a loss.
- **Option quotes (audit LG-7).** `GET /v1/options/quote` (public, 60/min)
  prices an open without placing it through `quote_option`, the function
  `open_option` charges with: spot and its date, 30-day volatility, value per
  share, premium for the contracts. Without `strike` it prices at the money
  (the latest close rounded to cents) and returns that strike.
- **Options** (`services/options/`): long-only book. Black-Scholes pricing
  with 30-day historical volatility as the IV proxy and a 5% risk-free rate;
  contracts are ×100 (`CONTRACT_MULTIPLIER`). Premiums debit the USD cash
  bucket and must honour pending-equity-BUY reservations. Option pricing is
  **not** a complete multi-currency ledger (unlike equity `apply_fill`). At
  expiry (17:30 job): ITM calls exercise into the equity book if *available*
  cash covers the strike, otherwise cash-settle intrinsic value; ITM puts
  sell *available* held shares at the strike, otherwise cash-settle; OTM
  expires worthless. Exercise goes through `apply_fill` (#62), so it writes a
  `Trade` with the equity P&L and the option leg realizes only the premium.
  A contract settles only on its **expiry session's** close: the bar dated the
  last weekday on or before expiry, or an older one once a later bar shows
  the market moved past a holiday expiry (LG-3); otherwise it stays open for
  a later run. Options remain USD-underlying only (`open_option` refuses
  others), which is why #62's FX legs are not needed yet.

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

`migrations/env.py` holds a Postgres advisory lock (`MIGRATION_LOCK_KEY`) for
the whole upgrade (audit OP-10): the API start and the cron both run
`alembic upgrade head`, and without it two runners meeting one pending
migration both applied it and one failed. The lock is a session lock because a
migration may commit part-way. `tests/test_migration_round_trip.py` starts two
real upgrades at once.

**Pence and FX age (Phase 4.5a, audits MD-2, MD-7).** yfinance quotes London
shares and dividends in pence (`GBp`) while the symbol is GBP. `upsert_bars`
divides provider bars (`yfinance`, `alpha_vantage`) by the instrument's
`quote_unit` scale (`MINOR_UNIT_SCALE`, GBX = 100), and dividend ingest does
the same; stored and seed rows are never scaled. The nightly full-history
upsert rewrites existing London rows on its first run. FX: the ingest drops a
NaN, zero or negative rate, `fx_rates` refuses one by check constraint, and a
fill converts only at a rate no older than the session before its own
(`rate_for_fill`, `fill_rate_floor`): the latest completed session for a
market order, the settled session for pending-order settlement. A stale rate
raises `NoFxRateError`, which cancels a pending order with the reason.

**Cash per currency (Phase 4.5b, design note option B).** `portfolios.cash_balance`
is the base-currency cash (`base_currency`, USD or INR); other
currencies live in `cash_balances`, written only by `services/trading/cash.py`
under the portfolio lock. In `apply_fill` a non-base sell credits its own
currency; a non-base buy spends that currency first and converts only the
shortfall from the base, writing an `fx_conversions` row (rate, rate date,
amounts, trade). The buying-power check is against that base shortfall.
Valuation adds foreign cash at the latest rate into `cash_balance` and
`total_value` (so snapshots and the leaderboard include it) and returns
`cash_by_currency`; `available_cash` stays the base's buying power. Dividends
(4.5c, migration `d61f0a3b8c27`) are paid into their own currency through
`cash.credit`; each `portfolio_dividends` row keeps `currency` and
`base_value` (the credit at the ex-date rate), and `ytd_income` sums
`base_value`. Option premiums stay in the base currency; replay is USD only.

**Instrument identity (Phase 4.3 expand, 4.4 reads).** `instruments` (venue
MIC, currency, `quote_unit`, asset type) and `instrument_identifiers` (`yahoo`
= the ticker, `aegis` = `stockviz:<ticker>`) sit beside `symbols`
(`models/instrument.py`). Every table with a `ticker` foreign key has a
nullable `instrument_id`, kept filled by triggers, so application code never
sets it: in production from migration `686dcf74171b`, and on any schema built
by `create_all` (SQLite tests, scratch Postgres) from `stockviz/db_identity.py`,
whose SQLite rules `tests/test_instrument_identity_parity.py` holds equal to
Postgres. A new symbol gets its instrument from a trigger on `symbols`;
`metadata` filling an empty exchange fills its venue.

Reads go by instrument: filter `X.instrument_id == instrument_of(ticker)` (or
`.in_(instruments_of(tickers))`) from `services/instruments`, never
`X.ticker == ticker`. `instrument_of` takes a string or a ticker column and
correlates through LATERAL joins; `resolve_symbol()` turns a public symbol
into an `Instrument`. 4.4a moved every `price_bars` read (index
`ix_price_bars_instrument_interval_ts`); 4.4b moved the ledger, alerts,
dividends, comments, earnings, news and recommendations reads. Still on
`ticker`, on purpose: the ingest dedupe lookups for dividends, earnings and
splits (they mirror unique keys that stay on `ticker` until 4.6),
`redate-bars` (scoped by source), `replay_positions` (no foreign key, so no
`instrument_id`), joins to `symbols` (keyed by ticker until 4.6), and plain
Python comparisons.

4.6a (migration `b4e2c7d9a610`) made `instrument_id` NOT NULL wherever the
ticker is (all but `news_articles`); the upgrade stops if any row is still
NULL.

4.6b (migration `e7a3c5d1f942`): **writers set `instrument_id`
themselves.** `db_identity` registers a `before_insert`/`before_update`
hook on every mapper that resolves the ticker to its current instrument on
the flush's connection, and gives each ticker model a private `noload`
relationship to `Symbol` so a symbol added in the same flush is inserted
first (a foreign key alone does not order a flush). Bulk upserts that skip
the ORM (`write_accepted_bars`, metrics `_upsert`) take ids from
`services.instruments.instrument_ids`. The Postgres triggers stay as a
backstop and write the same value. The keys are now the instrument:
`price_bars` `(instrument_id, ts, interval)`, `symbol_metrics`
`(instrument_id)` (ticker still unique), `watchlist_items`
`(watchlist_id, instrument_id)`, and the unique keys of positions,
dividends, portfolio dividends, corporate actions and earnings. Look rows up
with `metrics_for(session, ticker)` or a filter on `instrument_of(ticker)`,
never `session.get(..., ticker)`. The ticker columns, their indexes and the
`symbols.ticker` foreign keys stay. Tests seed symbols with
`tests/symbols.py::seed_symbols`: a bar for an unknown ticker is refused on
SQLite now, as Postgres always did. A new table with a `ticker` column
needs `instrument_id_column(required=True)` (or `primary_key=True`), the
trigger in a migration, and an entry in `services/instruments.TICKER_TABLES`.
`stockviz.cli instrument-check` is a read-only report of rows the triggers
missed; `instrument-verify` compares per-portfolio and per-symbol totals
read through each key, and exits 1 on any difference. Seed a `Symbol` before reading
a ticker's bars in a test: no symbol, no instrument.

**Several providers, paid ones as snapshots (Phase 4.7).** Each stored bar
keeps its `source`, and `prices.SOURCE_RANK` decides which wins for the same
instrument, day and interval: `kite` and `truedata` (3) over `yfinance` (2)
over `alpha_vantage` (1); unlisted sources (`v1_csv`, `bulk_*`) rank 0 and
are replaced as before. The Postgres upsert's `ON CONFLICT ... WHERE` and the
SQLite path both apply it, so the nightly yfinance refresh adds newer days
and never overwrites a paid snapshot. Kite (`services/ingest/providers/kite.py`)
is optional (`KITE_API_KEY`, `KITE_API_SECRET`; blank exits 2) and never
nightly: `stockviz.cli kite-login-url` prints Zerodha's login page; the owner
logs in by hand (daily tokens, an exchange rule: never automate the login)
and passes the redirect's `request_token` to `ingest-history --provider kite
[--apply] [tickers]`, which swaps it for the day's access token in memory
(never stored) and pulls every daily candle since 2000 in 2000-day requests.
Without `--apply` it only reports, per ticker, bars fetched, new days,
overlap and the largest close difference against stored bars. Applying also
records the `kite` identifier (instrument token). TrueData has no adapter
until its trial. Check a provider's redistribution terms before its bars are
shown publicly.

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

**Keys stay out of logs.** Alpha Vantage and NewsData.io take the key as
`apikey=` in the query string. Every process entry point (CLI, workers,
scheduler) calls `logging_setup.configure_logging()`, which keeps httpx and
httpcore at WARNING (their INFO lines are request URLs) and puts
`RedactSecrets` on the root handlers. `job_runs.error` goes through `redact`
too, since httpx error messages carry the URL. Never call
`logging.basicConfig` directly in a new entry point.

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
`seed-data/companies.json` layered on top. Before the database layer existed
the query silently degraded to the bare ticker ("AMZN" rather than
"Amazon.com Inc.").

**Universe (12 Nov 2026).** `seed-data/companies.json` (shipped in the API
image) holds 161 symbols: the original 32 plus 53 NSE and 76 US large caps
drawn from recent NIFTY 50 and S&P 100 membership, each checked against
yfinance for recent daily bars (not the exact index lists;
`tests/test_seed_universe.py`). New seed rows reach a database through
`stockviz.cli seed` (idempotent); the nightly ingest then backfills their full
history, and Monday's `metadata` fills sector and exchange (and so a US
listing's venue).

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
label + continuous score + optional confidence. Labels are `positive`,
`neutral`, `negative`, or `mixed` (strong signals both ways, emitted by Aegis
News; audit AG-4). `mixed` is stored as sent; StockViz's own providers and
`label_from_score` never produce it. `news_articles.sentiment` stays
as the denormalized "current best" label the badge reads. A provider never
raises for one document: unscorable inputs come back `None` and are stored as
NULL so `stockviz.cli score-sentiment` can retry them.

The legacy `refresh_symbol_sentiment` no longer feeds the hosted app: since
Phase 2, `symbol_metrics.sentiment_7d` comes from Aegis
(`services/aegis/read.py::refresh_aegis_sentiment`; see "Aegis News sync"
above). This section describes the legacy scoring pipeline, kept until it is
retired.

Full wire contract for the `http` provider: [`docs/SENTIMENT.md`](../../docs/SENTIMENT.md).
