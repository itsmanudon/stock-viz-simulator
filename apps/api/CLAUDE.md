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
                    ReplayJournal, aegis — read-only Aegis News copies,
                    setup — A2.2 Setup / SetupVersion / Thesis,
                    screen — saved screens + A2.3 ScreenRun, delivery —
                    A2.3 NotificationChannel / DeliveryAttempt)
  events/           versioned contracts (trades/market), outbox/inbox,
                    dispatcher, domain handlers, Kafka producer wrappers
                    (not imported by FastAPI startup)
  workers/          outbox_publisher, scheduler (dedicated APScheduler process),
                    plus trade-activity and market ingest/analytics consumers
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
                    (A2.2), notification_channels (A2.3), health
                    (`GET /live` liveness, `GET /health` readiness + DB)
  services/
    ingest/         External-API fetchers (yfinance primary, Alpha Vantage fallback);
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
    checklist/      A2.4: dimensions.py (the six DSL dimensions as system
                    setups), score.py (nightly scores), evidence.py (grades)
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
    bars/           A1.4a: resample.py (pure: daily -> 1wk/1mo, the partial
                    rule) and load.py (loads enough daily bars for n output bars);
                    A3.1: raw.py (`eod_raw` bars for `adjustment=raw`, `has_raw`)
    markets/        calendar.py — exchange calendars and completed sessions (Phase 4.1);
                    india_holidays.py — the maintained NSE/BSE holiday table (A0)
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
                    load_symbol), evaluate.py (vector, point, evaluate_at)
    setups/         A2.2 spine: store.py (setups and immutable versions),
                    presets.py (seeded system setups), rules.py (rule check)
    screener_rule.py  A2.2: judges a rule for every screener candidate
    screen_runs.py  A2.3: nightly members per screened setup version, diffs
    delivery/       A2.3: deliver() (outbox staging), drain(), channels.py
                    (signed webhook + SSRF rules, SMTP email, Telegram),
                    transport.py (the network edges tests stub)
    theses.py       A2.2: thesis reads (the router writes)
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
`checklist-evidence [--start D] [--end D] [--horizon N]`, `snapshot-portfolios`,
`dividends`, `credit-dividends`, `settle-options`, `run-scheduler`,
`prune-events [--days N] [--include-unpublished]`, `aegis-sync [--max-pages N]`,
`settle-orders [--session-date YYYY-MM-DD]`, `evaluate-alerts`, `revalidate-web`,
`publish-outbox [--once]`,
`consume-trade-activity [--once]`, `consume-market-ingest [--once]`,
`consume-market-analytics [--once]`, `nse-load PATH ... [--apply]`,
`nse-files [--limit N]`,
`export-parquet --out DIR [--since YYYY-MM-DD] [--tables T ...]`,
`rule-check "<rule>" [TICKER ...] [--date YYYY-MM-DD] [--explain]`,
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
- **Functions** (`functions.py`): the 21 registry indicators run on the
  timeframe's bar frame with the registry's parameters, defaults and bounds
  (`rsi atr hv cci roc willr mfi rvol wma vwap obv ad adx macd stoch
  supertrend bb donchian keltner`); outputs by `.name` (`macd().signal`;
  `macd adx stoch supertrend` default to `macd adx k line`; `bb donchian
  keltner` must name one). The registry's `sma`/`ema` are the primitives
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
  one `index_close` expression and the seven checklist dimension setups; 444,683 point evaluations over 7,537 bars before them, a process pool, about a
  minute), plus a test that perturbs everything after `t` and finds no
  value up to `t` changed. Vector mode: about 1.3 ms for a 5-condition rule
  over 10 years, 0.2 s for 163 symbols (synthetic, local).
- **CLI.** `stockviz.cli rule-check "<rule>" [TICKER ...] [--date]
  [--explain]` prints the canonical text, hash, type and warm-up, then per
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

**A2 done-when (one rule, three consumers).** `tests/test_one_rule_three_consumers.py`
saves one rule as a setup version and checks, over seeded random walks for
eight tickers, that the screen (`/v1/screener?setup_version_id=&as_of=`),
rule alerts armed the session before (`evaluate_pending_alerts` after the
target bar arrives) and the vector series (symbols turning true on that
date) name the same symbols on the same session. The rule is a crossing, so
"met on the date" and "turned true on the date" are the same set.

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
sessions even where the package lists a holiday, and their short hours are
not modelled. `HISTORY_CORRECTIONS` fixes the package's history where it is
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
       │              └─ portfolio_dividends  (credited payouts)
       ├─ portfolio_snapshots   (daily NAV — powers the equity curve and returns)
       ├─ watchlists ── watchlist_items   (A2.5: many lists, one default; notes, tags)
       ├─ column_sets           (A2.5: saved watchlist columns)
       ├─ alerts

symbols ─┬─ price_bars          (EOD OHLCV; everything prices off the latest 1d close)
         ├─ checklist_scores    (A2.4, by instrument and session)
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
(symbols, bars, quotes, news, indicators, checklist, rule check,
setup presets), **30/min**
screener, **20/min** backtest. Authenticated routers are deliberately *not*
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
