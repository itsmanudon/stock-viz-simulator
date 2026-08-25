# Kafka consumer-group scaling

This experiment measures **how a consumer group shares a 12-partition
benchmark topic** as Kubernetes replicas go 1 → 2 → 4 → 8. It does **not**
measure yfinance, Newsdata, Anthropic, or the trading ledger.

Domain topics stay at **3 partitions**. We did not raise `stockviz.market.v1`
to 12 — that would reshuffle ticker→partition mapping for every production
consumer group.

## Topics

| Topic | Partitions | RF (kind) | Purpose |
| --- | --- | --- | --- |
| `stockviz.trades.v1` | 3 | 1 | Domain. Unchanged. |
| `stockviz.market.v1` | 3 | 1 | Domain. Unchanged. HPA maxReplicas=3. |
| `stockviz.news.v1` | 3 | 1 | Domain. Unchanged. |
| `stockviz.benchmark.v1` | **12** | 1 | Synthetic events only |
| `stockviz.benchmark-results.v1` | 12 | 1 | Per-event completion + latency |

## Workload

- Keys: `SYM0000` … `SYM0999` (1,000 keys, round-robin). A handful of keys
  would pin traffic on a few partitions and fake a scaling ceiling.
- Payload: `event_id`, `run_id`, `seq`, `symbol`, `produced_at` (UTC ISO),
  tiny JSON body. No provider I/O. No SQL writes to financial tables.
- Consumer group: `stockviz.benchmark.<run>.<N>r` — **new group per replica
  count** so offsets start at beginning and runs do not contaminate each other.
- Processing: parse JSON, compute latency vs `produced_at`, write one result
  record, commit the input offset.
- Lag: watermark high-water minus committed offset, summed across partitions.

## How to run

Reduced (CI default): 3,000 events, replicas 1 and 2.

```bash
pnpm k8s:create && pnpm k8s:build && pnpm k8s:deploy
BENCHMARK_COUNT=3000 BENCHMARK_REPLICAS="1 2" pnpm k8s:benchmark
```

Full matrix (manual, not CI):

```bash
BENCHMARK_COUNT=100000 BENCHMARK_REPLICAS="1 2 4 8" pnpm k8s:benchmark
```

Output: `artifacts/benchmarks/kafka-scaling.json` (gitignored).

CLI used inside the cluster:

```bash
python -m stockviz.benchmarks.kafka_scaling produce --count 3000 --run-id demo
python -m stockviz.benchmarks.kafka_scaling consume --group stockviz.benchmark.demo --max-idle 30
python -m stockviz.benchmarks.kafka_scaling collect --group stockviz.benchmark.demo --expect 3000
```

## Results

Source: GitHub Actions kind job on commit `1ae731d`
([run 32827747239](https://github.com/itsmanudon/stock-viz-simulator/actions/runs/32827747239),
artifact `kafka-scaling`, generated 2026-08-25T08:45:49Z). kind cluster
`stockviz`, 1 node, Strimzi 0.45.1 / Kafka 3.9.0, 1 KRaft broker, RF=1,
topic `stockviz.benchmark.v1` with 12 partitions. Collector wall-clock
and per-event latency vs `produced_at`. Not a production SLO.

| Replicas | Events | Collected | Events/sec | p50 ms | p95 ms | Lag | CPU / Memory |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 3000 | 3000 | 667.23 | 4011 | 5115 | 0 | *empty — `kubectl top` not ready* |
| 2 | 3000 | 3000 | 365.23 | 19955 | 22197 | 0 | *empty — `kubectl top` not ready* |
| 4 | 100000 | *not run* | — | — | — | — | — |
| 8 | 100000 | *not run* | — | — | — | — | — |

Both reduced runs `complete: true` with `consumer_lag: 0`. The 2-replica
row is **slower**, not faster. On this 3,000-event kind node that is
expected: a new consumer group rebalances, then the work is gone before
the extra replica pays back. Do not read it as “Kafka does not scale.”
Do not invert the numbers to make a nicer graph.

`kubectl top` was empty (`kubectl_top: ""`). metrics-server is installed
with `--kubelet-insecure-tls`; it was not Ready in time for the sample.
That is a harness gap, not a fabricated zero.

The 100,000-event × 1/2/4/8 matrix was **not** executed. Run it with
`BENCHMARK_COUNT=100000 BENCHMARK_REPLICAS="1 2 4 8"` if you need that
table. Do not invent those cells.

## Interpretation (what the graph *should* show)

These are the scaling lessons the experiment is built to surface. They are
not a substitute for measured rows.

### Consumer-group parallelism

In one group, **useful** concurrency is about `min(replicas, partitions)`.
With 12 partitions, 1, 2, 4, 8 replicas can all take work. 16 replicas would
leave four idle.

### Partition ceiling on *domain* topics

`stockviz.market.v1` has **3** partitions. The market-ingest HPA therefore
caps at 3. A fourth replica in `stockviz.market-ingestion.v1` does not raise
throughput; it sits unused after rebalance.

### Diminishing returns

Even below the partition cap, events/sec will flatten because of broker
disk/network, JSON ser/de, result-topic produces, and coordinator rebalances.
The result writer is part of the measured path on purpose (it is cheap, but
not zero).

### Hot partitions

If we had keyed everything `AAPL`, one partition would take 100% of the
load and extra replicas would do nothing. 1,000 `SYM*` keys exist to avoid
that lie.

### Ordering

Kafka orders **per partition**. The product keys market/news by ticker and
trades by `portfolio_id` so each ticker/portfolio stays ordered. Spreading
a ticker across partitions would break that. Benchmark keys are synthetic
and do not imply a domain ordering change.

### CPU HPA vs lag

The market-ingest HPA uses **CPU**. A consumer that is blocked on I/O can
show low CPU and huge lag. Production should scale on **consumer lag**
(KEDA). This milestone does not add KEDA.

## Cluster used for a full run

When you actually run 100k:

- kind cluster `stockviz`, 1 control-plane node
- Strimzi 0.45.1, Kafka 3.9.0, 1 KRaft broker, RF=1
- Benchmark topic 12 partitions
- Same API image as the rest of the workers

That is a laptop/CI node, not a production broker. Do not cite the numbers
as capacity planning for a multi-AZ Kafka cluster.
