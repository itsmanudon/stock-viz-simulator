# Known limitations

Current product and engineering constraints, checked against the code.
Historical rewrite context is in [`REWRITE_PLAN.md`](../REWRITE_PLAN.md).
Shipped work and a short backlog are in [`IDEAS.md`](./IDEAS.md).

This is not a commitment to build the items below in any particular order.

---

## Demo and presentation

- **No verified public demo.** This repo does not publish a working hosted
  stack. GitHub’s repository homepage field may still point at a Vercel URL;
  that is GitHub metadata, not proof the API, database, and paper-trading
  flows are up. Run locally via [`SETUP.md`](./SETUP.md).
- **No in-repo screenshots.** There are no current product screenshots in
  the tree. Do not treat marketing images from the v1 static site as the
  present UI.

## Market data

- **End-of-day only.** Ingest stores daily OHLCV. Market orders, pending-order
  settlement, charts, backtests, and alerts all price off the latest `1d`
  close. There is no exchange real-time or true intraday book.
- **Simulated ticker quotes.** `GET /v1/stream/quotes/{ticker}` is a Gaussian
  random walk from the last cached close, capped at 15 minutes per connection.
  The ticker page labels it as a simulated quote.
- **Provider freshness.** Daily OHLCV ingest uses **yfinance first** (no API
  key). Alpha Vantage is a fallback only when `ALPHA_VANTAGE_KEY` is set and
  yfinance returns no rows. A blank Alpha Vantage key does **not** disable
  price ingest. Newsdata.io jobs no-op when `NEWSDATA_KEY` is blank. A clone
  that only runs `seed` + CSV `backfill` has historical bars, not a live
  vendor feed.
- **Small universe.** Seed data covers a few dozen symbols
  (`apps/api/seed-data/companies.json`). Header typeahead over
  `searchSymbols` is not wired; the API exists.

## Paper trading

- **Pending-order FX reservations are estimates.** A pending BUY reserves
  `quantity × limit_price` converted to USD at the **latest known** FX rate.
  Settlement still fills at the session close and revalidates actual USD cost
  against cash minus *other* orders' reservations. If FX moves against the
  book after the order was accepted, the fill can be cancelled even though
  the reservation was valid at submit time.
- **Fills at the close.** Triggered limit/stop/take-profit orders fill at the
  session close, not at the limit price.
- **Opening cash is fixed.** Every account starts at $100,000. There are no
  deposits or withdrawals (adding them would require time-weighted returns
  across portfolio analytics, the equity curve, and the leaderboard).
- **Realized P&L is per sell, not aggregated.** `trades.realized_pnl` is
  stored on sell fills. `/portfolio` does not show a realized-vs-unrealized
  split or closed-lot history. Cost basis is weighted-average, not FIFO/LIFO.
- **Options are long-only.** No spreads, writing, early exercise, or margin.
  Premiums use Black-Scholes with **30-day historical volatility** as the
  implied-vol proxy and a 5% risk-free rate. The UI should not be read as a
  live IV surface. Option premium accounting debits the USD cash bucket
  without the equity path's native-currency FX conversion — do not treat
  long options as a fully multi-currency book.
- **Alerts are in-app only.** Evaluation is bundled into the weekday hourly
  top-movers job (10:00–16:00 ET). No email or push; Friday after-hours
  triggers wait until Monday.

## Auth and accounts

- **Google OAuth button always renders.** Without `GOOGLE_CLIENT_ID` /
  `GOOGLE_CLIENT_SECRET`, “Continue with Google” fails at runtime.
  Email/password signup still works.
- **No password reset, email verification, or change-password flow.**
  Credentials auth is bcrypt-backed and suitable for local/demo use, not for
  accounts people would keep long-term.

## API vs UI

These backends exist and are unused or only partly used by the web app:

- Screener **sentiment min/max** query params (`/v1/screener`).
- Per-ticker sentiment **series** (`GET /v1/symbols/{ticker}/sentiment`).
- Symbol **search** (`searchSymbols`) — no header typeahead.

Sentiment scoring itself is optional (`none` / `anthropic` / `http`). Badges
on news rows appear only when articles have been scored. See
[`SENTIMENT.md`](./SENTIMENT.md).

## Operations

- **kind is a single-node lab.** [`docs/KUBERNETES.md`](./KUBERNETES.md)
  describes a local/CI cluster. It is not a multi-AZ production platform.
  In-cluster Postgres and single-node Strimzi Kafka are **dev/CI only**.
- **API scheduler is split in Kubernetes.** API pods set `ENABLE_SCHEDULER=false`.
  A singleton `stockviz-scheduler` Deployment runs APScheduler. Render can
  still run the scheduler in-process (`ENABLE_SCHEDULER=true`). Advisory
  locks remain defense-in-depth.
- **API rate limiter is in-process.** slowapi is per-pod; a multi-replica
  rate limit still needs shared storage (not implemented).
- **Consumer HPA uses CPU, not Kafka lag.** Market-ingest `maxReplicas: 3`
  matches `stockviz.market.v1`'s 3 partitions. Extra replicas in one group
  are idle. KEDA lag-based scaling is future work (not in this repo).
- **No coverage fail-under gate.** CI runs pytest, Vitest, audits, Docker
  build, `alembic check`, Playwright, and a kind smoke job, but does not
  fail on a coverage percentage.
- **Playwright covers a thin path.** Markets, signup, and one equity buy.
  Options, pending orders, backtest, screener, and leaderboard are not in e2e.
- **Unused v1 news CSVs.** `apps/api/seed-data/news-data-csv-files/` is not
  read by any Python path. Price CSVs and `companies.json` _are_ used by
  `seed` / `backfill`.
- **`NEXTAUTH_JWT_SECRET`** remains on the API settings/Blueprint as unused
  leftover so existing Render services keep the env var. The auth bridge
  verifies `INTERNAL_API_TOKEN` only.

## Kafka and the transactional outbox

- **Local Kafka is a single KRaft node**, not an HA cluster. Compose profile
  `events` (`pnpm events:up`). No Schema Registry, Kafka Connect, or UI.
- **No retry topics / DLQ.** A poison payload leaves the offset uncommitted
  (with backoff). That can stall a partition until the worker is fixed.
- **Providers may rate-limit or fail.** A failed fetch does not corrupt
  existing bars/articles; the worker retries the control event. Re-fetching
  a read-only provider after a crash is expected.
- **Scheduled reconciliation still exists** on purpose: full-universe
  `symbol_metrics_refresh` and `sentiment_aggregate_refresh` repair drift.
  Kafka is the incremental path.
- **Kafka consumers can run as Kubernetes Deployments** (same API image,
  different commands). kind + Strimzi is documented in
  [`KUBERNETES.md`](./KUBERNETES.md). Compose `pnpm events:up` remains the
  non-Kubernetes local path.
- **Recommendations remain scheduled**, not incremental. They need a
  universe of technical + sentiment features.
- **Financial settlement stays synchronous/scheduled by design:** pending
  orders, option expiry, dividend credits, FX, portfolio snapshots, and
  the trade ledger itself. That is not a Kafka gap.
- **At-least-once publication.** The publisher sets `published_at` after a
  broker ack. A crash between ack and that UPDATE can produce a duplicate.
  Consumers de-duplicate with `consumer_inbox`.
- **The API does not require Kafka.** Trades and scheduled control events
  commit to Postgres + outbox when the broker is down. `/health` does not
  check Kafka.

## Deployment configuration

Verifiable from this repository:

- `infra/render.yaml` — Render Blueprint, `branch: main`, `autoDeploy: true`,
  `ENABLE_SCHEDULER=true`.
- `apps/web/vercel.json` — install/build/output for the Next.js app. It does
  not encode Vercel dashboard auto-deploy.
- Production secrets are `sync: false` in the Blueprint and are not in git.

**Not** verifiable from source control: whether a given Vercel or Render
dashboard currently deploys on push, whether a listed homepage URL is healthy,
or whether ingest API keys are configured in production. Those are
owner-controlled. This file does not claim dashboard state.

Do not flip `autoDeploy` or trigger a production rollout from a docs PR.
