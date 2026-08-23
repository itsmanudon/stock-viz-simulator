# Event-driven architecture (trade.executed)

StockViz’s trading ledger is a **synchronous PostgreSQL transaction**. Kafka
is an **asynchronous** delivery mechanism for events that already committed
with that transaction via a transactional outbox. Kafka is not in the trade
commit path. The API process never opens a Kafka connection.

## Why Kafka exists here

Not because “microservices need a bus.” Concrete reasons for this slice:

- **Decouple** derived/read models from the fill transaction so a slow or
  down consumer cannot block a trade.
- **Replay.** The topic is an ordered log of `trade.executed` envelopes;
  a new consumer group can read from the earliest offset.
- **Independent consumers.** Later workers (analytics, notifications) can
  subscribe without changing `apply_fill`.
- **Consumer groups** scale by partition while **per-portfolio ordering**
  is preserved by using `portfolio_id` as the message key.

Ingest, news, sentiment, recommendations, alerts, snapshots, dividends, and
options settlement are **not** on Kafka in this milestone.

## Why a transactional outbox

Direct dual-write is unsafe:

1. `COMMIT` the trade, then produce to Kafka — if produce fails, the ledger
   moved and the event never left.
2. Produce to Kafka, then `COMMIT` the trade — if the DB rolls back, Kafka
   already announced a trade that does not exist.

The outbox stores the event row in the **same** PostgreSQL transaction as
the trade. A separate publisher process reads unpublished rows and produces
them. Trades succeed when Kafka is down; rows stay `published_at IS NULL`
until a broker ack.

```
request
  → FastAPI
  → PostgreSQL transaction
       UPDATE portfolio cash / position
       INSERT trade
       INSERT outbox_events
  → COMMIT
       ↓ later
  Outbox publisher  →  Kafka topic stockviz.trades.v1
       ↓
  Consumer group stockviz.trade-activity.v1
       ↓
  Derived portfolio_trade_activity  (not cash, not positions)
```

## Delivery guarantee: at least once

The publisher marks `published_at` **only after** the broker acknowledges
the produce (`acks=all`). Crash window:

- Kafka accepted the record
- process dies before `published_at` is committed

On restart the same outbox row is produced again. Consumers **must** be
idempotent. This design does **not** claim exactly-once or Kafka
transactions.

Multiple publisher processes claim rows with `SELECT … FOR UPDATE SKIP LOCKED`
so they do not intentionally publish the same pending row concurrently.
That does not remove the crash-window duplicate.

## Event contract (`trade.executed` v1)

Topic: `stockviz.trades.v1`  
Key: `str(portfolio_id)` — one portfolio stays on one partition.  
Partitions (local): **3** — enough fan-out for development, not a pretend
30-partition cluster.

Envelope (decimals are strings; no ORM objects, no secrets):

```json
{
  "event_id": "uuid",
  "event_type": "trade.executed",
  "schema_version": 1,
  "occurred_at": "2026-08-23T12:34:56",
  "aggregate_type": "portfolio",
  "aggregate_id": "123",
  "payload": {
    "trade_id": 456,
    "portfolio_id": 123,
    "ticker": "AAPL",
    "side": "buy",
    "quantity": "10",
    "price": "225.3",
    "currency": "USD",
    "fx_rate": "1",
    "usd_notional": "2253"
  }
}
```

Emitted from the shared `apply_fill` path (market buy/sell and pending-order
fills). Not emitted for rejects, cancels, failed settlements, or pending
order creation. Option fills are out of scope unless they already share
`apply_fill` (they do not).

**Compatibility:** consumers require `event_type == "trade.executed"` and
`schema_version == 1`. Unknown versions fail validation and **do not**
commit the Kafka offset. There is no DLQ in this milestone; a poison
payload can stall a partition until the worker is fixed. That is a known
limitation.

## Outbox publisher

Process: `python -m stockviz.workers.outbox_publisher` (`--once` for one
batch). Not an API request handler.

1. Claim unpublished rows (`SKIP LOCKED` on PostgreSQL).
2. Produce with `confluent-kafka` (`acks=all`, idempotent producer).
3. Wait for delivery callback / flush.
4. Set `published_at` on success; increment `publish_attempts` and store
   `last_error` on failure.
5. Sleep `OUTBOX_POLL_INTERVAL_SECONDS` when the batch is empty.

`confluent-kafka` is the client: production-grade librdkafka bindings,
explicit delivery callbacks, and AdminClient for topic ensure. We do not
also depend on aiokafka.

The API does not construct a producer at import or startup.

## Consumer

Group: `stockviz.trade-activity.v1`  
`enable.auto.commit=false`. Sequence: poll → validate → DB transaction
(derived activity + `consumer_inbox`) → commit DB → commit offset.

`consumer_inbox (consumer_name, event_id)` is unique. Reprocessing the same
`event_id` leaves `trade_count` unchanged.

Derived table `portfolio_trade_activity` is **not** the ledger. Cash and
positions stay on `portfolios` / `positions` / `trades`.

## Local demo

```bash
pnpm events:up          # Postgres + Adminer + KRaft Kafka
uv --directory apps/api run alembic upgrade head
pnpm api:dev            # trades commit without Kafka
uv --directory apps/api run python -m stockviz.workers.outbox_publisher --once
uv --directory apps/api run python -m stockviz.workers.trade_activity_consumer --once
```

CLI equivalents: `python -m stockviz.cli publish-outbox --once` and
`python -m stockviz.cli consume-trade-activity --once`.

## Future events (not in this PR)

`market.bar.updated`, `news.article.ingested`, `news.sentiment.scored`,
`portfolio.updated`, `order.filled`.
