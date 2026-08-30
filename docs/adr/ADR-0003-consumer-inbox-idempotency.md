# ADR-0003 — Durable inbox keys for at-least-once consumers

**Status:** Accepted.

## Context

[ADR-0002](./ADR-0002-transactional-outbox.md) makes delivery
at-least-once. Consumers must therefore tolerate seeing the same event
twice. Two of them are not naturally idempotent: `portfolio_trade_activity`
increments a counter, and sentiment scoring costs money per call.

## Decision

Each consumer writes a receipt into `consumer_inbox`, keyed
`(consumer_name, event_id)`, **in the same PostgreSQL transaction** as its
derived-state change. The Kafka offset is committed only after that
transaction succeeds.

Handlers follow one shape (`events/handlers.py`):

```python
if already_processed(session, event_id=..., consumer_name=...):
    return "duplicate"
...apply the domain change...
if not try_record_processed(session, event_id=..., consumer_name=...):
    return "duplicate"
return "applied"
```

`try_record_processed` inserts inside `session.begin_nested()` (a
SAVEPOINT) and catches `IntegrityError`, so a duplicate does not poison
the outer transaction.

## Alternatives considered

| Alternative | Why not |
| --- | --- |
| Kafka transactions / exactly-once semantics | Only covers Kafka-to-Kafka. The side effect here is a Postgres write, so a Kafka transaction would not include it. |
| Natural idempotency everywhere | Works for bars (PK upsert) and articles (unique URL), but not for counters or paid API calls. |
| Dedupe in memory per consumer | Lost on restart and on rebalance. |

## Consequences

- Keying on `(consumer_name, event_id)` rather than `event_id` alone lets
  independent consumer groups process the same event.
- The **unique constraint** is the actual guard; the leading
  `already_processed` read is only a cheap short-circuit and is not
  sufficient on its own (two workers could both pass it).
- Ordering per key is preserved by partitioning: trades key on
  `portfolio_id`, market and news on `ticker`.
- `consumer_inbox` grows without bound. No retention policy exists.
