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
imported book (filled by the Zerodha import, A5.3) never trades here.
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
