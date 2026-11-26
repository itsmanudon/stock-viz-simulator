# Known limitations

These are the current, code-verified boundaries of StockViz. They are not commitments or missing implementation phases.

## Market data and analytics

- **End-of-day data, not an exchange feed.** yfinance is the primary daily OHLCV source and Alpha Vantage is a fallback when configured. Quotes, charts, fills, backtests, and alerts use cached daily closes.
- **Provider quality and freshness.** yfinance can be delayed, unavailable, or rate-limited, and news is only as current as the last `aegis-sync` from Aegis News. Seed/backfill data is historical and does not prove a hosted feed is current.
- **Massive is evaluation-only.** The adapter is a private, nonpersistent
  shadow. Live semantic statistics and fractional-volume database precision
  still require a local credentialed run. An Individual subscription is not
  production/commercial display or redistribution permission; technical and
  licensing approval are separate gates. Massive must not be the primary
  provider yet. See [market-data semantics](./MARKET_DATA.md).
- **Small seeded universe.** The demo data contains a few dozen symbols. Symbol-search API support exists, but the header does not expose typeahead.
- **The Checklist is a count, not a model (A2.4).** Six published conditions (Rule DSL setups) are met, not met or unknown; "N of 6 met" is not a prediction and never a buy or sell call. Volume/Delivery's delivery condition applies to NSE/BSE listings only and stays unknown until NSE delivery files are loaded (A1); Quality is unknown on dates before fundamentals were collected.
- **Checklist evidence grades are survivorship-biased (until A1.4b).** The weekly `checklist-evidence` study measures each dimension on the pinned symbol list with today's provider history, so delisted and dropped names are missing and a grade can look better than it would have at the time. It uses split-adjusted closes without dividends, fees on a fixed 100,000 position, skips overlapping windows on one symbol but not correlated windows across symbols (the t-statistic is not adjusted for them), and dates fundamentals by fetch day. Every grade carries this stamp and its sample.

## Trading and quantitative models

- **Paper fills use daily closes.** Market, limit, stop-loss, and take-profit equity fills all take their execution decision from the versioned `legacy_close` kernel, then `apply_fill` records the ledger and a `SimulatedExecution` provenance row snapshots that decision. Triggered pending orders still fill at that session's close, not the trigger price or an intraday order book. Spreads, slippage, and OHLC-touch fills are not modeled. Execution is explainable and versioned, not realistic. Replay Lab (`/replay`) is a frozen 1d historical range with a next-bar clock; market truth is stored `PriceBar` data, not client OHLC and not live quotes. Replay is daily-bar only, USD-only, MARKET-only in the UI, and has no rewind, pending replay orders, historical FX, or dataset version snapshots. Historical bar corrections can still change observations. Forensics MAE/MFE use stored daily high/low as retrospective bar-range statistics after the bar is observable — not intraday excursion and not an execution timestamp. There is no immutable market-dataset version, so a later bar correction can change a past replay's analytics. Journal thesis fields lock after the first fill; they are not a cryptographic audit log. Replay forensics are deterministic and do not include retrospective AI. See [SIMULATION.md](./SIMULATION.md).
- **Pending BUY FX reservations are estimates.** Reservation uses the latest known USD conversion; settlement revalidates the actual converted cost and may cancel if FX moved against available cash.
- **Fixed opening cash and simplified accounting.** Accounts start with $100,000; there are no deposits/withdrawals. Equity cost basis is weighted average rather than tax-lot FIFO/LIFO.
- **Long-only options.** There are no written contracts, spreads, early exercise, or margin. Black-Scholes uses 30-day historical volatility as an implied-volatility proxy and a fixed 5% risk-free rate.
- **Options are not fully FX-aware.** Premium accounting uses the USD cash bucket without the equity path's native-currency conversion.
- **Backtests fill on the next bar's close.** A signal is known only after the current close, so the engine carries it forward; it does not model a next-bar open, partial fills, liquidity, or market impact.

## Kafka and failure handling

- **At least once, not exactly once.** A publisher crash after broker acknowledgement but before `published_at` can duplicate an event; durable inbox keys make implemented consumers idempotent.
- **No retry topics or dead-letter queue.** A failed record is rewound with `seek` so the same offset is retried, which means a genuinely poison record stalls its partition until the worker/code/data is corrected. That stall is the deliberate trade: without a DLQ, the alternative is silently dropping a market bar or news article. Retries are unbounded and unattended — there is no attempt counter, alert, or quarantine path.
- **No Schema Registry.** Versioned JSON event contracts are application-managed.
- **CPU-based consumer HPA.** The kind example demonstrates CPU autoscaling; Kafka lag would usually be a better production signal.
- **Scheduled reconciliation remains.** Full-universe metric and sentiment aggregation jobs intentionally repair incremental-processing drift. The checklist and financial settlement remain scheduled/synchronous by design.

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
- Alerts and notifications are end of day: judged after the nightly refresh, never in real time. Since A2.3 they also go to a user's signed webhook, email (only when the server has every `SMTP_*` value) or Telegram (only with `TELEGRAM_BOT_TOKEN`); hosted, the cron sends them once a night, so a failed send retries the next night unless the in-process scheduler runs.
- **TODO (A2.3): browser push.** Not built. It needs a VAPID key pair (a server secret the owner sets), a service worker and per-browser subscriptions; it would be one more channel behind `services/delivery`.
- The webhook signing secret is stored in plain text in `notification_channels.secret` (write-only through the API, never logged). Encrypting it at rest needs a server key that does not exist yet.
