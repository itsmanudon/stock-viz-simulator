# ADR-0004 — PostgreSQL first; no production Redis

**Status:** Amended 2026-09-06. Production Redis remains deferred; an optional local indicator-computation pilot is now permitted. See [architecture](../CACHING.md) and [measured evidence](../benchmarks/2026-09-06-caching.md).

## Context

A stack like this often reaches for Redis for caching, rate limiting,
queues, locks, or sessions. At the original decision StockViz had no Redis
client dependency, container or manifest. The September 2026 audit found
whole-history database scans that should be optimized before adding caching.
The approved milestone added bounded PostgreSQL reads, shared request-local
portfolio valuation and privacy-safe leaderboard reads first, then measured
one disabled-by-default local Redis computation pilot.

## Decision

Do not deploy production Redis without new traffic/capacity and economic
evidence. The local pilot caches only pure indicator results keyed by exact
current PostgreSQL inputs; it saves computation, not database queries.
PostgreSQL remains durable truth. Other roles remain with existing systems:

| Redis would do | StockViz uses instead | Where |
| --- | --- | --- |
| Cache hot reads | Precomputed Postgres tables (`symbol_metrics`, `portfolio_snapshots`) refreshed by scheduled jobs | `services/metrics.py`, `services/trading/snapshots.py` |
| Work queue | Transactional outbox → Kafka | `events/outbox.py` |
| Distributed lock | Postgres advisory locks | `scheduler.py::single_instance` |
| Rate limiting | In-process slowapi | `limiter.py` |
| Session store | NextAuth JWT cookie — stateless | `apps/web/auth.ts` |

## Alternatives considered

Adding Redis as a cache was not necessary: the expensive reads (screener
filters, leaderboard, recommendation scores) are *already* materialised
into Postgres tables by scheduled jobs, and read-heavy chart queries are
served by `ix_price_bars_ticker_interval_ts`. Adding Redis would introduce
a second consistency domain and a new failure mode for no measured win.

## Consequences

- **Rate limits are per-process.** slowapi's default storage is in-memory,
  so with the API HPA at `maxReplicas: 5` the effective budget is up to
  5× the configured limit, and it resets on every pod restart. This is
  recorded in [KNOWN_LIMITATIONS.md](../KNOWN_LIMITATIONS.md) as
  "CPU-local rate limiting". A shared store is the fix if limits ever need
  to be enforced globally.
- Cached values are only as fresh as the job that computes them. The
  screener reads `symbol_metrics`, which is refreshed at 16:50 plus
  incrementally by the analytics consumer.
- Advisory locks tie scheduler mutual exclusion to the database's
  availability, which is acceptable because every job needs the database
  anyway.
- The local indicator pilot now has measured incremental computation value,
  but that does not establish a lower production infrastructure bill.
  Shared rate limiting remains a separate scale/security-driven decision;
  Kafka queues and PostgreSQL locks are not replaced.
