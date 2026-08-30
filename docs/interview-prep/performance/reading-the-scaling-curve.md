# Performance: reading a scaling curve

> **Before this note:** read [KAFKA_SCALING.md](../../KAFKA_SCALING.md).
> **Source:** `apps/api/src/stockviz/benchmarks/`,
> `artifacts/benchmarks/kafka-scaling-100k.json`.

Most candidates have no measured performance data about their own project.
StockViz has a 100,000-event consumer-scaling matrix — and the interesting
part is that **the curve is not flattering**.

## The numbers

| Replicas | Consumer events/sec | vs. previous | p95 latency |
| ---: | ---: | ---: | ---: |
| 1 | 1,562.80 | — | 58,144 ms |
| 2 | 2,915.44 | **1.87×** | 30,042 ms |
| 4 | 3,234.39 | +10.9% | 27,685 ms |
| 8 | 3,052.10 | **−5.6%** | 27,696 ms |

Near-linear 1→2, a plateau at 4, and a **regression at 8**.

## Why reporting the regression is the point

The temptation is to show 1→2 and stop. Reporting the 8-replica regression
is worth more, for three reasons:

1. It demonstrates you measured rather than assumed.
2. It sets up the far more interesting question — *why* does it stop
   scaling?
3. An interviewer who suspects cherry-picking will probe until they find
   the ceiling anyway.

The repository's own framing is the right one: *"strong initial
parallelism followed by a plateau and a small regression in this
constrained lab."*

## Diagnosing the plateau

Candidate bottlenecks, and how to distinguish them:

| Hypothesis | Evidence for | Evidence against |
| --- | --- | --- |
| **Single broker** | 1 broker, RF=1, all partitions on one process | — |
| **Single kind node** | All 8 pods share one node's CPU and NIC | Peak CPU/pod *falls* (450m → 213m) |
| Partition limit | — | 12 partitions > 8 replicas, so not the ceiling |
| JSON serialization | Per-record cost | Would scale with replicas, not against |
| Offset commits | Synchronous commit per record | More consumers = more commit traffic to one broker |
| Group coordination | More members = more rebalance and heartbeat work | Fits the regression shape |

The strongest signal is in a column that is easy to skim past: **peak
CPU per pod falls from 450m to 213m as replicas increase.** The consumers
are progressively *less* busy, so they are waiting — on the broker, the
node's network, or coordination. That rules out consumer-side compute and
points at a shared downstream resource.

**Interview-worthy:** reading a per-pod resource number to infer where the
bottleneck is *not*.

## Methodology worth defending

Benchmarks are usually wrong in ways that flatter them. This one has
explicit guards:

| Guard | Prevents |
| --- | --- |
| New consumer group + distinct `run_id` per run | Counting a previous run's records |
| Seek-to-end and commit before producing | Consuming backlog left by an earlier run |
| Consumers filter by `run_id`; foreign records **fail the run** | Silent contamination |
| Throughput = `max(consumed_at) − min(produced_at)` | Coordinator wall-clock overhead inflating the result |
| 1,000 round-robin keys | Accidentally pinning work to a few partitions |
| Committed JSON artifact + a validator that fails on drift | Documentation diverging from the data |

The `run_id` filter with a hard failure is the strongest of these: it does
not just ignore foreign records, it invalidates the run.

The throughput definition matters too. Measuring the coordinator's wall
clock would include setup and teardown; measuring produced-to-consumed
timestamps measures the pipeline.

## Stating the limits

The doc is explicit that this is **not** capacity planning: one machine,
one node, one broker, RF=1, a synthetic topic, and a **single run per
replica count with no variance data**. Three runs with a spread would be
needed before calling a 5.6% difference real rather than noise — worth
volunteering, because an interviewer may otherwise ask whether 5.6% is
inside run-to-run variance. On one run, you cannot know.

## Connecting to the rest of the system

The benchmark topic has **12 partitions**; the domain topics have **3**.
That is deliberate: 12 gives headroom to test 8 replicas, while the domain
topics are sized for real parallelism, and
`market-ingest-hpa.yaml` caps `maxReplicas: 3` to match. See
[partitions and consumer groups](../kafka/partitions-and-consumer-groups.md).

So the benchmark answers "how does a consumer group scale?" — not "how
fast is StockViz's ingest?", which is bounded by provider HTTP, not by
Kafka.

## Interview questions

**Foundation — "What does throughput mean in your benchmark?"**
> 100,000 records divided by `max(consumed_at) − min(produced_at)` for that
> run — pipeline time, not the coordinator's wall clock, which would
> include setup.

**Strong SWE — "You went from 4 to 8 replicas and got slower. Why?"**
> Peak CPU per pod dropped from 450m to 213m, so the consumers are less
> busy, not more — they're waiting on something shared. With one broker on
> one kind node, the likely candidates are broker I/O, offset-commit
> traffic, and group-coordination overhead growing with member count. I
> didn't isolate it, so I'd present that as a hypothesis, not a finding.

**Strong SWE — "How do you know you're not counting records from a previous run?"**
> Each run uses a fresh consumer group and a distinct `run_id`, seeks to
> the end and commits before producing, and consumers filter on `run_id` —
> a foreign record fails the run rather than being skipped.

**Advanced — "Is 5.6% real, or noise?"**
> I can't tell from this data. It's one run per replica count with no
> variance measurement. I'd want at least three runs and a spread before
> treating it as a real regression — that's a limitation of the experiment,
> not a result.

**Advanced — "What would you do to scale past the plateau?"**
> First find the bottleneck rather than adding replicas: multi-broker with
> partitions spread across them, then batched or periodic offset commits
> instead of per-record synchronous ones, then a binary format instead of
> JSON. But for StockViz's actual ingest none of that is the constraint —
> provider HTTP latency and rate limits are, which is why the domain topics
> have 3 partitions and not 12.

## Memorise vs understand

**Memorise:** 1.87× at 2 replicas, plateau at 4, −5.6% at 8; CPU/pod falls
as replicas rise.

**Understand:** why falling per-pod CPU means a shared bottleneck; why
run isolation needs a hard failure rather than a filter; why one run can't
establish a 5.6% effect.
