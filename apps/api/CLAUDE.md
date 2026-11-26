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
                    `earnings` refreshes the idempotent yfinance calendar
                    (+ `run-scheduler` for the Kubernetes singleton)
  schemas.py        shared Pydantic response models
  observability.py  Sentry bootstrap (no-op without DSN)
  models/           SQLModel tables (market, portfolio, user, order, option, dividend,
                    earnings, alert, watchlist, metrics, checklist
                    (A2.4 ChecklistScore / ChecklistEvidence),
                    events — outbox, consumer inbox, derived trade activity,
                    execution — SimulatedExecution provenance,
                    replay — ReplaySession / ReplayPosition / ReplayFill /
                    ReplayJournal (A4.6: ReplayOrder, ReplayDrawing), aegis — read-only Aegis News copies,
                    setup — A2.2 Setup / SetupVersion / Thesis,
                    screen — saved screens + A2.3 ScreenRun, delivery —
                    A2.3 NotificationChannel / DeliveryAttempt,
                    drawing — A3.2 chart drawings, indicator_evidence —
                    A3.4 IndicatorEvidence, trial — A4.3 BacktestTrial /
                    HoldoutUnlock, drill — A4.7 DrillDeck / Drill,
                    trade_plan — A5.4 TradePlan (absorbed DrillPlan and
                    ReplayJournal, both archived), journal_entry — A5.5
                    JournalEntry / JournalEntryFill (round trips),
                    intraday — A6.1 IntradayBar / IntradayFile)
  (services/feeds/  A6.3: FeedProvider/BrokerProvider, SimulatedFeed, Alpaca,
                    Tiingo, Massive, Finnhub stub, intraday-backfill, feed status)
  (services/stream/ A6.5: the stream worker: minute bars from ticks, NOTIFY and
                    the SSE hub, per-bar alert judging, the SimulatedFeed replay)
  events/           versioned contracts (trades/market), outbox/inbox,
                    dispatcher, domain handlers, Kafka producer wrappers
                    (not imported by FastAPI startup)
  workers/          outbox_publisher, scheduler (dedicated APScheduler process),
                    plus trade-activity and market ingest/analytics consumers,
                    and stream (A6.5, the intraday stream worker; laptop only)
  benchmarks/       Kafka consumer-group scaling experiment (not domain logic).
                    Runs isolate by seek-to-end + run_id; throughput is
                    min(produced_at)→max(consumed_at), not collector wall-clock.
  routers/          /v1 endpoints, one file per resource — symbols, quotes, bars,
                    markets (one-call /markets summary), indicators, news,
                    checklist (A2.4), trading, orders, options, backtest,
                    experiments (saved backtests, Phase 5.4),
                    screener, sentiment, watchlist (the default list,
                    deprecated), watchlists + column_sets (A2.5), alerts, profile
                    (display currency), earnings, replay
                    (isolated ReplaySession), rules / setups / theses
                    (A2.2), notification_channels (A2.3), drawings
                    (A3.2), avwap (A3.3), events, strength (RS
                    percentile, delivery) and regime (A3.5), drills
                    (A4.7), books (A5.1), plans (A5.4), journal_entries (A5.5:
                    `/v1/journal/entries`), journal_stats (A5.6:
                    `/v1/journal/stats`), brokers (A5.7: broker
                    status), imports (A5.3: `/v1/books/{id}/imports`,
                    opening lots), health
                    (`GET /live` liveness, `GET /health` readiness + DB)
  services/
    ingest/         External-API fetchers (yfinance primary, Alpha Vantage fallback);
                    earnings ingestion is available through `stockviz earnings`
    indicators/     engine.py (Phase 6.1): one OHLCV indicator registry
                    (47 since A3.4; see "Indicator studies and evidence
                    badges"), each with a lookback and bounded parameters;
                    signals.py (A3.4: canonical signals), evidence.py
                    (A3.4: their grades); `/v1/symbols/{t}/indicators`
                    loads that many bars before the window and returns only
                    the window (audit RS-1); `/v1/indicators/catalog` lists
                    them. `compute.py`'s `compute_rsi` delegates to the
                    engine, so the screener, backtests and chart share one
                    RSI. `symbol_metrics` 52-week range = high/low of the
                    last 252 sessions (RS-14)
    checklist/      A2.4: dimensions.py (the six DSL dimensions as system
                    setups), score.py (nightly scores), evidence.py (grades)
    trading/        execute, orders (pending limit/stop + derived reservations),
                    simulation_adapter (PriceBar / PendingOrder → kernel types),
                    execution_provenance (SimulatedExecution writer),
                    buying_power, portfolio, analytics, dividends, fx, snapshots,
                    books (A5.1: resolve_book, the default book)
    books/          A5.1: book create, rename, archive, default, delete
    imports/        A5.3: Zerodha tradebook CSV: columns (the unconfirmed
                    map), parse, engine (pure holdings-only ledger, splits,
                    estimated fees), book (preview, commit, rebuild, delete,
                    opening lots)
    journal/        P&L calendar (`__init__`, `query`, `aggregate`; venue
                    dates since A5.5) and A5.5's round trips: `roundtrips.py`
                    (pure grouping, figures, R, MAE/MFE), `entries.py` (sync,
                    reads, news windows, R for chart fills), `edge.py` (A5.6:
                    stats, bootstrap, drift)
    plans/          A5.4: trade plans: record_fill (the lock), plans on
                    orders, written after entry, session plans for replay
                    and drills, outputs
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
                    A4.6: lag.py (30-day rule), orders.py (fees, resting
                    orders), context.py (indicators and events cut at the
                    clock), drawings.py (session-only drawings)
    options/        Black-Scholes-style pricing + option trade execution/settlement
    backtest/       engine.py — historical strategy simulation. Since Phase
                    5.2 (SIM-08) fills come from the kernel and book in the
                    shared SimLedger. 5.3: `fill_rule` picks the profile
                    (`next_open` v1, the API default: next bar's open;
                    `next_close` = `legacy_close`); `spread_bps` and
                    `slippage_bps` are a kernel `CostModel` that moves the
                    fill price against the trader; `commission_bps` and
                    `fee_schedule` (`services/simulation/fees.py`; A4.2:
                    date-versioned families, `auto` by default = the
                    symbol's market (NSE/BSE delivery for Indian listings,
                    `none` elsewhere); old names `us_equity_2026`,
                    `in_delivery_nse_2026`, `in_delivery_bse_2026` map to
                    `us_equity`, `in_equity_delivery_nse/_bse`; see
                    "Date-versioned costs (A4.2)"; a schedule's currency
                    must match the symbol's, else 400)
                    are fees per fill, listed per trade. Live trading passes
                    no cost model and stays on `legacy_close` (it pays the
                    default fee schedule since A4.2). The router loads warm-up bars before
                    `from` (SMA: long window + 1; RSI: 250) that signals see
                    but nothing trades on, and the equity curve and benchmark
                    start at `from` (SR-3). Responses carry `currency`
                    (SR-11), `price_basis` (or `mixed`) and `return_mode`;
                    `return_mode: "total"` credits dividends to shares held
                    into each ex-date, strategy and benchmark alike (SR-7).
                    A4.1: strategy.py (pure DSL backtester: stops, sizing,
                    R, baskets), strategy_run.py (loads rules, universe and
                    data; hash and fingerprint), fills.py (`book`: the one
                    backtest fill path through the kernel and SimLedger).
                    A4.3: report.py (pure: metrics, PSR/DSR, PBO, plateau,
                    MC fan, regime split), report_card.py, regime_history.py,
                    trials.py (families, ledger, holdout), checks.py.
                    A4.4: rotation.py (pure: top N by a DSL ranking,
                    rebalance sessions, resizing, cash filter),
                    rotation_run.py (loads, hash, fingerprint)
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
    bars/           A1.4a: resample.py (pure: daily -> 1wk/1mo, the partial
                    rule) and load.py (loads enough daily bars for n output bars);
                    A3.1: raw.py (`eod_raw` bars for `adjustment=raw`, `has_raw`)
                    A6.2: intraday.py (1m-60m from `intraday_bars`, resampled
                    within sessions, closed-bar partial rule, feeds and badges)
    markets/        calendar.py — exchange calendars and completed sessions (Phase 4.1;
                    A6.1: session_minutes, open/close in UTC with special hours);
                    india_holidays.py — the maintained NSE/BSE holiday table (A0;
                    A6.1: SPECIAL_HOURS)
    intraday/       A6.1: the owner's local intraday files: files.py (formats,
                    file name -> ticker), guard.py (local databases only),
                    partitions.py (monthly), load.py (intraday-load),
                    reconcile.py (intraday-reconcile, MoneyControl), size.py
    nse/            A1.1 NSE end-of-day files placed by hand: formats.py
                    (header detection), parse.py (+ date check), archive.py
                    (`NSE_ARCHIVE_DIR`, `data_files`), load.py (`eod_raw`,
                    `eod_extras`, ISIN identifiers), process.py (one file)
    export/         A1.6 Parquet export for the laptop's `lab/` package:
                    tables.py (what is exported), parquet.py (partitions,
                    manifest, atomic writes)
    dsl/            A2.1 Rule DSL: grammar.lark (Lark, LALR), parser.py, ast.py,
                    printer.py, canonical.py (canonical form, SHA-256 hash),
                    check.py (types), functions.py, bindings.py, pit.py
                    (fundamentals, news), timeframes.py, data.py (SymbolData,
                    load_symbol), evaluate.py (vector, point, evaluate_at),
                    drawings.py (A3.3: drawing()/avwap() values, user-scoped)
    setups/         A2.2 spine: store.py (setups and immutable versions),
                    presets.py (seeded system setups), rules.py (rule check)
    screener_rule.py  A2.2: judges a rule for every screener candidate
    screen_runs.py  A2.3: nightly members per screened setup version, diffs
    delivery/       A2.3: deliver() (outbox staging), drain(), channels.py
                    (signed webhook + SSRF rules, SMTP email, Telegram),
                    transport.py (the network edges tests stub)
    theses.py       A2.2: thesis reads (the router writes)
    drawings.py     A3.2: drawing rules per kind, position figures
    avwap.py        A3.3: anchored VWAP and its bands (pure, numpy)
    symbol_events.py  A3.5: the chart's merged event list (news clusters,
                    earnings, dividends, splits, the caller's fills)
    relative_strength.py  A3.5: RS percentile within a market, 52-week distance
    delivery_pct.py A3.5: delivery % and its 20-session average (eod_extras)
    regime.py       A3.5: rule-based market regime per market
    scan_event_study.py  A4.5: what followed a DSL trigger (A2.4's engine,
                    several horizons, dated costs, clustered t)
    drills/         A4.7: triggers.py (edges, sessions, lag, seeded draw),
                    anonymise.py (Mask: label, week shift, news counts),
                    score.py (pure process score), decks.py (create, read,
                    plan, reveal, delete)
    aegis/          Aegis News read sync (Phase 2): contract.py (lenient
                    feed models), token.py (EdDSA feed:read token), client.py
                    (the one client: timeouts, bounded retries), sync.py
                    (run_sync), read.py (documents_for_ticker, news_items,
                    daily_sentiment, refresh_aegis_sentiment)
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
`fx`, `metrics`, `fundamentals [--source yfinance|edgar]`,
`sentiment-aggregate`, `checklist`,
`checklist-evidence [--start D] [--end D] [--horizon N]`,
`indicator-evidence [--start D] [--end D] [--horizon N] [--only KEY ...]`, `snapshot-portfolios`,
`dividends`, `credit-dividends`, `settle-options`, `run-scheduler`,
`prune-events [--days N] [--include-unpublished]`, `prune-trials [--days N]`, `aegis-sync [--max-pages N]`,
`settle-orders [--session-date YYYY-MM-DD]`, `evaluate-alerts [--intraday --since T [--ticker T] [--dry-run]]`, `revalidate-web`,
`publish-outbox [--once]`,
`consume-trade-activity [--once]`, `consume-market-ingest [--once]`,
`consume-market-analytics [--once]`, `nse-load PATH ... [--apply]`,
`nse-files [--limit N]`,
`export-parquet --out DIR [--since YYYY-MM-DD] [--tables T ...]`,
`intraday-load --dir DIR --kind bulk1m|bulk1h|moneycontrol [--apply] [--create-symbols] [--only T ...]`,
`intraday-reconcile [TICKER ...] [--against daily|60m] [--interval 1m|60m] [--feed F] [--show N]`,
`intraday-size`,
`intraday-backfill --provider alpaca|tiingo|massive --symbols T ... --from D --to D [--feed iex|sip] [--apply]`,
`rule-check "<rule>" [TICKER ...] [--date YYYY-MM-DD] [--explain] [--user-id N]`,
`screen-runs`, `deliver-notifications [--channel webhook|email|telegram] [--limit N]`.
`seed` also writes the rule presets (A2.2) and the checklist dimension setups
(A2.4).

**NSE files (A1.1).** `services/nse/` parses NSE end-of-day files **placed
by hand**. Nothing downloads from NSE yet (that is A1.2, after the owner's
legal question). Formats are detected from the header (any order, case and
spaces ignored), never the file name: the CM bhavcopy in UDiFF
(`nse_cm_udiff`, since 8 Jul 2024) and legacy (`nse_cm_legacy`) layouts, and
`sec_bhavdata_full` (`nse_sec_full`); a `.zip` must hold one CSV. Values
are `Decimal`; empty or `-` is None; turnover is stored in rupees
(`TURNOVER_LACS` x 100,000). Every row must carry one date, equal to the
file name's date when it has one, and an XNSE session (special sessions
count); otherwise the file is `date_mismatch` and nothing loads.
`stockviz.cli nse-load PATH ...` is a dry run (format, date, rows, matched,
unmatched, would load; nothing written, not even the archive); `--apply`
copies each file to `NSE_ARCHIVE_DIR` (`<source>/<yyyy>/<file name>`),
writes a `data_files` row (SHA-256 unique: a file already recorded is a
no-op; status `parsed`, `date_mismatch`, `unrecognised` or `failed`) and
loads it in one transaction. Exit 1 if any file was not `parsed`. Series
`EQ BE BZ SM ST` (`load.LOAD_SERIES`) go to `eod_raw` (CM, raw exchange
numbers, never adjusted) and `eod_extras` (delivery), keyed by
(instrument, session, series), upserted, so a rerun changes nothing. Rows
match by the current `isin` identifier, else the Yahoo ticker
`<SYMBOL>.NS`; a ticker match records the ISIN (scheme `isin`, once). A
ticker match whose instrument holds a different current ISIN is counted as
a conflict and skipped. Unmatched rows are counted; no instruments are
created. Not in `RECORDED_JOBS` or the cron. `price_bars` is untouched
until A1.3. `nse-files` lists recent `data_files` rows. Tests use synthetic
files in `tests/fixtures/nse/` (real headers, invented numbers; never
commit real NSE data).

**Parquet export (A1.6, M1.8).** `stockviz.cli export-parquet --out DIR`
(`services/export/`) writes `price_bars` (`1d` only), `eod_raw`,
`eod_extras`, `corporate_actions`, `fundamental_facts` and `fx_rates` as one
zstd Parquet file per calendar month of their date column
(`<table>/year=YYYY/month=MM/part.parquet`; `ts`, `session_date`, `ex_date`,
`available_at`, `date`), and `instruments`, `instrument_identifiers` and
`data_files` (metadata only, never the raw files) whole as
`<table>/part.parquet`. It only reads the database. Rules: `Numeric(p, s)`
is Parquet `decimal(p, s)`, never float; timestamps naive UTC; rows stream
in chunks of `CHUNK_ROWS` (50,000), one month at a time, ordered by
instrument then date; each file goes to a hidden temporary name and is
renamed into place, the manifest last, so a failure never leaves a partial
file. `manifest.json` holds `schema_version` (`EXPORT_SCHEMA_VERSION`, 1;
bump it when the layout or columns change), `exported_at`, `source_commit`
(`RAILWAY_GIT_COMMIT_SHA`, else `git rev-parse HEAD`, else `unknown`), and per
partition rows, bytes, SHA-256 and min/max date. An empty table is skipped
and listed in `empty_tables`. `--since` rewrites only months on or after its
month and keeps older partitions untouched with their entries (a row added
later with an older date needs a full export); a manifest of another schema
version, or a table whose columns changed, gets a full export. Files the old
manifest listed and this run did not write are deleted; nothing else in
`DIR` is. `--tables` exports a subset and keeps the other tables' entries.
It refuses an `--out` inside the work tree that git would not ignore (exports
hold exchange data; use `lab/data/`, ignored, or a path outside the repo).
`pyarrow` is an API dependency for this; DuckDB and Polars are in `lab/`
only. Not in `RECORDED_JOBS` or the cron yet; where the export lives for the
laptop to pull is an open owner question. `tests/test_export_parquet.py`;
the reader is `lab/` (see `lab/README.md`).

**Intraday bars and the owner's files (A6.1, M2.2 foundation).** Migration
`a6b1c3d5e7f9` (additive): `intraday_files` and `intraday_bars`
(`models/intraday.py`). Design: workspace `docs/a6-design-note.md`.

- **Table.** Key `(instrument_id, feed, interval, ts)`, the only index; no
  ticker column. `ts` = the bar's **open** instant, naive UTC. `feed`
  `iex|sip|kite|file` (check), `interval` `1m|60m` (check; 60m only from
  the hourly files; 5-60 minutes over minutes are resampled on read in
  A6.2), OHLC `Numeric(18, 6)`, `volume`, `source` (`bulk_1m`, `bulk_1h`;
  later the feed's), `file_id` (to `intraday_files`), `ingested_at`,
  `available_at` (bar close, clipped at the session close). The note's key
  gained `interval` so a 60m bar and the 1m bar opening at the same instant
  both store. **PostgreSQL: `PARTITION BY RANGE (ts)`, one partition a
  month** (`intraday_bars_yYYYYmMM`, no default partition), created by the
  writer (`services/intraday/partitions.py::ensure_month_partitions`), not
  the migration; `migrations/env.py::include_object` keeps them out of
  autogenerate. SQLite (tests) gets a plain table. `price_bars` stays daily.
- **The local-only rule (owner, 26 Nov 2026): the owner's intraday files
  never go to production, demos included.** `services/intraday/guard.py`:
  the loader refuses (exit 2) unless the bound database is PostgreSQL on
  `localhost`, `127.0.0.1` or `::1` (SQLite allowed for tests); a URL with no
  host, or a query setting `host`/`hostaddr`/`service`, is refused. It is
  checked on the session's own URL, in dry runs too. **No flag, setting or
  variable overrides it**; never add one. `.railway/railway.ts` must never
  run `intraday-load` (a test reads it).
- **Loader** `stockviz.cli intraday-load --dir DIR --kind
  bulk1m|bulk1h|moneycontrol [--apply] [--create-symbols] [--only T ...]`
  (`services/intraday/load.py`; dry run by default). Formats
  (`files.py`): `<NAME>_bulk_data.csv` (1m, offset-aware),
  `<NAME>_1hr_bulk_data.csv` (60m, offset-aware; a bulk row without its
  offset is rejected, never guessed), `<YEAR>_<NAME>_1m_MoneyControl.csv`
  (naive, read as IST; reconciliation only, never written). Ticker from the
  name: `NIFTY50` -> `^NSEI`, `SENSEX` -> `^BSESN`, else `<NAME>.NS`
  (`BANKNIFTY.NS` as production names it). Unknown tickers are reported;
  `--create-symbols --apply` adds the `symbols` row (INR, NSE) and the
  identity rules make the instrument (an index name gets `asset_type
  'index'`: that is the flag that its zero volume is not real; volume is
  stored as given). Rows: unreadable or impossible ones rejected and
  counted (first lines listed, never values), repeated times are
  duplicates, a 1m bar must open inside a trading span of
  `session_minutes` and a 60m bar overlap one, else off-session (counted
  per day, not loaded). `--apply`: one transaction per file; the file in
  `intraday_files` (SHA-256 unique: name, size, counts), partitions, then
  `COPY` into a temporary table and `INSERT ... ON CONFLICT DO NOTHING`, so
  a rerun inserts nothing and a stored row is never changed. Progress line
  per file. MetaTrader commodity files are not read until the owner gives
  the server time zone; the `NIFTY/` options are A7.
- **Reconciliation** `stockviz.cli intraday-reconcile [TICKER ...]
  [--against daily|60m] [--interval 1m|60m] [--feed file] [--tolerance-pct
  0.5] [--volume-tolerance-pct 10] [--show N]` (read-only;
  `services/intraday/reconcile.py`): resample to one bar per venue date
  (first open, extremes, last close, summed volume) and compare with the
  stored daily `price_bars` or the 60m bars; a symbol "matches" at 99% of
  sessions within tolerance; volume skipped for indices. Percentages only,
  never prices. NSE daily closes are a last-30-minute VWAP, so minutes vs
  exchange daily bars differ on the close by design. `--kind moneycontrol`
  compares each MoneyControl file with the stored bulk 1m bars at the same
  UTC instants and per session (after-hours rows counted).
- **Size** `stockviz.cli intraday-size` (PostgreSQL): rows per symbol and
  interval, heap and index bytes over the partitions, bytes per row.
  Measured on the full local load (26 Nov 2026): 11,318,840 rows, 189.3
  bytes per row (2,044 MiB).
- **Parquet**: `export-parquet` exports `intraday_bars` (by month of `ts`,
  every feed and interval) and `intraday_files` (whole); `lab/` reads them
  like any table. The lake is the master copy of the owner's minutes.
- Tests (synthetic files written by each test; never the owner's rows):
  `test_intraday_load.py` (formats, naive IST = offset-aware instant,
  rejects, sessions, duplicates, idempotency, 60m overlap and availability,
  symbols, the guard and the CLI's refusal, Railway config, the COPY path and
  partitions on PostgreSQL), `test_intraday_reconcile.py`,
  `test_intraday_calendar.py`, `test_intraday_migration.py` (PostgreSQL
  up/down/up, partitions on demand, `alembic check`),
  `test_export_parquet.py`.

**Rule DSL (A2.1, M4.1).** One rule language, `services/dsl/`, for the
screens, alerts and setups A2.2 onwards builds. User reference:
`docs/rule-dsl.md`. A2.2 added the routes, tables and web editor (next
section).

- **Surface** (`grammar.lark`, Lark LALR, MIT, pinned in `uv.lock`):
  numbers, the series `open high low close volume delivery_pct
  deliverable_qty` and (A2.4) `index_close` (the venue index's close, as `rs`
  reads it: forward-filled at most 5 bars; on weekly/monthly the period's last;
  unknown without an index series), calls with positional and keyword arguments,
  `+ - * /`, `< <= > >= = !=` (`==` is `=`; comparisons never chain),
  `and or not`, parentheses, `crosses_above` / `crosses_below`, `[n]`
  offsets, `weekly.` / `monthly.` prefixes, `fundamental.<metric>`,
  `news.count(days, sentiment="...", event_type="...")`, `#` comments.
  Strings only as keyword values; names lowercase. Errors are
  `RuleError(kind, message, line, column)` (`pretty()` adds a caret).
- **Tree, canonical form, hash.** `ast.py` frozen dataclasses (`pos` is not
  compared); `parse(to_text(tree)) == tree`. `canonicalize`: arguments by
  position with defaults written out (`rsi()` is `rsi(14)`), default
  outputs dropped, `news.count` keywords sorted, `and`/`or` flattened and
  sorted by canonical text (Kleene `and`/`or` commute). Comparisons, `+` and
  `*` are never reordered. Hash = SHA-256 of the canonical text.
- **Types** (`check.py`): value `number` | `boolean`, kind `const` |
  `series` | `pit`. `fundamental.*` and `news.*` are point-in-time values:
  fine in arithmetic and comparisons, but anything built from them has no
  bar history (no `[n]`, windowed function, crossing or prefix). A rule must
  be a condition. Errors carry the column.
- **Functions** (`functions.py`): every registry indicator (45 besides
  `sma`/`ema` since A3.4) runs on the timeframe's bar frame with the
  registry's parameters, defaults and bounds (`engine.Param`: the same
  bounds the API and the chart's editor use); outputs by `.name`
  (`macd().signal`; `DEFAULT_OUTPUTS` names each multi-output study's
  default, e.g. `macd adx stoch supertrend psar pivots stochrsi tsi ppo` ->
  `macd adx k line sar pp k tsi ppo`; `bb donchian keltner ichimoku aroon
  vortex elder` must name one). `rsline` reads the venue index
  (`needs_benchmark`). The registry's `sma`/`ema` are the primitives
  on `close`. Primitives: `sma ema highest lowest sum change pct_change abs
  min max count_true bars_since rs`. `rs(n)` is 100 x ((stock n-bar
  return + 1) / (index n-bar return + 1) - 1) against
  `event_study.BENCHMARK_BY_VENUE` (`^GSPC`, `^NSEI`), index closes
  forward-filled at most 5 bars. Each function declares its lookback;
  `CompiledRule.lookback` is the rule's warm-up in daily bars (`None` for
  `bars_since`, `obv`, `ad`: whole history), and `load_symbol` loads that
  many bars before the window. A new function must join the conformance
  corpus before it is registered.
- **Three-valued logic.** Values are float arrays, conditions 1/0/NaN. A
  comparison with a missing input is unknown; `and`/`or`/`not` are
  Kleene's. `vector` returns a pandas nullable `boolean` Series (`pd.NA`
  unknown); `evaluate_at` gives `met | not_met | unknown` with reasons (the
  missing binding, or the function short of history).
- **Timeframes** (`timeframes.py`): A1.4a's periods. A period is closed on
  the venue's last session in it (Thursday before a Friday holiday); a
  weekly/monthly value on a daily bar is the last *closed* period at or
  before it, never the partial one. Prefixes do not nest; fundamentals,
  news and delivery are daily only.
- **Bindings, point in time** (`pit.py`, `data.py`): bars by instrument;
  fundamentals equal `valuation(ticker, bar date)` (facts with
  `available_at <=` the date, close converted at the FX rate on or before
  it; `tests/test_dsl_data.py`), computed once per known state; delivery
  from `eod_extras` (EQ first; "no delivery data" until NSE files load);
  news counts documents linked to the ticker with `available_at` in the
  days up to the session's close (calendar close), sentiment and event type
  as available by then; bars before the first Aegis document held are
  unknown.
- **Two modes, one evaluator.** `vector(rule, data)` over the whole frame;
  `point(rule, data, t)` = the same code on `data.cut(t)` (bars to `t`,
  facts to its date, news to its close). `tests/test_dsl_conformance.py`
  asserts `point(t) == vector[t]` for every bar of three seeded 10-year
  histories (split step, NSE holidays, partial last week, delivery gaps,
  USD-reporting INR listing, a bar hole) over 52 rules and 7 numeric
  expressions (A2.2 adds the four presets; A2.4 adds three `index_close` rules,
  one `index_close` expression and the seven checklist dimension setups; A3.4
  adds the 32 indicator signal rules (two were already there), seven rules
  for the new studies without a signal and three expressions; 444,683 point
  evaluations over 7,537 bars before them, a process pool, about a minute;
  about two minutes since A3.4), plus a test that perturbs everything after `t` and finds no
  value up to `t` changed. Vector mode: about 1.3 ms for a 5-condition rule
  over 10 years, 0.2 s for 163 symbols (synthetic, local).
- **CLI.** `stockviz.cli rule-check "<rule>" [TICKER ...] [--date]
  [--explain] [--user-id N]` (A3.3: whose drawings `drawing()`/`avwap()`
  read) prints the canonical text, hash, type and warm-up, then per
  ticker the status at the latest stored bar on or before the date
  (default: the venue's latest completed session; a stale bar is flagged)
  with reasons; `--explain` lists each sub-expression's value. Exit 2 on a
  syntax or type error, 1 for an unknown ticker or no bars. Read-only, not
  in the cron.

**Setups, theses and the screener rule (A2.2, M4.1 consumers, M4.3).** The
spine: migration `e6364eff4e51` (additive) adds `setups`, `setup_versions`,
`theses` (`models/setup.py`) and a nullable `setup_version_id` on
`saved_screens`, `alerts` and `experiment_runs` (nothing writes the last two
yet: A2.3 rule alerts, A4 rule backtests).

- **Versions are immutable.** No code path updates a `setup_versions` row;
  `services/setups/store.py::add_version` writes n+1, or returns the version
  that already has the rule (unique `(setup_id, rule_hash)` on the canonical
  hash, so spacing, comments, default arguments and `and` order do not make a
  new version). A concurrent save of the same rule loses the race and gets
  the winner's row. Caps: 200 setups a user, 500 versions a setup.
- **Presets** are setups with `user_id` null, `is_preset` (check
  `ck_setups_preset_owner`) and a unique `preset_key`. `stockviz.cli seed`
  runs `services/setups/presets.py::seed_presets` after the symbols:
  idempotent; name, kind and description follow the code; a changed rule
  becomes a new version. Four today (Minervini trend template,
  52-week-high breakout on rising volume, RSI(2) pullback in an uptrend,
  Piotroski-style quality); each description states its source and limits,
  and every preset rule is in the conformance corpus
  (`test_corpus_covers_every_function_and_is_large_enough` checks). The
  cron does not run `seed`, so a new preset reaches a host with a manual
  `seed` run or the next deploy that runs it.
- **API.** `POST /v1/rules/check` (public, 60/min; always 200: `valid`,
  `canonical`, `hash`, `type`, `warmup_bars`, `warmup_whole_history`,
  `uses`, or `error {kind, message, line, column}`). `/v1/setups` (authed):
  list (yours and presets, `include_archived`), create (rule = version 1),
  get (versions newest first), `POST /{id}/versions` (201 new, 200 when the
  rule is already a version), `POST /{id}/archive`, `POST /{id}/fork`
  (`{name?, version_id?}`; presets and your own; `forked_from_version_id`).
  `GET /v1/setups/presets` is public (60/min). Presets are 403 on versions
  and archive; another user's setup is 404; an archived setup takes no
  version (409); a rule that does not compile is 422 with the error object
  as `detail` (`services/setups/rules.py::compile_or_422`, shared by every
  writer). `/v1/theses` (authed): list (`status=`), create (`ticker`,
  `title`, `body`, optional `kill_rule`, which must compile; stores its text
  and hash), `PATCH` while open (`kill_rule: null` removes it), `POST
  /{id}/close` (`closed` | `invalidated`, final). Theses key on
  `instrument_id` (no ticker column, so no identity trigger); reads map it
  back through the `yahoo` identifier. Nothing evaluates kill rules yet.
  `/v1/screens` takes and returns `setup_version_id` (yours or a preset's,
  else 404); saving by name replaces it with what was sent.
- **Screener rule.** `GET /v1/screener?rule=` (or `setup_version_id=`: a
  preset's for anyone, your own with a Bearer token through
  `auth.OptionalUserIdDep`; not both, 400) runs after the SQL filters, which
  still pre-filter. `services/screener_rule.py` judges every remaining
  candidate (`dsl.load_symbol` + `evaluate_at`), then the screener sorts and
  pages what is left: `rule_mode=met_only` (default) keeps met rows and
  `total` counts them; `all` keeps every row. Each venue has one session:
  the newest stored daily bar of its active symbols on or before the target
  (`as_of=`, capped at the venue's latest completed session, else that
  session). A symbol without a bar that day is `unknown` ("no bar for D;
  latest D'"), never judged on stale prices. Rows add `rule_result`,
  `rule_reason` (unknown only: the evaluator's reasons) and `rule_bar_date`;
  the page adds `rule {text, canonical, hash, setup_version_id, mode, as_of,
  sessions, counts, evaluated, cached}` and, on every page, `universe`
  (`backtest/universe.py::screen_universe`: pinned, survivorship-biased).
  Latency, 5-condition rule (`rs` included) over 161 symbols x 10 years,
  in-memory SQLite on the laptop: 0.72 s cold. Results are cached in
  process per (rule hash, ticker, session) for 15 minutes, 50,000 entries
  LRU (`CACHE`; a new session is a new key): 5-30 ms warm. Each API process
  has its own cache. Tests: `tests/test_screener_rule.py`,
  `test_setups_router.py`, `test_theses_router.py`,
  `test_setups_migration.py` (PostgreSQL up/down/up); `conftest.py` clears
  the cache around every test.

**Rule alerts, screen runs and delivery (A2.3, M4.5 end of day).**
Migration `6e6c8aed50fb` (additive; its downgrade deletes `rule` alerts,
which older code cannot word): `screen_runs`, `notification_channels`,
`delivery_attempts`, `saved_screens.notify_on_change` (default false),
`notifications.data` (JSON) and check `ck_alerts_rule_has_version`.

- **Rule alerts.** `alerts.kind = 'rule'` with `setup_version_id` (your
  setup's or a preset's; another user's 404, an archived setup 409, a rule
  that no longer compiles 422) and a ticker (400 without; account-wide rule
  alerts are not in A2.3). `services/alerts/engine.py::_evaluate_rule_alerts`
  runs inside `evaluate_pending_alerts`: once per new daily bar of the
  ticker, `dsl.point` on that bar (bars, facts and news as known at its
  close). Same rules as price/technical: fires on not-true -> true,
  `known_at_arming` gives the starting state, `once` / `every_cross` +
  `cooldown_sessions`, `alert_events` keyed `<rule>:<bar date>`. **Unknown
  never fires and never counts as true**: it is stored as `last_state =
  false`, so true -> unknown -> true fires on the second true. `params`
  holds a copy of the setup's name, version, canonical text, hash and
  `preset` (written by the router, never the caller), so `describe` reads
  "AAPL: Name v2 becomes true (canonical)" without a lookup and the firing
  message names the rule. `PATCH /v1/alerts/{id}` takes `setup_version_id`
  (rule alerts only; re-arms) and `paused`, both optional. Alert
  notifications carry `data {alert_id, kind, ticker, bar_date,
  setup_version_id}`. Note: `evaluate-alerts` runs before `aegis-sync` in
  the cron, so a `news.*` rule alert sees the previous night's Aegis copy.
- **Screen runs.** `stockviz.cli screen-runs` (recorded; scheduler twin
  `screen_runs_refresh` 17:05 ET) takes every setup version a saved screen
  points at, judges it over the whole active universe with
  `screener_rule.evaluate_rule` (no cache; each venue on its latest
  completed session) and upserts `screen_runs` (unique `(setup_version_id,
  session_date)`, the job's New York session; a rerun replaces the day):
  `members` = instrument ids that were `met`, `not_evaluated` = unknown
  count (never members), `sessions` per venue, `universe` (the pinned
  stamp's name), venue `all`. Against the version's previous stored run,
  entries and exits become one `screen` notification per saved screen with
  `notify_on_change` (`source_key` `<screen id>:<session date>`, `data
  {screen_id, screen_name, setup_version_id, session_date, entries,
  exits}`), filtered by the screen query's `market`/`exchange`/`currency`
  only. A version's first run records state only. A version that no longer
  compiles is logged and skipped; an evaluation error fails the job (exit
  1) after the other versions run. `/v1/screens` takes `notify_on_change`
  (null keeps it; true needs a setup version, else 400) and `PATCH
  /v1/screens/{id}` `{notify_on_change}`.
- **Delivery (outbox).** `notify()` now calls
  `services/delivery.deliver`, which stages one `delivery_attempts` row
  (unique `(notification_id, channel)`) per channel the user enabled, the
  server can send and whose `muted_categories` lack the category, in the
  notification's transaction. `stockviz.cli deliver-notifications`
  (recorded; scheduler twin `notifications_delivery` every 15 min) drains
  due `pending` rows oldest first, one row per commit, the row locked
  `FOR UPDATE SKIP LOCKED` on PostgreSQL. Retry: retryable errors (timeout,
  connection, 408, 429, 5xx, SMTP errors) wait 1 min, 5 min, 30 min, 2 h,
  6 h (`BACKOFF_SECONDS`); attempt `MAX_ATTEMPTS` (6) or a permanent error
  (refused address, redirect, other 4xx, missing config) marks `dead` with
  `dead_at`. A row whose channel was turned off or lost its server config
  is `skipped`. It exits 0 unless it crashes (failed sends are row state);
  `--channel email|telegram` exits 2 when that channel is off here.
  Payload: `{id, category, title, body, created_at, data}`; receivers
  should de-duplicate on `id`.
- **Channels** (`services/delivery/channels.py`). Webhook: POST the
  compact, key-sorted JSON with `X-StockViz-Signature: sha256=<hex
  HMAC-SHA256 of the body under the user's secret>` and
  `X-StockViz-Timestamp` (Unix seconds), 5 s timeout, never following a
  redirect. SSRF rules on every send: https only (`http` for `localhost`,
  `127.0.0.1`, `::1` outside production only, and only those may resolve
  to loopback); no credentials in the URL; every resolved address must be
  global (private, loopback, link-local incl. 169.254.169.254, CGNAT,
  multicast, reserved refused; IPv4-mapped unwrapped); the request goes to
  the checked IP with the host in `Host` and TLS SNI, so a second DNS
  answer cannot swap it. Email: `SmtpSender` (STARTTLS, or TLS on 465)
  behind the `EmailSender` protocol, on only when `SMTP_HOST`, `SMTP_PORT`,
  `SMTP_USER`, `SMTP_PASSWORD` and `SMTP_FROM` are all set; to the
  channel's address or the account email. Telegram: `sendMessage` with
  `TELEGRAM_BOT_TOKEN` to the user's chat id. Errors never carry the
  secret, the token or a URL (httpx messages are replaced). Browser push
  is not built (needs a VAPID key pair; see `docs/KNOWN_LIMITATIONS.md`).
- **API.** `GET /v1/notifications/channels` → `{channels: [{channel,
  enabled, available, configured, url, secret_set, address, chat_id,
  muted_categories, updated_at}], categories}`; the secret is write-only.
  `PUT` `{channels: [{channel, enabled?, url?, secret?, address?,
  chat_id?, muted_categories?}]}` (null = unchanged; `secret: ""` removes
  it; at least 16 characters; URL checked without DNS; enabling a channel
  the server cannot send is 409, an unfilled one 422). `POST
  /{channel}/test` sends a test through the same sender (409 off here, 422
  not filled in, 429 past 5 a minute per channel; else 200 `{channel, ok,
  detail}`); nothing is stored. The webhook secret is stored in plain text
  in `notification_channels.secret` (not encrypted: no server key exists
  for it yet) and never returned or logged.
- **Cron.** `screen-runs` after `metrics` (so after `ingest`,
  `corporate-actions`, `aegis-sync` and Friday's `fundamentals`: every
  binding a rule reads holds tonight's data); `deliver-notifications` after
  `snapshot-portfolios` (after every notifying step) and before
  `prune-events` / `revalidate-web`. `railway config plan`/`apply` is the
  owner's. Tests: `test_rule_alerts.py`, `test_screen_runs.py`,
  `test_delivery.py` (stubbed transports), `test_a2_delivery_migration.py`,
  `test_railway_cron.py`, `test_cron_chain.py`.

**The Checklist (A2.4, M4.4).** Replaces the 7-vote Signals. Migration
`65fc5117cbf1`: `checklist_scores` and `checklist_evidence`, and
`recommendations` moved to the `archive` schema (rows, primary key, indexes
kept; its keys to `symbols`/`instruments` and its instrument trigger dropped,
restored by the downgrade, keys NOT VALID; dropping it is the owner's call).
`services/recommend/`, `routers/recommendations.py`, `/v1/recommendations`
and the `recommend` command, scheduler job and cron step are removed.

- **Dimensions** (`services/checklist/dimensions.py`): Trend, Momentum/RS,
  Volume/Delivery, Market regime, Quality, Risk/Reward, each a few named
  Rule DSL conditions with a cited source (rule text in `docs/rule-dsl.md`).
  Each is a system setup of kind `checklist` (`preset_key`
  `checklist-<key>`; seeded by `seed_dimensions`, which `seed`, both jobs and
  the first API read call, since the cron never runs `seed`); its rule is the
  `and` of its conditions, so a changed formula is a new version and
  `load_variants` finds the version by the current rule's hash. Delivery is
  an NSE/BSE figure, so Volume/Delivery has two setups: `india` (XNSE, XBOM:
  volume and `delivery_pct > 50`) and `other` (volume only); 7 setups in all.
  A dimension is met / unknown / not met by Kleene `and` (`aggregate`, tested
  equal to the DSL conjunction). Wording is neutral ("N of 6 met"); a test
  bans buy/sell words in every label and description.
- **Nightly** `stockviz.cli checklist` (recorded; scheduler `checklist_refresh`
  17:00 ET; cron after `screen-runs`, so after `metrics`, `aegis-sync` and
  Friday's `fundamentals`): every active non-index symbol on its venue's
  session (`screener_rule.venue_sessions`: the newest stored bar of the
  venue's symbols on or before its latest completed session); no bar that day
  = every dimension `unknown` ("no bar for D; latest D'"). One `load_symbol`
  per symbol with the union of needs, then `evaluate_at` (point mode) for the
  dimension rule and each condition. Upsert on (instrument, session date), so
  a rerun replaces the night. Rows: `dimensions` JSON `[{key, scope,
  setup_version_id, status, reason, conditions: [{label, rule, status,
  reason}]}]`, `met_count`, `evaluated_count`.
- **Evidence** (`services/checklist/evidence.py`, `stockviz.cli
  checklist-evidence`, recorded; Fridays in the cron, scheduler 18:00 ET
  Fridays): per dimension setup version, over the last 10 years to the latest
  New York session: event = first bar true after a bar false (vector mode;
  unknown before is not an event); outcome = forward 20-session close return
  minus the round-trip fees of the venue's schedule (`us_equity_2026`,
  `in_delivery_nse_2026`, `in_delivery_bse_2026`; 100,000 position;
  dividends not added); excess = outcome minus the same-date mean forward
  return (before costs) of every in-scope symbol of the same market; events
  within 20 bars of the last counted one on a symbol are skipped. Grade A (t
  >= 3 and mean excess >= 1%), B (t >= 2), C (t >= 1), D, or `insufficient`
  under 30 events. Data is cut at the window's end first (a test perturbs
  every later bar). Upsert on (version, universe, window, horizon). The stamp
  is `backtest/universe.py::evidence_universe` (pinned, survivorship-biased).
- **API** (public, 60/min): `GET /v1/checklist?min_met=&dimension=&sort=met|ticker&limit=&offset=`
  -> `{dimensions: [{key, name, summary, source, variants: [{scope,
  setup_id, setup_version_id, version, canonical, hash, conditions, evidence
  {grade, n_events, symbols, horizon, window_start, window_end, mean_excess,
  t_stat, hit_rate, mean_net_return, base_rate, overlapping_skipped,
  fee_schedules, universe, computed_at} | null}]}], rows: [{ticker, name,
  sector, currency, session_date, met, evaluated, total, results, computed_at,
  stale}], total, universe, disclaimer}` (latest row per instrument; `stale`
  = more than 5 days behind the venue's newest checklist session; unknown
  dimension key 400). `GET /v1/symbols/{t}/checklist` -> `{ticker,
  dimensions, row | null, universe, disclaimer}` (404 unknown or index).
- Tests: `test_checklist.py`, `test_checklist_evidence.py` (planted effect
  grades A, noise D, fees, no look-ahead, overlap), `test_checklist_migration.py`
  (PostgreSQL up/down/up with an archived row), the conformance corpus (every
  checklist setup and `index_close` rules), `test_railway_cron.py`,
  `test_cron_chain.py`.

**Indicator studies and evidence badges (A3.4, M2.6).** Pure NumPy/pandas
(no TA-Lib; design note question 2).

- **Registry** (`services/indicators/engine.py`): 47 studies. A3.4 added
  Ichimoku, HMA, DEMA, TEMA, KAMA, Parabolic SAR, pivot points (classic,
  prior bar/week/month/year), Aroon, Vortex, choppiness, TRIX, Elder ray,
  PPO, StochRSI (0-100), TSI, Ultimate oscillator, Chande momentum,
  Coppock, the RS line (`rsline`, close / venue index), ATR %, mass index,
  RMV tightness (StockViz's definition, after Deepvue's unpublished RMV),
  CMF, Chaikin oscillator, force index and ease of movement. Each `Spec`
  holds `parameters` (`Param`: name, default, `lo`/`hi`, integer or
  decimal, optional `choices`; whole numbers in [lo, hi], decimals in (lo,
  hi]); `coerce` enforces them, so `/indicators` answers 400 ("... must be
  ...") and the DSL a type error for the same values. Every study's
  largest parameters keep its lookback within the route's 5,000-bar cap
  (ADX `n` is capped at 250 for that). KAMA's warm-up is the bars until its
  seed weighs under 0.01% at the slowest smoothing (2,219 at defaults);
  Parabolic SAR is path-dependent and warms up on 250 bars (tested equal
  from different starts). **Ichimoku displacement:** each bar carries the
  cloud drawn on it, i.e. senkou A/B computed `shift` bars earlier; the 26
  bars of cloud past the last bar are not drawn and the lagging span is left
  out, so neither the chart nor a rule sees a later bar. `frame(rows,
  bench)` adds a `bench` column (index close on or before each bar,
  forward-filled at most 5) for studies with `needs_benchmark`; the router
  loads `event_study.benchmark_for(ticker)` closes only when one is asked
  for (and skips the indicator cache then).
- **Reference tests** (`tests/test_indicator_studies.py`): published
  StockCharts ChartSchool worked examples (`tests/fixtures/indicators/*.csv`,
  the columns needed from each article's `cs-*.xls`, read 26 Nov 2026) for
  CMF, A/D, KAMA, TSI (to 0.02 points: the sheet rounds its EMA
  multipliers), Ultimate oscillator, Vortex, StochRSI, price relative (RS
  line), mass index, Coppock, ease of movement and PPO's formula; small
  cases worked by hand for the rest; every new study's warm-up (window
  values independent of the start); bounds.
- **Catalog** `GET /v1/indicators/catalog` (still a list): adds per study
  `parameters [{name, label, type int|float, default, min, max,
  min_exclusive, step, choices}]`, `default_key`, `anchored`, `description`,
  `source` and `signal {rule (canonical), hash, description, source,
  evidence (the checklist's evidence shape) | null} | null`.
- **Canonical signals** (`services/indicators/signals.py`): 32 studies, each
  one Rule DSL rule on its default parameters (e.g. `rsi(14) crosses_above
  30`, MACD over its signal, close over the SMA/EMA/HMA/KAMA/..., Supertrend
  and SAR flips, Donchian breakout `close > donchian(20).upper[1]`, Aroon
  and Vortex crosses, CCI through -100, close over the cloud). Studies
  without a textbook single-bar signal (OBV, A/D, ATR, ATR %, HV, relative
  volume, pivots, RS line, RMV, mass index, Elder ray, UO, choppiness, VWAP,
  WMA) have none: "No grade", never an invented one. Every rule is in the
  conformance corpus (the test checks).
- **Evidence** (`services/indicators/evidence.py`, `stockviz.cli
  indicator-evidence [--only KEY ...]`, recorded in `job_runs`; **not in the
  scheduler or the cron**: config is deferred, run it by hand): loads every
  active non-index symbol once, then `checklist/evidence.py::study` per
  rule (same events, 20-session horizon, fees, base rate, overlap, grades,
  10-year window, pinned survivorship-biased stamp). Migration
  `d89bb4083e68` (additive): `indicator_evidence` (indicator, canonical
  rule, `rule_hash`, universe, window, horizon, the study's figures, grade,
  fee schedules), unique on (rule hash, universe, window, horizon), so a
  rerun replaces it. `latest_by_indicator` reads the newest row whose hash
  is the current rule's: a changed rule shows no grade until rerun. On
  `stockviz_e2e` (25 symbols, 26 Nov 2026) every graded signal was D except
  Supertrend (C).
- Tests: `test_indicator_studies.py`, `test_indicator_evidence.py`
  (signals on defaults, neutral wording, RSI and MACD graded on a seeded
  universe equal to the study run directly, catalog shape, bounds 400 and
  DSL errors, the RS line on the route), `test_indicator_evidence_migration.py`
  (PostgreSQL up/down/up).

**Chart events, relative strength, delivery and the regime (A3.5, M2.7,
M2.8, M3.1).** Migration `bb2ee29c23d3` (additive): `symbol_metrics`
gains `return_1m/3m/6m/12m` (percent return over 21/63/126/252 sessions),
written by the nightly `metrics` job (`services/metrics.py::_returns`).

- **Events** `GET /v1/symbols/{t}/events?from&to&types=` (`routers/events.py`,
  public, 60/min, `auth.OptionalUserIdDep`) -> `{ticker, from, to, types,
  fills_included, news_rule, events: [...]}`, a discriminated union by
  `type`: `news {date, count, sources, headlines [{id, title, source, url,
  available_at, published_at}] (up to 20 a day)}`, `earnings {date,
  report_time, fiscal_period, eps_estimate, eps_actual, surprise_pct}`,
  `dividend {date (ex-date), amount, currency}`, `split {date, ratio_from,
  ratio_to}`, `fill {date (the venue's date since A5.5), ts, side, quantity,
  price, r_multiple (A5.5: the entry's R on the fill that closes a journal
  entry, else null), book_id, journal_entry_id, closes_entry}`; oldest first, then in type order. Default range: the last 365
  days; at most 25 years (400); unknown type 400; `from > to` 400. **News
  clusters** by the UTC date of `available_at` (the field `/news` orders
  by; never `published_at`), so a day's count equals the `/news` items that
  day (tested). Titles, sources and links only: no article text.
  **Fills**: default types add `fill` only with a verified Bearer token,
  and the query joins trades to `portfolios.user_id` = the token's user;
  anonymous callers never see fills (an explicit `types=fill` returns
  none), a bad token is 401 (`services/symbol_events.py`).
- **Relative strength** `GET /v1/symbols/{t}/relative-strength`
  (`routers/strength.py`, public, 60/min): per period `{period, sessions,
  return_pct, percentile}`, `distance_from_high_52w_pct` (last close over
  the 252-session high), `universe {market, size, as_of, point_in_time:
  false, survivorship_biased: true, note}`, `method`, `reason`. Universe:
  the active non-index symbols sharing the venue index
  (`BENCHMARK_BY_VENUE`: US `^GSPC`, India `^NSEI`), on the market's newest
  metrics date (a stale symbol is not ranked). Percentile = `100 x (below +
  0.5 x tied) / (n - 1)`, null under 5 members. Ranking returns within a
  market ranks the RS line's change (same index divides every member). No
  DSL binding: an `rs_pct(n)` series would need the whole universe's
  history per bar (not cheap, not point/vector-safe today).
  `SymbolDetailOut` adds `market` (`US`/`IN`), `benchmark`,
  `benchmark_name`, `is_indian`.
- **Delivery** `GET /v1/symbols/{t}/delivery?interval=1d|1wk|1mo&from&to`
  (public, 60/min): `{applicable (NSE/BSE), has_data, avg_sessions: 20,
  points [{ts, delivery_pct, avg_20}], note}`. One value per session, EQ
  first (the DSL's order); `avg_20` = mean of the last 20 sessions holding
  a value, null before 20; weekly/monthly = the period's mean, the average
  at its last session. Empty with "No delivery data yet" until NSE files
  load (the backfill is deferred).
- **Regime** `GET /v1/regime` (public, 60/min, `Cache-Control: public,
  max-age=600`, in-process cache 10 minutes, `regime.clear_cache()`):
  per market (US `^GSPC`, India `^NSEI`) `{state, reason, as_of, inputs
  [{name, value, description}], rules [{state, rule, description, met}],
  breadth_count, breadth_universe, breadth_as_of, vol_window_sessions,
  hv_20}`, plus `method` and `disclaimer`. Inputs: `index_close`,
  `index_sma_200` (200-session SMA), `breadth_200` (% of the market's
  symbols on its newest metrics date with close > `sma_200`), `vol_pct_20`
  (percentile of the index's 20-session realised volatility, `engine.hv`,
  among its last 1,260 sessions; needs 252). Rules (`REGIME_RULES`, data,
  so the text shown is the text evaluated), read in order with Kleene
  logic: **High-vol down** `index_close < index_sma_200 and vol_pct_20 >=
  80`; **Calm trend** `index_close > index_sma_200 and breadth_200 >= 50
  and vol_pct_20 < 60`; **Choppy** otherwise. An unknown rule before a met
  one leaves the state null ("Not enough data: ... unknown"). No VIX (not
  ingested), no HMM (A9). Neutral wording; a test bans buy/sell words.
- Tests: `test_a35_chart_context.py` (merge, types, range, clustering,
  news parity, fill isolation, percentile and 52-week distance, delivery
  average and empty state, each regime state on synthetic inputs and
  series, the route), `test_a35_metrics_migration.py` (PostgreSQL
  up/down/up). On `stockviz_e2e` (no index bars) both regimes are unknown
  (US breadth 12%, 3 of 25).

**Weekly and monthly bars (A1.4a, M2.2 first half).** Resampled on read,
never stored (`services/bars/resample.py`). `GET /v1/symbols/{t}/bars` and
`/indicators` take `interval=1d|1wk|1mo` (`1h` was never written or sent and
is refused now). A week is the ISO week (Monday to Sunday) and a month the
calendar month, by the bar's venue date; open is the first session's open,
high/low the extremes, close the last session's close, volume the sum, all
`Decimal`; `ts` is the period's last stored session, `sessions` the daily
bars in it, and `source` / `adjustment_semantics` the daily bars' own or
`mixed`. Only the newest bar can be `partial`: when the venue calendar still
has a session in its period after the last stored one, or that session is
not complete at now (`session_complete_at`). Older bars have a later bar, so
their period is over (a gap in old data is not "so far"). `limit` counts
output bars; `load_resampled` reads `(n + 1) x 7` (weeks) or `x 31` (months)
daily rows and drops the oldest period when that cap was hit. `from`/`to`
select bars by their `ts`, and every bar covers its whole period. Indicators
on `1wk`/`1mo` run the same registry on resampled bars with the warm-up
counted in output bars, and leave a partial newest bar out of the inputs:
`IndicatorsOut.partial_bar_excluded` names it, `interval` says what they ran
on. `BarOut` adds `source` and `adjustment_semantics` on every interval
(null `sessions`/`partial` on `1d`). Tests: `tests/test_resample.py`,
`tests/test_bars_interval.py` (clock patched through `bars.load.now_utc`).

**Intraday intervals (A6.2, M2.2 intraday).** `services/bars/intraday.py`;
design: workspace `docs/a6-design-note.md`. `GET /v1/symbols/{t}/bars`,
`/indicators` and `/avwap` take `interval=1m|5m|15m|30m|60m` and
`feed=iex|sip|kite|file` (default: the first stored of `FEED_RANK` sip, kite,
iex, file). Nothing is stored beyond A6.1's `1m`/`60m` rows.

- **Resampling.** `1m` is the stored minutes; `5m`/`15m`/`30m` are built from
  them; `60m` is built from the minutes for every session that has any and
  is the stored hourly bar (`bulk_1h`) for a session that has none (the
  hourly files reach 2015, the minute files 2023), so one session never
  mixes the two and `source` says which. Buckets start at each trading
  span's open (`calendar.session_minutes`) and every N minutes after; the
  last one of a span is clipped at its end: NSE 60m = 09:15 ... 14:15, 15:15-15:30;
  a Muhurat evening is its own bars; the 2024 DR sessions give 09:15-10:00
  then 11:30-12:30 (never across the pause). No bar crosses a night,
  weekend or holiday. A minute outside every span is dropped; a day outside
  the calendar is bucketed from UTC midnight. OHLCV as Decimal (first open,
  extremes, last close, summed volume).
- **Fields.** `BarOut` adds `closed_at` (bucket end, clipped), `session_date`
  (the venue date), `feed`, `badge` (`FEED_BADGES`: "File (local)", "IEX
  only", "SIP", "Kite") and `minutes` (stored minutes in it); `ts` is the
  bar's **open**, naive UTC. Null on 1d/1wk/1mo. `adjustment_semantics` is
  null (the files carry no adjustment label); `adjustment=raw` is 409.
- **Partial (closed-bar semantics).** Only the newest bar: partial while
  `closed_at` > now, or while its last stored minute ends before `closed_at`
  and now < `closed_at` + `LATE_MINUTE_GRACE` (2 min). Older bars are closed
  (a gap is a gap). Clock: `intraday.now_utc` (tests patch it).
- **Limits.** `limit` counts output bars: `load_intraday` reads the newest
  `(limit + 1) x N` minutes (and drops the oldest bucket when that cap was
  hit), plus, for 60m, the stored hours of sessions without minutes inside
  that range and the newest older hours still wanted. `from`/`to` select by
  the bar's open (naive = UTC, offsets converted); a bar opening at `to`
  loads whole. Measured on the owner's local load (TCS.NS, 26 Nov 2026): 375
  1m bars 0.5 s cold, 154 60m bars 0.05 s, 1,800 60m bars 0.7 s.
- **Empty.** 404 with the reason: no intraday bars for the symbol, none from
  the asked feed, or no 1-minute bars to build 5-30m ("60m is available"). A
  range with no bars is `[]`.
- **Indicators** run the registry on these bars with the warm-up counted in
  intraday bars (loads `limit + lookback + 1`), never daily ones; a partial
  newest bar is left out (`partial_bar_excluded`); `IndicatorsOut.feed`.
  The RS line gets no index on intraday (its daily close is later in the day
  than the bar), so its series is empty.
- **AVWAP at an instant.** `anchor_at` (ISO; naive = UTC) or `anchor` (a
  date = that session's open, how a date-anchored drawing lands). 1m-30m sum
  the **1-minute** bars from the first one opening at or after the anchor
  (at most `MAX_INTRADAY_MINUTES` 100,000, else 422) and sample each chart
  bar at its last minute, keyed by the bar's open (`computed_from: "1m"`);
  60m sums the 60m chart's own bars (`"60m"`, at most 5,000).
  `AvwapOut` adds `anchor_at`, `anchor_bar_at`, `feed`. Daily unchanged.
  `services/avwap.compute_from(..., start)` is the shared maths.
- **Symbol detail** `intraday: {feed, badge, intervals, first, last, venue,
  time_zone, feeds, coverage [{feed, interval, first, last}]} | null`
  (`intraday_info`: one min/max per stored feed and interval; all five
  intervals with minutes, `["60m"]` with hourly bars only).
- **Not in A6.2:** a daily value on intraday bars (the DSL's `daily.` prefix
  and alignment: A6.4, see "Intraday rules, backtests and alerts"), live
  bars (A6.5).
- Tests: `tests/test_intraday_bars.py` (synthetic minutes: NSE 15m/60m day,
  no bar across a night, Muhurat, DR pause, off-span minutes, 60m
  precedence, hourly-only 404, partial and grace, limits and from/to, empty
  and refused cases, feed default, symbol detail, indicator warm-up and the
  partial bar, RS line empty, AVWAP at an instant on 1m and 5m, date anchor,
  60m and refusals).

**Intraday rules, backtests and alerts (A6.4, M4.5 intraday, M2.2).**
Design: workspace `docs/a6-design-note.md`. Migration `b7c2d4e6f8a1`
(additive; the downgrade refuses while an intraday version exists):
`setup_versions.feed` (`auto|iex|sip|kite|file`, default `auto`), checks
`ck_setup_versions_timeframe` (`daily|1m|5m|15m|30m|60m`) and
`ck_setup_versions_feed`, the unique key widened to `(setup_id, rule_hash,
timeframe, feed)`; `alerts.last_bar_at`, `last_fired_bar_at`;
`alert_events.bar_at`, `feed`.

- **DSL on instants** (`services/dsl/`). `compile_rule(text,
  timeframe=)`: `CompiledRule.timeframe`; the hash stays the rule text's.
  `SymbolData.timeframe` (`daily` default; every daily path is unchanged and
  the A2 conformance corpus passes as before) with, intraday, `bars` indexed
  by open instant (naive UTC), `closed_at` (ns), `sessions` (venue dates),
  `daily` (daily frame) and `feed`. `cut(t)`: bars opening at or before
  `t`, news by `t`'s close, facts dated before its session, daily bars and
  benchmark strictly before its session. `Evaluation.base` is the timeframe;
  `daily.` aligns each bar to the last daily row dated before its session
  (`searchsorted(..., "left") - 1`), `weekly.`/`monthly.` through it.
  `load_symbol_intraday` (= `intraday_bars_for` + `intraday_symbol`): closed
  bars from `load_intraday` (start + lookback, or all), the whole daily
  history when `Needs.daily`/delivery/benchmark/drawings. Lookback: intraday
  bars; a prefix adds none. Per-binding rules in `check.py` (index, `rs`,
  `rsline`, delivery and drawings only under `daily.`; fundamentals and news
  at the bar, never under `daily.`; `daily.` refused on daily). Reference:
  `docs/rule-dsl.md` ("Intraday timeframes").
- **Conformance** `tests/test_dsl_intraday_conformance.py`
  (`dsl_fixtures.intraday_universe`: synthetic minutes through the real
  resampler on NSE 26 Feb-6 Mar 2024 (2 Mar DR pause) and 28 Oct-6 Nov 2024
  (1 Nov Muhurat), XNYS 20 Nov-4 Dec 2024 (29 Nov half day)): 25 rules and
  7 expressions point = vector at every 5m bar (both symbols), every 15m and
  60m bar (NSE), 5 rules on 1m; perturbing later bars, today's and later
  daily bars, benchmark, facts and news changes nothing up to `t`;
  `daily.close` equals the previous session's close at every bar; refusals.
  `DSL_CONFORMANCE_STRIDE` applies. About 20 s locally.
- **Setups and checks.** `SetupIn`/`SetupVersionIn` take `timeframe` and
  `feed` (a daily version with a feed 422); `RuleCheckIn.timeframe`,
  `RuleCheckOut.timeframe`, `uses` may hold `daily_bars`.
  `store.version_rule(version)` compiles a version for its timeframe. Daily
  consumers refuse an intraday version: the screener and screens 400,
  screen runs skip it, `_resolve_rule(..., timeframe)` raises
  `StrategyError` (rotations, scan event studies, drills 400).
- **Backtests** (`strategy_run._intraday_input`, `strategy.run_strategy`
  with `SymbolInput.sessions`/`adv`, `flatten_at_close`,
  `same_day_schedule`, `periods_per_year`): rules in `docs/SIMULATION.md`
  ("Intraday strategy backtests (A6.4)"). `periods_per_year(ticker, tf)`;
  `report_card.build(periods_per_year=, session_days=)`;
  `engine._sharpe`, `report.sharpe_stats/metrics/regime_split` take the
  periods (252 default). Registry stamps: `timeframe`, `feed`,
  `feed_badge`, `flatten_at_close`, `periods_per_year`, `at`, `entry_at`,
  `exit_at`, `same_day`.
- **Alerts** (`services/alerts/intraday.py`): `judge_bar(session, alert,
  rule, data, bar_at, now=)` judges one **closed** bar in point mode (the
  stream worker of A6.5 calls it); state per bar instant (`last_bar_at`,
  `last_state`, `last_fired_bar_at`), same crossing, arming (`armed_at` vs
  bar close), `once`/`every_cross` with `cooldown_sessions` counted in bars;
  dedupe key `<alert>:<bar open UTC, minutes>Z`; events carry `bar_at`,
  `feed`, a message with the timeframe, the bar's close in the venue's zone
  and the feed's badge ("Replayed from stored bars, not live" for a
  replayed feed); notifications add `bar_at` and `feed`. The nightly
  `evaluate_pending_alerts` skips intraday versions. `stockviz.cli
  evaluate-alerts --intraday --since <ISO> [--ticker T] [--dry-run]` judges
  every closed stored bar from `since`, oldest first (exit 1 without
  `--since`; not recorded in `job_runs`; not in the cron).
- Tests: `test_a64_intraday.py`, `test_a64_intraday_migration.py`
  (PostgreSQL up/down/up, the refusal), the conformance file above.

**US feeds and the minute backfill (A6.3, M1.6).** `services/feeds/`; design:
workspace `docs/a6-design-note.md` ("Feed and broker interface", "Owner
decisions (26 Nov 2026)": free plans only). No migration; no web change.
**No provider was called while building it**: every adapter is tested against
hand-written fixtures (`tests/fixtures/feeds/`, documented shapes, invented
numbers; never replace them with real responses).

- **Interfaces** (`base.py`). `FeedProvider`: `name`, `label`,
  `capabilities` (`Capabilities`: `history`, `stream`, `coverage` feed tags,
  `symbols_limit`, `history_days`, `rate_limits` (`RateLimitSpec(calls,
  per_seconds)`), `notes`), `configured`, `minute_bars(symbol, start, end)
  -> list[FeedBar]` (bars opening in [start, end), oldest first; `FeedBar`
  symbol, `ts` = the bar's open as aware UTC, Decimal OHLC, int volume,
  `feed` iex|sip|kite|file, `source`) and `stream(symbols) -> AsyncIterator[Tick
  | FeedBar]` (`Tick`: symbol, ts, price, size, feed, `replayed`, `label`
  "Replayed"/"Live"). `reconnecting(connect, backoff=Backoff(base, factor,
  cap, max_attempts), sleep, on_reconnect)` wraps a stream: reconnects after
  a network or rate error (at least its `retry_after`), resets after an
  item, raises an auth/provider error at once. `BrokerProvider`: `status`,
  `login_url`, `import_fills`, `export_basket`, each a `BrokerAnswer(supported,
  reason)`; `StubBroker` (Zerodha) answers "not supported" until A6.11.
  `registry.py`: `build_feed(name, settings)`, `FEED_NAMES`,
  `KEY_ENV_VARS`, `BROKERS`. `us_symbol` refuses NSE/BSE, `^` indices and
  other venues (US feeds never get an Indian symbol); Alpaca and Massive
  write share classes `BRK.B`, Tiingo `brk-b`, StockViz keeps `BRK-B`.
- **Errors.** `FeedError(provider, fixed message, status, retry_after)`
  with `kind` `auth` (401, 403), `rate` (429), `network` (timeouts,
  connection errors, 5xx), `provider` (other 4xx, bad JSON, shapes outside
  the docs), `not_supported`. The text never holds the key, a URL query, a
  header or the provider's body; `summary` ("Alpaca auth error") is what
  `job_runs` keeps. `http.py::get_json` is the one HTTP edge: a token from
  the limiter per request, a 429 retried twice after its `Retry-After`
  (default 60 s), JSON numbers as Decimal. `FeedNotConfigured` when the key
  is blank (raised before any request).
- **Rate limits** (`ratelimit.py`): a token bucket per documented limit
  (full at start), clock and sleep injected (tests use a fake clock);
  `estimate_seconds(specs, calls)` is the plan's least waiting time.
- **SimulatedFeed** (`simulated.py`): replays stored `intraday_bars` (any
  feed, e.g. the owner's `file` minutes locally; `from_store(session,
  tickers, feed=, start=, end=)` reads 1m rows only) or given `FeedBar`s.
  One to four ticks per bar at +0/15/30/45 s: open, then low and high in
  the bar's direction (up bar: low first), then close; a repeated price is
  merged; volume split evenly, remainder on the last. Order by instant then
  symbol; `start_at` skips earlier bars; `speed` x real time (0 = no
  waiting) through an injected async sleep; `mode="bars"` yields each bar at
  its close. Labelled "Replayed", never live. For tests and A6.5.
- **Adapters** (history only; the live stream is A6.6, `stream()` raises
  `NotSupported` with that reason). Each is off until its key is set.
  - **Alpaca** (`alpaca.py`, feed `iex`, or `sip`; source `alpaca_iex` /
    `alpaca_sip`): `GET https://data.alpaca.markets/v2/stocks/{symbol}/bars`,
    `timeframe=1Min`, `start`/`end` RFC-3339 (end inclusive; the bar at
    `end` is dropped), `limit=10000`, `adjustment=split`, `feed`,
    `sort=asc`, `page_token` from `next_page_token`; headers
    `APCA-API-KEY-ID`/`APCA-API-SECRET-KEY`; rows `{t, o, h, l, c, v, n,
    vw}`, `t` = bar start (UTC). Basic plan: 200 calls a minute, IEX for
    recent data, 30 WebSocket symbols, history since 2016, **SIP only when
    the query's end is at least 15 minutes old** (`SipTooRecent` before any
    call; the backfill clips the end instead).
  - **Tiingo** (`tiingo.py`, feed `iex`, source `tiingo_iex`):
    `GET https://api.tiingo.com/iex/<ticker>/prices?startDate&endDate&resampleFreq=1min&columns=open,high,low,close,volume`
    (volume only when named, IEX-only volume), in 5-day chunks;
    `daily_bars()` reads `/tiingo/daily/<ticker>/prices` (adjusted close,
    dividends, splits; not stored by this batch). `Authorization: Token
    <key>`. Starter: 50 requests an hour, 1,000 a day, 500 symbols a month,
    1 GB a month, personal use. **Unconfirmed by the docs** (check on the
    first real run): `endDate` on IEX, the `date` format and zone (an
    instant without an offset is refused), `date` = bar start, row caps,
    error codes and bodies (a 200 with an object body is a provider error).
  - **Massive** (`massive.py`, feed `sip`, source `massive`): reuses the
    shadow adapter's `fetch_massive_minute_range`
    (`services/ingest/providers/massive.py`): `GET
    https://api.massive.com/v2/aggs/ticker/{T}/range/1/minute/{from}/{to}`,
    `adjusted=true&sort=asc&limit=50000` (base aggregates), `next_url`
    paging (its `apiKey` stripped), `Authorization: Bearer`; rows `{o, h, l,
    c, v, vw, n, t}` (ms, window start), pre/after-market included (kept out
    by session). 30-day chunks. Basic: 5 calls a minute, 2 years, no
    WebSocket. The shadow adapter's messages (which may quote Massive's
    text) become fixed ones. `MASSIVE_API_KEY` thus also enables this.
  - **Finnhub** (`finnhub.py`): stub. Stock candles are premium (a free
    key gets "You don't have access to this resource"), so no history;
    the backup stream comes in A6.6, once Finnhub's own pages are read.
- **Backfill** `stockviz.cli intraday-backfill --provider alpaca|tiingo|massive
  --symbols T ... --from YYYY-MM-DD --to YYYY-MM-DD [--feed iex|sip]
  [--apply]` (`backfill.py`). Exit 2 when the key is blank (nothing else
  runs, no row). Dry run: XNYS sessions in range (regular hours, early
  closes, none that has not opened), calls per symbol (Alpaca: pages of
  10,000 minutes; Tiingo: 5-day chunks; Massive: 30-day chunks), the rate
  limit and the least waiting; nothing fetched. Notes when the start is
  clipped to 2 years (Massive) or the end to 15 minutes ago (Alpaca SIP).
  `--apply`: per symbol, minutes inside a session span stored as
  `interval 1m` with the feed tag, `available_at` = open + 1 minute clipped
  at the close, others counted off-session; monthly partitions, then
  `INSERT ... ON CONFLICT DO NOTHING RETURNING` in chunks of 1,000, one
  commit per symbol: a rerun inserts nothing and never changes a row. A
  ticker with no instrument is listed and skipped (add it with `ingest`).
  An auth or rate error stops the run (the rest `skipped`); a network or
  provider error skips that symbol. One `job_runs` row per apply,
  `intraday-backfill-<provider>` (`FEED_BACKFILL_JOBS`), with a fixed
  summary ("Tiingo: network error on 1 symbol(s)"). Any database (US
  provider data, not the owner's files); not in `RECORDED_JOBS`, the cron
  or the scheduler (a test reads `railway.ts`). Exit 1 on bad arguments or
  a failed symbol.
- **Status** `GET /v1/broker/feeds` (authed; `status.py`): per provider
  `{provider, label, configured, state not_configured|configured|ok|error,
  key_env_vars (names), capabilities, last_success_at, last_failure_at,
  last_error}` from the newest backfill runs (`error` for 3 days, like
  Kite's `offline`). Never a key. `/v1/status` and `/health` leave
  `MANUAL_PROVIDER_JOBS` (Kite snapshot and the backfills) out.
- **Sources** (official docs, read 26 Nov 2026 with WebFetch; no account
  or key):
  - Alpaca: https://docs.alpaca.markets/reference/stockbarsingle-1 and
    https://docs.alpaca.markets/reference/stockbars (params, limits 1-10,000,
    response, 400/401/403/429, `X-RateLimit-*`),
    https://docs.alpaca.markets/docs/about-market-data-api (Basic: IEX, 30
    symbols, 200/min, since 2016, "latest 15 minutes"),
    https://docs.alpaca.markets/docs/market-data-faq (SIP end >= 15 minutes
    old, bar `t` is the interval's left side, no bar without trades),
    https://docs.alpaca.markets/docs/historical-stock-data-1,
    https://docs.alpaca.markets/docs/real-time-stock-pricing-data and
    https://docs.alpaca.markets/docs/streaming-market-data (for A6.6:
    `wss://stream.data.alpaca.markets/v2/iex`, auth and subscribe
    messages, `b` bars, error codes 402/405/406/409, one connection).
  - Tiingo: https://www.tiingo.com/documentation/iex,
    https://www.tiingo.com/documentation/end-of-day,
    https://www.tiingo.com/documentation/general/connecting (token header),
    https://www.tiingo.com/documentation/general/overview,
    https://www.tiingo.com/about/pricing (Starter limits, internal use).
  - Massive: https://massive.com/docs/rest/stocks/aggregates/custom-bars,
    https://massive.com/docs/rest/quickstart (`apiKey` or Bearer),
    https://massive.com/pricing and https://massive.com/stocks (Basic $0, 5
    calls a minute, 2 years, minute aggregates, no WebSockets).
  - Finnhub: https://finnhub.io/docs/api/stock-candles, `/websocket-trades`,
    `/rate-limit` and https://finnhub.io/pricing did not render (JavaScript
    only). Candles premium: https://github.com/finnhubio/Finnhub-API/issues/546
    and the Grafana Finnhub data-source troubleshooting page
    (https://grafana.com/grafana/plugins/clarity89-finnhub-datasource/docs/troubleshooting/).
- **Env vars** (blank = off; local `.env` only, never committed):
  `ALPACA_KEY_ID` + `ALPACA_SECRET_KEY` (both), `TIINGO_API_KEY`,
  `MASSIVE_API_KEY` (shared with the shadow), `FINNHUB_API_KEY` (status
  only until A6.6).
- Tests: `test_feeds.py` (protocols, capabilities, every adapter's parsing,
  UTC, feed tags, pagination, chunks, the SIP rule, malformed rows, error
  classes and no key in messages or logs, 429 Retry-After, token buckets on
  a fake clock, reconnect backoff, SimulatedFeed ticks, order, start, speed
  and `from_store`), `test_feed_backfill.py` (plans and clipping, regular
  minutes and availability on an early close, exit 2 without keys, dry run
  without requests, idempotent apply and `job_runs`, auth stop, network
  skip, US-only refusal, not in the cron, feed states and the route, status
  and health; PostgreSQL partitions and idempotency).

**The stream worker (A6.5, M1.6, M4.5 intraday).** `services/stream/`,
`workers/stream.py`, `routers/stream.py`; design: workspace
`docs/a6-design-note.md` ("Stream worker"). Migration `c8d3e5f7a9b2`:
`intraday_bars.feed` may be `replayed`, and `feed_streams` (model
`feed_stream.py`).

- **Run it** (laptop only during A6; nothing on Railway starts it):
  `python -m stockviz.workers.stream --replay --from-feed file --symbols
  TCS.NS --start 2026-01-05 --end 2026-01-10 [--speed 60] [--no-deliver]`.
  Symbols default to the watched ones (`replay.watched`: intraday alert
  symbols, then watchlists, capped at 30). `--feed alpaca` exits 2 (no key:
  "Offline"; with a key: the live stream is A6.6). Exit 2 also for no
  window, no symbols or no stored minutes in it.
- **Loop** (`worker.py::StreamWorker.run`): a pump task feeds an
  `asyncio.Queue` (never `wait_for` on an async generator: a timeout would
  close it). `bars.py::MinuteBarBuilder` builds 1m bars per symbol: a later
  minute's tick closes the open bar, a tick for a closed minute is `late`
  and dropped, `due(now)` closes bars a `grace` (5 s) after their minute on
  a wall-clock feed (`StreamSpec.wall_clock`), `flush()` at the end, a
  provider `FeedBar` closes at once. Replayed ticks rebuild the stored bars
  exactly (OHLCV).
- **Per closed bar** (`close_bar`, one transaction): off-session bars
  (venue calendar) are counted, not stored; otherwise `write_rows` (ON
  CONFLICT DO NOTHING) with the stream's feed (`replayed`, source
  `replay_<feed>`), `available_at` = close clipped at the session close;
  if inserted, `hub.notify_bar` (`pg_notify('intraday_bar', json)`,
  delivered at commit; no-op on SQLite); then every active intraday rule
  alert of the symbol whose version feed is in `StreamSpec.version_feeds`
  (`auto` and the replayed source feed) is judged with A6.4's `judge_bar`
  on each bar of its timeframe that this minute closed (`now` = the
  minute's close, `recorded_at` = the wall clock), only bars opening at or
  after `judge_from` (the stream's first bar: warm-up is context, never a
  firing). Rules compile once per version. Then `feed_streams` is updated.
  After the commit a firing drains deliveries at once (`delivery.drain`).
- **Replay** (`replay.py::plan_replay`): copies the source feed's bars of
  the sessions before the window into `replayed` unjudged (warm-up:
  `warmup_sessions`, the longest alert rule's lookback, at least 2), then
  loads the window into `SimulatedFeed`. Replayed bars sit beside the real
  ones and `FEED_RANK` reads them last; firings carry `feed = replayed` and
  say "Replayed from stored bars, not live".
- **Server-sent events**: `GET /v1/stream/bars?tickers=A,B` (public, 30 a
  minute, at most 10 tickers): `: connected`, then `event: bar` per stored
  minute (`hub.BarEvent`: ticker, feed, badge, interval `1m`, `ts` = open,
  `closed_at`, OHLCV strings, `replayed`) and a keep-alive comment every
  15 s. `hub.BarHub` LISTENs on its own autocommit psycopg connection in a
  thread started by the first subscriber and stopped after the last, so an
  API with no open intraday chart holds no connection; each subscriber
  has a 256-event queue that drops its oldest when full; at most 200.
- **Status**: `/v1/broker/feeds` adds `streams` (`feeds/status.py::
  stream_statuses`): name, label, `live` (false for `simulated`), state
  `streaming|closed|error`, `stale` (streaming but silent 5 minutes: shown
  closed), symbols, last tick and bar, counters, a fixed error summary.
- **Tests**: `tests/test_a65_stream_worker.py` (synthetic NSE minutes; the
  replayed done-when: firings equal A6.4's stored-bar judgement, a rerun
  adds nothing), `tests/test_a65_stream_migration.py` (PostgreSQL: up,
  down, up; a real LISTEN/NOTIFY round trip). Locally on the owner's TCS
  5m January 2026 minutes (rolled back): 25 replayed firings, the same bars
  as the stored path and the backtest.


**Raw prices on the bars route (A3.1, M2.3).** `GET /v1/symbols/{t}/bars`
takes `adjustment=adjusted|raw` (default `adjusted`, the split-adjusted
`price_bars`). `raw` reads `eod_raw` (A1.1) through `services/bars/raw.py`:
one bar per session, the first series of `RAW_SERIES_ORDER` (EQ, BE, BZ, SM,
ST, the delivery order) when a session has several; `ts` is the session date
at midnight (the naive venue label daily `price_bars` carry), `source` the
row's, `adjustment_semantics` `"raw"`. `1wk`/`1mo` resample the raw daily
bars with the same rules and partial flag (`load_raw_resampled`, same clock
as `load_resampled`); `from`/`to`/`limit` behave as on adjusted bars. An
instrument with no `eod_raw` row is **409** ("Only adjusted prices are
stored for T..."); `SymbolDetailOut.has_raw` (`has_raw()`, one indexed
lookup) tells the web whether to offer the toggle. Nothing adjusts raw rows
or fills their gaps, and indicators always run on adjusted bars. Until the
NSE backfill loads files, `has_raw` is false everywhere. Tests:
`tests/test_bars_raw.py`.

**Chart drawings (A3.2, M2.4).** Migration `f3bb96a753c6` (additive):
`drawings` (`models/drawing.py`): user (cascade), instrument (cascade, no
ticker column, like theses), `kind` (check `ck_drawings_kind`), `points`
JSON `[{ts: "YYYY-MM-DD" | null, price: "<decimal>"}]`, `style` JSON
`{colour, width 1-4, dash solid|dashed|dotted, fill_opacity 0-0.5}`
(colours `DRAWING_COLOURS`: the list palette plus `foreground`, each a web
token), `label` (80), `locked`, created/updated; index (user, instrument).
An anchor is a daily bar's venue date and a price, never a pixel; the web
maps it onto weekly/monthly bars. Rules (`services/drawings.py`):

- Points per kind (`POINT_COUNTS`): trendline, ray, rectangle, ruler,
  fib_retracement 2; channel, fib_extension, position_long, position_short
  3; hline, text 1. Prices > 0 (schema, up to 6 decimals).
- Dates must lie between the instrument's first and last stored daily bar
  (`bar_range`); nothing is anchored in the future (a ray extends on its
  own). An hline's `ts` may be null; a position's stop and target are prices
  only (`ts` must be null). Long: stop < entry < target; short: target <
  entry < stop. Fib: the first two prices differ. Text needs a label.
- 200 per user and instrument (409). A locked drawing refuses edits and
  deletes (409) unless the same PATCH sets `locked: false`.
- **API** (authed; another user's drawing is 404). `GET
  /v1/drawings?ticker=` -> `{ticker, drawings, limit, first_bar, last_bar}`
  (oldest first); `POST {ticker, kind, points, style?, label?, locked?}`
  (201); `PATCH /{id} {points?, style?, label?, locked?}` (`label: null`
  clears; re-validated); `DELETE /{id}` (204). `DrawingOut.position` carries
  `{side, entry, stop, target, risk_per_share, reward_per_share,
  reward_risk, stop_pct, target_pct}` for position tools.
- Tests: `test_drawings_router.py` (CRUD, validation per kind, isolation,
  limit, lock), `test_drawings_migration.py` (PostgreSQL up/down/up).

**Anchored VWAP and drawing references (A3.3, M2.5).** Migration
`b8d4e6f1a3c7` (additive): `ck_drawings_kind` adds `avwap`; the downgrade
deletes avwap rows, then restores the A3.2 check.

- **The kind.** One point `{ts: anchor date, price: null}` (`DrawingPoint.price`
  is nullable now; every other kind still needs a price, 422 "needs a
  price"), a label required (rules name it), the anchor within the stored
  bars. `DrawingStyle.bands` (0-2, default 0; other kinds ignore it) says
  which bands the chart draws.
- **Maths** (`services/avwap.py`, pure): from the first daily bar on or
  after the anchor, cumulative typical price ((H+L+C)/3) x volume over
  cumulative volume, float64 `cumsum` in bar order; bands = +-1/+-2
  volume-weighted standard deviation `sqrt(sum(v tp^2)/sum(v) - vwap^2)`
  (clamped at 0). A bar with a missing price or volume adds nothing; no
  value until the summed volume is above 0. A value never changes when a
  later bar arrives (tested on prefixes).
- **API.** `GET /v1/symbols/{t}/avwap?anchor=YYYY-MM-DD&interval=1d|1wk|1mo&bands=0|1|2`
  (`routers/avwap.py`, public, 60/min) -> `{ticker, anchor, anchor_bar,
  interval, bands, computed_from: "daily", decimals: 4, points: [{ts, vwap,
  upper1, lower1, upper2, lower2}]}` (bands null unless asked; values
  rounded to 4 decimals). Always from daily adjusted bars; on `1wk`/`1mo`
  each point is the daily AVWAP at the period's last stored session, which is
  the resampled bar's `ts`. 404 unknown symbol; 422 an anchor outside the
  stored daily bars, bad `bands` or `interval`.
- **DSL bindings** (`services/dsl/drawings.py`; grammar `NAME "(" STRING ")"`
  -> `ast.Ref(kind, label, output)`): `drawing("label").price` (hline: its
  price; trendline: linear by weekdays, `numpy.busday_count`, only between
  its anchors; ray: from its first point towards the second, extended;
  rectangle `.top`/`.bottom` from its left edge on) and `avwap("label")`
  (`.upper1 .lower1 .upper2 .lower2`), daily only (a prefix is a type
  error), kind `series`. Canonical: label trimmed, spaces collapsed,
  lowercased; `avwap("x").vwap` is `avwap("x")`. Lookback: a line 0, an
  AVWAP `None` (whole history). Unknown, with the reason, for: no owner
  loaded, no drawing with that label ("drawing 'x' not found", which is what
  a deleted or renamed drawing gives), two with it, a kind the binding cannot
  read, both anchors on one day, before the start / after a trendline's end,
  before the AVWAP's anchor. `SymbolData.drawings` is kept whole by `cut`
  (geometry, not data), so point = vector and the perturb test hold; the
  conformance corpus has 10 rules and 3 expressions over synthetic drawings
  (`tests/dsl_fixtures.py::_drawings`: anchors mid-history, a leftward ray, a
  weekend anchor, an AVWAP anchored in SYNC's hole, an ambiguous label).
- **User scoping.** `Needs.drawings` / `CompiledRule.user_scoped`.
  `load_symbol(..., user_id=)` loads that user's drawings on the
  instrument; without it the values are unknown. Consumers: `POST
  /v1/rules/check` returns `user_scoped` (and `uses` has `drawings`);
  `SetupVersionOut.user_scoped`; the screener refuses a user-scoped rule
  signed out (401) and judges it on the caller's drawings without the cache
  (`ScreenQuery.rule_user_id`, `ScreenerRuleOut.user_scoped`); rule alerts
  read `alert.user_id`'s; `screen-runs` reads the setup owner's;
  `rule-check --user-id N`. `store.UserScopedRule`: `add_version` refuses
  one on a preset (so `seed_setups` too), `fork` refuses another user's (403;
  their setup is 404 first anyway).
- Tests: `test_avwap.py` (hand-computed example with bands, weekend anchor,
  prefixes, weekly/monthly sampling, the route, the kind's validation),
  `test_avwap_migration.py` (PostgreSQL up/down/up), `test_dsl_drawings.py`
  (parse/type/canonical, every kind, reasons, owner-only, presets, fork,
  screener, deleted/renamed drawing and its alert, `rule-check`).

**A2 done-when (one rule, three consumers).** `tests/test_one_rule_three_consumers.py`
saves one rule as a setup version and checks, over seeded random walks for
eight tickers, that the screen (`/v1/screener?setup_version_id=&as_of=`),
rule alerts armed the session before (`evaluate_pending_alerts` after the
target bar arrives) and the vector series (symbols turning true on that
date) name the same symbols on the same session. The rule is a crossing, so
"met on the date" and "turned true on the date" are the same set.

**Backtester on the Rule DSL (A4.1, M7.1).** `POST /v1/backtest/strategy`
(`routers/backtest.py`, public, 20/min, `auth.OptionalUserIdDep`) takes
`StrategyBacktestIn`: `entry` and optional `exit` (each `{setup_version_id}`
(yours or a preset's) or `{rule}` text), `stops {fixed_pct, atr {multiple,
period}, trailing {kind atr|pct, value, period}, time_bars}` (any
combination), `sizing {kind all_in|fixed_fraction|fixed_risk, fraction,
risk_pct, max_positions}`, `universe {ticker | watchlist_id | tickers (<=
50)}`, `from`, `to`, `initial_cash`, `fill_rule` (default `next_open`),
`fee_schedule`, `commission_bps`, `slippage_bps`, `spread_bps`,
`direction long|short`, `shortable`. Errors: unknown symbol, setup version
or someone else's watchlist 404; a watchlist or a drawings rule signed out
401; a rule that does not compile 422 (the rules error object); a basket in
two currencies, a fee schedule of another currency, fixed-risk sizing
without a price stop, an index, or a short on a symbol not declared
shortable or not US-listed 400.

- **Engine** (`services/backtest/strategy.py`, pure): signals are each
  rule's vector mode on the symbol's `load_symbol` data (lookback = the
  rules' and ATRs' warm-up; `atr(n)` itself is a DSL expression); fills use
  the `Decimal` `price_bars` rows of the same dates. Replay over the union
  of the symbols' dates; an order fills on the symbol's next bar. Unknown =
  no action, counted (`unknown_entry_bars` while flat in the window,
  `unknown_exit_bars` while held; the last bar never acts). Entry while held
  is ignored (counted); a basket takes entries in universe order while a
  slot is free (`skip_reasons`: `no_slot`, `no_cash`, `atr_unknown`).
  Stops and their priority: `docs/SIMULATION.md` ("Range stops and the DSL
  backtester"); `STOP_PRIORITY` is returned on every result. Sizing in
  whole shares, never above free cash with fees: all-in (a basket: cash /
  (max positions - held)), fraction of the previous close's equity, or
  fixed risk (`risk_pct` of equity / |expected fill - tightest initial
  stop|). Trade `pnl` is net of both legs' fees; `r_multiple` = pnl /
  (qty x |entry fill - initial stop|) whenever a price stop existed. Open
  positions at the end are marked (`end_of_data`, `open`), not sold.
  Benchmark: buy and hold, equal-weight for a basket. Summary: the template
  summary (net) plus `gross_return`/`gross_final_nav` (fees and price costs
  added back), `total_fees`, `price_costs`, `trade_count`. Price return only.
- **Identity.** `strategy_hash` = SHA-256 of the rule hashes (canonical, so
  inline text and its version hash the same), stops, sizing, tickers,
  dates and costs; `data_fingerprint` = SHA-256 of every `price_bars` row
  read (warm-up included, volume too), delivery columns, benchmark closes,
  facts, news and drawings the rules loaded.
- **Registry.** `POST /v1/experiments/runs` takes `{strategy: ...}` instead
  of `{backtest: ...}` (exactly one, else 422). `save_strategy_run` refuses
  a failing run first, then turns inline text into a version of the user's
  "Rules from backtests" setup (kind `strategy`, one version per distinct
  rule), stores the request naming versions (`kind` `strategy`, `ticker`
  `AAPL` or `AAPL+4`, `setup_version_id` = the entry's) and the full
  `StrategyBacktestOut`; rerun runs it as its owner. No migration.
  The acceptance (`test_saved_strategy_reruns_identical`): entry, exit, an
  ATR stop and fixed-risk sizing rerun `identical`, and a changed bar gives
  `data_changed`.
- **Kernel.** `simulation.evaluate_range_stop` and `SimLedger.apply_short`
  are new; `evaluate_order` and `apply` are unchanged. The three-way
  equality test (live `apply_fill`, replay, backtest `fills.book`):
  `tests/test_kernel_three_way.py`, matrix in `docs/SIMULATION.md`.
- The two templates stay as they were (fractional all-in shares, total
  return, their own warm-up): not trivially equivalent to DSL strategies.
- Tests: `test_range_stop.py`, `test_strategy_engine.py`,
  `test_strategy_backtest.py`, `test_kernel_three_way.py`.

**Date-versioned costs (A4.2, M7.2).** No migration for the schedules:
they are a typed table in `services/simulation/fees.py` (families,
versions with `effective_from`/`effective_to`, components each citing
`Source` URL, title, document date and `read_on`); the rules, rates and
rerun behaviour are in `docs/SIMULATION.md` ("Costs: date-versioned fee
schedules") and every figure with its source in the workspace note
`docs/a4-cost-sources.md`. `services/fee_view.py`: the default per venue
(`DEFAULT_BY_VENUE`: XNSE/XBOM delivery, else `none`),
`resolve_fee_schedule` (`auto`), `fee_date` (the venue date of an instant)
and the API shapes (`CostsOut`, `LiquidityOut`, `FeeSchedulesOut`).

- **Routes** (`routers/fees.py`, public, 60/min): `GET /v1/fees/schedules`
  -> `{schedules: [{name, aliases, label, currency, market, segment, venue,
  coverage_from, brokerage, versions: [{effective_from, effective_to,
  start_confirmed, components: [{key, label, kind, rate, rate_text, side,
  cap, gst_on, per_scrip_day, note, source {url, title, date, read_on}}],
  notes}], notes, default_for}], defaults, default_other, brokerage_models,
  notes}`; `GET /v1/fees/estimate?ticker&side&quantity&price?&on?` (the
  order review): the ticker's default schedule on `on` (default today on its
  venue), `{schedule, label, on, effective_from, before_coverage,
  brokerage, notional, total, net_amount, lines [{key, label, amount,
  rate_text, source}], dp_note}`; 404 unknown symbol, 422 no close.
- **Backtests** (`BacktestIn`, `StrategyBacktestIn`): `fee_schedule`
  default `auto`, `brokerage` `zerodha`|`zero`, `adv_cap_pct` (default 10,
  null off). Results add `costs` and `liquidity`; the template summary adds
  `gross_return`, `gross_final_nav`, `total_fees`, `price_costs`; trades
  add `requested_shares` / `requested_quantity` and `exit_adv_pct`;
  `skip_reasons` may hold `adv_cap`. The template fingerprint hashes volume
  only when the cap is on, and the strategy hash adds `adv_cap_pct` /
  `brokerage` only when set, so runs saved before A4.2 keep both.
  `registry.as_saved` reruns a stored request without `adv_cap_pct`
  uncapped; `STAMPS_ADDED_LATER` (any depth) skips the new fields a stored
  result lacks.
- **Live paper trading.** Migration `c4f2a8e91b07` (additive, nullable):
  `trades.fees` (native currency), `fee_schedule`, `fee_lines` (JSON:
  key, label, amount, rate, effective_from, source_url). `apply_fill`
  charges `execute.fill_fees` (default schedule, version on `fee_on`, DP
  once per scrip per venue day): buys pay value + fees, sells receive value
  - fees (refused when fees exceed the value); `realized_pnl` stays the
  price gain. `charge_fees=False` books none. `buy_reservation` adds the
  estimated fees at the limit. `TradeOut` adds `fees`, `fee_schedule`,
  `fee_lines`, `net_native`, `realized_pnl_net`; `PortfolioOut` adds
  `fees_paid` and `realized_pl_net` (realized minus every fee paid, in the
  display currency). Rows before A4.2 keep NULL fees.
- **Checklist and indicator evidence** price round trips with the newest
  version of each venue's schedule (no date); `fee_schedules` keys are the
  family names now (`us_equity`, `in_equity_delivery_nse`, ...).
- Tests: `test_dated_fees.py` (version boundaries, the F&O series across
  1 Apr 2026 with sources, Zerodha calculator examples, GST base, stamp and
  STT sides, DP per scrip per day, US dates, the routes, live fills,
  reservations, defaults, the ADV cap, rerun honesty),
  `test_kernel_three_way.py`, `test_rupee_portfolios.py`.

**Report card, trial ledger, holdout (A4.3, M7.4).** Migration
`e5a7c9b1d324` (additive): `backtest_trials` and `holdout_unlocks`
(`models/trial.py`). The rules, formulas and sources are in
`docs/SIMULATION.md` ("Report card, trial ledger and the locked holdout")
and the worked PSR/DSR/PBO example in
`docs/benchmarks/2026-11-26-a4-report-card.md`.

- **Results.** `BacktestOut` and `StrategyBacktestOut` add `window`
  (`RunWindowOut`: requested range, the range used, `holdout`
  `last_20pct`|`none`, `holdout_from/to`, note), `report` (`ReportCardOut`:
  `metrics [{key, label, value, unit, formula, note}]`, `sharpe` (per-day
  and annual Sharpe, skewness, kurtosis, PSR(0), formula), `monte_carlo`
  (seeded fan) or `monte_carlo_reason`, `regimes` (rows per state)) and
  `checks` (`OverfittingChecksOut`: `trials` {family, scope, n, runs,
  variance}, `dsr`, `holdout` {status `locked|seen|none`, `unlocked_at`,
  `can_unlock`, `result`}). `checks` is built per response from the ledger and
  never stored (`registry` dumps results with `exclude={"checks"}`);
  `ExperimentRunOut.checks` is read live on full reads of `single` and
  `strategy` runs. Sweep results add `window`, `pbo` (or `pbo_reason`) and
  `plateau {sharpe, total_return}`; walk-forwards add `window`.
- **Requests.** `BacktestIn.holdout` and `StrategyBacktestIn.holdout`
  (default `last_20pct`: the run, sweeps and walk-forwards use the first 80%
  of the calendar days). `registry.as_saved` reruns a stored request without
  the field with `none`; the strategy hash adds `holdout` only when it is not
  `none`.
- **Ledger.** `POST /v1/backtest` now takes `auth.OptionalUserIdDep` too.
  Every run is recorded (`checks.record_trial` through `template_checks` /
  `strategy_checks`): public routes (`run`), saved runs (`saved`), sweep and
  walk-forward settings (`record_members`). Signed out: `user_id` NULL, one
  shared pool, nothing identifying stored. `stockviz.cli prune-trials
  [--days 365]` (not in the cron).
- **Unlock.** `POST /v1/backtest/holdout/unlock` (authed) `{backtest} |
  {strategy}`: records the family's unlock once (409 again, 400 without a
  holdout) and returns the checks with the holdout's result.
- **Regime split** reads index closes and computes breadth from stored bars
  in one SQL window query (`DATE(ts)` on SQLite, `CAST(ts AS DATE)` on
  PostgreSQL).
- `risk.engine.stationary_indices` is the bootstrap's index generator, shared
  by `block_bootstrap` (same draws as before) and the drawdown fan.
- Tests: `test_report_card.py` (each metric on a hand series, the worked
  PSR/DSR/PBO, plateau, MC by seed, regime history without look-ahead, the
  ledger recording unsaved runs and counting variants, families across
  numbers, holdout excluded from sweeps and walk-forwards, unlock once then
  seen, reruns identical after ledger writes, prune),
  `test_a43_trial_ledger_migration.py` (PostgreSQL up/down/up).

**Cross-sectional rotation (A4.4, M7.1 rotation).** `POST
/v1/backtest/rotation` (`routers/backtest.py`, public, 20/min,
`auth.OptionalUserIdDep`) takes `RotationBacktestIn`: `ranking` (inline
numeric DSL text; `setups/rules.py::compile_number` refuses a condition,
422), `top_n` (1-50), `schedule weekly|monthly`, `weighting
equal|inverse_volatility`, `buffer`, optional `cash_filter` (`{rule}` or
`{setup_version_id}`, prices and `index_close` only, else 400), `universe
{watchlist_id | tickers}` (2-50, one currency; `top_n` <= the count),
dates, costs as `StrategyBacktestIn`, `holdout`. Method in
`docs/SIMULATION.md` ("Cross-sectional rotation (A4.4)"): ranks on the
venue calendar's last session of each week or month (`rebalance_signals`;
plus the session before the window), fills on the next bar through
`fills.book`, resizes every holding to its target each rebalance (sells,
then buys; trims are `resize` round trips), cash filter on the market
index's own bars (`benchmark_for`; at most 5 sessions stale, unknown does
not act). `RotationBacktestOut`: `rules`, `timing`, `rebalances
[{signal_date, trade_dates, equity, cash_filter, skipped, ranked [{ticker,
value, rank}], unranked [{ticker, reason}], held_before, held_after,
entered, exited, weights, bought, sold, turnover, replaced_orders,
not_filled}]`, `trades` (round trips, reason `rebalance|resize|
cash_filter|end_of_data`), `equity_curve`, `summary` (net first),
`benchmark` (equal-weight hold), `turnover {rebalances,
mean_per_rebalance, total, annualised, definition}`, `costs`,
`liquidity`, `window`, `report`, `checks` (family
`trials.rotation_family`: ranking and filter skeletons, weighting,
tickers). Registry: `ExperimentRunIn.rotation` (`kind` `rotation`, request
stored as sent; rerun `identical`); `HoldoutUnlockIn.rotation`.
`POST /v1/rules/check` takes `expect: "condition"|"number"`. No migration.
Tests: `test_rotation.py` (holiday weeks and month ends, no look-ahead by
perturbing bars after a rebalance, unknown ranks excluded, cash filter
met / unknown, costs and turnover, resizing, buffer, inverse volatility,
rerun identical and data changed).

**Scan event study (A4.5, M7.3).** `POST /v1/research/scan-event-study`
(`routers/research.py`, public, 10/min, `auth.OptionalUserIdDep`;
`services/scan_event_study.py`) takes `ScanEventStudyIn`: `trigger`
(`{rule}` | `{setup_version_id}`), `universe {tickers (<= 50) |
watchlist_id | market US|IN}` (a market over 300 symbols 400), optional
`from`/`to` (default the last 10 years to the latest completed session),
`horizons` (default 5, 20, 60), `cooldown` (0-250 sessions). It runs
`checklist/evidence.py::study_horizons` (A2.4's engine, generalised):
event = false-to-true edge in vector mode (a session after an unknown one
is not an event), cooldown skips an edge within N bars of the previous
event on its symbol; per horizon an event without its window is
`incomplete`; outcome net of a round trip at the venue's schedule
(`schedule_for`) version in force on each leg's date (`dated_costs`);
base rate per (market, date) over all symbol-days. `study()` (the
checklist and indicator grades) is `study_horizons(..., horizons=(h,))`
with the old per-horizon overlap rule and undated costs, held equal to the
pre-A4.5 code by `test_study_equals_the_pre_a45_engine`. Output per
horizon: `n`, `symbols`, `incomplete`, `overlapping`, `enough` (>= 30),
`base_rate`, mean and median net and excess, `hit_rate` (net > 0),
`hit_rate_excess`, `t_stat` (A2.4's), `t_stat_clustered` (by event date,
CR1) and `clusters`, `net_percentiles`, `excess_percentiles`, `histogram`
(20 bins, 1st-99th percentile); stats null under the minimum. Plus
`events` (newest 200, net and excess per horizon), `events_found`,
`events_skipped_cooldown`, `method`, `universe` (`evidence_universe`) and
`disclaimer`. Errors: rule 422, unknown symbol/setup/watchlist 404,
watchlist signed out 401. Tests: `test_scan_event_study.py`.

**Replay in any currency (A4.6, M9.1, M9.2).** Migration `a6c4e2f8b913`
(additive): `replay_sessions.currency` (default `USD`), `fee_schedule`
(default `none`), `lag_override` (default false); `replay_fills.fees`
(default 0), `fee_lines`, `order_id` (to `replay_orders`, SET NULL); new
`replay_orders` (checks `ck_replay_orders_type`, `ck_replay_orders_status`)
and `replay_drawings` (both cascade from the session). Rules and the method
in `docs/SIMULATION.md` ("Replay in any currency, the lag, the chart and
resting orders").

- **Currency, cash, fees.** A session takes the symbol's currency;
  `starting_cash` omitted = `DEFAULT_CASH_BY_CURRENCY` ($100,000, ₹10,00,000,
  else 100,000). Fees: `resolve_fee_schedule("auto", ticker)` frozen on the
  session; `orders.replay_fill_fees` prices each fill on the bar's venue date
  with DP once per bar's sells, booked through `SimLedger` like live and
  backtests. An index session (`is_index_ticker`) is watch-only:
  orders 400 `ReplayNotTradable`. `ReplaySessionOut` adds `currency`,
  `fee_schedule`, `lag_override`, `tradable`, `open_orders`; the list rows
  `currency`; the summary `currency`, `fees_paid`; fills `fees`, `fee_lines`,
  `order_id`; forensics `currency` and episode `fees` (`realized_pnl` net).
- **Lag** (`services/replay/lag.py`): XNSE/XBOM sessions must end
  `REPLAY_MIN_LAG_DAYS` (30) days before the venue's today, else 400
  `ReplayLagError` naming the latest allowed end. Owner-only override:
  `REPLAY_LAG_OVERRIDE_USER_IDS` (empty). Availability adds `lag_days`,
  `max_end`, `lag_waived`, `default_starting_cash`, `fee_schedule`,
  `tradable`. `create_replay_session(today=)` for tests.
- **Routes** (authed, `routers/replay.py`): `GET .../orders`, `POST
  .../orders/{order_id}/cancel` (404 another session's, 409 not open);
  `POST .../orders` with a non-market type returns `{session, decision:
  null, order}`; `GET .../indicators?names=` (`IndicatorsOut`, daily, the
  registry's grammar; `context.replay_indicators`); `GET .../events`
  (`ReplayEventsOut`: news with `available_at <= current_at` via
  `symbol_events.news_clusters(available_until=)`, and the session's fills);
  `GET`/`POST .../drawings`, `PATCH`/`DELETE .../drawings/{id}` (A3.2's
  validation with anchors from the first bar to the clock; avwap 422).
- **Orders** (`services/replay/orders.py`): placed at the clock, judged from
  the next bar by `evaluate_open_orders` inside `advance_replay_session`
  (same lock and transaction), fills freeze the journal; rejected with the
  reason when the book cannot pay or deliver; expired on completion,
  cancelled with the session; 20 open at most.
- Tests: `test_replay_a46.py` (the acceptance: rupees, lag refusal and
  override, indicators and news at every step against future bars and the
  live route, drawings isolation, resting orders, DP, forensics net, no
  prize), `test_replay_a46_migration.py` (PostgreSQL up/down/up),
  `test_kernel_three_way.py` (INR replay compared, skip removed).

**Drills and decks (A4.7, M9.3).** Migration `53b66a2e2ec2` (additive):
`drill_decks` (rule as a setup version, universe JSON, range, `k` 1-25,
`lead_bars`/`follow_bars`, `seed`, `anonymised` default true, trigger
counts), `drills` (deck cascade, `position`, replay `session_id` cascade
and unique, ticker, `trigger_at`/`trigger_date`, `date_offset_weeks`,
`revealed_at`) and `drill_plans` (keyed on the replay session, unique,
cascade; entry, stop, size, long only, `locked_at`). Rules and method in
`docs/SIMULATION.md` ("Drills and decks").

- **Triggers** (`services/drills/triggers.py`): the rule's vector series on
  every symbol of the universe (`scan_event_study.resolve_universe`), edges
  by `checklist/evidence.py::edge_indices` (shared with the scan event
  study; `is_edge`, `rule_state` too), no cooldown. Session: N bars before
  to M after, clamped; opens at the trigger (`current_at` set after
  `create_replay_session`). NSE/BSE triggers ending inside the lag are
  skipped and counted. `random.Random(seed).sample` over (date, ticker)
  order; `offset_weeks(seed, position)` 52-520 weeks, never shown past
  today. Inline rules become versions of "Rules from drills" (kind
  `screen`) through `strategy_run.inline_rule_version` (A4.1's helper,
  extracted).
- **Anonymised view** (`anonymise.Mask`): every drill response while
  `deck.anonymised` and not revealed: ticker -> "Stock A".. by position,
  ticker and company name replaced in free text, every date/datetime and
  ISO date in a string shifted, news reduced to counts. Errors from the
  replay layer are masked too (`routers/drills.py::_guard`).
  `routers/replay.py::_load` 404s an anonymised unrevealed drill session
  (`decks.is_hidden_session`) and the replay list leaves out every drill
  session (`drill_session_ids`). The replay router's drawing handlers are
  module functions (`drawings_of`, `create_drawing`, `patch_drawing`,
  `delete_drawing`) the drill routes reuse with dates translated.
- **Routes** (authed, `routers/drills.py`): `POST /v1/drills/decks` (201;
  404 unknown symbol/setup/watchlist, 401 drawings rule, 422 rule, 400 no
  eligible trigger or a bad range, 409 past 100 decks), `GET
  /v1/drills/decks`, `GET`/`DELETE /v1/drills/decks/{id}`, `GET
  /v1/drills/{id}` (`DrillOut`: session, summary, bar, history, orders,
  fills, plan, `needs_plan`, `score` and `reveal` once revealed), `PUT
  .../plan` (422 stop not below entry, 409 after the first fill or the
  reveal), `POST .../orders` (409 without a plan), `.../orders/{id}/cancel`,
  `.../advance?expected_current_at=` (the shown date; unshifted),
  `.../indicators`, `.../events`, `.../drawings`, `POST .../reveal`
  (cancels a running session; idempotent). Another user's deck or drill is
  404.
- **Score** (`score.py`, pure): entry within 2%, stop honoured on closes,
  peak size within the plan; R achieved beside it, "not the score". The
  deck summary counts statuses, traded, followed the plan and checks.
- Tests: `test_drills.py`, `test_drills_migration.py`.

**Tradebook import (A5.3, M10.2 CSV part).** Migration `e3a1c5d7f902`
(additive; downgrade refuses while any `broker_fills` row exists):
`import_batches` (book, broker, `column_map`, `file_sha256`, row counts,
`created_at`: never the file, its name or a client id), `broker_fills` (one
row per trade as traded, or an opening lot: `kind` trade|opening, exchange,
segment, series, `trade_id`, `order_id`, instrument, ticker, ISIN, raw
symbol, side, quantity, price, `executed_at` naive UTC, `time_known`,
`auction`, and per rebuild `status` posted|needs_opening_lot, `product`,
estimated `fees`/`fee_source`/`fee_lines`, `basis_uncertain`; unique
`(portfolio_id, broker, exchange, trade_id)`), `trades.broker_fill_id`
(unique, cascade). Models in `models/broker_import.py`; code in
`services/imports/`, router `routers/imports.py`.

- **Format:** `columns.ZERODHA_TRADEBOOK_V1`, the one table of fields and
  aliases, **unconfirmed** (third-party column list, design note question
  10): `format_status: "unconfirmed"` in every response. Headers match
  ignoring case, spaces, `_`, `-`, `.`, `/`; required symbol, trade date,
  exchange, trade type, quantity, price, trade id; optional ISIN, segment,
  series, auction, order id, order execution time. Dates: ISO, month names,
  numeric with the day/month order inferred from the file (a part over 12),
  ambiguous or conflicting rows rejected; IST times to naive UTC; no time =
  the start of the IST trade date, `time_known` false. NFO/BFO/MCX/CDS and
  F&O/currency/commodity segments are `segment` problems (A6). Problems
  carry the row (header = row 1), field and a fixed reason, never a value.
- **Routes** (authed; another user's book 404, a paper book 409, archived
  or non-INR 409 for writes): `POST /v1/books/{id}/imports/preview`
  (`text/csv` body read under 2 MiB, 413 past it, 415 another type; 422 an
  XLSX or unreadable file; stores nothing) -> `ImportPreviewOut` (columns
  and unmatched headers, counts, first 20 new trades, up to 300 problems);
  `POST .../imports/commit?file_sha256=` (the same bytes; 409 another file;
  200 with `batch: null` when nothing is new; 30 commits an hour per user,
  429); `GET .../imports` (batches, opening lots, sells waiting per symbol);
  `DELETE .../imports/{batch_id}`; `POST|DELETE .../opening-lots[/{id}]`.
  Instruments: ISIN (`instrument_identifiers` scheme `isin`, the row's venue
  preferred), else symbol + `.NS`/`.BO`; unmatched rows are skipped.
- **Ledger:** `book.rebuild_book` replays every fill of the book through
  `engine.replay_fills` and rewrites its `trades` (updated in place, so plan
  links survive) and `positions` on every commit, batch delete, opening lot
  and split (`corporate_actions.apply.rebase_book` rebuilds an imported book
  instead of scaling it; imported books with fills before the cut-off are
  candidates). Holdings only, `fx_rate` 1, realized P&L on the weighted
  average; a sell with too few shares is `needs_opening_lot` and does not
  post, except an **intraday short**: a trade sell on an NSE/BSE listing
  while nothing is held, whose quantity (plus any short already open) the
  scrip's later buys the same venue day cover, posts (`FillOutcome.short =
  "open"`, realized null); later buys that day cover it first (`"cover"`,
  realized = (average short price - buy price) x quantity, `avg_cost_at_fill`
  the short average), any rest of a covering buy adds to the holding; a
  short never stays open overnight, and a sell the day's buys do not cover
  keeps the opening-lot rule. Shorts and covers pair no plan (imported plans
  are long only). Preview counts `intraday_short`; sample rows carry
  `intraday_short`. `returns_ledger.realized_totals` and the P&L calendar's
  `unavailable_realizations` count a covering buy's figure and do not call
  an imported sell without one "unavailable". Fills on a venue date before a due split's ex-date are restated
  (qty x r, price / r); `basis_uncertain` when the restated price is outside
  the day's bar low-2%..high+2%. Fees: the A4.2 schedules on the as-traded
  numbers, the offsetting part of a scrip's day priced intraday, DP once per
  scrip-day on delivery sells; `TradeOut.fees_estimated` and
  `broker_fill_id` mark them.
- **Plans:** `POST /v1/plans?book=<imported>` makes `source: imported`
  plans. A posted buy opening a position links the newest open plan for the
  instrument created at or before its time (`record_fill` locks it); later
  buys of the position join it; the position back to zero closes it; a plan
  whose fills are all deleted is closed and stays frozen. Opening lots pair
  no plan.
- **Privacy:** nothing in the import path logs; `observability.scrub_event`
  drops the body, query and frame variables of Sentry events on import
  routes. `services/trading/account.activity` adds `imports` and `opening
  lots`; deleting a book deletes its fills and batches.
- Tests: `test_imports.py` (aliases, date formats, ambiguous dates, bad
  values, size/type, preview stores nothing, dedupe and overlap, ISIN,
  isolation, fees and intraday inference, DP, split restatement, basis,
  later split rebuild, opening lots, batch delete rebuild, book delete,
  plan lock / written after entry / closed after delete, flows, no cell in
  logs, Sentry scrub, intraday shorts: posted with intraday fees, rebuilt on
  batch delete, uncovered sells still waiting), `test_imports_migration.py`
  (PostgreSQL up/down/up).

**Trade plans (A5.4, M10.3).** Migration `b5d4a7e1c902`: `trade_plans`
(`models/trade_plan.py`): user, `portfolio_id` (paper, imported; cascade),
`replay_session_id` (replay, drill; unique, cascade), `instrument_id`,
`source` paper|replay|drill|imported, `side` long|short, planned entry,
stop, target (nullable), size, `setup_version_id`, `thesis_id` (SET NULL),
`thesis_text`, `why`, `invalidation`, `horizon_bars`, `confidence`,
`notes`, `tags` (JSON), `status` open|active|closed|cancelled,
`locked_at`, `first_fill_at`, `written_after_entry`, created/updated;
checks on each enum, positive prices, the home (`ck_trade_plans_home`) and
`NOT (written_after_entry AND locked_at)`. `trades.trade_plan_id` and
`pending_orders.trade_plan_id` (SET NULL). The upgrade copies every
`drill_plans` / `replay_journals` row into one plan per session
(idempotent: a session with a plan is skipped) and moves both tables to the
`archive` schema (keys to `replay_sessions` dropped). Downgrade refuses
while paper or imported plans exist; otherwise it restores the tables
(keys NOT VALID) and upserts the replay and drill plans back.

- **The lock** (`services/plans.record_fill`): the first fill a plan meets
  locks it at that fill's time when the plan was written before it
  (paper: `created_at <= trade.ts`; replay: the plan existed when the fill
  happened, `locked_at` = the simulated `evaluated_at`), else
  `written_after_entry` (never locked). Either way `frozen`: `PATCH`
  changing entry, stop, target, size, setup, thesis, why, invalidation,
  horizon or confidence is 409 (`PlanLocked`); notes, tags and status
  stay editable. A replay plan started after the first fill is written
  after entry.
- **Orders.** `POST /v1/trades` and `POST /v1/orders` take `trade_plan_id`
  (your open or active paper plan in that book, same symbol) or `plan` (a
  `TradePlanDraft`, created in the same transaction; a refused order writes
  no plan); buys only (422), not both (422), another user's plan 404, a
  cancelled or closed plan 409. `apply_fill(trade_plan=)` links the fill;
  a pending order keeps `trade_plan_id` and links at settlement. A sell
  that empties a book's position closes its active plans in the symbol.
  `TradeOut` and `PendingOrderOut` carry `trade_plan_id`. Paper plans are
  long only (paper trading cannot short).
- **Routes** (`routers/plans.py`, authed): `GET /v1/plans?book=&status=&
  source=&setup_version_id=&ticker=` -> `{plans: [TradePlanOut], limit}`
  (no `book`: every plan of yours; plans of anonymised unrevealed drills
  are left out and 404 by id); `POST /v1/plans?book=` (201; a writable
  paper book; `link_open_position: true` links the book's current
  position's buys, which makes it written after entry; no position 422,
  one with a plan 409; an index 422); `GET`/`PATCH`/`DELETE /{id}`
  (`status: closed` an active plan, `cancelled` an open one; delete only
  before a fill, else 409; replay and drill plans 409 here). `TradePlanOut`
  adds `ticker`, `currency`, `risk_per_share`, `planned_risk`,
  `reward_per_share`, `reward_risk`, `setup_label`, `thesis_title`,
  `locked`, `frozen`, `fills`. Errors map in `main.py` (`PlanNotFound` 404,
  `PlanError` 422, `PlanConflict`/`PlanLocked` 409). Deleting a book
  deletes its plans.
- **Replay and drills** read and write the session's plan:
  `services/replay/journal.py` (the journal's shape over the plan),
  `drills/decks.py` (`plan_of` = a session plan with an entry; `put_plan`),
  `replay/session.py` (fills lock it; completion closes an active plan and
  cancels an unfilled one).
- Tests: `test_trade_plans.py` (lock at the fill, 409 after, notes and
  tags, sell to zero, plan on the ticket, pending order at settlement,
  written after entry, the rule itself, validation, per user and per book,
  hidden drill plans), `test_trade_plans_migration.py` (PostgreSQL
  up/down/up with data: identical drill scores, deck summary and
  forensics; archive row counts; idempotent copy; downgrade refused with a
  paper plan). `test_drills_migration.py` and
  `test_replay_journal_migration.py` now stop at their own revisions.

**Journal entries (A5.5, M10.3).** Migration `c9d2e4f6a8b1` (additive;
the downgrade refuses while any entry holds notes or tags):
`journal_entries` (`models/journal_entry.py`: user, `source`
paper|imported|replay, `portfolio_id` or `replay_session_id` (check
`ck_journal_entries_home`; both cascade), instrument, `entry_key` (unique per
user), `plan_id` (SET NULL), `status` open|closed|detached, `opened_at`,
`closed_at`, and the user's text: `review_notes`, `mistakes`, `lessons`,
`setup_tags`, `mistake_tags` (JSON)) and `journal_entry_fills` (entry
cascade; exactly one of `trade_id` / `replay_fill_id`, each unique, both
cascade). **Only the grouping and the text are stored**; every figure is
computed on read (`services/journal/`).

- **Grouping** (`roundtrips.group_round_trips`, the replay episode rule):
  per book and instrument (`trades`, so paper and imported alike) or per
  replay session (`replay_fills`), in time order, a buy while flat opens an
  entry and the quantity back to zero closes it; partial sells stay in it, a
  later buy opens a new one, a sell while flat belongs to none, a position
  still held is open. Hidden drills (anonymised, unrevealed) are left out.
  **Imported books** (`allow_short`): a posted sell while flat is always an
  intraday short, so it opens a `side: "short"` entry that buys close
  (`JournalEntrySummaryOut.side` long|short). Short figures mirror long:
  average entry = the sells' average, exit = the buys', realized = (average
  short - buy price) x quantity, return on the sells' notional; MAE = average
  short - the highest high (adverse = the price going up), MFE = average short
  - the lowest low; R is null with `SHORT_NO_PLAN` (no plan pairs: imported
  plans are long only). A buy that covers and goes long in one trade gives
  the short entry its covering part only. A5.6 stats count a short as a win
  or loss by its net P&L like any entry.
- **Sync on read** (`entries.sync`, run by every list and detail read under a
  `FOR UPDATE` on the user row): each round trip is matched to its row by
  `entry_key`, a stable name of its first fill (`paper:<book>:t<trade id>`,
  `imported:<book>:<broker>:<exchange>:<broker trade id>` or
  `imported:<book>:opening:<id>`, `replay:<session>:f<fill id>`), and
  `status`, times, `plan_id` and the fill links are rewritten when they
  differ. An imported book rebuilds its `trades` on every commit, delete,
  opening lot and split, and the next read follows; nothing to invalidate.
  A row whose round trip is gone is deleted without text, or kept
  `detached` (hidden, 404) with it; the same file imported again finds it,
  notes intact.
- **Plans:** a paper or imported entry's plan is the one its fills link
  (`trades.trade_plan_id`: A5.4's ticket, A5.3's import pairing, which locks
  a plan written before the buy); a replay session's plan pairs with the
  session's first round trip. `plan.label` is `locked` or
  `written_after_entry`; only `locked` has `counts_for_adherence`.
- **Figures** (instrument currency): average entry (buy notional / shares
  bought), average exit, most shares held, realized ((price - ledger average
  cost) x qty per sell), fees (estimated for imports, `fees_estimated`), net
  P&L = realized - fees (+ open shares x (last close - average cost),
  `as_of_date`/`mark_close`), return, holding days and sessions. **R** = net
  P&L / (|average entry - plan stop| x most shares held) (the drill's
  definition), null with `r_reason` without a plan, a stop or a close to mark
  at. **MAE/MFE** (`excursions`): worst/best (daily low/high - ledger average
  cost) while held, per share, %, money (x shares held that day), R and the
  date and price. Basis `exact_close` for replay (forensics' rule and
  numbers: the entry bar counts from its close) or `approximate_daily` for
  paper and imported (the entry and exit days count their whole range: the
  fill's place in the day is unknown; "Daily bars: may include moves before
  entry or after exit", design note question 6). A venue session (calendar)
  without a stored bar makes both null with the reason and
  `missing_sessions`. **Adherence** (`drills/score.score_drill` on venue-date
  closes) for a plan locked before entry with entry, stop and size; a plan
  written after entry is shown with a note, never scored.
- **Venue dates:** a fill's date is its venue's (`venue_for_ticker`, IST for
  `.NS`/`.BO`; an imported fill without a time is the IST day start). The P&L
  calendar (`journal/query.py`) reads a window a day wider each side and
  keeps equity fills by their own venue date, so an NSE fill is never on New
  York's day; options stay on New York's.
- **News** (`entries.news_window`): documents linked to the instrument with
  `available_at` from the start of the third session before the entry day to
  the end of the entry day, and from the session before the exit day to the
  end of the session after it (venue time zone; up to 20, headline, source,
  link, time, venue date). Replay entries are capped at the session's clock.
  A window ending before the first Aegis document held is
  `coverage: before_news_copy` ("No news copy for this date").
- **Routes** (`routers/journal_entries.py`, authed; another user's entry or
  book 404): `GET /v1/journal/entries?book=<id>|all&status=open|closed&
  source=&setup_version_id=&tag=&ticker=&from=&to=&limit=&offset=` ->
  `{entries: [JournalEntrySummaryOut], total, limit, offset, note}` (no
  `book` or `all`: every book and replay; newest first; `from > to` 400);
  `GET /{id}` -> `JournalEntryOut` (+ fills, adherence, news at entry and
  exit, the text); `PATCH /{id}` (`JournalEntryPatch`: text and tags only,
  extra fields 422, `""` clears, tags de-duplicated ignoring case, at most
  12 of 32 characters).
- **Chart markers:** `symbol_events._fills` asks `entries.fill_r_multiples`
  (the user's books' whole history in the instrument, grouped the same way;
  read only) for each fill's R, entry id and whether it closes the entry.
- Tests: `test_journal_entries.py` (the done-when with hand-computed MAE,
  MFE and R; written after entry; no plan; replay equal to forensics; open
  paper entry; missing bar; partials and re-entry with markers; the pure
  rules; delete and re-import keeping notes; venue dates in the journal,
  the P&L calendar and markers; news windows and "no news copy";
  isolation; filters and patch rules), `test_journal_entries_migration.py`
  (PostgreSQL up/down/up).

**"Is my edge real?" (A5.6, M10.3 stats).** No migration; nothing stored.
`GET /v1/journal/stats?book=<id>|all&source=paper|imported|replay|all&
setup_version_id=&tag=&from=&to=` (`routers/journal_stats.py`, authed;
another user's book 404; `from > to` 400) -> `EdgeStatsOut`
(`services/journal/edge.py`, which reads `entries.sync` and the entry
figures: same net P&L, R and adherence as the entry pages).

- **Sources:** no `source` = paper and imported (replay never pooled by
  default); `all` pools the three; the by-source groups ignore `source`.
  Dates filter the entry's venue date. Open entries are `open_excluded`.
- **Groups** (`EdgeGroupOut`): `overall`, `by_setup` (plan's setup
  version, "No setup" last), `by_setup_tag`, `by_mistake_tag` (case
  ignored), `by_source`. Each: `n`, `wins` (net > 0), `losses`,
  `breakeven`, `n_r`, then win rate, average win/loss, payoff, profit factor,
  `expectancy` (mean net P&L) with `expectancy_interval`, `expectancy_r`
  (over entries with R) with `expectancy_r_interval`, `adherence_rate`
  (`followed_plan` of plans locked before entry), `avg_holding_days`,
  `total_net_pnl`. Mixed currencies: money null with `money_note`.
- **Under 30** (`checklist/evidence.MIN_EVENTS`): `counts_only` with
  `counts_only_reason`, every other figure null; R figures also need 30
  entries with R (`r_note`).
- **Interval:** `bootstrap_interval`: the values in closing order, 5,000
  resamples of `risk.engine.stationary_indices` (mean block 3; 1 is iid),
  5th-95th percentile of the means, `numpy.random.default_rng(SEED)`,
  `SEED` 20261126 returned as `seed`.
- **Drift** (`EdgeDriftOut`, per setup version in `by_setup`): the newest
  `experiment_runs` row of yours with `kind = 'strategy'` and that
  `setup_version_id`; closed trades from the stored result (open left out):
  expectancy in R, win rate, average holding (calendar days); differences
  live - backtest. Status: `no_backtest`, `backtest_no_r`,
  `too_few_live_trades` (n_r < 30), `too_few_backtest_trades`, else
  `consistent` (inside the live R interval, ends included) or
  `outside_interval`. `backtest.sample`: `in_sample` (window note) or
  `holdout_seen` (a `holdout_unlocks` row for the run's
  `trials.strategy_family`).
- **Honesty:** `honesty` lists the notes (recorded trades, survivorship
  N/A, small samples, association, not advice) plus the imported-fees note
  when imported entries are included (`imported_fees_estimated`).
- Tests: `test_journal_edge.py` (each metric by hand, breakeven, 29 counts
  only / 30 an identical interval, R needs 30, currencies, bootstrap by seed,
  drift cases, the route with filters, All books, isolation, open entries,
  the imported flag, newest backtest and holdout seen).

**Survivorship stamp (A1.4a, part of M1.5).** Every backtest result carries
`universe: {name, point_in_time, survivorship_biased, note}`: the public
`POST /v1/backtest` (`BacktestOut.universe`), stored single runs, and
walk-forward and sweep results; `ExperimentRunOut.universe` gives list rows
the stamp. One helper sets it, `services/backtest/universe.py::universe_for`:
today every run is `pinned` (the seed list with provider history),
`point_in_time: false`, `survivorship_biased: true`, because delisted names
are missing. A1.4b changes that function. Runs stored before the stamp read
back with the pinned stamp, and `registry.result_differences` skips a field
in `STAMPS_ADDED_LATER` that the stored result lacks, so their rerun is
still `identical` (`tests/test_backtest_universe.py`).

**Bars on closed days (A0, audit MD-9).** `stockviz.cli non-session-bars
[tickers]` (`services/ingest/non_session_bars.py`) lists, per ticker, the
daily bars dated on a day its venue did not trade: weekend and
weekday-holiday counts, how many repeat the previous bar's prices, the span
and the sources. It is read-only by default. `--apply TICKERS` deletes the
**weekend** bars of the tickers named, in one transaction (no all-tickers
delete; holiday bars are never deleted by it); run `metrics` after. The
12 weekend dates production held on 25 Nov 2026 were all real special
sessions, now in the calendar, so read the dates before deleting anything.
Production deletions are the owner's call.

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
`.NS` XNSE, `.BO` XBOM). `ingest` judges each ticker against its venue's
session. Option expiry uses the last New York session on or before expiry.
Outside a calendar's range the weekday rule applies and a warning is logged.

**Indian holidays (A0).** The package has no NSE calendar and its BSE list
ends with 2026, so XNSE and XBOM are built in `calendar.py` from one list:
the package's BSE holidays before 2026, then the table in
`services/markets/india_holidays.py`. A year there is `official` (the
exchanges' published list, with names and the source checked) or
`provisional` (no list yet: only the fixed-date holidays, 26 Jan, 14 Apr,
1 May, 15 Aug, 2 Oct and 25 Dec, close; a warning is logged once per venue
and year), through `PROVISIONAL_THROUGH` (2030). **When NSE publishes a
year's list (usually November or December), add it to `OFFICIAL_HOLIDAYS`
and move `OFFICIAL_THROUGH`.** `holiday_basis(day, venue)` says which source
answered. Hours are the package's BSE ones. Special sessions (weekend
Budget days, Diwali Muhurat on a weekend or on the Laxmi Pujan weekday
holiday, live tests of new systems and of the DR site) are
`SPECIAL_SESSIONS` in the same module, each with its source; they count as
sessions even where the package lists a holiday. Since A6.1 their hours are
modelled where they differ (`SPECIAL_HOURS`: the Muhurat evenings, the two
2024 DR-switch sessions with their pause, the 24 Feb 2021 close extended to
17:00); Budget days trade the normal hours. 2023 onwards read from the
owner's minute files, earlier ones as reported and consistent with the hourly
files. `session_minutes(day, venue)` gives a session's open, close and
trading spans in UTC (None on a closed day, an unknown venue or outside the
calendar); `session_complete_at` follows the special close. US: regular
hours only (`tests/test_intraday_calendar.py`). `HISTORY_CORRECTIONS` fixes the package's history where it is
wrong (Muharram 2013 moved from 14 to 15 Nov). Add new ones as the exchanges announce
them. `tests/test_india_calendar.py`.

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
once the ex-date bar is complete on the venue, rebases each user's candidate
books (A5.1: each book once) and their price alerts in one
transaction (`services/corporate_actions/apply.py`): shares bought before the
cut-off and still held times r with the total cost kept; pending orders, live
alerts and open options made before the cut-off scaled likewise (options
carry `shares_per_contract`, 100 until a split changes it; value and
exercise read it, never `CONTRACT_MULTIPLIER`). Trade rows stay as filled.
`corporate_action_applications` (A5.1: unique per action and book for a
book's rebase, and per action and user where `portfolio_id` is null for the
user's alerts) makes each part run once. Old splits change nothing because no ledger row predates them. The
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

**News and portfolio rules, notifications (Phase 7.2).** `news` rules
(`params.sentiment`, `params.event_type`) fire once per Aegis document linked
to the ticker whose `available_at` is after `armed_at` and that matches; the
key is `<rule>:doc:<document id>`, so rescanning the newest 200 is harmless
and a late-synced document is still caught. `portfolio` rules (no ticker:
`drawdown_pct` from the peak of opening, snapshots and live NAV,
`position_weight_pct`, `day_change_pct`) are judged once per session in the
base currency; the first judgement only records state; an incomplete
valuation is skipped. `notifications` (`models/notification.py`,
`services/notifications.py::notify`, unique `source_key`, staged in the
writer's transaction): alert firings (`on_alert_fired`), settlement fills,
cancellations and expiries, dividend credits, split rebasing and option
expiry. `/v1/notifications` (list with `category`, `unread`, `before_id`),
`/unread-count`, `/{id}/read`, `/read-all`. `prune-events` deletes read
notifications over 180 days old. In-app only in Phase 7; A2.3 adds
delivery channels (see "Rule alerts, screen runs and delivery (A2.3)"). Migration `4d4accec26be`.

**Index benchmarks and news event studies (Phase 7.4).** `^GSPC` (S&P 500,
USD) and `^NSEI` (NIFTY 50, INR) are seeded index instruments (a `^` ticker
is asset type `index` in both identity rules; migration `4ec3f175fd60`;
`calendar.INDEX_VENUES` dates them by XNYS and XNSE). The nightly ingest
stores their bars; `is_index_ticker` keeps them out of trading
(`NotTradable`, 400), options, the screener, the markets table and signals.
`services/event_study.py::run_event_study`: for each Aegis document linked
to a stock and matching a sentiment label and/or event type, the event day
is the first stored bar whose session closed after `available_at`; abnormal
return = stock log return minus its index's on the dates both traded; CAR
from `-pre` to `+post`; mean, standard error and t across events for the
windows (0,1), (0,5), (-5,-1), (0,20). Events lacking the full window are
counted, not used; overlapping windows are counted; under `MIN_EVENTS` (10)
no averages. `GET /v1/research/event-study?tickers=&sentiment=&event_type=&pre=&post=`
(public, 20/min, up to 20 tickers).

**Phase 7.5 fixes.** RS-10: `ingest_earnings_for_ticker` first moves an
unreported upcoming row the provider no longer lists to the nearest newly
listed date within 45 days (`previous_date` keeps the old one); rows left
by earlier moves are listed by `stockviz.cli earnings-duplicates`
(read-only; removing them is the owner's call). SR-8: `recommendations.bar_date`
was the newest bar behind the votes, with `bar_date` and `stale` on
`/v1/recommendations` (both retired in A2.4; the Checklist rows carry their
session date and `stale` the same way). OP-9: the API calls `configure_logging()`; every log line carries
`[request id]` (`logging_setup.REQUEST_ID`, `RequestIdFilter`);
`request_id.py` middleware takes a valid `X-Request-ID` (the web sends one
per call) or makes one, tags Sentry and returns it. OP-12: a failed outbox
event holds back later events of its topic and key in the batch; after
`MAX_PUBLISH_ATTEMPTS` (10) it gets `dead_at`, is no longer claimed, and
shows in `stockviz.cli outbox-dead` and `/health`'s `dead_outbox_events`.
Migration `d55cf5f51697`.

**Returns (Phase 8.1, #68).** `services/trading/returns.py` (pure):
`time_weighted_return` chains sub-period returns between valuation points and
takes outside flows (none exist yet: paper accounts get no deposits, so the
account's TWR equals its NAV return); `period_returns` gives 1M, 3M, YTD, 1Y
and ALL, each starting at the last point on or before its start (ALL at the
opening value), null with a reason when the account is younger, annualised
only past a year; `xirr` solves dated flows (Newton, bisection fallback),
null with a reason under 30 days or without a sign change.
`returns_ledger.py` reads the flows in the base currency: equity fills at
`trades.fx_rate`, dividends at `base_value`, today's value at the latest
rate; the options book as one line (USD accounts only; a book that expired
worthless is -100%). `PortfolioAnalyticsOut.returns` carries the periods,
the account's and each holding's XIRR, and each method's name and basis.
#68: `PortfolioOut.unrealized_pl` is equities plus open options
(`unrealized_pl_equity`, `unrealized_pl_options`), and `realized_pl` sums
equity sells and option closes in the base, with `realized_pl_unavailable`
counting closes that have no stored figure (never estimated).

**Exposure and FX attribution (Phase 8.2).** `services/trading/exposure.py`:
weights of NAV (display currency) by sector, instrument country and
currency, equities at market value and cash under its currency ("Cash" for
sector and country); open options beside them at delta-adjusted notional
(`PortfolioOptionPosition.delta_notional`), never added into the weights.
`attribution.py`: per holding, the gain since entry in the base currency
split into price (qty x (close - avg cost) x entry rate), currency (qty x
avg cost x (rate now - entry rate)) and cross, which sum exactly to value
minus cost; the entry rate is the notional-weighted `trades.fx_rate` of the
current holding's buys (after the running quantity last reached zero), and
dividends since then are income. Both on `PortfolioAnalyticsOut`
(`exposure`, `attribution`) with their method and basis.

**Risk (Phase 8.3).** `GET /v1/portfolio/risk` (authed, computed on
request) runs `services/risk/`: `scenarios.py` replays today's holdings over
the last 500 dates with a stored bar for any held stock (250 needed, else a
`reason`), each stock's close-to-close return combined with its currency's
move into the base (`(1 + local)(1 + fx) - 1`), the market index (`^NSEI`
for Indian listings, `^GSPC` otherwise) before a stock's own history starts
(listed as proxied), 0 on its market's closed days; foreign cash moves with
its currency; open options repriced in full with Black-Scholes at the
scenario spot, today's volatility and the horizon off their expiry.
`engine.py` (pure): VaR = the k-th largest loss, k = ceil(n x (1 -
confidence)), CVaR = the mean of those k; 95% and 99% over 1 and 10
sessions (overlapping real 10-session windows, not the square-root rule);
a stationary block bootstrap (mean block 5, 10,000 paths, 252 sessions,
fixed seed) of the portfolio's daily returns. The worked examples are in
`docs/benchmarks/2026-11-13-risk-hand-check.md`, each asserted by a test.

**Stress tests (Phase 8.4).** `GET /v1/portfolio/stress` (authed, on
request) runs `services/risk/stress.py`: every scenario applied instantly to
today's holdings in the base currency (stocks by the scenario's move,
currencies by its rate move, foreign cash with its currency, options
repriced in full). Historical replays (`HISTORICAL`: 2008, COVID 2020, 2022
rates, 2013 taper) use each stock's own close-to-close move over the window
(a start bar within a week of the window's start), else its index's move
times its beta over the last 500 sessions (`proxied`), else `missing` and
unmoved. Fixed shocks (`HYPOTHETICAL`) move US-listed and Indian-listed
stocks by instrument country, and the rupee against the dollar. The combined
shock is worked by hand in `docs/benchmarks/2026-11-13-risk-hand-check.md`.

**Pre-trade limits (Phase 8.5).** `risk_limits` (one row per portfolio,
migration `a3e5c7f9b812`, every cap nullable: off until the user sets it;
check constraints keep each in (0, 100]). `services/risk/limits.py`:
`check_buy` evaluates, as % of NAV in the base currency before the fill,
the holding after the fill, the order's cost, the sector after, a non-base
currency's stocks and cash after, and (only when set) an estimated 1-day 95%
VaR with the order added (`not checked: ...` without 250 sessions).
`apply_fill` calls `enforce_buy` on buys under the portfolio lock before
anything moves (`LimitBreached`, a `TradeExecutionError`: 409 on
`POST /v1/trades`, a cancel with the reason at settlement); option exercise
passes `check_limits=False`. Option opens check the premium against the
single-order cap only (`enforce_option_open`, 409). Sells are never checked.
`GET`/`PUT /v1/portfolio/limits`, `GET /v1/portfolio/limits/check?ticker=&quantity=`
(the order review's preview).

**Removed in A0 (25 Nov 2026).** The leaderboard, comments and the
simulated quote stream (`/v1/stream/quotes`) are gone. `/v1/profile`
(`routers/profile.py`) now carries the display currency only. The
`users.public_profile`, `public_handle` and `display_name` columns stay,
unused. Migration `89b9ba1b46b5` moves `comments` to the `archive` schema
(rows kept; its keys to live tables and its trigger dropped, restored by the
downgrade); dropping it is the owner's call.

**Phase 8.6 small items.** Goals: `GET
/v1/portfolio/risk?goal=` adds `monte_carlo.goal` and `prob_goal`, the share
of the one-year bootstrap paths ending at or above it.

**Status (audit OP-5, Phase 7.6).** `GET /v1/status` (public, 30/min):
each recorded job's latest run (name, state, start, finish, last success),
the latest Aegis sync's state and time, the newest daily bar per market
(instrument country) and the dead outbox count. Names, times and states
only, never `job_runs.error`. The web `/status` page reads it.
Camus trial (Phase 7.6): `docs/benchmarks/2026-11-13-kafka-vs-camus.md`;
`scripts/events/broker-benchmark.sh` runs the scaling benchmark against any
broker. No hosted broker (owner, Phase 7).

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

**Many watchlists, notes, tags, column sets (A2.5, M4.6).** Migration
`5a167f08f3f7` (additive): `watchlists` gains `colour` (palette
`models/watchlist.WATCHLIST_COLOURS`: aqua blue violet pink amber lime slate,
each a `--list-<name>` token in the web), `position`, `is_default` and
`column_set_id` (to `column_sets`, `ON DELETE SET NULL`); `watchlist_items`
gains `note` (VARCHAR 2000) and `tags` (JSON list); `column_sets` (user,
name, ordered `columns`) is new. The upgrade numbers each user's lists by
id, flags the oldest as default and renames a repeated name " (2)" before
`uq_watchlists_user_name` (user, name) and the partial unique index
`uq_watchlists_user_default` (one default per user) land. Rules live in
`services/watchlists.py`:

- **Default list.** `ensure_default` makes an empty "Default" on first use,
  or flags the first list by position if none is. Deleting the default moves
  the flag to the first remaining list; deleting the **last** list leaves a
  fresh empty "Default", so every user always has one. `PATCH {is_default:
  true}` moves it (false is 422).
- **Limits.** 50 lists a user; names 1-64 characters, unique per user
  ignoring case (409); 100 symbols a list (the news filter's bound; a bulk
  add that would pass it adds nothing, 409); a bulk add takes up to 100
  tickers, de-duplicated, reporting `added`, `already_listed`, `unknown`.
  Notes up to 2,000 characters (blank clears); up to 10 tags of 1-24
  letters, digits, spaces or `- _ . & /`, de-duplicated ignoring case.
  Column sets: 20 a user, columns from `COLUMN_KEYS` (each once; the
  `ColumnKey` literal in `schemas.py` must equal it, a test checks).
- **API** (authed). `/v1/watchlists`: `GET` (`?contains=T` adds `contains`
  per list), `POST {name, colour}` (201), `PATCH /{id}` `{name?, colour?,
  is_default?, column_set_id?}` (null clears), `POST /reorder {ids}` (every
  id once, else 422), `DELETE /{id}`; `GET /{id}/items?column_set_id=&columns=a,b`
  -> `{watchlist, columns, column_set_id, items: [WatchlistRowOut: the
  WatchlistItemOut fields + note, tags, values]}` (columns: `columns=`, then
  `column_set_id=`, then the list's set, then `DEFAULT_COLUMNS`), `POST
  /{id}/items {tickers}`, `PATCH /{id}/items/{ticker} {note?, tags?}`,
  `DELETE /{id}/items/{ticker}`. `/v1/column-sets`: `GET`, `POST {name,
  columns}`, `PATCH /{id}`, `DELETE /{id}` (lists using it fall back to the
  default columns). Another user's list or set is 404.
- **Values** (`column_values`): every row in a fixed number of queries:
  the sparkline bars (also `close` and `change_pct`, last close against the
  one before), one `symbol_metrics` read (RSI, gaps to the 52-week high and
  SMA 50/200 from the snapshot's close, ATR %, volatility, average volume,
  P/E, P/B, USD market cap, yield, ROE, 7-day sentiment), the newest daily
  bar's volume (`volume_ratio` = it over the 20-day average), the newest
  `eod_extras` session (`delivery_pct`, EQ first) and the newest
  `checklist_scores` row (`checklist_met`, with `checklist_evaluated`). No
  data is `null`, never 0.
- **Old routes.** `/v1/watchlist` (GET, `POST /{ticker}`, `DELETE
  /{ticker}`) act on the default list and keep their shapes; marked
  deprecated in OpenAPI. Earnings' `scope=watchlist` reads every list of
  the user. No alert kind or screen run reads watchlists. News for a list is
  `/v1/news?tickers=` with the list's symbols.
- Tests: `test_watchlists_router.py`, `test_watchlist_router.py`,
  `test_watchlist_batched.py`, `test_watchlists_migration.py` (PostgreSQL
  up/down/up with a duplicated name).

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
runs it with that flag and sets `EVENTS_OUTBOX_ENABLED=false` (the default
since A0; see Scheduler). It also deletes
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
  `/v1/symbols/{ticker}/sentiment` read the `aegis_*` tables. `/v1/news` lists only documents linked to a StockViz
  symbol; `?scope=market` lists the rest (documents linked to no symbol:
  general market headlines), and refuses `tickers` (400). Whether a
  document links depends on Aegis resolving its entities to a seeded
  `stockviz:` mapping (Aegis `data/instruments/stockviz.json`, all 161
  symbols since 16 Nov 2026). `symbol_metrics.sentiment_7d` (the screener's
  sentiment filter; it was also the 7th Signals vote until A2.4) is written by `refresh_aegis_sentiment`, run at
  the end of every `aegis-sync` (also after a failed sync) and by the
  `sentiment-aggregate` CLI and scheduler job (audit AG-14). The legacy
  pipeline is gone since A0 (see "Sentiment" below).
- **The news archive (26 Nov 2026).** `GET /v1/news/feed` and
  `GET /v1/news/overview` (public, 60 a minute; `services/aegis/feed.py`)
  serve the `/news` page. Feed: keyset paging over `available_at` desc,
  `document_id` asc (`cursor`, an opaque base64url of both; a bad one is
  400), `limit` up to 100, `total`; filters `q` (every word in the headline,
  ILIKE with `%`/`_` escaped, at most 8 words), `tickers`, `sentiment`
  (`unscored` = no sentiment analysis), `topic`, `source`,
  `scope=symbols|market|all` (market with tickers is 400) and `from`/`to`
  (UTC dates on `available_at`, never `published_at`; from > to is 400).
  Each item carries `reactions` for up to 3 tickers: the first stored daily
  bar whose session completed after `available_at` (event_study's rule),
  its change on the previous close and 5 closes either side
  (`reaction_index`); none without a later bar. Overview: `days` over the
  whole archive (date filters ignored, so the page's brush can widen again)
  with tone counts; `total`, sentiment, topic and source counts honour
  every filter; `heatmap` is the 12 most-covered tickers over the 30 days
  ending at the newest headline, each cell `count` and `net`
  ((positive - negative) / count). Headline, source, dates and links only.
  Tests: `tests/test_news_feed.py`.
- **Signals (SR-8, SR-9) are retired (A2.4).** The 7-vote engine, its router
  and the `recommend` step are gone; see "The Checklist (A2.4)".

Kafka workers (same image, different command; broker optional for the API):

```powershell
pnpm events:up   # compose profile "events" — KRaft Kafka + topic init
pnpm events:publisher
pnpm events:market-ingest
# also: events:market-analytics
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

`scheduler.py::build_scheduler` registers its cron jobs (timezone
America/New_York, weekdays unless noted):

- 09:30 — `dividend_credit_refresh` (credit due dividends to portfolios)
- 10:00–16:00 hourly — `hourly_top_movers` (refresh `TOP_TICKERS_HOURLY`)
- 16:30 — `daily_price_refresh` (refresh every active symbol)

**Price jobs keep Kafka off the default path (A0).** Both call
`_refresh_prices`: by default each ticker goes through the cron's
`ingest_ticker`, then its metrics and alerts are judged in the same
transaction (what the market-analytics worker did); one failing ticker is
logged and the rest run. With `EVENTS_OUTBOX_ENABLED=true` (set only in
`infra/k8s/base/configmap.yaml`, the events lab) they enqueue
`market.refresh.requested` per ticker for the Kafka workers instead.
`tests/test_scheduler_price_jobs.py`.
- 16:45 — `fx_refresh` and `pending_orders_settlement` (fill limit/stop orders against the new close)
- 16:50 — `symbol_metrics_refresh` (RSI / 52w range the screener reads)
- 16:55 — `sentiment_aggregate_refresh` (rolling per-symbol Aegis News sentiment)
- 17:00 — `checklist_refresh` (A2.4: the six dimensions for every active symbol)
- 18:00 Fridays — `checklist_evidence_refresh` (A2.4: the weekly evidence grades)
- 17:15 — `portfolio_snapshots_refresh` (daily NAV snapshot per user)
- 17:30 — `options_expiry_refresh` (settle expired option positions)
- 17:05 — `screen_runs_refresh` (A2.3: screened setup versions' members, diffs)
- every 15 min, every day — `notifications_delivery` (A2.3: send due deliveries, retries)

No job fetches news: Aegis News owns it (`aegis-sync`; A0 removed `news_refresh`).

`symbol_metrics_refresh` and `sentiment_aggregate_refresh` remain
full-universe **reconciliation** jobs. In the events lab the Kafka consumers
are the incremental path. Pending orders, options, dividends, FX, snapshots, and the checklist
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
       │              ├─ portfolio_dividends  (credited payouts)
       │              ├─ portfolio_snapshots  (A5.1: daily NAV per book; also carries user_id)
       │              └─ risk_limits          (one row per book)
       ├─ watchlists ── watchlist_items   (A2.5: many lists, one default; notes, tags)
       ├─ column_sets           (A2.5: saved watchlist columns)
       ├─ alerts
       ├─ drawings              (A3.2: per instrument; anchors are bar dates + prices)

symbols ─┬─ price_bars          (EOD OHLCV; everything prices off the latest 1d close)
         ├─ checklist_scores    (A2.4, by instrument and session)
         ├─ symbol_metrics      (precomputed RSI / 52w / rolling sentiment)
         └─ dividends           (declared payouts per symbol)
fx_rates                        (currency + date, USD-per-unit)
```

A5.1: a user holds up to 20 portfolios ("books"), exactly one `is_default`.
`portfolio_snapshots` hangs off the book (`portfolio_id`, unique with the
date); its `user_id` is kept for the combined view (A5.2).

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
(symbols, bars, quotes, news, indicators, checklist, rule check,
setup presets, AVWAP, events, relative strength, delivery, regime), **30/min**
screener, **20/min** backtest (rotation too), **10/min** scan event study. Authenticated routers are deliberately *not*
slowapi-limited — every authed request arrives from the Next.js server, so a
per-IP limit would be one global bucket for all users. Where per-user
throttling matters, do it in the router with a DB count of recent rows. Disable the limiter with `RATELIMIT_ENABLED=0` — note that slowapi reads that
variable itself and keeps the raw string, so `limiter.py` parses it and assigns
a real bool after construction; without that, `"0"` was truthy and the switch
did nothing.

## Trading domain rules

Everything prices off the **latest `1d` close** in `price_bars` — there are no
intraday fills anywhere in the app:

- New portfolios start with **$100,000** cash (`DEFAULT_STARTING_CASH`,
  `services/trading/books.py`), auto-created on the first `/v1/portfolio`
  call via `ensure_default_portfolio` (idempotent; it finds the default
  book, `is_default`).
- **Books (A5.1, M10.1).** Migration `6ad74b7c4b5b`. `portfolios` gains
  `kind` (`paper` | `imported`), `is_default`, `cash_tracked` (false for
  imported: holdings only), `broker` (`zerodha` or null), `holder_kind`
  (`self` | `family` | `huf`), `holder_label` (free text, 60; a PAN-shaped
  label is 422: no PAN is stored) and `archived_at`. The unique `user_id`
  index is gone; a partial unique index `uq_portfolios_user_default`
  (`user_id WHERE is_default`) keeps the first-use race guard, and
  `(user_id, name)` is unique (the API also refuses names equal ignoring
  case). Checks: kind, holder kind, broker, `ck_portfolios_default_not_archived`.
  The upgrade makes every existing portfolio its user's default paper book.
  **Downgrade refuses** while any user holds more than one book (it names
  how many; nothing changed), else it folds the split applications back to
  one per (action, user) and restores the old keys. `alerts.portfolio_id`
  (nullable, cascade): the book a portfolio rule watches, null = default.
  **One resolver:** `services/trading/books.py::resolve_book(session,
  user_id, book_id | None, write=False)`: None = the default book (created
  on first use); another user's or a missing id raises `BookNotFound`
  (404, `main.py` handler); `write=True` refuses an archived or imported
  book (`BookNotWritable`, 409). `owned_book` checks a row's own book
  (cancel an order, a trade's provenance); `require_writable` guards
  closes of an option or strategy in its own book. Every book-scoped route
  takes `?book=<id>` (`routers/book_query.py::BookQuery`): portfolio,
  overview, analytics, risk, stress, limits (GET/PUT, check), history,
  dividends, trades (GET/POST), base currency, orders (GET/POST), options
  trade/positions/strategies/book, the journal, earnings `scope=holdings`
  (default: every book's holdings) and symbol events (fills from all the
  caller's books by default; each fill event carries `book_id`).
  `POST /v1/alerts` takes `book_id` for portfolio rules. Nightly jobs
  iterate books: snapshots (archived ones too), split rebases, dividend
  credits (books with `cash_tracked` false get none); pending orders and
  option expiry were already per book. `tests/test_book_lookup_allowlist.py`
  fails on any new `Portfolio.user_id ==` / `PortfolioSnapshot.user_id ==`
  in `src/` outside its allow-list. Risk limits are per book; price alerts,
  watchlists and the display currency stay per user.
- **Book CRUD (A5.1).** `services/books/`, `routers/books.py`:
  `GET /v1/books` -> `{books: [BookOut], limit: 20}` (default first; it
  creates the default); `POST /v1/books {name, kind?, base_currency?
  USD|INR, holder_kind?, holder_label?, broker?}` (201; a paper book starts
  with `STARTING_CASH` in its currency and a day-zero snapshot; an imported
  one with 0; 409 past 20 or a taken name); `PATCH /v1/books/{id} {name?,
  holder_kind?, holder_label? (null clears), archived?, is_default: true}`
  (409: archiving the default, archiving with pending orders, making an
  archived or imported book the default); `DELETE /v1/books/{id}` (204;
  409 for the default or last book, and for a book with activity that is
  not archived; deletes everything in it). `BookOut` carries `writable` and
  `activity`. Only a paper book can be the default.
- **All books (A5.2, M10.1).** `routers/book_query.py::BookOrAllQuery`
  (`?book=<id>|all`, `parse_book`) on `GET /v1/portfolio`, `/portfolio/overview`,
  `/portfolio/analytics`, `/portfolio/history`, `/v1/trades` and `/v1/orders`;
  every other book route still takes an id only, so `all` is 422 there.
  `services/books/combined.py`: `combined_view` values every book with
  `compute_portfolio` in the user's display currency and merges them
  (`merge_valuations`: one row per ticker, quantity summed, average cost
  weighted by quantity; cash per currency summed; `portfolio_id` 0,
  `base_currency` = display). The series (`book_series` + pure `combine`):
  each book's points (opening value on `created_at`'s date, its snapshots,
  today's live value) are in its base currency and convert into the display
  currency at the rate on or before that point's own date (`RateBook`); a
  book's value between its points is its last point; a book adds nothing
  before it opened. Outside flows: a book opening after the first book's
  opening adds its `opening_nav` on its opening date; an imported book's buys
  add cost + fees and its sells remove proceeds - fees, at `trades.fx_rate`
  into its base, then the trade date's display rate (`imported_flows`).
  Cross-book transfers do not exist yet. TWR = `period_returns` over the sum
  with those flows; total return, drawdown and Sharpe read `growth_index`
  (flow-free), XIRR takes `-first value`, `-flows`, `+today`
  (`combined_xirr_flows`). FX age: `stale_floor(d)` =
  `previous_session(session_on_or_before(d))` on XNYS (MD-7's fill rule); an
  older rate is used and reported as `ValuationWarningOut.code =
  "stale_fx_rate"`; a date with no rate at all is dropped from the series
  (its flows count on the next date kept) and reported as `no_fx_rate`.
  `PortfolioOut.combined` lists each book's value, `fx_rule` and
  `per_book_only`. Per book only: risk, stress, attribution (null),
  holding XIRRs (empty), limits, dividends, options and the journal.
  `/portfolio/history?book=all` returns snapshots only, summed, each with
  `flow` (null on one book's history). `TradeOut.book_id` and
  `PendingOrderOut.portfolio_id` name each row's book. Tests:
  `tests/test_books_combined.py` (the hand-worked USD + INR example: TWR
  4.3133%; imported flows 0.47619%; stale and missing rates; the routes).
- **Rupee accounts (Phase 4.8).** `PUT /v1/portfolio/base-currency`
  (`services/trading/account.py`; A5.1: per book, `?book=`, paper and not
  archived) restarts a **fresh** book in USD
  ($100,000) or INR (₹1 crore, `STARTING_CASH`): no trades, orders, options,
  positions, dividends or foreign cash, else 409. It restates the opening
  NAV and that book's snapshots, and sets the display currency to match
  only when the book is the default.
  `PortfolioOut` carries `base_currency` and `base_currency_locked`.
- **Fees (A4.2).** Indian symbols pay their venue's equity delivery
  schedule on every live fill (see "Date-versioned costs (A4.2)"); other
  markets pay none. Cash moves net of fees; realized P&L on the trade row is
  gross, `realized_pnl_net` / `realized_pl_net` are after fees.
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
  creation serializes on the user row; one default book per user is unique
  (A5.1, `uq_portfolios_user_default`).
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
  Orders take intent only; a market order fills at the current bar close
  (A4.6: limit / stop orders rest, see "Replay in any currency (A4.6)").
  Any currency since A4.6. Cancel is manual. Reaching the last bar keeps the session
  active, so that bar can be traded; advancing from it marks `completed`
  (the web's "Finish replay"). Cash and positions go through the shared
  `services/simulation/ledger.py::SimLedger` (Phase 5.1), whose arithmetic
  `tests/test_sim_ledger.py` holds equal to `apply_fill`; the backtester
  moves onto it in 5.2. `stockviz.cli benchmark-kernel` measures kernel +
  ledger throughput (about 140k fills/s locally; `test_kernel_benchmark.py`
  keeps a 10k floor).
  No delete endpoint; child rows cascade if a session row is removed.
  Replay Lab UI is `/replay` (SIM-06); market, limit, stop-loss and
  take-profit in the UI since A4.6.
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
- **Options basics (Phase 9.1).** `services/options/pricing.py` adds rho
  (per 1.00 of rate) to `OptionPrice`, `RISK_FREE_RATES` with
  `risk_free_rate(currency)` (USD 5%; `trade.RISK_FREE_RATE` is its USD
  value), and `implied_volatility()` (Newton on vega with a bisection
  fallback, 1% to 500%, `None` with a reason below intrinsic, above the
  no-arbitrage bound or past expiry). LG-14: `quote_option` (so every open)
  refuses a ticker with fewer than `MIN_VOL_CLOSES` (20) closes in the
  volatility window (422) and floors the premium at `MIN_PREMIUM_PER_SHARE`
  (0.01); the quote says `premium_floor_applied`, `volatility_method` and
  `volatility_closes`. LG-15: "today" for options (open, quote, valuation,
  close gate) and for the `settle-options` and `credit-dividends` jobs is
  `services/markets/calendar.py::trading_date`, New York's calendar date;
  `tests/test_options_basics.py` fails if the options service reads the UTC
  date. `GET /v1/options/implied-volatility?ticker&option_type&strike&expiry&price`
  (public, 60/min) solves a user-entered per-share price on the quote's
  inputs and returns it beside the historical volatility; nothing is
  stored. Greeks (with rho) are on the quote, `/v1/options/positions` and
  each `PortfolioOptionOut.greeks` (null when unpriceable).
- **Covered short legs (Phase 9.2).** `options_positions.side` (`long` |
  `short`) and `cover` (`shares` | `cash`; migration `e1b7d3f5a924`, a check
  refuses a short leg with no cover: no naked options). `open_option(side=
  SHORT)` writes a **covered call** (needs that many available shares) or a
  **cash-secured put** (needs its full strike value in available cash: not
  less the premium, which is already spendable cash), credits the premium in
  USD, and is for USD accounts only for now (`InsufficientCoverForOption`,
  422). The cover is a derived reservation in `buying_power.py`
  (`option_share_reservation`, `option_cash_reservation`), so the shares
  cannot be sold and the cash cannot be spent while the leg is open;
  `exclude_option_id` (also on `apply_fill`) lets the leg's own buy-back or
  assignment use it. `close_option` buys a short leg back (realized =
  premium - cost, `proceeds` = -cost). At expiry long legs settle first,
  then short: an ITM covered call sells its reserved shares at the strike,
  an ITM cash-secured put buys the shares at the strike with its reserved
  cash (both through `apply_fill`, so a `Trade` is written; the option leg
  realizes the premium); OTM short legs expire with the premium kept.
  `services/options/margin.py` (pure) gives each leg's collateral, shares
  held back, most it can lose and gain, breakeven and basis; the quote
  (`?side=short`) returns them as `risk`. Valuation: a short leg is a
  liability (`position_sign`): negative market value, cost basis and delta
  notional, negated Greeks, and a negative size in VaR and stress tests.
- **Strategies (Phase 9.3).** `option_strategies` (migration `f2c8e4a6b135`)
  groups legs opened from one template (`services/options/strategies.py`):
  covered call, cash-secured put, protective put (needs the shares held),
  bull call, bear put, bull put, bear call, iron condor, straddle, strangle,
  calendar. Strikes go low to high; a template lists each long leg before
  the short leg it covers. A short leg in a spread or calendar has `cover =
  'leg'` and `covering_leg_id` (a check keeps them in step). Every leg is
  priced by `quote_option`, then all open in one transaction or none.
  `margin.same_expiry_risk` works same-expiry legs exactly (the payoff is
  piecewise linear: extremes at 0, a strike or infinity) and refuses an
  unlimited loss (a naked call); `collateral` = the most the legs can cost
  at expiry with premiums aside (a credit spread holds back its width, an
  iron condor its wider side). `calendar_risk`: a call calendar needs no
  cash; a put calendar holds back K(1 - e^(-r t)) a share (a European put
  can sit that far below intrinsic). The open needs available cash + net
  premium >= collateral; the single-order limit checks the most it can
  lose. `strategy_collateral_usd` reserves a strategy's collateral while a
  leg-covered short is open in it; `exclude_strategy_id` lets its own close
  use it. `close_strategy` closes every open leg at model value as one net
  payment; a long leg covering an open short cannot be closed alone. Status
  goes to `closed` or `settled` when no leg is open. **Expiry (Phase 9.4):**
  `settle_expired_strategies` runs first in `settle_expired_options` and
  settles each multi-leg strategy as a unit **in cash**: every leg expiring
  that day at intrinsic value from the expiry session's close (LG-3; it
  waits while that close is missing), long legs receive, short legs pay, the
  net moves once (never more than the collateral held back) and nothing
  goes through the equity book. A calendar's near short leg settles first:
  out of the money it expires and the far leg stays open as a plain long;
  in the money the far leg is sold at its Black-Scholes value at that close
  to pay the short's intrinsic (a call's value is at least that). One
  notification per strategy (`strategy:<id>:settled:<expiry>`). Legs whose
  strategy still has another open leg never take the single-leg path.
  Acceptance worked by hand: `docs/benchmarks/2026-11-16-options-hand-check.md`
  (`tests/test_options_hand_check.py`).
- **Payoff and the book (Phase 9.5).** `services/options/payoff.py`:
  `POST /v1/options/strategies/payoff` (public, 60/min) returns the quote,
  two P&L curves after premiums over a price range (at the first expiry,
  where later legs keep their Black-Scholes value, and today) and a model
  chance of profit (lognormal price at the first expiry, the legs'
  volatility and the risk-free drift; checked against the closed form). A
  covered call and a protective put include their shares from today's
  close. `services/options/book.py`: `GET /v1/options/book` (authed) sums
  the open legs' Greeks in money per underlying (delta in shares and
  dollars, gamma, theta per day, vega and rho per percentage point; short
  legs negated) and groups legs by expiry with what today's close would do,
  in settlement's terms, and the money at risk.
- **Option chains (Phase 9.6).** `option_quotes` (migration `a7d9c1e3f246`,
  keyed by instrument, one row per contract per snapshot day): the nightly
  `stockviz.cli options-snapshot [tickers]` (recorded job, in the cron after
  `fx`) fetches each active US stock's listed chain for the nearest 4
  expiries from yfinance (`services/options/chains.py`; `cli.fetch_option_chain`
  is the network call, stubbed in `test_cron_chain.py`), stores bid, ask,
  last, volume, open interest, the price used (bid-ask mid, else last) and
  the IV solved from it against that day's stored close; a rerun replaces
  the day; one ticker failing never stops the rest; exit 1 only when every
  ticker failed. Pricing (`quote_option`, `value_option`) uses
  `chain_volatility`: the nearest listed contract of the same type (expiry,
  then strike) from a snapshot at most 5 days old, within 45 days of expiry
  and 10% of strike, else the 30-session historical volatility (with the
  LG-14 20-close rule); `OptionQuote.volatility_method` says which. The
  payoff prices each leg at its own volatility. `GET /v1/options/surface?ticker=`
  (public, 30/min) returns IV by expiry and strike from the latest snapshot.
  History starts when collection starts; nothing is backfilled. VaR and
  stress scenarios still revalue options on historical volatility. API: `POST /v1/options/strategies/quote` (public, 60/min),
  `POST /v1/options/strategies`, `GET /v1/options/strategies`,
  `POST /v1/options/strategies/{id}/close`.
- **Options** (`services/options/`): long legs plus covered short legs (Phase 9.2, above). Black-Scholes pricing
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
`base_value`. Option premiums stay in the base currency; replay books are in
their symbol's currency (A4.6), so they need no FX.

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
dividends, comments, earnings, news and (now retired) recommendations reads. Still on
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

**Broker status and graceful degradation (A5.7, M1.7).** No live broker
connection exists. `GET /v1/broker/status` (`routers/brokers.py`, authed;
`services/brokers/`) -> `{brokers: [{broker: "zerodha", label, provider:
"kite", configured, state, live_data: false, imported_books,
last_imported_at, last_snapshot_at, last_failure_at}], offline_window_hours,
checked_at}`. `configured` = `KITE_API_KEY` and `KITE_API_SECRET` both set
(never returned). `state`: `not_configured` (blank keys), `offline` (the
newest `kite-snapshot` run failed within `OFFLINE_WINDOW`, 3 days),
`snapshot_only` (a snapshot has succeeded), else `not_connected`.
`imported_books` counts the caller's active imported Zerodha books;
`last_imported_at` is the newest `import_batches.created_at` across the
caller's Zerodha books (A5.3; archived books included). Provider
health reuses `job_runs`: once `ingest-history --provider kite` reaches Kite
(keys and a request token set) it writes one `kite-snapshot` row through
`record_provider_run`: `failed` on a Kite login error or any `KiteError` /
`httpx.HTTPError` while fetching (a ticker Kite does not list is not one),
else `succeeded`. The row keeps a fixed summary ("Kite login failed",
"Kite error on N ticker(s)"), never the token, key or Kite's message.
`/v1/status` and `/health` leave `kite-snapshot` out (it is not a nightly
job). The web shows the state on Settings, `/status` (Brokers) and
imported books. Tests: `tests/test_broker_status.py`.

**Owner note: adding the daily Kite login later (future plan, not built;
deferred to A6, A5 design note question 8).** What it would take:

- **A paid Kite Connect app.** Kite Connect is ₹500 a month per app
  (Zerodha support page cited in `docs/a5-design-note.md`, read 26 Nov
  2026); the free Personal app logs in but carries no historical or live
  data. That is an ongoing subscription, which the owner does not want
  today.
- **A registered redirect URL** on the app, pointing at a new API callback
  route (for example `/v1/broker/kite/callback`) that receives Zerodha's
  `request_token`, checks a signed `state` tying it to the signed-in user,
  and swaps it for the day's access token with `open_session` (the app
  secret stays server-side).
- **Encrypted token storage:** a per-user table holding the access token
  encrypted at rest under a server key kept out of the database and the
  repo (no such key exists yet), never logged, never returned, deleted on
  sign-out of the broker.
- **Daily expiry:** Kite tokens expire every morning (around 06:00 IST); the
  login stays manual every day (an exchange rule: never automate it). The
  status would then add a `connected` state until expiry, and a reminder
  (Telegram) would prompt the next login.

## Ingestion contract

Each ingest service writes straight to Postgres — no CSV intermediate.
Price ingest uses **yfinance first** (no key). Alpha Vantage is attempted
only when `ALPHA_VANTAGE_KEY` is set and yfinance returned no rows. Massive is
private/nonpersistent shadow only: `MASSIVE_SHADOW_ENABLED=true` requires
`MASSIVE_API_KEY`, and candidate bars never enter persistence, events, or APIs.
StockViz fetches no news (A0): Aegis News owns it.

**Keys stay out of logs.** Alpha Vantage takes the key as
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

**Removed in A0 (25 Nov 2026).** StockViz no longer scores sentiment: the
`services/sentiment/` providers (Anthropic, HTTP, null), the NewsData.io
ingest (`services/ingest/news.py`), the `news` and `score-sentiment` commands,
the `news_refresh` scheduler job, the news event contracts and the three Kafka
news workers are gone, with `NEWS_PROVIDER`, `NEWSDATA_KEY`,
`ANTHROPIC_API_KEY` and `SENTIMENT_*` (still set on a host, they are ignored)
and the `anthropic` dependency. Migration `ea0040711437` moves `news_articles`
and `news_sentiment` to the `archive` schema (rows, primary and unique keys and
the key between them kept; the keys to `symbols` and `instruments` and the
instrument trigger dropped, restored by the downgrade); dropping them is the
owner's call.

Sentiment is Aegis's label, stored as sent in `aegis_analyses.label`. The label
set (`positive`, `neutral`, `negative`, `mixed`; AG-4) is the
`NewsArticleOut.sentiment` literal in `schemas.py`; news alert rules take
`alerts/rules.py::NEWS_SENTIMENTS` (no `neutral`). `refresh_aegis_sentiment`
(see "Aegis News sync") writes `symbol_metrics.sentiment_7d`, and the
`sentiment-aggregate` command and scheduler job run it.
`docs/SENTIMENT.md` is kept as history.
