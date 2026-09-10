# Trading Journal / P&L Calendar — design

Date: 2026-09-05

**Initial design record.** The completed implementation and revised accounting
decisions are documented in [TRADING_JOURNAL.md](../../TRADING_JOURNAL.md).
Review on 2026-09-06 superseded the inferred cost basis and closing-time signal
lookup below: new fills persist their basis; historical entry signals remain
unavailable. The shipped API also adds bounded day pages, lazy week highlights,
incomplete-history counts, and a second migration for equity basis. Desktop
inspection begins at 1024px and reserves calendar space. New option purchases
require USD underlyings until option FX accounting exists.

Strengthens the **Track** stage of Screen → Research → Simulate → Track with a
month-grid view of *realized* trading P&L, drilling Month → Week → Day →
individual closing execution.

## 1. Source of truth

| Instrument | Row | Realized P&L | Session timestamp |
| --- | --- | --- | --- |
| Equity | `trades` | `trades.realized_pnl` (USD, `Numeric(20,6)`, set by `apply_fill` on sells) | `trades.ts` (naive UTC) |
| Option | `options_positions` | `options_positions.realized_pnl` (**new**) | `options_positions.settled_at` |

Nothing else feeds the Journal. Specifically **excluded**: NAV snapshots,
mark-to-market/unrealized P&L, cash flows, dividends (`portfolio_dividends`),
and Replay fills (`replay_fills` — an isolated book, by design).

Ownership is enforced by resolving `ensure_default_portfolio(session, user_id)`
and filtering on `portfolio_id` / `user_id`. No endpoint accepts a portfolio or
user id from the client.

## 2. Definition of a "trade"

> A Journal **trade** is one *closing execution* — an execution that realized a
> gain or loss.

- Equity: a `trades` row with `realized_pnl IS NOT NULL` (i.e. a sell). A buy
  opens exposure and realizes nothing; counting buys would make "win rate"
  meaningless.
- Option: an `options_positions` row in a terminal status (`closed`,
  `exercised`, `expired`) with `realized_pnl IS NOT NULL`.

Classification: `realized_pnl > 0` → winner, `< 0` → loser, `== 0` → scratch
(counted in `trade_count`, in neither winners nor losers). `win_rate =
winners / (winners + losers)`, `null` when that denominator is 0.

Partial closes, scale-outs, multiple fills, and the same symbol traded several
times in a day each produce their own closing execution and are each counted —
this is deliberately a *fill-level* not a *round-trip-level* definition, and it
matches what `trades.realized_pnl` already measures.

## 3. Options accounting (new)

`options_positions` gains two nullable columns:

- `proceeds` — cash actually credited by the terminal event.
- `realized_pnl` — USD gain/loss over the whole life of the contract.

Populated at the moment the position leaves `OPEN`:

| Terminal event | `proceeds` | `realized_pnl` |
| --- | --- | --- |
| Sold to close | theoretical value credited | `proceeds − premium_paid` |
| Expired OTM | `0` | `−premium_paid` |
| ITM, cash-settled (call or put) | intrinsic credited | `proceeds − premium_paid` |
| ITM call exercised into equity | `0` | `−premium_paid` |
| ITM put exercised against held shares | `strike × shares` | `(strike − avg_cost) × shares − premium_paid` |

The last two rows are where the money changes book. An exercised call converts
into an equity position at the strike cost basis; the remaining P&L is realized
later by the equity book, so the option leg realizes only the sunk premium — no
double counting. An exercised put sells held shares *without* writing a `Trade`
row, so that equity realization has no other home and is recorded on the option
leg instead.

**Backfill.** The migration backfills `EXPIRED` rows only
(`realized_pnl = −premium_paid`, `proceeds = 0`) — deterministic from data
already stored. Historical `CLOSED` / `EXERCISED` rows keep `NULL`, because
their proceeds were never persisted and re-pricing them today would not be
reproducible. NULL rows are excluded from every Journal aggregate. This is the
"no claims we can't count" rule applied literally.

## 4. Session-date semantics

A day cell is a **New York trading session date**, not a UTC date. Timestamps
are naive UTC in the DB; the Journal attributes each execution with the
existing `services/ingest/bar_semantics.new_york_session_date()` after
re-attaching UTC. A 2026-08-20T01:30Z fill is therefore an **Aug 19** trade,
and DST is handled by `zoneinfo`, not by a fixed offset.

The API takes `year`/`month` as a New York calendar month and converts the
month bounds to a UTC half-open range for the SQL predicate, so the query stays
index-friendly instead of wrapping the timestamp column in a function.

Weekends stay visible but muted: `execute_trade` fills at the latest close on
*any* calendar day, so a Saturday fill is real data and must not be hidden.

## 5. Currency

Realized P&L is a **USD** ledger quantity captured at fill-time FX (the
`fx_rate` column exists precisely so history isn't re-converted at today's
rate). The Journal reports USD and says so, matching the existing `/trades`
page. It does **not** convert into `users.display_currency`, because doing so
would re-price historical realizations at a current rate.

## 6. Aggregation service

`services/journal/` — pure, session-scoped, no HTTP knowledge:

- `session_date(ts) -> date` — the UTC→NY attribution.
- `realized_executions(...) -> list[JournalExecution]` — one normalized record
  per closing execution across both instruments, carrying `session_date`,
  `kind`, `ticker`, `realized_pnl`, and the fields the day inspector needs.
- `month_summary(...)` — folds executions into day buckets, then week buckets
  (Monday-anchored weeks clipped to the month), then a month total.
- `day_detail(...)` — the executions for one session date.

Aggregation is pure over the execution list, so every edge case (scratch days,
month boundaries, decimal precision) is unit-testable without a database.
All arithmetic is `Decimal`; serialization is `Decimal` → JSON string, matching
`schemas.py` convention.

## 7. API

```
GET /v1/portfolio/journal/months/{year}/{month}   -> JournalMonthOut
GET /v1/portfolio/journal/days/{date}             -> JournalDayOut
```

`JournalMonthOut` carries `period`, `summary`, `days[]` (only days with
activity), and `weeks[]`. It deliberately carries **no trade list** — the month
payload stays O(days) regardless of trade volume. `JournalDayOut` carries the
day's summary plus its executions, fetched lazily when a day is opened.

`summary.return_pct` is realized P&L as a percentage of the portfolio NAV at
the start of the month (last `portfolio_snapshots.nav` strictly before the
month). It is `null` — and the UI hides the metric — when no such snapshot
exists. It is *not* labelled a time-weighted return, because it isn't one.

`profit_factor` = gross profit / gross loss, `null` when gross loss is 0.

**Signal at entry** (per equity execution): the most recent `recommendations`
row for that ticker with `computed_at <= trade.ts`. This is look-ahead safe by
construction — the row was written before the fill. Shown as `score / 7`
(`MAX_SCORE`). `null` when no such row exists; never reconstructed from today's
data.

## 8. Indexes

`trades` currently indexes `portfolio_id` and `ts` separately. The month query
filters `portfolio_id = ? AND ts >= ? AND ts < ?`, so add
`ix_trades_portfolio_ts (portfolio_id, ts)`. `options_positions` gains
`ix_options_positions_user_settled (user_id, settled_at)` for the same reason.

## 9. Caching

ADR-0004 rejects Redis, and it stays rejected: this is one indexed range scan
over a single user's own trades. The aggregation sits behind
`services/journal/` with no HTTP or ORM-session assumptions leaking out, so a
cache would wrap `month_summary` at exactly one call site. Documented, not
built.

## 10. Frontend

Journal is a fifth `PortfolioTab`, reusing the established tab + URL-state
convention rather than adding a route:

```
/portfolio?tab=journal&month=2026-08[&date=2026-08-19][&week=2026-08-17]
```

The first month is server-rendered in `loadPortfolioData` so there is no
spinner on arrival. Month navigation and inspector opens are client-side
fetches through browser-callable route handlers (`app/api/journal/...`,
following `app/api/alerts/route.ts`), with `window.history.pushState` for URL
sync — no server round trip, and Back/Forward work through `useSearchParams`.
In-flight requests are aborted on change so rapid date switching cannot flash
stale data.

Components (`components/journal/`):

`JournalPanel` (state + fetching) → `JournalSummary`, `PnlCalendar` →
`PnlCalendarHeader`, `PnlCalendarWeekRow` → `PnlCalendarDayCell`,
`WeeklySummaryCell`; `JournalInspector` → `DayInspector` / `WeekInspector` →
`JournalExecutionRow`.

Accounting, date math, and tint normalization live in
`lib/journal-view-model.ts` as pure functions; components only present.

### Tint normalization

Deterministic, month-local, and robust to one outlier:

```
median = median of |pnl| over the month's non-zero days
ratio  = |pnl| / median                      (median <= 0 -> every day level 1)
level  = 1 if ratio < 0.6, 2 if ratio < 1.4, else 3
```

In words: a day well under a typical day this month gets the lightest tint, a
day well over it the strongest. The anchor is a median, so one outsized session
cannot move it, and it is month-local so a quiet month still shows its own
internal contrast.

A `log1p(|pnl|) / log1p(scale)` version was tried first and is recorded in the
code because it looks reasonable and is not: a ratio of logs sits near 1 for
almost any two large numbers, so on real data every day but the very smallest
collapsed onto the strongest tint.

Three levels render as `--positive` / `--negative` at 5% / 9% / 14% surface
opacity (6% / 11% / 17% on the dark ground, which swallows a tint that warm
paper takes readily) — a tint over the card surface, never an opaque card.
Sign is *also* carried by an explicit `+`/`−` on the number and by the aria
label, so colour is never the only channel.

### Inspector

One `radix-ui` `Dialog`, responsive: a right-side slide-over from `sm` up
(the left app sidebar is never covered, and the calendar stays visible), a
bottom sheet below. Selecting a different day updates the open inspector in
place. `Escape` closes; arrow keys move the focused day cell within the grid;
each cell is a real `<button>` with an aria label of the form
"August 19, profit 5,267 dollars, 20 trades".

### Typography

No font change. Space Grotesk + JetBrains Mono are a deliberate, documented
identity choice, and JetBrains Mono already supplies true tabular figures and a
slashed zero — which is what the financial-alignment requirement actually
needs. `globals.css` already applies `font-variant-numeric: tabular-nums
slashed-zero` to `.font-mono`, `.tabular-nums`, and `[data-financial]`.
Migrating to Geist would churn every surface in the app for no numeric gain.

## 11. Testing

- **API**: day/week/month aggregation (profit, loss, scratch, empty, multiple
  trades and symbols per day, month boundaries), UTC→NY attribution including a
  DST transition, options realized P&L for each terminal event, decimal
  precision, and cross-user isolation.
- **Web**: tint normalization, calendar grid construction, week clipping,
  URL-state round trip, and inspector open/close/empty/error rendering.

## 12. Known limitations

- Historical `CLOSED` / `EXERCISED` options (written before this change) have
  no realized P&L and are excluded from the Journal.
- "Trade" is fill-level, not round-trip level. A round-trip view would need a
  lot-matching layer that does not exist yet.
- No commissions or fees are modelled anywhere in StockViz, so none are
  deducted here.
- Realized P&L is USD-only, by design (see §5).
