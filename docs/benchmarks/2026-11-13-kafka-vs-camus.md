# Kafka and Camus on StockViz's event workload (Phase 7.6 trial)

Date: 2026-11-13. **Local evidence on one machine in one session**, not a
production measurement. Decision for Phase 7, approved by the owner: trial
and write-up only, no hosted broker.

Raw results: [`2026-11-13-camus-trial-results.jsonl`](2026-11-13-camus-trial-results.jsonl).

## Setup

- Apple M4 Pro, 48 GiB, macOS 26.6.2. Both brokers ran on the same machine,
  one after the other, with nothing else running.
- **Camus** at commit `56f0c3a`, built from the workspace clone (unchanged)
  with Rust 1.91.0 (`cargo +1.91.0 build --release -p camus-broker`; the
  default 1.84.1 cannot build a dependency that needs the 2024 edition). One
  broker in the default `wal` mode, `--dev-plaintext` on loopback only, with
  MinIO `RELEASE.2025-10-15T17-29-55Z` built with `go install` as its bucket.
- **Kafka** `apache/kafka:3.9.1`, the `events` profile of
  `infra/docker-compose.yml` (one KRaft node in Docker).
- Client: confluent-kafka / librdkafka 2.15.0, the versions StockViz pins.
- Workload: `stockviz.benchmarks.kafka_scaling` through
  `scripts/events/broker-benchmark.sh` (the k8s benchmark's steps without
  Kubernetes): 12 partitions; seek the group to the end; N consumers; produce
  the events; collect. Each consumer **commits synchronously after every
  message** (the benchmark's at-least-once design). Throughput is
  min(produced_at) to max(consumed_at) over the run's events.
- Memory: Camus is the broker process's resident size (`ps`, every 0.2 s);
  Kafka is the container's usage (`docker stats`, about one sample a second,
  JVM heap included). They are not the same measure; both are what a host
  would have to provide.

## Results

| Broker | Events | Consumers | Collected | Producer events/s | Consumer events/s | p50 latency | Broker memory |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Camus | 10,000 | 1 | 10,000 | 16,977 | 70 | 71.9 s | 20 MiB idle, 123 MiB peak |
| Camus | 100,000 | 4 | 100,000 (see below) | 19,380 | 107 | 436 s | 181 MiB peak |
| Kafka | 10,000 | 1 | 10,000 | 76,762 | 2,577 | 2.1 s | 427 MiB idle, 1,050 MiB peak |
| Kafka | 100,000 | 4 | 100,000 | 168,037 | 9,608 | 4.8 s | 1,570 MiB peak |

Latency is produce to consume. Every event is produced up front, so it is
mostly queueing time, and it grows with how slowly the consumers drain.

**Integration tests:** `tests/test_kafka_integration.py` (outbox publisher,
consumers, inbox de-duplication, against PostgreSQL) passed against Camus
unchanged: 3 passed with `KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:19092
STOCKVIZ_KAFKA_REQUIRED=1`.

## What was found

1. **A Fetch compatibility bug.** For a partition with nothing new to return,
   Camus leaves `records` null (`row.records = None` in
   `crates/broker/src/kafka.rs`, Fetch handler around line 3520), which
   encodes as size −1. librdkafka 2.15 refuses it: `invalid MessageSetSize -1`
   / `Protocol parse failure for Fetch v16`. That happened 39,142 times in the
   first aborted run. Apache Kafka sends empty, zero-length records instead.
   The client recovers by refetching, so the integration tests and the 10k run
   still completed. But the benchmark's collector never finished reading the
   100k run's results topic, and was stopped after 21 minutes. The 100k row
   above was read straight from that topic with a fresh consumer that gave
   librdkafka time to retry (100,000 records, no errors seen).
   Suggested upstream fix: send `Some(empty)` when no batch is read. Per the
   handover this is a pull request to the author, not a fork; nothing in the
   clone was changed.
2. **Commit latency dominates this workload.** With a synchronous commit per
   message, one consumer manages 70 events/s on Camus, about 14 ms per message
   and its commit. That is the order of Camus's own published `wal` write
   latency (p50 5.65 ms on one broker, 11.06 ms on three; its README), and the
   commit and the result produce are both durable writes. On Kafka the same
   message and commit took about 0.4 ms. Four consumers on
   Camus gave 107/s, not 4 × 70: they share one broker's WAL. Producing is fast
   on both brokers; consuming with per-message commits is 37 to 90 times slower
   on Camus.
3. **Memory is the case for Camus.** Idle at 20 MiB and at most 181 MiB under
   this load, against 0.4 to 1.6 GiB for the Kafka container. That is in line
   with Camus's published figures.

## Decision

- **No hosted broker in Phase 7.** Nothing in this phase needs one: alerts,
  notifications and event studies run on end-of-day data in the nightly cron.
- **Camus is not ready for StockViz's consumers as they are.** The Fetch bug
  would show as stalls and retries in every consumer, and per-message commits
  would cap each consumer at about 70 events/s. Revisit when both hold: the
  Fetch fix is released upstream, and either StockViz batches its commits
  (every N messages or N ms; safe because the inbox already de-duplicates) or
  Camus's commit path gets faster. When something needs events between
  nights, rerun this benchmark first.
- Running the trial again: build Camus and MinIO as above; start MinIO on
  `127.0.0.1:9100` with a `camus` bucket, then the broker with
  `--kafka-addr 127.0.0.1:19092 --dev-plaintext`; `POST /admin/init`; then
  `BOOTSTRAP=127.0.0.1:19092 BROKER=camus COUNT=100000 REPLICAS=4 bash
  scripts/events/broker-benchmark.sh`. Kafka: `pnpm events:up` (or the
  `events` profile), `BOOTSTRAP=127.0.0.1:9092`.
