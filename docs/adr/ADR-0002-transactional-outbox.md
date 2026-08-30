# ADR-0002 — Transactional outbox instead of dual writes

**Status:** Accepted.

## Context

Committing a trade in PostgreSQL and then producing to Kafka is a dual
write. Either order is wrong:

- Commit then produce → a crash in between loses the event; downstream
  state silently diverges.
- Produce then commit → the transaction may roll back, and an event has
  been published for something that never happened.

There is no distributed transaction between PostgreSQL and Kafka.

## Decision

Domain services stage an **outbox row in the same session** as the ledger
mutation (`events/outbox.py::enqueue_event`, and typed helpers such as
`enqueue_trade_executed`). The row commits atomically with the trade.

A separate process (`workers/outbox_publisher.py`) claims unpublished rows
with `FOR UPDATE SKIP LOCKED`, produces to Kafka with `acks=all` and
producer idempotence, and sets `published_at` **only after the broker
acknowledges**.

The FastAPI process never imports the Kafka producer at startup. This is
why the compose `api` service does not set `KAFKA_BOOTSTRAP_SERVERS`.

## Alternatives considered

| Alternative | Why not |
| --- | --- |
| Publish inline from the request | The dual-write problem above, plus broker latency in the user's request path. |
| Debezium / CDC on the ledger tables | Removes the outbox table but adds a connector, a schema-mapping layer, and an operational dependency far heavier than this project needs. |
| Best-effort publish with retry in-process | A process crash still loses the event. |

## Consequences

- **At-least-once, not exactly-once.** A crash after the broker ack but
  before the `published_at` commit republishes the row. This is stated in
  `ConfluentBrokerPublisher`'s docstring and accepted deliberately —
  [ADR-0003](./ADR-0003-consumer-inbox-idempotency.md) is the other half.
- The outbox is a queue in a table, so it needs the queue-shaped index:
  `ix_outbox_events_unpublished` is **partial** (`WHERE published_at IS
  NULL`) so it stays small as history grows.
- A publish failure increments `publish_attempts` and stores `last_error`
  rather than crashing the batch. There is no attempt ceiling and no
  alert — a permanently failing row retries forever, unattended.
- Published rows are never archived. That is fine at current volume and is
  a known future cleanup.
