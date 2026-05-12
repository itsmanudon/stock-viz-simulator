# StockViz — feature ideas & roadmap

Brainstormed against the current v2 codebase (Phase 7 complete). Each idea
notes the rough effort, the surfaces it touches (web / api / both), and any
existing scaffolding we can build on.

---

## High impact, moderate effort

### 1. Watchlist UI  
**Surface:** web + api | **Effort:** M

`models/watchlist.py` and the DB table exist; the API has no router for it yet
and the web has no `/watchlist` page. Add a `GET/POST/DELETE /v1/watchlist`
router, a watchlist sidebar on the markets page, and a persistent "add to
watchlist" button on each ticker page.

### 2. Portfolio performance chart  
**Surface:** web + api | **Effort:** M

Capture a daily portfolio NAV snapshot (cash + positions × close price) in a
new `portfolio_snapshots` table. Expose via `GET /v1/portfolio/history`.
Render a `lightweight-charts` area chart on the `/portfolio` page so users can
see P&L over time, not just the current balance.

### 3. Price alerts  
**Surface:** web + api | **Effort:** M

Let users set a target price on any symbol (above / below). A new APScheduler
job polls quotes every minute (or on the hourly top-movers pass) and writes
triggered alerts to an `alerts` table. Surface them as an in-app notification
bell in `SiteHeader` using a polling `useEffect` or a Server-Sent Events stream.

### 4. Advanced order types  
**Surface:** web + api | **Effort:** M

Extend the paper-trading engine in `services/trading/` to support:
- **Stop-loss** — auto-sell when price drops below a threshold.
- **Take-profit** — auto-sell when price rises above a threshold.
- **Limit orders** — queue a buy/sell to execute only at a specified price.

The APScheduler hourly job already fetches quotes — hook into it to settle
pending orders.

---

## High impact, higher effort

### 5. Portfolio analytics dashboard  
**Surface:** web + api | **Effort:** L

A dedicated analytics tab on `/portfolio` showing:
- Total return %, annualised return
- Sharpe ratio (using risk-free rate from a config variable)
- Max drawdown
- Sector allocation pie chart
- Top gainers / losers in the portfolio

Most numbers can be derived from existing `bars` + `trades` data server-side.

### 6. Stock screener  
**Surface:** web + api | **Effort:** L

A `/screener` page with filter controls:
- Sector / industry (already in symbol metadata)
- 52-week high/low proximity
- RSI range (overbought / oversold) — indicators service already computes RSI
- Price momentum (N-day return)

Back the UI with a `GET /v1/symbols/screen?sector=Tech&rsi_max=30` endpoint
that queries the `bars` table and runs indicator math server-side.

### 7. Backtesting engine  
**Surface:** api (+ light web UI) | **Effort:** XL

A headless service that replays historical `bars` data through a strategy
definition (e.g., "buy when RSI < 30, sell when RSI > 70") and returns
trade-by-trade P&L. Expose `POST /v1/backtest` accepting a JSON strategy spec.
The web UI can be a simple form + results table first; a visual equity curve
can come later.

---

## Quality-of-life improvements

### 8. OAuth login (Google / GitHub)  
**Surface:** web | **Effort:** S

NextAuth v5 supports it out of the box; it was explicitly deferred past Phase 3.
Add the provider config in `auth.ts`, add `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`
to the env examples, and add a "Sign in with Google" button to the login page.
No API changes needed — the user bridge still works the same way.

### 9. Trade history export  
**Surface:** web | **Effort:** S

A "Download CSV" button on `/trades` that hits a Next.js route handler
(`/api/export/trades`), streams the user's trade log as a CSV, and triggers a
browser download. No new API endpoints; the server action reuses `authedGet`.

### 10. Real-time price ticker  
**Surface:** web + api | **Effort:** M

Add a `GET /v1/stream/quotes` Server-Sent Events endpoint (FastAPI's
`EventSourceResponse`) that pushes the latest quote for a subscribed symbol
every 30 seconds. On the stock detail page, replace the static "last price"
badge with a live-updating component. Falls back gracefully when the user is
not subscribed.

### 11. News sentiment badges  
**Surface:** api (+ web) | **Effort:** S–M

Call the Anthropic API (or a lightweight sentence-transformer) to score each
news headline as Positive / Neutral / Negative on ingest. Store the score in
the `news` table (new column). Surface it as a coloured badge next to each
headline on `/news` and the ticker news panel.

### 12. Leaderboard  
**Surface:** web + api | **Effort:** M

A public `/leaderboard` page that ranks all users by portfolio return % since
account creation (opt-in toggle in profile settings to stay private). The
backend aggregates NAV per user from `portfolio_snapshots` (idea #2) and
caches the ranking hourly.

---

## Technical / infrastructure improvements

### 13. Real NextAuth JWT verification on the API  
**Surface:** api | **Effort:** S

Replace the `X-Internal-Token` + `X-User-Id` bridge in `auth.py` with proper
JWT verification (`python-jose` / `PyJWT`) so the API can independently verify
the session. The `auth.py` docstring already documents this as the upgrade
target.

### 14. Rate-limiting middleware  
**Surface:** api | **Effort:** S

Add `slowapi` to the FastAPI app to rate-limit public endpoints (e.g.,
`/v1/symbols`, `/v1/bars`) per IP. Prevents abuse of the free-tier Render
instance without requiring auth.

### 15. E2E tests with Playwright  
**Surface:** web | **Effort:** M

Add a `tests/e2e/` directory under `apps/web` with Playwright tests for the
critical paths: sign-up → land on portfolio, place a trade, view trade history.
Wire them into CI after the existing unit tests.

### 16. Mobile-responsive layout improvements  
**Surface:** web | **Effort:** M

The markets table and portfolio page are functional but cramped on small
screens. Audit with Chrome DevTools mobile emulation, add responsive
breakpoints to the data tables (collapse columns on < md), and ensure the
chart re-renders at the correct width on resize.

---

## Ideas parking lot (not yet scoped)

- **Multi-currency support** — trade symbols priced in GBP / EUR / JPY
- **Options paper trading** — call/put positions with Black-Scholes pricing
- **Dividend tracker** — log and project dividend income from holdings
- **Dark/light mode toggle** — currently hardcoded dark; CSS variable swap is
  already in place via Tailwind v4 CSS variables
- **Community discussion threads** — per-ticker comment section
- **Broker integration** — connect a real brokerage account via OAuth + Plaid

---

## Picking what to build next

Suggested order given the current scaffolding:

1. **Watchlist UI** (scaffolding is there, quick win)
2. **OAuth login** (small, increases accessibility)
3. **Portfolio performance chart** (most-requested type of feature for a trading sim)
4. **Price alerts** (builds on scheduler infra already in place)
5. **Advanced order types** (deepens the trading sim value prop)
