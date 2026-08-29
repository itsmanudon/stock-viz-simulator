# Market data semantics and Massive shadow evaluation

This is the implementation and verification report for the private Massive US
market-data shadow milestone. yfinance remains the sole persisted/default provider.
Massive is neither a fallback nor a public data path, and this
milestone does not authorize a production cutover.

## Architecture changes

The existing seam is unchanged: providers produce canonical `BarRecord`
objects, `fetch_daily_bars()` selects the persisted provider, and the existing
upsert, event, analytics, portfolio, screener, backtest, and API paths consume
stored `PriceBar` rows.

- `PriceBar.source` remains the provider-provenance field. No redundant provider
  column, provider key component, shadow-history table, or Massive response
  model was added.
- `BarRecord` and persisted `PriceBar` now carry generic
  `adjustment_semantics` and `session_scope`. Existing yfinance/seed rows migrate
  to `split_adjusted`; existing `alpha_vantage` rows migrate to `unadjusted`;
  existing rows migrate to `regular` session scope.
- The worker may make a bounded Massive comparison after its normal yfinance
  fetch. It returns and persists the yfinance list unchanged. Massive failures
  are unmistakably logged but cannot replace persisted data.
- The private CLI compares in memory and writes only ignored local artifacts
  below `artifacts/private/`. No FastAPI or Next.js route can retrieve Massive
  bars or reports.

## Canonical US daily-bar semantics

| Concern | Canonical meaning |
| --- | --- |
| OHLC basis | Split-adjusted, not dividend-adjusted. Historical OHLC reflects stock splits; cash dividends do not rewrite OHLC. |
| Splits | Reflected in price/volume adjustment semantics and inspected as corporate-action dates during comparison. |
| Dividends | Separate cash events; never folded into canonical OHLC. Dividend dates define comparison windows only. |
| Time zone | Provider instants are interpreted in `America/New_York`. |
| Session date | New York trading-session date, stored in the existing naive-midnight `PriceBar.ts` label. Midnight is a date label, not a UTC observation instant. |
| Session scope | `regular` means the regular US equity session. `provider_daily` means a vendor-defined aggregate whose eligibility must be independently validated. |
| Volume | Exact `Decimal` split-adjusted share-equivalent count at the canonical boundary; never rounded to fit persistence or another provider. |
| Missing sessions | Not synthesized and not forward-filled. Missing/extra dates remain explicit comparison results. |
| Latest bar | Completed daily bars only. A daily bar labeled with the current New York date is conservatively excluded from persistence and comparison. |
| Intraday | Outside this milestone. No partial same-day aggregate becomes a completed daily bar. |

yfinance is requested with `auto_adjust=False`. Its returned OHLC is treated as
split-adjusted and not dividend-adjusted, with regular-session volume. The
Alpha Vantage fallback uses the unadjusted daily series and is persisted with
`unadjusted` semantics, so consumers need not infer the basis from `source`.

The completion rule deliberately does not guess holidays or early closes: a
date becomes eligible only after New York advances to the next calendar date.
A future exchange-calendar service may make this less conservative while
preserving the canonical session date.

## Provider adapter design

`services/ingest/providers/massive.py` owns endpoint URLs, Bearer
authentication, pagination, ticker normalization, JSON keys, request/action
IDs, raw millisecond timestamps, status payloads, split/dividend payloads, and
the daily open-close probe. Exact JSON numbers are parsed directly as `Decimal`.

The adapter requests adjusted daily aggregates and emits only canonical
`BarRecord` objects with `source=massive`, `split_adjusted` semantics, and
`provider_daily` scope. The provisional scope is intentional: a Massive
aggregate is not silently labeled `regular`. The live workflow samples the same
dates through the independent daily open-close endpoint; material price or
volume differences block the technical provider gate.

No Massive-specific type crosses into persistence, Kafka events, analytics,
portfolio, backtest, screener, or API code. Corporate-action and open-close
records exist only inside the private comparison workflow.

## Config and environment changes

| Variable | Meaning |
| --- | --- |
| `MASSIVE_SHADOW_ENABLED` | Defaults to `false`. `true` enables bounded private worker shadow calls and requires a key at settings construction. |
| `MASSIVE_API_KEY` | Required whenever Massive shadow execution is selected. Never commit it. |
| `MASSIVE_SHADOW_LOOKBACK_DAYS` | Positive bounded worker lookback; default 90. |
| `NEWS_PROVIDER` | Blank preserves legacy auto-resolution; explicit `newsdata` requires `NEWSDATA_KEY`; `none` disables it. |
| `NEWSDATA_KEY` | Required when `NEWS_PROVIDER=newsdata`. Never commit it. |
| `SENTIMENT_PROVIDER` | Blank preserves legacy auto-resolution; explicit `anthropic` requires its key and explicit `http` requires its URL. |

Compose passes provider selections and credentials from local configuration.
Settings reject an explicitly enabled provider whose credential or endpoint is
absent. The optional live script repeats validation before its first Docker
command, preventing a successful-looking silent no-op.

## Shadow comparison methodology

The private command compares at least AAPL, MSFT, NVDA, AMZN, META, TSLA, and
JPM. C, GE, and AIG broaden the precision audit around long histories and split
activity.

For each symbol, it:

1. fetches raw yfinance and Massive histories over one bounded range and
   records each provider's newest raw date;
2. converts timestamps to canonical New York dates and removes the incomplete
   latest session under the shared completion rule;
3. joins by date and records common, yfinance-only, and Massive-only sessions;
4. calculates exact-Decimal OHLC errors and counts over 1, 5, 10, and 50 basis
   points;
5. calculates volume errors and counts over 0.01%, 0.1%, 1%, and 5%;
6. reports mean, median, nearest-rank p95, p99, and maximum error;
7. separates ordinary sessions from the action date and two common sessions on
   each side of Massive split/dividend dates;
8. compares selected aggregates with Massive's independent open-close endpoint
   to test whether `provider_daily` may be promoted to `regular`;
9. classifies differences as adjustment basis, provider timing, corporate
   action, session/timezone normalization, incomplete latest session, provider
   eligibility/session scope, or actual provider disagreement.

The comparison never alters input to improve agreement. A successful HTTP
request is only transport evidence and cannot pass the semantic gate.

Each run produces `report.json` and `report.md` in a timestamped private
directory. JSON retains per-field statistics, missing/extra dates, action
windows, discrepancy classifications, newest raw/completed dates, session-scope
samples, and observed volume scale. Markdown provides the review table. Both
are private provider-derived evidence and must not be committed, served, copied
into an image, or published.

## Per-symbol mismatch statistics

No live Massive credential was available in this implementation environment,
so statistics have not been fabricated. The optional workflow failed before
Docker as designed.

| Symbol | Common sessions | OHLC stats | Volume stats | Missing/extra sessions | Newest bar | Status |
| --- | ---: | --- | --- | --- | --- | --- |
| AAPL | n/a | not evaluated | not evaluated | not evaluated | not evaluated | blocked on local live key |
| MSFT | n/a | not evaluated | not evaluated | not evaluated | not evaluated | blocked on local live key |
| NVDA | n/a | not evaluated | not evaluated | not evaluated | not evaluated | blocked on local live key |
| AMZN | n/a | not evaluated | not evaluated | not evaluated | not evaluated | blocked on local live key |
| META | n/a | not evaluated | not evaluated | not evaluated | not evaluated | blocked on local live key |
| TSLA | n/a | not evaluated | not evaluated | not evaluated | not evaluated | blocked on local live key |
| JPM | n/a | not evaluated | not evaluated | not evaluated | not evaluated | blocked on local live key |

Run `pnpm verify:providers:live` after placing local values in `infra/.env`.
The private Markdown report then contains quantified per-symbol values and the
JSON is the machine-auditable source.

## Corporate-action findings

Deterministic tests prove that action windows are separated from ordinary
sessions and discrepancies are classified rather than massaged. They also test
timestamp normalization, incomplete-session filtering, adjusted/unadjusted
classification, missing/extra sessions, Decimal statistics, and independent
session-scope sampling.

Live split-period, dividend-period, and aggregate-scope findings remain not
evaluated until a private credentialed run completes. This is a technical
blocker, not evidence that the providers agree.

## Volume precision and downstream integer assumptions

The audit found:

- `price_bars.volume` remains PostgreSQL `BIGINT`; public bar/replay schemas
  still type it as `int`;
- recommendation inputs accept `(Decimal, int)` but convert volume to float for
  averages, so the algorithm does not fundamentally require an integer;
- simulation contracts already use `Decimal` volume;
- web JSON/chart consumers use JavaScript `number` and need fractional-volume
  serialization coverage when the public schema changes.

Canonical `BarRecord.volume` is `Decimal`. The persistence bridge accepts
integral values from current persisted providers and rejects—not rounds—any
fractional value. Massive remains nonpersistent.

The database/public-schema conversion to fixed precision is deferred until the
live report measures Massive's maximum whole and fractional digits. The planned
shape is `NUMERIC(19 + S, S)`, where `S` is the observed maximum provider scale
across required and precision-probe symbols. No arbitrary scale was selected.

## Tests and clean-container verification

Credential-free deterministic verification:

```powershell
pnpm verify:pipeline:clean
```

This uses an isolated Compose project, no-cache source builds, separate ports,
network, and database volume. On 2026-08-29 it rebuilt API, web, and API-test
images; started healthy Postgres, Kafka, API, and web services; passed 65
selected settings, market, news, outbox, PostgreSQL, and Kafka tests (including
market and news/sentiment roundtrips); received HTTP 200 from API and web; and
removed the environment. Non-provider evidence is summarized in
`artifacts/verification/README.md`.

Optional private live-provider verification:

```powershell
# Configure infra/.env locally; do not commit or paste keys.
pnpm verify:providers:live
```

It rebuilds the API image, starts only an isolated database, migrates, seeds,
exercises persisted yfinance ingest, optionally exercises explicitly selected
news, and runs the seven-symbol comparison under
`artifacts/private/live-verification/`. It never starts API or web services, so
Individual-subscription responses cannot become publicly served data.

## Blockers, licensing assumptions, and recommendation

The technical provider gate and production/commercial licensing gate are
independent:

- **Technical provider gate — not evaluated.** It requires live quantified
  coverage, ordinary/action-window mismatches, latest timing, timestamp
  normalization, independent session-scope evidence, and measured precision.
- **Commercial licensing gate — not approved.** An Individual subscription is
  private/local evaluation only here. Production persistence, display, derived
  analytics, redistribution, and end-user access require a separate agreement.

Recommendation: **do not cut over**. Massive is not safe to select as the
primary US provider until both gates pass. yfinance remains the sole persisted
and default path.

## Deferred NSE/BSE and mixed-currency changes

TrueData integration is not started. A later India milestone requires:

- canonical exchange-qualified identity, cross-listings, and symbol-history
  validity ranges rather than a globally unique bare ticker;
- provider instrument identifiers mapped to canonical instruments with validity
  periods, never leaked into portfolio or analytics code;
- INR and other ISO-4217 currencies with explicit price/cash precision;
- NSE/BSE calendars, holidays, special sessions, timezone rules, and
  venue-specific completed-session logic;
- exchange-specific split, bonus, rights, and dividend semantics;
- historical FX aligned to valuation/execution time;
- mixed-currency cash, cost basis, realized/unrealized P&L, benchmarks,
  portfolio aggregation, and backtests with an explicit reporting currency.

These changes must precede—not be improvised inside—a TrueData adapter.
