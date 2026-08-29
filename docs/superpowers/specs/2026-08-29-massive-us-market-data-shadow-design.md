# Massive US Market Data Shadow Integration Design

**Date:** 2026-08-29

**Status:** Approved for implementation

**Scope:** US daily market-data shadow evaluation only

## Objective

Integrate Massive as a private, non-persistent shadow provider behind StockViz's
existing market-data seam, quantify whether its daily US equity bars have the
same financial meaning as the yfinance bars used by analytics and backtests,
and make the preceding Pipeline Activation milestone reproducible from clean,
source-built containers.

This milestone does not make Massive the default or production provider, does
not serve Massive-derived data from any API or page, and does not begin
TrueData, NSE, or BSE integration.

## Existing-System Audit

StockViz currently obtains daily bars in
`apps/api/src/stockviz/services/ingest/prices.py`. `fetch_daily_bars()` calls
yfinance first and Alpha Vantage only when yfinance returns no rows. All
providers map into the generic `BarRecord` dataclass before `upsert_bars()`
writes `PriceBar` rows. The Kafka market-ingest worker calls the same function,
and the event handler persists bars and emits `market.bars.refreshed` without
exposing provider types downstream.

The current yfinance request uses `interval="1d"`, `auto_adjust=False`, and
`actions=False`. Yahoo/yfinance's OHLC values are split-adjusted but not
dividend-adjusted in this mode. Dividends are handled separately by StockViz's
dividend ingest and portfolio-credit model. The yfinance daily index carries
the exchange timezone, but StockViz currently removes `tzinfo` and stores the
resulting midnight value. In practice, `PriceBar.ts` is a session-date label,
not an observation instant, despite older replay wording that calls it naive
UTC.

Current limitations relevant to this milestone are:

- `PriceBar.source` already records provider provenance and must be preserved.
- Adjustment basis and session scope are not persisted.
- `PriceBar.volume` is a `BigInteger`, while Massive documents fractional
  volume for split-adjusted aggregates.
- Same-day yfinance daily bars are not filtered, so an incomplete session can
  become the latest bar used by trading, portfolio valuation, analytics, and
  replay creation.
- Missing trading sessions are represented by missing rows; no exchange
  calendar is used to synthesize bars.
- The `(ticker, ts, interval)` primary key cannot store two providers for the
  same session without overwriting one. Shadow bars therefore must remain
  non-persistent.

The downstream volume audit found that the public and replay bar schemas type
volume as `int`, and recommendation inputs use `(Decimal, int)`. The simulation
kernel already uses `Decimal` volume. The web API types and chart library use a
JavaScript `number`, which can accept fractional volume without an interface
redesign. No portfolio, execution-price, backtest-price, or indicator formula
depends on volume being an integer; the recommendation engine converts volume
to `float` before computing its mean and comparison.

## Canonical US Daily-Bar Semantics

The canonical contract for completed StockViz US daily bars is:

1. **Price basis:** OHLC is adjusted for stock splits onto the current share
   basis and is not adjusted for cash dividends or capital distributions.
2. **Corporate actions:** Splits affect historical OHLC and share-equivalent
   volume. Dividends remain separate cash events and are never folded into
   OHLC.
3. **Session scope:** OHLCV represents the regular US equity session. Extended
   hours are excluded from the canonical daily bar.
4. **Session timezone:** Session membership and dates use
   `America/New_York`, including DST transitions.
5. **Stored timestamp:** For compatibility, `PriceBar.ts` remains a naive
   midnight label whose date is the New York trading-session date. It is not a
   vendor event timestamp or data-availability timestamp.
6. **Volume:** Volume is the split-adjusted share-equivalent count represented
   as an exact `Decimal`. Fractional values caused by split ratios are valid and
   must not be silently rounded to integers.
7. **Missing sessions:** No bar is synthesized when a provider supplies none.
   Weekends, holidays, suspensions, and provider gaps are distinguishable only
   through comparison against another provider or a future exchange calendar.
8. **Completion:** A daily bar whose New York session date is today is not a
   completed daily bar. StockViz persists it only on a later New York calendar
   date. This conservative rule avoids early-close and correction-timing
   guesses without introducing a calendar subsystem in this milestone.
9. **Newest observation:** Shadow reports retain each provider's newest raw
   candidate separately from the newest completed canonical bar so timing and
   incomplete-session discrepancies remain visible.

Generic persisted semantics use `adjustment_semantics` and `session_scope`.
Existing yfinance rows are backfilled as `split_adjusted` and `regular`. The
existing `source` column remains the sole provider-provenance field; no
redundant provider field is added.

## Volume Precision Selection

Massive's REST schema specifies volume as a JSON number and its official
documentation shows fractional adjusted volume, but it does not promise a
fixed decimal scale. The implementation must not select a database scale from
an arbitrary example.

The live comparison command will parse JSON floats directly into `Decimal` and
record the decimal exponent for every Massive volume in the required symbol
set over the maximum history allowed by the configured subscription. Before
the migration is finalized, it will report:

- maximum whole-number digits;
- maximum fractional digits;
- counts by fractional scale;
- the symbols and sessions producing the maximum scale.

The `price_bars.volume` migration will use `NUMERIC(19 + S, S)`, where `S` is
the maximum observed Massive fractional scale. Nineteen whole-number digits
preserve the capacity of the existing signed `BigInteger`; `S` comes directly
from provider evidence. Adapter and persistence validation will reject, rather
than round, a later value whose scale or whole-number digits exceed the chosen
column. If a live precision scan cannot be run, the migration is a declared
blocker and is not guessed.

The API's bar and replay schemas change volume from `int` to `Decimal`.
Recommendation type annotations change accordingly; its existing float-based
mean calculation is unchanged. The generated TypeScript contract remains
`number`, and serialization tests pin that fractional volume reaches the web as
a JSON number accepted by the chart.

## Adapter and Shadow Architecture

### Massive adapter

A focused Massive module under `services/ingest/providers/` owns:

- Massive endpoint URLs, query parameters, authorization, pagination, and
  error payloads;
- Massive ticker normalization;
- response keys such as `o`, `h`, `l`, `c`, `v`, and `t`;
- provider request IDs and corporate-action IDs;
- UTC millisecond timestamp conversion to a New York session date;
- exact JSON-number parsing with `Decimal`;
- validation that aggregate responses are split-adjusted;
- mapping into generic `BarRecord` values with `source="massive"`,
  `adjustment_semantics="split_adjusted"`, and an explicit session scope.

The adapter uses the existing `httpx` dependency and does not introduce the
Massive SDK. No Massive response model is imported outside the adapter and
shadow-comparison package.

### Primary path

`fetch_daily_bars()` remains the yfinance-first persisted/default path. It
continues to return the bars persisted by the market worker. Before
persistence, the common completion filter removes same-New-York-date daily
bars. Alpha Vantage remains the existing fallback and is not removed.

### Operational shadow

When `MASSIVE_SHADOW_ENABLED=true`, the market-ingest worker privately fetches
Massive over a bounded lookback in addition to its normal yfinance request. It
compares the two `BarRecord` lists and emits a structured summary to logs. A
Massive HTTP or semantic failure is logged unmistakably but does not replace or
erase a valid yfinance persistence result. Missing credentials are different:
settings validation fails at process startup, before any work can silently
no-op.

The operational shadow does not write Massive bars to `price_bars`, create a
shadow-history table, add Massive fields to market events, or expose Massive
data through FastAPI or Next.js.

### Reproducible comparison command

A manual CLI command fetches both providers for an explicit date range and
symbol list. Defaults include AAPL, MSFT, NVDA, AMZN, META, TSLA, and JPM. It
also retrieves Massive split and dividend events solely for mismatch
classification. Vendor action IDs stay in private raw evidence and never enter
domain models.

The command writes a JSON artifact containing machine-readable observations
and a Markdown report containing aggregate statistics. Both go beneath a
gitignored private artifact directory by default. Individual-subscription data
and derived comparisons must not be committed, published, returned by an API,
or included in public build artifacts.

## Comparison Methodology

Bars are joined by canonical New York session date. Each symbol reports:

- reference and candidate row counts;
- common, yfinance-only, and Massive-only sessions;
- newest raw and newest completed sessions from each provider;
- raw Massive timestamp, converted timezone offset, and canonical session
  date validation;
- OHLC absolute and relative errors: mean, median, p95, p99, maximum, and
  counts above 1, 5, 10, and 50 basis points;
- volume absolute and relative errors: mean, median, p95, p99, maximum, and
  counts above 0.01%, 0.1%, 1%, and 5%;
- fractional-volume scale distribution;
- statistics inside and outside corporate-action windows;
- split execution and dividend ex-date findings;
- missing/extra-session date lists;
- a classification for each material discrepancy.

Corporate-action windows cover the action session plus the two common sessions
before and after it. A discrepancy may be classified as adjustment basis,
provider timing, corporate action, session/timezone normalization, incomplete
latest session, provider eligibility/session scope, or unexplained provider
disagreement. Classifications do not change or massage provider values.

Massive custom daily aggregates may include eligible extended-hours trades,
while yfinance is requested without pre/post-market data. The comparison
therefore samples Massive's per-date daily open/close endpoint, which separates
regular OHLC from pre-market and after-hours values, against the custom daily
aggregate. This independently tests whether the historical aggregate is safe
to label `regular`. If the two Massive endpoints materially disagree, the
candidate fails the canonical session-scope gate even if its HTTP requests
succeed.

## Configuration and Fail-Fast Behavior

New settings are:

- `MASSIVE_SHADOW_ENABLED=false`
- `MASSIVE_API_KEY=`
- `MASSIVE_SHADOW_LOOKBACK_DAYS` with a bounded positive default used only by
  the operational shadow
- `NEWS_PROVIDER=` where blank preserves backward compatibility by resolving
  to `newsdata` when `NEWSDATA_KEY` exists and `none` otherwise

Settings validation requires a Massive key when shadow mode is enabled. An
explicit `NEWS_PROVIDER=newsdata` requires `NEWSDATA_KEY`. An explicit
`SENTIMENT_PROVIDER=anthropic` requires `ANTHROPIC_API_KEY`; an explicit
`SENTIMENT_PROVIDER=http` requires `SENTIMENT_SERVICE_URL`. Validation errors
name the missing variable and prevent the affected process from starting.

Compose passes these variables from `infra/.env`; no secret is committed.
Example env files document the two verification modes and the private/local
restriction.

## Clean Verification

### Credential-free deterministic workflow

An isolated Compose verification configuration uses distinct container names,
host ports, network, and database volume. It:

1. force-builds the production API and web images from their Dockerfiles;
2. builds a test target from the same API source and lockfile;
3. starts disposable Postgres and Kafka services;
4. runs migrations from the rebuilt API image;
5. runs deterministic market, news, outbox, Kafka-contract, persistence, and
   analytics tests inside the test image without external provider calls;
6. starts the rebuilt API and web images and verifies their health endpoints;
7. records image IDs and command results;
8. removes only the isolated verification containers, network, and volume.

This workflow requires no provider credentials and proves that source-built
images contain the Pipeline Activation changes. It does not claim that a live
vendor was reachable.

### Optional live-provider workflow

A separate local-only workflow requires explicitly selected providers and
their credentials. It runs yfinance market ingest, NewsData ingest when
selected, Massive shadow comparison, and the event/manual twins from the
rebuilt API image. It refuses to start when a selected provider lacks its key.
Live artifacts remain in the gitignored private directory and are never copied
into the web image or served application directories.

Pre-existing unrelated test failures are captured separately from failures
introduced by this milestone. No existing test is deleted or weakened.

## Technical and Licensing Gates

Massive cutover has two independent gates:

1. **Technical provider gate:** canonical semantics, mismatch thresholds,
   session-scope equivalence, completeness, precision, and operational
   reliability are acceptable across the representative symbol set.
2. **Production/commercial licensing gate:** StockViz has a Massive agreement
   that explicitly permits its deployment model, end-user display, derived
   analytics, persistence, and any redistribution.

Passing the technical gate never implies licensing approval. An Individual
subscription may be used only for private/local shadow evaluation under the
applicable terms. This milestone cannot recommend production cutover unless
both gates pass, and it does not perform a cutover under any outcome.

## Future NSE/BSE Domain Requirements

TrueData integration is deferred. Before mixed US and Indian coverage, the
domain will need:

- a stable instrument identity separate from display ticker;
- canonical exchange-qualified symbols such as `(exchange, local_symbol)`;
- provider-specific instrument identifiers and validity ranges;
- explicit asset currency and price/quantity precision by venue;
- NSE and BSE trading calendars, holidays, special sessions, and timezone
  rules;
- session-date semantics that do not assume New York;
- corporate-action identity and adjustment policy by market;
- historical FX aligned to portfolio valuation and transaction dates;
- mixed-currency cash, cost basis, realized P&L, benchmark, and backtest
  policies;
- rules for fungible or cross-listed instruments and symbol changes.

These requirements are documented only; no TrueData code, NSE/BSE provider,
or production schema expansion for them is part of this milestone.

## Completion Criteria

The milestone is complete only when:

- both production images rebuild from source and pass isolated clean checks;
- deterministic market/news/event paths pass without credentials;
- selected live providers fail fast without required credentials;
- Massive maps into generic bars without leaking vendor types;
- yfinance remains the sole persisted/default provider;
- incomplete same-day bars are excluded from completed persistence;
- the live precision audit justifies the fixed-precision volume migration;
- private JSON and Markdown reports contain per-symbol quantified results;
- corporate-action and session-scope findings are explained rather than
  normalized away;
- existing tests pass, with unrelated pre-existing failures documented;
- technical and licensing recommendations are reported separately.

A successful Massive HTTP response alone does not satisfy these criteria.
