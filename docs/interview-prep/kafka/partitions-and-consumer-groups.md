# Partitions, keys, ordering, and consumer scaling

> **Before this note:** read [KAFKA_SCALING.md](../../KAFKA_SCALING.md)
> (measured results) and
> [EVENT_DRIVEN_ARCHITECTURE.md](../../EVENT_DRIVEN_ARCHITECTURE.md).
> **Source:** `events/contracts/{trades,market,news}.py`,
> `infra/k8s/kafka/topics.yaml`,
> `infra/k8s/base/scale/market-ingest-hpa.yaml`.

## StockViz's topics

| Topic | Partitions | Key | Why that key |
| --- | --- | --- | --- |
| `stockviz.trades.v1` | 3 | `portfolio_id` | All events for one portfolio land on one partition, so a portfolio's trade sequence is ordered |
| `stockviz.market.v1` | 3 | `ticker` | Refresh requests and bar-refreshed events for a symbol stay ordered relative to each other |
| `stockviz.news.v1` | 3 | `ticker` | Article ingest and its sentiment scoring stay ordered per symbol |
| `stockviz.benchmark.v1` | 12 | run-scoped | A scaling experiment, not domain logic |

## The one guarantee, stated precisely

**Kafka orders records within a partition, not within a topic.** Since the
partition is chosen by `hash(key) % partitions`, the real guarantee is:
*records sharing a key are ordered relative to each other.*

That is why key choice is a correctness decision, not a performance
tuning knob. `portfolio_id` for trades means portfolio 42's BUY is always
processed before its later SELL. Two *different* portfolios have no
ordering relationship — and need none, because they share no state.

Choosing `trade_id` as the key would have been the classic mistake: every
event on its own partition, perfect parallelism, and no ordering where
ordering actually mattered.

## The partition count is a scaling ceiling

This is the most testable fact in the whole area:

> **A consumer group can have at most one consumer per partition.**
> Members beyond the partition count sit idle.

StockViz encodes this pairing explicitly:

```yaml
# infra/k8s/base/scale/market-ingest-hpa.yaml
minReplicas: 1
maxReplicas: 3          # == MARKET_TOPIC_PARTITIONS
```

```python
# events/contracts/market.py
MARKET_TOPIC_PARTITIONS = 3
```

**Interview-worthy:** an HPA ceiling deliberately matched to the partition
count. Most projects set `maxReplicas: 10` and never notice that pods 4–10
consume nothing while still holding database connections and burning
cluster budget.

### Why you cannot just raise partitions

The Strimzi topic manifest carries the warning in its own annotation:

```yaml
stockviz.io/purpose: Domain trades. Changing partitions reshuffles keyed ordering.
```

Adding partitions changes `hash(key) % partitions`, so a key that lived on
partition 1 may move to partition 2 — while its older records stay behind.
For a window, two partitions hold records for the same key, and per-key
ordering is broken. Partition count is effectively a **permanent
decision** for a keyed topic. This is a genuinely good interview answer
because most candidates think of it as a dial.

## Scaling signal: CPU is the wrong one

```yaml
metrics:
- type: Resource
  resource: { name: cpu, target: { averageUtilization: 70 } }
```

The market-ingest consumer spends most of its time **blocked on provider
HTTP calls**. An I/O-bound consumer with a growing backlog can sit at low
CPU, so the HPA will not scale it out — the metric is uncorrelated with
the thing you care about.

The right signal is **consumer lag** (KEDA, or a custom metric). The
repository says so itself in
[KNOWN_LIMITATIONS.md](../../KNOWN_LIMITATIONS.md) and
[KAFKA_SCALING.md](../../KAFKA_SCALING.md) — "CPU HPA is a demonstration".

Being able to say "the autoscaler in my own repo uses the wrong signal,
here's why, here's what I'd use instead" is far stronger than defending it.

## Rebalancing

Members joining or leaving triggers a rebalance; partitions are
reassigned, and processing pauses briefly. In StockViz this is safe
because of the commit ordering: a partition reassigned mid-flight replays
from the last committed offset, and the inbox turns the replay into
`duplicate`.

Note the interaction with [ADR-0005](../../adr/ADR-0005-rewind-on-handler-failure.md):
before the rewind fix, a rebalance was the *only* thing that could
redeliver a failed record — which is why the loss was so easy to miss in
testing.

## Lag

Lag = log-end offset − committed offset, per partition. It is the single
most useful health metric for this pipeline, and **StockViz does not
collect it** ([observability](../../observability/overview.md)). Read it
by hand:

```bash
kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
  --describe --group stockviz-market-ingest
```

Lag on **one** partition while others drain is the signature of a stalled
poison record. Lag on **all** partitions is a dependency outage or genuine
under-capacity.

## Kafka vs the alternatives, for this system

| Option | Fit here |
| --- | --- |
| **Kafka** (chosen) | Replayable log, keyed ordering, independent consumer groups over one stream. Multiple consumers (analytics, sentiment, activity) read the same events for different purposes — that fan-out is the real justification |
| Postgres-backed job queue | Genuinely sufficient at current volume, and one less system. The honest answer to "did you need Kafka?" is: not for the load, yes for the fan-out and the replay |
| Redis queue | No durable replay; no consumer groups. Would not support re-reading history |
| RabbitMQ | Good routing, but per-message ack semantics rather than a replayable offset log |
| SQS | Managed and simple, no ordering (FIFO queues aside) and no replay |

Do not oversell this. The volume here does not require Kafka; the
architecture shape does, and the benchmark measures what it actually
bought.

## Interview questions

**Foundation — "What does a partition guarantee?"**
> Ordering within itself. Since partition is `hash(key) % count`, that
> means records with the same key are ordered relative to each other, and
> nothing is guaranteed across keys.

**Strong SWE — "Why key trades on `portfolio_id`?"**
> A portfolio's events must be applied in order — its own BUY before its
> own SELL. Different portfolios share no state, so they need no ordering.
> Keying on `trade_id` would maximise parallelism and destroy the one
> guarantee that mattered.

**Strong SWE — "You have lag. Add consumers?"**
> Only up to the partition count — 3 here. Beyond that, extra members idle.
> First I'd check whether lag is on one partition or all: one partition
> means a stalled record, and more consumers won't help at all.

**Advanced — "So raise the partition count."**
> Not on a keyed topic without accepting a correctness window. Rehashing
> moves keys to new partitions while their history stays behind, so
> per-key ordering breaks during the transition. I'd size partitions for
> peak parallelism up front and treat the number as fixed.

**Advanced — "Your consumer HPA scales on CPU. Defend it."**
> I won't — it's a demonstration and it's the wrong signal. That consumer
> is I/O-bound on provider HTTP, so it can be badly backed up at low CPU.
> Lag-based scaling via KEDA is the correct approach; the CPU HPA proves
> the mechanics on a single-node kind lab.

## Memorise vs understand

**Memorise:** consumers ≤ partitions; ordering is per-partition; lag =
end − committed; adding partitions rehashes keys.

**Understand:** why key choice is a correctness decision; why CPU and lag
decouple for I/O-bound consumers; why partition count is effectively
permanent.
