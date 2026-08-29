# Resume and portfolio copy

Every statement below is limited to behavior implemented and locally/CI validated in this repository.

## Project title

**StockViz — Event-Driven Market Analytics & Paper Trading Platform**

## One-line description

Full-stack financial application combining a strongly consistent PostgreSQL trading ledger with Kafka event processing, deterministic backtesting, and Kubernetes worker orchestration.

## Recommended resume bullets

- Designed a strongly consistent paper-trading ledger with PostgreSQL row locks and pending-order cash/share reservations, preventing concurrent portfolio overcommit under real multi-session integration tests.
- Implemented a transactional outbox and Kafka pipeline with at-least-once delivery, per-portfolio/ticker ordering, and durable consumer idempotency, deployed as independent workers on Kubernetes.
- Benchmarked a 12-partition Kafka consumer group with 100,000 events across 1/2/4/8 kind replicas, measuring 1,563–3,234 events/sec plus latency, lag, CPU, and memory.

## SWE-focused variants

- Built a Next.js, FastAPI, and PostgreSQL market analytics application spanning authentication, interactive charts, paper trading, options, watchlists, alerts, and deterministic backtesting.
- Protected concurrent order flows with row-level locks, atomic rollback, and cash/share reservations, then covered the behavior with real PostgreSQL multi-session integration tests.
- Shipped automated quality gates for TypeScript/Python linting, type checks, unit/integration/e2e tests, migrations, container builds, and a kind/Strimzi deployment smoke test.

## Backend/distributed-systems variants

- Separated the synchronous financial ledger from asynchronous derived processing using a transactional outbox, broker-acknowledged publication, and Kafka at-least-once delivery.
- Made consumers replay-safe with atomic inbox deduplication and database-before-offset commits while preserving per-portfolio and per-ticker ordering through stable partition keys.
- Orchestrated singleton scheduling, one-shot migrations, an outbox publisher, and independently scalable market/news/trade workers on Kubernetes with probes, PDBs, and partition-aware HPA limits.

## Quant/SWE hybrid variants

- Developed an FX-aware equity paper-trading ledger with pending limit/stop/take-profit reservations, dividends, realized P&L, and long-only Black-Scholes option pricing using a historical-volatility proxy.
- Built a look-ahead-safe backtest engine over stored daily OHLCV bars with deterministic fills, configurable transaction costs, technical signals, and a buy-and-hold comparison.
- Connected durable market/news ingestion to incremental analytics and rule-based recommendations while keeping provider calls outside the financial transaction path.

## Short card description

Full-stack market analytics and paper trading with a strongly consistent PostgreSQL ledger, Kafka outbox pipelines, deterministic backtesting, and locally validated Kubernetes workers.

## Medium portfolio description

StockViz is a Next.js and FastAPI financial application for market research, deterministic strategy backtesting, and paper trading. PostgreSQL row locks and pending-order reservations protect cash and shares during concurrent requests. A transactional outbox publishes committed events to Kafka, where idempotent consumers process trade activity and event-driven market/news workflows. The stack runs as distinct Kubernetes workloads on a real kind/Strimzi lab and includes a reproducible 100,000-event scaling benchmark.

## Technical deep-dive description

StockViz explores where strong consistency and asynchronous processing belong in a financial application. Trades remain synchronous: FastAPI locks the PostgreSQL portfolio row, validates buying power or shares after outstanding reservations, updates cash and positions, and inserts both the trade and its outbox event in one transaction. Kafka is deliberately outside the commit path.

An outbox publisher sends committed facts with at-least-once semantics. Consumers atomically record durable inbox keys with their derived writes, so crashes between database and offset commits replay safely. Stable keys preserve partition-local order per portfolio for trades and per ticker for market/news updates. A singleton scheduler emits durable refresh requests; ingestion workers call providers, persist results, and emit downstream events for analytics and sentiment, with reconciliation retained for drift repair.

The Kubernetes reference separates API, web, migrations, scheduling, publication, and worker roles and runs with Strimzi on kind. A measured 100,000-event, 12-partition matrix peaked at 3,234 consumer events/sec with four replicas before regressing slightly at eight—evidence of both parallelism and single-node/single-broker limits, not a production capacity claim.

## Claim boundaries

Safe claims include local Docker, real PostgreSQL and Kafka integration, a real kind/Strimzi cluster, deterministic benchmark evidence, and CI smoke coverage. Do not describe this as production traffic, cloud Kubernetes, multi-broker HA, multi-AZ PostgreSQL, exactly-once delivery, or a predictive/ML recommendation system.
