# Observability

An honest inventory. StockViz has **structured-ish logging, health
endpoints, and optional Sentry — and no metrics, no tracing, no
dashboards, and no alerting.** Knowing precisely where the gaps are is
what makes the [runbooks](../operations/runbooks.md) usable.

## What exists

| Signal | Implementation | Where |
| --- | --- | --- |
| Logs | Python `logging`, `INFO` level, format `%(levelname)s %(name)s: %(message)s` | `events/dispatcher.py::worker_main` |
| Errors | Sentry, **only when `SENTRY_DSN` is set** | `observability.py::init_sentry` |
| Liveness | `GET /live` — no I/O, always 200 for a live process | `routers/health.py` |
| Readiness | `GET /health` — `SELECT 1`, **503** when the DB is down | `routers/health.py` |
| Kafka scaling data | A one-off 100k-event benchmark harness | `benchmarks/`, [KAFKA_SCALING.md](../KAFKA_SCALING.md) |

### The probe split is the good part

```python
GET /live    # process is alive. Does NOT touch Postgres.
GET /health  # readiness + DB. 503 when Postgres is unreachable.
```

Kubernetes uses `/live` for `livenessProbe` and `/health` for
`readinessProbe` (`infra/k8s/base/app/api-deployment.yaml`). The reasoning
is written into the docstrings: **a database outage must not restart a
healthy API process.** If liveness probed the database, a Postgres blip
would kill every API pod simultaneously and turn a recoverable dependency
failure into a full outage.

Render points `healthCheckPath` at `/health`. The docstring records that
this endpoint used to always return 200, which meant Render could never
notice an instance that had lost its database.

### Log lines worth knowing

The event pipeline logs at each hand-off, which is what makes it traceable
without a tracing system:

| Message | Emitted by | Tells you |
| --- | --- | --- |
| `outbox enqueued event_id=… topic=… key=…` | `outbox.py::enqueue_event` | The intent was staged |
| `outbox publisher claimed batch_size=…` | `publish_batch` | The publisher is alive and finding work |
| `outbox published event_id=… attempts=…` | `publish_batch` | The broker acked |
| `outbox publish failed event_id=… attempts=…` | `publish_batch` | Broker or serialization problem |
| `kafka received topic=… partition=… offset=… key=…` | `producer.py::poll_json` | A consumer got the record |
| `kafka offset committed result=…` | `dispatcher.py` | `applied` \| `duplicate` \| `ignored` |
| `handler failed; … rewinding and backing off` | `dispatcher.py` | The record will be retried |

`event_id` is a UUID that survives the whole path — outbox row → Kafka
value → `consumer_inbox`. **It is the closest thing to a trace id in this
system**, and grepping it across processes is the practical substitute for
distributed tracing.

## What does not exist

| Missing | Consequence |
| --- | --- |
| Metrics endpoint (no Prometheus, no `/metrics`) | No request rate, latency, or error-rate series. The API HPA scales on **CPU** because CPU is the only signal available. |
| Consumer lag monitoring | A stalled partition ([ADR-0005](../adr/ADR-0005-rewind-on-handler-failure.md)) is invisible until someone looks. |
| Outbox backlog metric | `COUNT(*) WHERE published_at IS NULL` must be run by hand. |
| Distributed tracing | No trace propagates web → API → worker. `event_id` is the manual substitute. |
| Dashboards / alerting / on-call | Nothing pages anyone. |
| Defined SLIs / SLOs | No error budget, no latency target. |
| Structured (JSON) logs | Logs are human-formatted, so field-based querying is not possible. |

This is recorded in [KNOWN_LIMITATIONS.md](../KNOWN_LIMITATIONS.md) — "No
production secret manager or observability stack" — and in the
[roadmap](../ENGINEERING_ROADMAP.md).

## If you were to add observability here

In priority order, judged by what actually breaks in this system:

1. **Consumer lag + outbox backlog.** These are the two queues, and both
   fail silently. Lag per group, and `COUNT(*) WHERE published_at IS NULL`
   with an age histogram.
2. **RED metrics on the API** (Rate, Errors, Duration), p50/p95/p99. This
   also unlocks a request-based HPA instead of CPU.
3. **Provider call outcomes** — success/failure/latency per provider, with
   the provider as a label. Ingest failures currently only surface as a
   stalled partition.
4. **Structured JSON logs carrying `event_id`**, which turns the manual
   grep into a real query.
5. **Ledger invariant checks** as gauges — e.g. reserved cash never
   exceeding `cash_balance`.

Cardinality warning specific to this domain: **do not label metrics with
`ticker`**. The universe is small today but is the obvious thing to grow,
and a per-ticker label on every ingest metric multiplies series by the
universe size. Aggregate by provider and outcome; keep the ticker in logs.

## Debugging without any of this

That is what the [runbooks](../operations/runbooks.md) are for. The
practical toolkit today is:

```bash
kubectl logs -n stockviz deploy/stockviz-market-ingest --tail=100
kubectl get pods -n stockviz            # restarts, CrashLoopBackOff
kubectl top pods -n stockviz            # the only resource signal
psql "$DATABASE_URL" -c "SELECT count(*) FROM outbox_events WHERE published_at IS NULL;"
curl -sS localhost:8000/health          # 503 => DB unreachable
```
