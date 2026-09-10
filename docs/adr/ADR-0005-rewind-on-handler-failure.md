# ADR-0005 — Rewind a failed record rather than skip it

**Status:** Accepted.

## Context

`events/dispatcher.py::consume_once` polls one record, runs the handler,
commits the database transaction, and only then commits the Kafka offset.
On a handler exception it logged "offset not committed" and backed off.

That log was misleading. `poll()` advances the consumer's **in-memory
position** whether or not the offset was committed, so the next poll
returned the *following* record. The failed record was not retried; and
once a later record committed its offset, the committed position moved
**past** the failed record, which was then never redelivered.

For this pipeline that means a silently dropped price bar, news article,
or trade-activity update — a data-quality failure with no error surface,
since the only trace was a log line claiming the opposite.

The behaviour was untested: no test covered the dispatcher's failure path.
`KNOWN_LIMITATIONS.md` separately claimed a poison record "can stall its
partition", which the code did not do.

## Decision

On any handler failure, seek the partition back to the failed record's
offset before backing off, so the next poll redelivers it:

- `producer.py::ConfluentBrokerConsumer.seek` wraps
  `Consumer.seek(TopicPartition(topic, partition, offset))`.
- `dispatcher.py::_rewind` calls it and swallows seek errors so a failed
  seek cannot kill the worker loop.

`tests/test_dispatcher_retry.py` models the position/commit split with a
fake consumer and asserts a failed record is retried before the next one
is handled.

## Alternatives considered

| Alternative | Why not |
| --- | --- |
| Dead-letter topic | The right long-term answer, and it is on the [roadmap](../ENGINEERING_ROADMAP.md). It needs a DLQ topic, a redrive path, and an alert — more than a correctness fix should carry. |
| Retry in-process N times, then skip | Still drops data at the end, and hides the failure behind a counter. |
| Leave the skip and document it | Silent data loss in a financial pipeline is not an acceptable documented behaviour. |

## Consequences

- **A genuinely poison record now stalls its partition** until the code or
  data is fixed. That is deliberate: with no DLQ, a loud stall beats a
  silent gap. It is the behaviour `KNOWN_LIMITATIONS.md` already
  described, now actually true.
- Retries are unbounded and unattended — no attempt counter, no alert. A
  stalled partition is currently only visible via consumer lag and worker
  logs. See
  [the runbook](../operations/runbooks/kafka-consumer-stalled.md).
- Other partitions are unaffected; ordering per key is preserved.
- A DLQ with bounded retries remains the follow-up.
