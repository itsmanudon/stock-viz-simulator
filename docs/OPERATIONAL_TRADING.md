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
- Settlement compares the latest **1d close** to the limit/trigger and fills at that close, not at the trigger price, on the weekday 16:45 ET job (after the daily refresh).
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
| `/trade` | `ticker` |
| `/orders` | `status` |
| `/watchlist` | none (single default list) |
| `/alerts` | `ticker` (create prefill), `view=active\|triggered\|all` |

## Server / client boundaries

Server Components load account, orders, quotes, watchlist, and alerts. Client islands submit server actions. Optional quote/sparkline fetches fail independently.

## Currency display

Operational prices for a security (close, limit/trigger, fill, alert target, estimated notional) use that symbol's ISO-4217 currency from the tracked universe. Cash, reserved cash, buying power, and total value stay in the portfolio display currency. The ledger and FX conversion are unchanged; this is formatting only. Unknown tickers fall back to USD.

## Known EOD execution limitations (intentional)

- Market orders fill immediately at the latest stored daily close.
- Pending orders are not intraday trigger execution.
- Estimated notional in the ticket is a display product of quantity × displayed price/close; it is not a pre-trade risk engine.
- Alerts are not real-time monitoring.

These are the seams a later Simulation Fidelity / Replay architecture should replace, not widen in the UI.
