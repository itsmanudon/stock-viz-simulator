# ADR-0001 — PostgreSQL is the system of record; Kafka is not

**Status:** Accepted.

## Context

StockViz maintains a paper-trading ledger: cash balances, positions,
pending-order reservations, trades, option contracts, and dividend
credits. These have invariants that span multiple rows — a BUY must debit
cash *and* update a position *and* respect reservations held by other
pending orders, or do none of it.

The system also processes market data, news, and sentiment, which are
high-volume, provider-driven, and tolerant of delay.

## Decision

PostgreSQL is the single source of truth for all domain state. Every
money-moving operation commits in one PostgreSQL transaction. Kafka
distributes committed facts to derived consumers and is never consulted to
decide whether a trade is valid.

Kafka consumers are structurally forbidden from writing ledger tables. The
docstring in `models/events.py` states it, and in practice consumers write
only `symbol_metrics`, `news_*`, and `portfolio_trade_activity`.

## Alternatives considered

| Alternative | Why not |
| --- | --- |
| Command on Kafka, ledger applied by a consumer | Makes the HTTP result asynchronous. Reservation conflicts, insufficient-funds errors, and read-your-write all become much harder for no benefit at this scale. |
| Event sourcing the ledger | Rebuilding cash from an event log is defensible, but every read path would need a projection, and the invariants here are naturally relational. |
| Two databases (OLTP + analytics) | No current read volume justifies it. |

## Consequences

- Trade correctness does not depend on Kafka being up. A broker outage
  degrades data freshness, not trading.
- Buying power is decided under a row lock (`lock_portfolio`), which
  serialises concurrent writes to one portfolio. That is a throughput
  ceiling per portfolio, and an acceptable one — a single user's orders
  *should* serialise.
- Postgres is a single point of failure and, in this repo, a single
  instance with no replica.
- Scaling the API horizontally increases connection pressure on that one
  instance. See [the runbook](../operations/runbooks/postgres-connections.md).
