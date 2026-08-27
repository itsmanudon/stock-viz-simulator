# StockViz Phase 6 Operational Trading Workspace Design

**Date:** 2026-08-27  
**Branch:** `cursor/feat-operational-trading-workspace-0ecf`  
**Base:** Phase 5 Research workspace (`cursor/feat-research-workspace-0ecf`). `origin/dev` did not yet contain Phase 5 when this branch was cut; PR #77 was open and green.

## Objective

Make Trade, Orders, Watchlist, and Alerts feel like one operational system without inventing execution, alerting, or market-data capabilities.

```
Discover → Research → Stock workspace → Place / manage paper trade
        → Track orders → Monitor watchlist + alerts → Portfolio
```

Standalone `/trade` is an **execution workstation** (symbol switching, buying power, ticket, open orders, recent fills). The stock workspace remains the preferred contextual ticket while researching one ticker.

## Product decisions

- **Trade vs stock ticket.** `/trade` is not a second stock page. It owns symbol selection, account context, and mixed order types. `/stocks/[ticker]` keeps the existing contextual ticket.
- **Order families stay as they are.** Immediate fills go through `POST /v1/trades` (market, latest stored 1d close). Pending limit / stop-loss / take-profit go through `POST /v1/orders`. Stop-loss and take-profit remain sell-only.
- **`/trade?ticker=` is first-class.** Portfolio already emitted this query; the page now reads it and writes it back when the symbol changes.
- **Orders filters are URL-backed.** `?status=pending|filled|cancelled|all` (default `pending`). Cancel keeps the current query.
- **Cancel reasons are visible.** The API already returns `cancel_reason`; the UI must show it. User-initiated cancel has no reason string today — label that as cancelled by user rather than inventing a backend enum.
- **Watchlist stays under Portfolio.** It answers “what do I care about right now?”, not “what am I executing?”. Route `/watchlist` is unchanged.
- **Alerts get a dedicated `/alerts` route** under Portfolio, next to Watchlist. The utility-bar bell stays a compact unread/triggered indicator plus a jump to `/alerts`. No email/push/SMS.
- **Honesty copy.** Market fills and alert evaluation use stored daily closes. Pending orders settle on the weekday EOD job. Do not say live exchange, real spread, or real-time monitoring.
- **No new accounting.** Estimated notional is display-only from API decimal strings. Buying power, reservations, and fills stay on the backend.

## Information architecture

| Surface | Route | Nav |
| --- | --- | --- |
| Trade ticket | `/trade` | Trade → Trade ticket |
| Orders | `/orders` | Trade → Orders |
| Watchlist | `/watchlist` | Portfolio → Watchlist |
| Alerts | `/alerts` | Portfolio → Alerts |
| Trade history | `/trades` | Portfolio → Trade history (unchanged ledger) |

Trade/Orders share a small operational subnav. Watchlist/Alerts share a monitoring subnav. Portfolio overview is not duplicated onto these pages.

## Server / client boundaries

- Pages are Server Components. They load portfolio, orders, watchlist, alerts, quotes, and symbol lists in parallel.
- Client islands: order ticket, option ticket, watchlist add/remove, alert create, cancel button pending state, bell.
- Mutations stay on existing server actions (`placeTradeAction`, `placeOrderAction`, `cancelOrderAction`, `toggleWatchlistAction`, alert CRUD). No browser JWT.

## Future seam (not in this phase)

A later Simulation Fidelity program can replace EOD fill copy and settlement with a shared execution kernel. Phase 6 should keep those assumptions visible so SIM-01…SIM-10 can land without undoing the workstation IA.
