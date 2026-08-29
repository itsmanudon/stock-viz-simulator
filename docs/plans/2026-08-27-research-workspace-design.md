# StockViz Phase 5 Research Workspace Design

**Date:** 2026-08-27  
**Branch:** `cursor/feat-research-workspace-0ecf`  
**Base:** latest `dev`

## Objective

Turn `/compare`, `/backtest`, and `/recommendations` into one quantitative Research domain without merging them into a single route or a dashboard of equal-weight cards. Each page keeps one dominant analytical question:

| Route | Question |
| --- | --- |
| `/compare` | How do these securities differ over the selected window? |
| `/backtest` | How would this deterministic trading rule have behaved on stored history? |
| `/recommendations` (Signals) | What evidence currently supports or contradicts a bullish view? |

The pages remain distinct URLs inside the Phase 1 workstation shell. They share navigation, typography, density, and cross-links so the path Markets → stock workspace → Compare / Signals → Backtest feels like one product.

## Product decisions

- Research sidebar children lead with Compare, Backtest, and Signals. Screener and News stay listed until a later Discovery pass relocates them. Clicking the Research domain lands on `/compare`.
- Backtest moves out of Trade. It is an experiment tool, not an order ticket.
- `/recommendations` keeps its URL. The surface is titled **Signals**, never “AI recommends”.
- The current engine is a seven-vote **bullish-evidence** scorer (`score >= 4` → bullish, otherwise neutral). There is no bearish vote set, so the UI does not invent one.
- `/compare` with no tickers shows an empty state rather than silently redirecting to a default basket. A sample-set control still one-clicks `AAPL,MSFT,GOOGL,AMZN`. Existing `tickers` and `tf` query params are preserved; `symbols` is accepted as an alias.
- `/backtest?ticker=AAPL` prefills the symbol. Form ticker changes write that query param.
- No new execution engine, optimizer, or fabricated factor (beta, alpha, correlation, Sharpe on compare) is introduced.
- Optional analytics (screener metrics, sentiment) fail independently and must not take down the page.

## Shared language

Research pages use the workstation tokens, `PageFrame` workstation width, hairline separators, and tabular financial type. Shared primitives stay small: page header, domain subnav, empty state, and signal evidence rows. Green/red is reserved for signed performance and vote pass/fail, always paired with text.

## Compare

Dominant surface: a theme-aware normalized performance chart (rebase to 100 at the first bar). Below it, a metric table built only from data the app already has:

- selected-window return, last close, window volatility, window max drawdown (derived from the loaded bars)
- sector, RSI-14, 52-week positioning, trailing-week sentiment when the screener/metrics payload is present

Insights are deterministic observations (leader/laggard, RSI extremes, sentiment extremes, sector concentration), not commentary.

## Backtest

The existing `/v1/backtest` engine remains authoritative. Desktop layout is setup on the left and results on the right; mobile stacks setup above results. Result hierarchy: equity curve, then return/benchmark/excess/NAV, then Sharpe/drawdown/costs/trade count. Execution assumptions are visible: next-bar fills, all-in/all-out, EOD bars only, commission and slippage, 5% annual risk-free rate used by Sharpe.

Empty, running, success, and failure states are first-class. Failure preserves the form and distinguishes validation from system errors.

## Signals

Dense table, not a card wall. Columns: ticker, company, signal, strength, supporting votes, sentiment, updated. Expanding a row shows the seven named votes with pass/fail and the engine’s metric detail, plus links to the stock workspace and Backtest. Filters/sorts that exist in the URL: signal class, sector, ticker query, min score, sort.

## Non-goals

New execution/microstructure simulation, walk-forward, parameter search, AI recommendations, VaR, broker integration, and recommendation-algorithm changes.
