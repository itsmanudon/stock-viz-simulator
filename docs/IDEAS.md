# StockViz — what shipped, and what's next

This file used to be a roadmap. Nearly everything on it got built, so keeping it
in the future tense was actively misleading: an agent reading it would propose
rebuilding the watchlist or the screener. It is now a changelog with a short
backlog at the end.

Current constraints are in [`KNOWN_LIMITATIONS.md`](./KNOWN_LIMITATIONS.md).
**Cross-check any idea against the code before starting it.**

---

## Shipped

Originally items 1–16 of the post-Phase-7 brainstorm. All of these exist today.

| #   | Idea                             | Where it lives                                                                           |
| --- | -------------------------------- | ---------------------------------------------------------------------------------------- |
| 1   | Watchlist UI                     | `routers/watchlist.py`, `app/(authed)/watchlist/`                                        |
| 2   | Portfolio performance chart      | `portfolio_snapshots`, `GET /v1/portfolio/history`, `components/equity-curve.tsx`        |
| 3   | Price alerts                     | `models/alert.py`, `services/alerts.py`, `components/alerts-bell.tsx`                    |
| 4   | Advanced order types             | `services/trading/orders.py` (limit / stop-loss / take-profit)                           |
| 5   | Portfolio analytics dashboard    | `services/trading/analytics.py`, `GET /v1/portfolio/analytics`                           |
| 6   | Stock screener                   | `routers/screener.py`, `app/screener/`                                                   |
| 7   | Backtesting engine               | `services/backtest/engine.py`, `app/backtest/`                                           |
| 8   | OAuth login (Google)             | `auth.ts`                                                                                |
| 9   | Trade history export             | `app/api/export/trades/route.ts`                                                         |
| 10  | Simulated quote ticker           | `routers/stream.py` (SSE random walk from last close), `components/live-price-badge.tsx` |
| 11  | News sentiment badges            | `services/sentiment/`, `components/sentiment-badge.tsx`                                  |
| 12  | Leaderboard                      | `routers/leaderboard.py`, `app/leaderboard/`                                             |
| 13  | Real JWT verification on the API | `auth.py::require_user_id`                                                               |
| 14  | Rate-limiting middleware         | `limiter.py`                                                                             |
| 15  | E2E tests with Playwright        | `apps/web/tests/e2e/`                                                                    |
| 16  | Mobile-responsive layout         | responsive breakpoints across the table views                                            |

From the old parking lot, also shipped: multi-currency trading (`fx_rates`),
options paper trading (`services/options/`), the dividend tracker
(`models/dividend.py`), dark/light mode, and per-ticker comment threads.

Delivered later, from `docs/CODEBASE_REVIEW.md`: options in NAV, a shared fill
path with FX, backtest benchmarking and trading costs, the one-call
`/v1/markets/summary`, materialized `symbol_metrics`, the sentiment provider
abstraction with `news_sentiment`, and realized-P&L tracking on trades.

---

## Backlog

Genuinely not built. Checked against the code as of the codebase review.

### Realized P&L reporting

`trades.realized_pnl` is captured per sell, but there is no aggregated view:
no realized-vs-unrealized split on `/portfolio`, no per-position closed-trade
history, and no FIFO/LIFO lot tracking (the basis is weighted-average only).

### Cash deposits and withdrawals

Every account is permanently on the $100k opening balance. Adding deposits
means return calculations must switch to **time-weighted** returns — a NAV
series with external cash flows can't be compared as a simple first/last ratio.
That change touches the leaderboard, `/portfolio/analytics`, and the equity
curve together.

### Alert delivery beyond the in-app bell

Alerts are evaluated hourly, weekdays 10:00–16:00 ET, so one that triggers
Friday at 16:30 waits until Monday. No email or push, no repeat/one-shot
setting, no per-user cap on alert rows. Email needs a provider (Resend,
Postmark) and a template layer — real infrastructure, not a small change.

### Options depth

The book is long-only: no spreads, no writing, no early exercise, no margin.
Implied volatility is 30-day historical vol as a documented proxy, which the UI
should say out loud so nobody reads it as a real IV surface.

### Symbol search

32 symbols fit in a table. A typeahead over ticker + company name matters once
the universe grows past a screenful.

### Sentiment, further

The provider abstraction and `news_sentiment` are in place. Not yet built:
a `sentiment_threshold` backtest strategy (buy when the 3-day mean crosses
+0.3, sell below −0.3), and a `sentiment` alert type — `Alert` already has
direction + threshold semantics, so it mostly needs an `alert_type` column.
The backtest strategy is the interesting one: with the buy-and-hold benchmark
now in `BacktestSummary`, it can actually answer whether the signal predicts
anything.

### Broker integration

Connect a real brokerage via OAuth + Plaid. Large, and it changes what this
app _is_ — worth a design discussion before any code.
