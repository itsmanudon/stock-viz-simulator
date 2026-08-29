# Market-data semantics

Market data is not ordinary CRUD data. This document states the
assumptions StockViz's ingest and pricing code actually makes, so they can
be checked rather than guessed at. Every claim here is verifiable in
`apps/api/src/stockviz/services/ingest/prices.py` and
`apps/api/src/stockviz/models/market.py`.

Read alongside [Schema and indexing](./schema.md) and
[KNOWN_LIMITATIONS.md](../KNOWN_LIMITATIONS.md).

## The core assumption

**Everything in StockViz prices off the latest `1d` close.** Quotes,
charts, market fills, pending-order triggers, backtests, alerts, option
pricing, and NAV all read `price_bars` where `interval = '1d'`. There is
no intraday book anywhere in the application.

## Timestamp semantics

| Property | Value | Where |
| --- | --- | --- |
| Column type | `TIMESTAMP` **without** time zone | `models/market.py` |
| Python convention | Naive UTC at the boundary | `_time.py::utcnow` |
| Bar `ts` for a daily bar | The provider's session date with tz stripped | `services/ingest/prices.py` (`ts.replace(tzinfo=None)`) |

> **Assumption to be explicit about.** For a `1d` bar, `ts` is a *session
> date*, not a UTC instant. yfinance returns a date-indexed frame; the
> ingest strips any tzinfo rather than converting. So `ts` identifies
> "which trading day", and comparing it to `utcnow()` compares a session
> date against a UTC wall clock. Everything downstream treats it as a day
> key, which is consistent — but it is a convention, not a UTC timestamp,
> and adding intraday intervals would force this to be revisited.

`SimulatedExecution.observed_at` / `evaluated_at` are a different thing
again: they are evaluation and settlement wall-clock time, **not**
`PriceBar.ts`. See [SIMULATION.md](../SIMULATION.md).

## Adjusted vs unadjusted prices

```python
kwargs = {"interval": "1d", "auto_adjust": False, "actions": False}
```

**Bars are stored unadjusted.** `auto_adjust=False` is explicit in
`_default_yfinance_history`. Consequences:

- A stock split produces a discontinuity in the stored series. Nothing in
  ingest detects or back-adjusts for it.
- Historical `avg_cost` on a position held across a split will not line up
  with post-split prices.
- The seed CSVs are likewise not split-adjusted, which is why
  `apps/web/scripts/seed-demo.mjs` derives demo cost basis from *today's*
  close rather than reading it from history — the script header explains this.
- Backtests over a period containing a split will show a spurious jump.

`dividends` are modelled separately as declared payouts per symbol and
credited to portfolios by a scheduled job; they are **not** folded into
price history.

## Corporate actions

| Action | Handled? |
| --- | --- |
| Cash dividends | Yes — `models/dividend.py`, credited by `dividend_credit_refresh` |
| Splits | **No** — no detection, no back-adjustment, no position adjustment |
| Reverse splits | No |
| Mergers / ticker changes | No — `symbols.ticker` is the natural PK; a renamed ticker is a new symbol |
| Delistings | Partial — `symbols.is_active` lets the scheduler skip a symbol without losing history |

## Idempotent ingest

Three independent guards make re-ingest safe:

1. **`price_bars` PK `(ticker, ts, interval)`** with Postgres
   `ON CONFLICT DO UPDATE` (`upsert_bars`). Re-fetching a date rewrites
   the row.
2. **`consumer_inbox`** — a replayed Kafka event is skipped entirely.
3. **`news_articles.url` unique** — the same article from a second query
   is a no-op.

This is why at-least-once delivery is acceptable: the write path is
idempotent at the storage layer, not just at the message layer.

### Historical corrections are silently accepted

`upsert_bars` overwrites on conflict. If a provider revises a past bar,
the new values win and **the old values are not retained**. There is no
bar-version history and no `corrected_at` column. That has a real
consequence for replay: a past replay session's forensics can change if an
underlying bar is later corrected, because replay reads live `PriceBar`
rows rather than an immutable dataset snapshot. This is recorded in
[KNOWN_LIMITATIONS.md](../KNOWN_LIMITATIONS.md).

## Incomplete bars

The daily refresh runs at **16:30 America/New_York**
(`scheduler.py::daily_price_refresh`), after the US close, and the hourly
top-movers job runs 10:00–16:00. There is no explicit "is this bar
final?" check — the code relies on job timing rather than a market
calendar. Consequences:

- A manual `stockviz.cli ingest` run mid-session can store a partial bar
  for today, which the upsert will later overwrite with the final one.
- There is **no exchange-calendar library**. Weekends and holidays are
  handled implicitly: the provider returns no rows, and ingest logs
  "provider returned no bars" and marks the request processed.
- FX rates handle the same gap explicitly by forward-filling — reading the
  most recent rate on-or-before the requested date (`models/market.py::FxRate`).

The one place staleness *is* checked explicitly is pending-order
settlement: `settle_pending_orders` takes a `session_date` and leaves
orders pending when the latest bar predates it, so a failed refresh cannot
fill an order against a stale close.

## Provider differences and provenance

| | yfinance | Alpha Vantage |
| --- | --- | --- |
| Role | Primary | Fallback, only when yfinance returned **no** rows |
| Key required | No | `ALPHA_VANTAGE_KEY` |
| Free-tier limit | Generous | 25 requests/day |

`price_bars.source` records which provider wrote each row, so mixed-source
history is at least attributable. But note the gap: because the fallback
only fires when yfinance returns nothing, a single ticker's history can
interleave sources across dates, and **the two providers are not
reconciled**. If they disagree on a bar, whichever wrote last wins, and
`source` is overwritten along with the OHLCV values.

Currency comes from `symbols.currency` (ISO-4217), set from the suffixed
provider ticker (e.g. `BARC.L` → GBP). `fx_rates` stores USD-per-unit so
conversion is multiplicative; USD short-circuits to `Decimal(1)` and is
never stored.

## Checklist when touching ingest

- Does the write stay idempotent under replay?
- Does it preserve the `(ticker, ts, interval)` key meaning?
- Does it mix adjusted and unadjusted prices?
- Does it assume a bar is final?
- Does it treat `ts` as a UTC instant rather than a session date?
- Does it convert native currency to USD before touching cash?
