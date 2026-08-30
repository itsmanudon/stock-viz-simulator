# ADR-0004 — No Redis

**Status:** Accepted. Recorded because its absence is a frequent question.

## Context

A stack like this often reaches for Redis for caching, rate limiting,
queues, locks, or sessions. StockViz has **no Redis** — no client
dependency, no container, no manifest. The only mentions in the repository
are an aspirational comment in `apps/web/lib/rate-limit.ts` and an
unrelated test fixture string.

## Decision

Do not introduce Redis. Each role it would play is served by something
already present:

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
- **If Redis were added**, the honest first use case is the shared rate
  limiter, not caching.
