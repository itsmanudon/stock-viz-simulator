# Findings

Engineering issues found while building this curriculum. Each is
classified, and resolved into a **fix**, a **test**, **documentation**, or
a tracked follow-up. Resolved entries stay for the record but are marked;
this file is not an unbounded dump.

Severity: Critical · High · Medium · Low · Improvement
Category: correctness · reliability · performance · security ·
maintainability · observability · scalability · data quality ·
architecture · developer experience

---

## Resolved

### F-001 — Failed Kafka records were silently dropped ✅ FIXED

**Severity:** High · **Category:** reliability, data quality

**Problem.** `events/dispatcher.py::consume_once` did not commit the Kafka
offset when a handler raised, and logged "offset not committed" — implying
a retry. But `poll()` advances the consumer's in-memory position
regardless of commits, so the next poll returned the *following* record.
Once that record committed its offset, the committed position moved
**past** the failed record, which was then never redelivered.

**Evidence.**
- No `seek`, `pause`, or `assign` call existed anywhere in
  `events/` or `workers/`.
- `consume_once`'s failure path had **zero test coverage** — the only
  consumer tests (`test_kafka_integration.py`) require a live broker and
  skip without one.
- `KNOWN_LIMITATIONS.md` claimed a poison record "can stall its
  partition", which the code did not do.

**Impact.** Silently dropped price bars, news articles, and trade-activity
updates on any transient handler failure — a provider timeout was enough.
The symptom is *missing data*, which produces no error to observe, and the
log line actively pointed the wrong way.

**Fix.**
- `producer.py::ConfluentBrokerConsumer.seek` — rewinds the partition to a
  given message's offset.
- `dispatcher.py::_rewind` — called on both failure paths; swallows seek
  errors so a failed seek cannot kill the worker loop.

**Tests.** `apps/api/tests/test_dispatcher_retry.py` — 7 tests using a
fake consumer that models the position/commit split. Verified to fail
without the fix (3 failures, with `committed == [2]` proving offset 0 was
skipped) and pass with it.

**Docs.** [ADR-0005](../adr/ADR-0005-rewind-on-handler-failure.md);
`KNOWN_LIMITATIONS.md` corrected;
[runbook](../operations/runbooks/kafka-consumer-stalled.md);
[failure scenarios §2](./distributed-systems/failure-scenarios.md).

**Accepted consequence.** A genuinely poison record now stalls its
partition. Deliberate — with no DLQ, a loud stall beats a silent gap for
financial data. See F-002.

---

### F-005 — Documentation contradicted code ✅ FIXED

**Severity:** Low · **Category:** maintainability

`KNOWN_LIMITATIONS.md` described poison-record behaviour the code did not
implement. Corrected as part of F-001, and now accurate.

---

## Open — tracked, not yet actioned

### F-002 — No dead-letter queue or retry ceiling

**Severity:** Medium · **Category:** reliability

Retries are unbounded and unattended: no attempt counter on the consumer
side, no DLQ, no alert. After F-001 a poison record stalls its partition
indefinitely, and the only signal is consumer lag — which nothing
monitors.

Already on the [roadmap](../ENGINEERING_ROADMAP.md) ("consumer retry/DLQ
policy"). **Not fixed here** because it needs a DLQ topic, a redrive path,
and alerting — more than a correctness fix should carry, and it is the
kind of architectural change that should be proposed rather than slipped
in.

*Proposed shape:* retry counter in the message header; after N attempts
produce to `stockviz.<domain>.dlq.v1` with the failure reason and commit
the offset; a redrive CLI twin; alert on DLQ depth > 0.

### F-003 — Rate limits are per-process while the API autoscales

**Severity:** Medium · **Category:** security, scalability

slowapi's default storage is in-memory, so each API replica keeps its own
buckets. With `maxReplicas: 5` the effective budget is up to 5× the
configured limit, and it resets on every pod restart.

Partially documented ("CPU-local rate limiting"), now explained with its
cause in [ADR-0004](../adr/ADR-0004-no-redis.md). **Not fixed** because
the fix is a shared store — the one genuine reason this project would add
Redis — which is an infrastructure decision, not a code cleanup.

### F-004 — Consumer autoscaling uses the wrong signal

**Severity:** Low · **Category:** scalability

`market-ingest-hpa.yaml` scales on CPU, but the consumer is I/O-bound on
provider HTTP: it can be badly backed up at low CPU and never scale out.

Already acknowledged in `KNOWN_LIMITATIONS.md` and `KAFKA_SCALING.md` as a
deliberate demonstration. Documented, not changed — lag-based scaling
needs KEDA, which is a real infrastructure addition.

*Worth noting the part that is right:* `maxReplicas: 3` correctly matches
`MARKET_TOPIC_PARTITIONS = 3`.

### F-006 — Connection-pool ceiling is reached by scaling out

**Severity:** Medium · **Category:** scalability

`db.py` uses SQLAlchemy defaults (~15 connections per process). At full
scale — 5 API + scheduler + publisher + 6 consumer types — worst-case
demand exceeds a default `max_connections = 100`. No PgBouncer.

Not currently hit, because replicas sit at their minima. Documented in
[schema](../database/schema.md#connection-pooling) and
[runbook](../operations/runbooks/postgres-connections.md). **Not fixed**
because setting pool sizes without measuring would be guessing; the real
answer is a pooler.

### F-007 — No exchange calendar; bar finality is timing-based

**Severity:** Low · **Category:** data quality

Nothing checks whether a session has closed before writing a bar. The
16:30 America/New_York schedule is the only guard, so a manual mid-session
`cli ingest` can store a partial bar (later overwritten). A market holiday
and a provider outage are indistinguishable in the logs — both produce
"provider returned no bars".

Documented in [market-data semantics](../database/market-data.md).

### F-008 — Missing index on `trades(portfolio_id, ts)`

**Severity:** Low · **Category:** performance

`portfolio_id` is indexed alone; trade history ordered by time filters
then sorts. Trivial at demo volume. **Not added** without an
`EXPLAIN ANALYZE` to justify it — the repository has no query-plan
evidence, and adding indexes on intuition is how you end up with unused
ones.

---

## Noted as strengths

Worth recording, because knowing *why* something is right is as useful as
finding what's wrong:

- **Outbox + inbox + commit ordering** — textbook-correct, with the
  reasoning in docstrings rather than tribal knowledge.
- **`/live` vs `/health` split** — with the outage-amplification reasoning
  written down.
- **HPA ceiling pinned to partition count** — rarely got right.
- **Pure execution kernel** — no Session, FX, settings, or wall clock;
  deterministic and testable.
- **Provider I/O outside transactions**, structurally enforced by the
  dispatcher's `process` vs `handlers` split.
- **`lock_portfolio` refreshing the ORM instance** — the non-obvious half
  of a correct row lock.
- **Every scheduled job has a manual CLI twin** — makes every runbook
  recovery step trivially available.
