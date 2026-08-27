# Known limitations

These are the current, code-verified boundaries of StockViz. They are not commitments or missing implementation phases.

## Market data and analytics

- **End-of-day data, not an exchange feed.** yfinance is the primary daily OHLCV source and Alpha Vantage is a fallback when configured. Quotes, charts, fills, backtests, and alerts use cached daily closes.
- **Simulated live badge.** The ticker SSE endpoint emits a labeled Gaussian random walk from the latest close; it is not a tradable real-time quote.
- **Provider quality and freshness.** yfinance and Newsdata.io can be delayed, unavailable, or rate-limited. Seed/backfill data is historical and does not prove a hosted feed is current.
- **Small seeded universe.** The demo data contains a few dozen symbols. Symbol-search API support exists, but the header does not expose typeahead.
- **Rule-based recommendations.** Technical votes and optional article sentiment produce explainable scores; this is not a predictive model.

## Trading and quantitative models

- **Paper fills use daily closes.** Market orders use the latest stored close (now decided by the `legacy_close` kernel, then recorded by `apply_fill`). Triggered limit/stop/take-profit orders still fill at that session's close via `_should_fill`, not the trigger price or an intraday order book. See [SIMULATION.md](./SIMULATION.md).
- **Pending BUY FX reservations are estimates.** Reservation uses the latest known USD conversion; settlement revalidates the actual converted cost and may cancel if FX moved against available cash.
- **Fixed opening cash and simplified accounting.** Accounts start with $100,000; there are no deposits/withdrawals. Equity cost basis is weighted average rather than tax-lot FIFO/LIFO.
- **Long-only options.** There are no written contracts, spreads, early exercise, or margin. Black-Scholes uses 30-day historical volatility as an implied-volatility proxy and a fixed 5% risk-free rate.
- **Options are not fully FX-aware.** Premium accounting uses the USD cash bucket without the equity path's native-currency conversion.
- **Backtests fill on the next bar's close.** A signal is known only after the current close, so the engine carries it forward; it does not model a next-bar open, partial fills, liquidity, or market impact.

## Kafka and failure handling

- **At least once, not exactly once.** A publisher crash after broker acknowledgement but before `published_at` can duplicate an event; durable inbox keys make implemented consumers idempotent.
- **No retry topics or dead-letter queue.** A poison record can stall its partition until the worker/code/data is corrected.
- **No Schema Registry.** Versioned JSON event contracts are application-managed.
- **CPU-based consumer HPA.** The kind example demonstrates CPU autoscaling; Kafka lag would usually be a better production signal.
- **Scheduled reconciliation remains.** Full-universe metric and sentiment aggregation jobs intentionally repair incremental-processing drift. Recommendations and financial settlement remain scheduled/synchronous by design.

## Deployment and operations

- **Single-node lab.** The demonstrated Kubernetes environment is one kind node, one Strimzi Kafka broker with replication factor one, and development PostgreSQL. It provides no broker, node, or zone high availability.
- **One-machine benchmark.** The 100,000-event results are one complete local run, not production capacity, sustained load, or run-to-run variance evidence.
- **No cloud deployment evidence.** Render/Vercel configuration exists, but the repository does not prove a currently healthy public deployment or cloud Kubernetes environment.
- **No production secret manager or observability stack.** Kubernetes development secrets and optional Sentry configuration do not constitute managed secrets, centralized telemetry, on-call alerting, or SLOs.
- **CPU-local rate limiting.** API/web request limits are process-local, so replicas do not share one global budget.
- **Thin browser e2e path.** Playwright covers markets, account creation, research workspace, an equity buy, and the operational trading loop; it does not cover every option, pending-order, backtest, screener, and leaderboard path.

## Authentication and UI

- Google OAuth needs valid provider credentials; email/password signup remains available without them.
- There is no email verification, password reset, or change-password flow.
- Alerts are in-app only. They are evaluated by incremental market analytics after refreshed bars and are not email/push notifications.
