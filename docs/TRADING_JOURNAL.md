# Trading Journal / P&L Calendar

Journal strengthens **Track** in Screen → Research → Simulate → Track. Open
`/portfolio?tab=journal&month=2026-08`; optional `date=2026-08-19` or
`week=2026-08-17` restores an inspector. These URLs identify a view, never an
account: another signed-in user sees their own data.

See [implementation verification](TRADING_JOURNAL_VERIFICATION.md) for commands,
test results, visual review, and the changed-file inventory.

## Repository integration

- Next.js App Router / React 19: Portfolio remains the authenticated server page
  with overview performance and Positions, Options, Orders, Income, Journal tabs.
  No competing Portfolio route or account store was added.
- `loadPortfolioData` fetches the first month only for the active Journal tab.
  Existing portfolio, analytics, history, orders and dividend calls retain their
  independent failure handling. Journal failure stays within its tab.
- Browser requests use Next route handlers and the existing `authedGet` bridge:
  NextAuth session → short-lived signed user JWT → FastAPI `UserIdDep`.
  The service resolves the default portfolio and scopes both instrument queries
  by ownership. No client-supplied account ID is accepted.
- SQLModel / SQLAlchemy on PostgreSQL, Alembic migrations, `Numeric` / `Decimal`
  accounting and decimal-string JSON are preserved. Vitest/Testing Library,
  pytest (SQLite and PostgreSQL), and Playwright remain the test tools.
- Existing Space Grotesk and JetBrains Mono remain. Mono financial values use
  tabular figures. Switching the whole application to Geist would add churn.
  Radix Dialog/Button/Tabs, existing financial colors, surfaces, focus rings,
  currency formatting, and sidebar breakpoints are reused. The calendar needs
  no new chart dependency; portfolio charts continue using existing utilities.

## Source of truth and the meaning of a trade

A Journal **trade** is one closing equity fill or one terminal option event
with a persisted realization. Two partial sells count as two trades; two buys
and one final sell count as one. This is an execution-level measure, not a
round trip, tax lot, order submission, or current position count.

Equity records come from `trades.realized_pnl`, written by the same `apply_fill`
path used by market and pending orders:

`realized_pnl_usd = (exit_price_native − weighted_avg_cost_native) × sold_quantity × fill_fx_rate`

The ledger quantizes to six decimal places. Buying recalculates weighted-average
cost; selling preserves the cost of remaining shares. New fills also persist
`avg_cost_at_fill` before mutating the holding. Legacy entry cost is shown as
unavailable: reversing a rounded realization can materially distort the basis
of a small fractional fill. Historical P&L is never revalued at current FX.

This is the existing ledger's **price P&L translated at closing FX**, not a
separate calculation of currency gains between acquisition and disposal.
Native equity entry/exit prices retain the symbol currency; every Journal gain
or loss is explicitly USD.

Live equity and option books are long-only. The current live book has no fees,
commissions, short sales, partial option closes, or multi-leg execution model.
Journal does not invent those capabilities or subtract hypothetical fees.
Replay is a separate book and is excluded, as are dividends, deposits, NAV
movement, and unrealized mark-to-market changes.

## Options

`options_positions.proceeds` and `realized_pnl` are persisted when an open
position closes or settles. Contract quantity uses the existing multiplier of
100. These values describe the simulator's ledger, not broker tax reporting.

| Terminal event | Cash credited (`proceeds`) | Realized P&L |
| --- | --- | --- |
| Sell to close | Current theoretical value × contracts × 100 | Proceeds − premium paid |
| Worthless expiry | 0 | −premium paid |
| Intrinsic cash settlement | Intrinsic × contracts × 100 | Proceeds − premium paid |
| Call exercised into equity | 0 | −premium paid; shares retain strike basis |
| Put exercised against held equity | Strike × delivered shares | (Strike − equity average cost) × shares − premium paid |

The physical exercise convention preserves the existing equity book: a call's
remaining gain is realized on subsequent share disposal. A put's share disposal
does not create a separate Trade row, so its equity realization is included in
the option event exactly once. Proceeds on an exercised put are therefore share
sale proceeds, **not exit premium**. The inspector labels them “Proceeds.”

Settlement refreshes and rechecks OPEN under the portfolio lock. It waits until
the New York expiry date is complete and uses the latest stored daily close on
or before expiry; delayed workers cannot use a later price. A missing price
leaves the position open for a later run. This remains an EOD theoretical
simulator: it has no market option quotes, holiday calendar, or quote freshness
guarantee at expiry.

Non-USD option premiums and exercises previously lacked FX accounting. New
option purchases are restricted to USD underlyings. Historical non-USD options
are excluded from Journal totals and counted as unavailable; correct FX support
for those contracts requires a separate accounting migration.

## Dates and aggregation

Database instants are naive UTC by repository convention. The service attaches
UTC and reuses `new_york_session_date` / `America/New_York`. APIs return explicit
UTC offsets; inspector times are ET. Today/reset uses the same timezone on the
server and in the browser. DST changes are handled by `zoneinfo` and `Intl`.

The calendar is an **account reporting calendar of execution dates in New York**,
not the date of the price bar used to fill an order. A fill at September 1,
01:30 UTC appears on August 31. Weekend executions remain visible because the
paper engine can fill at the latest EOD close on weekends. Delayed option
settlement appears on its actual settlement date, not retroactively on expiry.

The current symbol model has no exchange-timezone abstraction. Foreign equities
use this same explicitly labeled account reporting timezone; local-exchange
session calendars are a follow-up, not an inferred mapping from ticker suffixes.

Queries use half-open UTC bounds converted from New York midnight. Timestamp
columns are not wrapped in timezone functions, preserving index use. Pure
Decimal folds produce daily, Monday–Sunday weekly (clipped to the selected
month), and monthly totals. Winners are `P&L > 0`, losers `< 0`, scratches `= 0`.
Win rate is winners / (winners + losers); no decided trades yields null.
Profit factor is gross profit / absolute gross loss; no losses yields null.
Best/worst means the highest/lowest recorded execution, including scratch trades.

“% of prior NAV” divides realized P&L by the last positive USD NAV snapshot
strictly before the month. It is a ratio to recorded NAV, **not monthly portfolio
return or a cash-flow-adjusted return**. No eligible snapshot means no percentage.

## API, components, and performance

| FastAPI read | Response |
| --- | --- |
| `/v1/portfolio/journal/months/{year}/{month}` | Period, summary, days, clipped weeks, prior NAV, unavailable count; no execution list |
| `/v1/portfolio/journal/days/{date}?offset=0&limit=100` | Full-day statistics and an execution page; limit 1–200, `has_more` |
| `/v1/portfolio/journal/weeks/{start}` | Clipped week statistics and best/worst execution details |

Next `/api/journal/...` proxies are authenticated and `private, no-store`.
`services/journal/{model,query,aggregate}` separates accounting records, owned
range reads, and pure folds. The package's view functions orchestrate them.
Generated OpenAPI types and `schema-check.ts` check the frontend contract.

`JournalPanel` coordinates URL state, abortable requests, retries, a six-month
working cache, refresh-on-focus, and explicit refresh. Cached revisits revalidate.
`JournalSummary`, `PnlCalendar`, `PnlCalendarDay`, and `WeeklySummaryCell` render
the calendar. `JournalInspector` presents day/week detail and
`JournalExecutionRow` links back to the stock workspace.

Month work is proportional to that account's executions **in the month**, not
its entire history; the response is proportional to days. There are no per-fill
database calls. Day payloads default to 100 records. Current day statistics and
pagination read/fold the selected day's rows before slicing; server memory is
therefore O(day executions), even though response size is bounded. SQL rollups
and cursor pagination are the next step if measured activity requires them.
An append-only ledger and `(timestamp, reference ID, instrument)` ordering keep
page boundaries deterministic; historical imports during pagination require refresh.

There is no Redis (ADR-0004). Future caching belongs around the view functions,
with user/portfolio/month keys and invalidation after committed fills and option
settlements. Correctness currently takes priority over a second cache service.

## Presentation and accessibility

Tint intensity uses the median nonzero absolute daily P&L within the month.
Ratios below 0.6, below 1.4, and at least 1.4 select three restrained semantic
tints. Zero is neutral; signs and accessible descriptions also communicate gain
and loss. With only two active days the median is less resistant to an outlier.

The desktop inspector reserves right-hand space without covering the left
sidebar or date controls. Container queries move week summaries below rows as
space narrows. Below 1024px the inspector becomes a modal bottom sheet with a
scrim, focus containment, and Escape/close. At 320px the calendar can scroll
inside its own region; it does not widen the page. Compact figures omit repeated
currency symbols under the explicit USD summary; exact amounts are in detail.
Arrow keys move between dates; Home/End follow the actual calendar week.
Reduced motion disables the 160–190ms panel animations.

## Migrations and limitations

Apply `alembic upgrade head` before deploying API/web code:

1. `a4d7c19f6e02`: option proceeds/realization and composite indexes
   `trades(portfolio_id, ts)` / `options_positions(user_id, settled_at)`.
   Only worthless EXPIRED options are deterministically backfilled.
2. `b6e8a20f4c31`: nullable `trades.avg_cost_at_fill`; no speculative backfill.
   This is separate so an environment that already applied the unfinished first
   migration can advance normally.

### Review of b6e8a20f4c31 and production rollout

The upgrade emits only `ALTER TABLE trades ADD COLUMN avg_cost_at_fill NUMERIC(18,6)`.
It adds a nullable column with no server default, data update, index build, or
constraint validation. Existing rows read NULL, and old application writers
that omit the column continue to work. The ORM also defaults to None. New sells
capture the existing position's native average cost; legacy values are not
inferred from rounded P&L. Existing ledger columns and row identities are preserved.

PostgreSQL does not rewrite the heap for this addition, but it acquires
`ACCESS EXCLUSIVE`, conflicting with readers and writers. The lock lasts until
the surrounding transaction commits. A long-running transaction can delay DDL,
and queued DDL can delay subsequent traffic. Table size does not turn this into
a backfill, but production blocking duration cannot be guaranteed from the
migration alone. See [ALTER TABLE](https://www.postgresql.org/docs/current/sql-altertable.html)
and [explicit locking](https://www.postgresql.org/docs/current/explicit-locking.html).

For a database already at `a4d7c19f6e02`, run b6 alone with deployment-scoped
timeouts, for example from apps/api (adjust timeouts to the deployment policy):

```powershell
$env:PGOPTIONS='-c lock_timeout=5s -c statement_timeout=60s'
uv run alembic upgrade b6e8a20f4c31
```

Inspect long transactions first and use a low-traffic window. On timeout, the
PostgreSQL transaction rolls back; resolve the blocker and retry. Do not blindly
terminate application sessions. PGOPTIONS should be scoped to the migration
process, not made a permanent application setting. Deploy the application after
the schema change; an application rollback can leave the additive column intact.

**The preceding a4 migration needs separate scheduling on large tables.** It
updates expired options and builds ordinary, non-concurrent indexes on options
and trades. Regular index builds block writes; a4's column-addition lock on
options can also block reads until commit. This repository wraps pending
migrations in one transaction, so upgrading through both at once can retain
those locks for the full operation. Size and rehearse a4 separately; use a
maintenance window or a separately engineered concurrent-index rollout when
the write-blocking window is unacceptable. Do not treat a4 + b6 as a metadata-only
deployment. See [CREATE INDEX](https://www.postgresql.org/docs/current/sql-createindex.html).

`alembic downgrade a4d7c19f6e02` drops only the new basis column. It preserves
trade rows and old fields but **permanently loses captured cost basis**; upgrading
again returns NULL, not the previous values. Roll back code that maps the column
before a schema downgrade and export captured values if they must be retained.
Dropping the column also takes an exclusive lock. Leaving the column in place
is preferable for a routine application rollback.

Migration tests verify old rows, old-writer inserts, nullability/defaults,
numeric precision, unchanged PostgreSQL heap identity, downgrade data loss,
and a real two-connection lock timeout followed by successful retry.

Unknown legacy close/settlement P&L is omitted and counted in month, day, and week
incomplete-history notices, including unsupported non-USD option accounting.
Undated historical settlements cannot be assigned to a month. No historical
entry signals are displayed: average-cost closes lack links to opening
decisions, and a recommendation before a sell is not a signal at entry.
`signal_at_entry` remains a nullable contract extension for future persisted
opening-decision provenance and score-bucket analytics.

Local browser fixtures live exclusively in tests and require a disposable
`stockviz_journal_verify_*` database. They create buys and sells through
`apply_fill`; no example activity is shipped in production code.
