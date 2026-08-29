# Distributed-systems failure scenarios

> **Before this note:** read
> [outbox and delivery](../kafka/outbox-and-delivery.md) and
> [ADR-0005](../../adr/ADR-0005-rewind-on-handler-failure.md).

Concepts are only worth as much as the failure you can trace. Each section
is a concrete StockViz scenario, what actually happens, and the general
principle.

---

## 1. The duplicate bar

```
scheduler enqueues market.refresh.requested
  → publisher produces to Kafka, gets an ack
  → publisher crashes BEFORE setting published_at
  → publisher restarts, row is still unpublished
  → produces the SAME event again
  → market_ingest_consumer receives it twice
```

**What happens:** the first delivery upserts bars and writes a
`consumer_inbox` receipt. The second hits `already_processed` and returns
`"duplicate"` — and even if it didn't, `upsert_bars` would rewrite
identical rows on the `(ticker, ts, interval)` key.

**Principle:** at-least-once delivery is only safe when application is
idempotent. StockViz has that at two layers — storage (natural key) and
message (inbox key) — because the storage layer alone doesn't protect
counters or paid API calls.

---

## 2. The silently dropped record (a real bug, now fixed)

```
market_ingest_consumer polls offset 100 → provider times out → handler raises
  → offset 100 not committed
  → next poll returns offset 101 (position advanced anyway!)
  → 101 succeeds → commit(102)
  → offset 100 is now behind the committed offset. Gone forever.
```

**What happened:** `poll()` advances the consumer's in-memory position
regardless of commits. Not committing does *not* mean "retry this one" —
it means "this one is skipped until a rebalance", and a later commit
removes even that chance.

**The fix:** `dispatcher.py::_rewind` seeks the partition back to the
failed offset, so the next poll redelivers it. See
[ADR-0005](../../adr/ADR-0005-rewind-on-handler-failure.md) and
`tests/test_dispatcher_retry.py`.

**Principle:** *position* and *committed offset* are different things.
Conflating them is one of the most common Kafka bugs, and it fails silently
— the logs said "offset not committed", which was true and gave exactly
the wrong impression.

**Why it stayed hidden:** the only test coverage of consumers required a
real broker, and the failure path had no test at all. A bug that only
manifests as *missing* data has no error to observe.

---

## 3. Trading during a Kafka outage

```
Kafka is down for an hour. A user places a trade.
```

**What happens:** the trade **succeeds**. The ledger and the outbox row
commit to Postgres in one transaction; the publisher fails to produce and
records `last_error` and `publish_attempts` per row. When Kafka returns,
the backlog drains.

**Principle:** this is the payoff of
[ADR-0001](../../adr/ADR-0001-postgres-as-system-of-record.md) — the
critical path depends on one system, and the optional path degrades
independently. Availability is a property of *which dependencies are on
the critical path*, not of how many nines each component has.

---

## 4. Split brain in the scheduler

```
Rolling update: old scheduler pod is terminating, new one is Ready.
Both fire pending_orders_settlement.
```

**What happens:** both call `pg_try_advisory_lock(sha256("pending_orders_settlement"))`.
One gets it; the other gets `false` immediately and skips. No order fills
twice.

**Principle:** `replicas: 1` is not mutual exclusion — it is *approximately*
one, and rolling updates and node partitions both violate it. When
correctness depends on at-most-one, enforce it with a lock, not with a
replica count.

---

## 5. Lost update on cash

```
Two concurrent BUYs on the same portfolio.
Both read cash = $1000. Both check $600 ≤ $1000. Both write $400.
Result: $800 spent, $400 debited.
```

**What happens now:** `lock_portfolio` serialises them with `SELECT … FOR
UPDATE` **and refreshes the ORM instance**, so the second transaction
re-reads $400 and correctly rejects the second $600 order.

**Principle:** a lock protects the row, not your in-memory copy of it. The
ORM identity map sits between the two, and a stale cached object turns a
correct lock into a no-op. See
[transactions and locking](../databases/transactions-and-locking.md).

---

## 6. Provider rate limit

```
Alpha Vantage free tier: 25 requests/day. Daily refresh: every active symbol.
```

**What happens:** yfinance is primary and Alpha Vantage is only attempted
when yfinance returned **no** rows, so the fallback is rarely reached. If
it is exhausted, the handler raises, the record rewinds, and the partition
retries — which under a hard daily quota means retrying until midnight.

**Honest gap:** there is no circuit breaker and no per-provider budget.
Retries are unbounded and unattended. A circuit breaker that failed fast
on a known-exhausted quota would be the right addition.

**Principle:** retrying into a rate limit converts one failure into
sustained load. Backoff bounds the rate; a circuit breaker bounds the
*attempt*.

---

## 7. Clocks and time

StockViz has **no distributed clock problem**, and knowing why is worth
more than reciting vector clocks:

- Ordering comes from Kafka partition offsets, not timestamps.
- Idempotency uses UUID `event_id`, not time.
- `PriceBar.ts` is a **session date** from the provider, not a locally
  generated instant.
- Postgres generates transaction ordering.

The one place time is load-bearing is `settle_pending_orders(session_date)`,
which refuses to fill when the latest bar predates the session — an
explicit staleness check rather than a clock comparison.

**Principle:** prefer logical ordering (offsets, sequence numbers, UUIDs)
over wall-clock ordering. Most "clock skew" problems are really "we used a
timestamp where we needed an identifier".

---

## 8. CAP, concretely

| Partition | StockViz choice |
| --- | --- |
| API ↔ Postgres | **CP.** `/health` returns 503, pods leave the Service. Refuses to serve rather than serve wrong balances |
| API ↔ Kafka | **AP for data.** Trading stays available; async data goes stale |
| Consumer ↔ Postgres | **CP.** Handler fails, record rewinds, retried later |

The interesting answer is that a system makes *different* CAP choices per
dependency. "We chose CP" is rarely true of a whole system.

---

## Interview questions

**Foundation — "What is idempotency and why does it matter here?"**
> Applying the same operation twice has the same effect as once. It
> matters because my delivery is at-least-once, so every consumer will
> eventually see a duplicate.

**Strong SWE — "A worker fails mid-processing. What's lost?"**
> Nothing. The DB transaction commits before the Kafka offset, so a crash
> in between replays the record and the inbox key makes it a no-op. If the
> handler itself fails, the partition rewinds and retries the same record.

**Strong SWE — "Your at-least-once pipeline touches money. Isn't that dangerous?"**
> It would be, which is why it doesn't. Consumers can only write derived
> state — metrics, sentiment, activity counters. Cash and positions are
> mutated exclusively in the synchronous ledger transaction. A duplicate
> event can recompute a metric; it can't spend money twice.

**Advanced — "Tell me about a distributed-systems bug you found."**
> The dispatcher's failure path. It didn't commit the offset on error,
> which reads like a retry, but `poll()` advances position regardless — so
> the record was skipped and permanently lost once a later offset
> committed. I fixed it by seeking back to the failed offset, and wrote a
> fake consumer that models the position/commit split so the regression is
> covered. It also made the docs true again: they claimed a poison record
> stalls its partition, which is now what actually happens.

**Advanced — "Poison record. No DLQ. Now what?"**
> It stalls its partition, deliberately — with no DLQ the alternative is
> silently dropping financial data. Operationally you diagnose from the
> repeated `event_id` in the logs, and if the record is genuinely
> undeliverable you make an explicit decision to advance the offset past
> it and record why. The real fix is a DLQ with bounded retries, which is
> on the roadmap.
