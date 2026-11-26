# Operational trading domain

StockViz operational trading is the authenticated loop after research: execute a paper order, manage pending conditions, watch symbols, and observe in-app price alerts. It is not a brokerage, and it is not a live tape.

```
Markets / Research / Stock workspace
        → /trade          execution workstation
        → /orders         pending vs history
        → /watchlist      monitoring list
        → /alerts         price conditions
        → /portfolio      impact
```

## Trade vs stock-workspace trading

| Surface | Job |
| --- | --- |
| `/stocks/[ticker]` | Investigate one security; ticket is contextual and ticker-locked. |
| `/trade` | Choose a symbol, see buying power / position / pending orders, submit a market or conditional order, then jump to Orders or Portfolio. |

`/trade?ticker=AAPL` prefills the ticket. Changing the symbol rewrites that query. Do not hide the selected ticker in client-only state.

## Orders

`/orders?status=pending|filled|cancelled|all` (default `pending`).

- Pending BUY orders reserve cash; pending SELL orders reserve shares. The backend is authoritative.
- Settlement compares the latest **1d close** to the limit/trigger (via the shared `legacy_close` kernel) and fills at that close, not at the trigger price, on the weekday 16:45 ET job (after the daily refresh).
- `cancel_reason` is shown when the API provides one (insufficient cash/shares at settlement, missing FX, missing portfolio). A user cancel currently stores no reason; the UI labels that as cancelled by the user.

## Watchlist placement

Watchlist stays under **Portfolio**, not Trade. It is a monitoring surface (“what do I care about”), not an order blotter. `/watchlist` is stable.

## Alerts

`/alerts` is the management surface. The header bell is compact status (triggered, undismissed count) and a shortcut — not the whole system.

- Directions: `above` / `below` against the latest stored close.
- Evaluation runs when bars refresh (market analytics worker), not as a real-time stream.
- Delivery is in-app only. Dismiss applies to triggered alerts; delete removes the row.

`/alerts?ticker=AAPL` prefills create. The same server actions are used from the stock header popover.

## URL conventions

| Route | Shareable state |
| --- | --- |
| `/trade` | `ticker`, `book` |
| `/orders` | `status`, `book` |
| `/portfolio`, `/dashboard`, `/trades` | `book` (and their own state) |
| `/watchlist` | none (single default list) |
| `/alerts` | `ticker` (create prefill), `view=active\|triggered\|all` |

## Server / client boundaries

Server Components load account, orders, quotes, watchlist, and alerts. Client islands submit server actions. Optional quote/sparkline fetches fail independently.

## Books (A5.1, A5.2)

A user can hold up to 20 books (`/v1/books`). One is the default: every
trading route without `?book=<id>` uses it. Trades, orders, options,
positions, snapshots, split rebases, risk limits, the journal and portfolio
alerts are per book; price alerts, watchlists and the display currency stay
per user. Each paper book has its own base currency (USD or INR, fixed after
its first activity) and starts with that currency's starting cash. An
archived book is readable but takes no trades or orders (409), and an
imported book (filled by the Zerodha import, A5.3, below) never trades here.
Another user's book is 404.

**In the web (A5.2).** The selected book is URL state: `?book=<id>` on the
dashboard, portfolio, trade, orders, trades and settings pages, `?book=all`
for All books (not on settings); absent means the default book. The top-bar
switcher lists every book (kind, currency, holder, archived) and links with
`?book=`; it also remembers the choice in a cookie, used only when a page is
opened without `?book=`. Links between these pages keep the book. Every
ticket says which book it trades into and posts that book's id; in All
books, an archived book or an imported book it is disabled with the reason.
Books are created, renamed, made default, archived and deleted in Settings →
Books.

**All books** is read-only: each book's NAV is converted to the display
currency at that date's stored rate and summed; returns leave out the money
a new book (its opening value) or an imported buy brings in; a rate older
than the session before its date is used with a warning, and a date with no
rate is left out with a warning. Risk, stress, attribution, limits,
dividends, options Greeks and strategies, and the journal are per book only.

## Zerodha tradebook import (A5.3)

An imported book (Settings → Books, kind Imported; created in INR) is filled
from a Zerodha Console tradebook downloaded as **CSV** (equity segment, up
to a year, at most 2 MB). On `/portfolio/import?book=<id>` (linked from the
imported book's notice and the sidebar):

1. **Preview.** The file goes to a server action and on to the API as
   `text/csv`; nothing is stored. The preview shows which header each field
   was read from, the first 20 new trades (with estimated charges and any
   split restatement) and every problem by row number: rejected rows (with
   the field and a fixed reason, never the cell), F&O and other segments
   (skipped until A6), unknown symbols, trade ids repeated in the file or
   already imported, sells that need an opening lot and basis-uncertain
   prices.
2. **Confirm import.** The same file is sent again with the preview's
   SHA-256; another file is refused. The new trades are stored and the book
   is rebuilt: holdings only (no cash), weighted-average cost and realized
   P&L, buys and sells counted as outside flows in All books.

**The column map is unconfirmed**: Zerodha publishes no column list, so the
default names come from a third-party description. If the preview's columns
look wrong, send the header row (never the file).

- **Dates:** ISO, month names and numeric dates; a numeric date is read
  day-first or month-first only when the file shows which (a part over 12),
  otherwise ambiguous rows are rejected. Times are IST.
- **Dedupe:** one trade per (book, exchange, trade id); the same file twice
  adds nothing, an overlapping file adds only the new trades.
- **Charges are estimated** from the dated schedules (NSE/BSE delivery; the
  part of a day's buys and sells of one scrip that offset is priced as
  intraday, "inferred").
- **Splits:** trades before a recorded split are restated to the
  split-adjusted bars (the stored fill keeps the as-traded numbers); a
  price far outside its day's bar is flagged "basis uncertain" (a bonus or
  rights issue not recorded yet).
- **Opening lots:** a sell with too few shares bought before it waits until
  you add an opening lot (symbol, date, quantity, average price).
- **History:** each import lists its counts and can be deleted in two steps;
  its trades leave the book and positions are rebuilt from the rest.
- **Plans:** a plan written in the imported book before a buy's time locks
  at that buy; "Plan an open position" links one written later (labelled
  written after entry).
- **Privacy:** the file, its name and your client id are never stored or
  logged; the import keeps parsed fields and the file's hash.

## Trade plans (A5.4)

Both paper tickets (the stock page and `/trade`) have an optional "Plan this
trade" section for a buy (market or limit): planned entry, stop, target
(optional), size, a setup version, a thesis (one of your open theses on the
symbol and/or your own words), why now and tags. The review shows the plan
with its risk if stopped and reward : risk. Placing the order creates the
plan and links the order: a market buy links its fill at once, a limit buy
when it settles. **The plan locks at its first fill**: after that its entry,
stop, target, size, setup and reasons are frozen and the API refuses edits
with 409; notes and tags stay editable. When the book's position in the
symbol returns to zero, its active plans close.

The Portfolio **Journal** tab lists the book's plans (status filter; badges
Locked, Written after entry, Not filled yet). "Plan an open position" writes
a plan for a holding bought without one: its fills came first, so the plan
is labelled **written after entry**, never shown as locked, and is left out
of plan-adherence figures (A5.6). Plans are per book and private; API
`/v1/plans` (see `apps/api/CLAUDE.md`).

## Currency display

Operational prices for a security (close, limit/trigger, fill, alert target, estimated notional) use that symbol's ISO-4217 currency from the tracked universe. Cash, reserved cash, buying power, and total value stay in the portfolio display currency. The ledger and FX conversion are unchanged; this is formatting only. Unknown tickers fall back to USD.

## Known EOD execution limitations (intentional)

- Market orders fill immediately at the latest stored daily close.
- Pending orders are not intraday trigger execution.
- Estimated notional in the ticket is a display product of quantity × displayed price/close; it is not a pre-trade risk engine.
- Alerts are not real-time monitoring.

These are the seams a later Simulation Fidelity / Replay architecture should replace, not widen in the UI.
