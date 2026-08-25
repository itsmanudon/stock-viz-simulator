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

## Isolation (methodology correction)

An earlier revision used a **fresh consumer group** plus
`auto.offset.reset=earliest` on the retained topic `stockviz.benchmark.v1`.
That does **not** isolate runs. Run 2's group has never committed offsets, so
`earliest` replays Run 1's retained records as well as Run 2's. The consumer
also did not filter on `run_id`. Numbers from that harness (commit `1ae731d`,
CI run [32827747239](https://github.com/itsmanudon/stock-viz-simulator/actions/runs/32827747239))
are **invalid** and are not the result table below.

Current isolation (both layers; neither is "timing"):

1. Coordinator **seeks the new group to the topic end** and commits those
   offsets **before** producing this run.
2. Every event carries `run_id`. Each consumer is given that `run_id` and the
   expected count. Non-matching records are **not** written to the results
   topic; the offset is still committed so the group advances.
3. Collection and latency/throughput stats keep **current-run records only**.
   Any same-group foreign `run_id` fails the hard gate.

## Metrics

| Field | Meaning |
| --- | --- |
| `producer_events_per_second` | Produce+flush wall-clock for this run. Not consumer throughput. |
| `processing_duration_seconds` | `max(consumed_at) - min(produced_at)` over **current-run** completions. |
| `consumer_events_per_second` | `current_run_count / processing_duration_seconds`. Not collector read speed. |
| `p50_ms` / `p95_ms` / `p99_ms` / `mean_ms` | `consumed_at - produced_at` for current-run events only. |
| `initial_consumer_lag` | First lag sample (committed offset vs watermark, all partitions). |
| `peak_consumer_lag` | Max lag sample **during** the workload. |
| `final_consumer_lag` | Last lag sample. |
| `cpu` / `memory` | Peak `kubectl top` of benchmark-consumer pods **while the run is active**. `null` if metrics-server is not ready. Never a fabricated zero. |

The smoke job **fails** if collected ≠ expected, a foreign `run_id` is counted,
`processing_duration_seconds` is missing/non-positive, current-run p50/p95 are
missing, peak lag is missing, or `complete` is not true.

## Workload

- Keys: `SYM0000` … `SYM0999` (1,000 keys, round-robin). A handful of keys
  would pin traffic on a few partitions and fake a scaling ceiling.
- Payload: `event_id`, `run_id`, `seq`, `symbol`, `produced_at` (UTC ISO),
  tiny JSON body. No provider I/O. No SQL writes to financial tables.
- Consumer group: `stockviz.benchmark.<run_id>` — new group per replica count,
  seek-to-end, then produce.
- Processing: parse JSON, skip/commit foreign `run_id`, else write one result
  record and commit. The process exits after `--expect` matching events
  (idle timeout is only a stall guard after the first match).
- Lag: sampled on a sidecar Job via committed offset vs watermark, not after
  the run is already drained.

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
python -m stockviz.benchmarks.kafka_scaling seek-end --group stockviz.benchmark.demo
python -m stockviz.benchmarks.kafka_scaling consume --group stockviz.benchmark.demo --run-id demo --expect 3000
python -m stockviz.benchmarks.kafka_scaling produce --count 3000 --run-id demo
python -m stockviz.benchmarks.kafka_scaling collect --group stockviz.benchmark.demo --run-id demo --expect 3000
```

The coordinator script (`scripts/k8s/run-benchmark.sh`) does seek-end, starts
consumers, samples lag/CPU, then produces, then collects.

## Results

**Methodology:** seek-to-end + `run_id` filter; consumer throughput from event
timestamps; lag sampled during the workload. kind cluster `stockviz`, 1 node,
Strimzi 0.45.1 / Kafka 3.9.0, 1 KRaft broker, RF=1, topic
`stockviz.benchmark.v1` with 12 partitions. Environment-dependent. Not a
production SLO.

The primary table is filled from the k8s-smoke artifact **after** this
methodology landed. Until that run finishes, do not cite the superseded
`1ae731d` rows (collector wall-clock, `earliest` replay of prior runs, lag
sampled after drain so it was always 0).

| Replicas | Events | Collected | Producer evt/s | Consumer evt/s | p50 ms | p95 ms | Peak lag | CPU / Memory |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 3000 | *pending CI* | — | — | — | — | — | — |
| 2 | 3000 | *pending CI* | — | — | — | — | — | — |
| 4 | 100000 | *not run* | — | — | — | — | — | — |
| 8 | 100000 | *not run* | — | — | — | — | — | — |

Do not expect 2 replicas to outperform 1 on a 3,000-event single-node kind
cluster. Report whatever the run actually measured. Do not invert the
numbers to make a nicer graph.

The 100,000-event × 1/2/4/8 matrix was **not** executed. The tooling still
accepts `BENCHMARK_COUNT=100000 BENCHMARK_REPLICAS="1 2 4 8"`. Do not invent
those cells.

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
