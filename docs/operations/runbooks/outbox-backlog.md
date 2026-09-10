# Runbook — Outbox backlog

## Symptoms

`SELECT count(*) FROM outbox_events WHERE published_at IS NULL` grows and
does not drain. Downstream consumers are idle — no lag, because nothing is
being produced.

## Impact

Events are **not lost** — they are durably committed in Postgres and will
publish when the publisher recovers. But every async path stalls: no bar
refreshes, no news ingest, no sentiment, no derived metrics or alerts.
Trading is unaffected
([ADR-0001](../../adr/ADR-0001-postgres-as-system-of-record.md)).

Note the asymmetry with a consumer stall: consumer lag means *Kafka has
the data and workers are stuck*; outbox backlog means *the data never
reached Kafka*.

## Initial checks

```bash
# Size and age of the backlog — age matters more than count
psql "$DATABASE_URL" -c "
  SELECT count(*) AS pending,
         min(created_at) AS oldest,
         now() - min(created_at) AS age
    FROM outbox_events WHERE published_at IS NULL;"

# Are rows failing, or is nothing even trying?
psql "$DATABASE_URL" -c "
  SELECT id, event_type, publish_attempts, last_error
    FROM outbox_events
   WHERE published_at IS NULL AND publish_attempts > 0
   ORDER BY created_at LIMIT 10;"

kubectl get pods -n stockviz -l app.kubernetes.io/component=outbox-publisher
kubectl logs -n stockviz deploy/stockviz-outbox-publisher --tail=100
```

`publish_attempts = 0` on everything means the publisher is not running at
all. Non-zero attempts with a `last_error` means it is running and failing.

## Likely causes

| Cause | Signal | Fix |
| --- | --- | --- |
| Publisher not running | `publish_attempts = 0`, no pod, or CrashLoopBackOff | Start/fix the deployment |
| Broker unreachable | `last_error` mentions broker transport or timeout | Check Kafka pods and `KAFKA_BOOTSTRAP_SERVERS` |
| Wrong bootstrap address | Publisher logs connection refused to `localhost:9092` | Inside compose it must be `kafka:29092`, not the default |
| Topic missing | `last_error` mentions unknown topic | `ensure_event_topics`, or the Strimzi `KafkaTopic` resources |
| Flush timeout | `flush timed out with N message(s) in flight` | Broker is up but unhealthy — check under-replicated partitions |
| A single poison row | One `id` with a high `publish_attempts` | See below |

The `localhost:9092` default catches people out: `KAFKA_BOOTSTRAP_SERVERS`
defaults to `localhost:9092`, and every worker running inside compose needs
`kafka:29092`.

## Recovery

**Publisher down —** restart it. The claim uses `FOR UPDATE SKIP LOCKED`,
so it is safe to run more than one publisher; they will not claim the same
row.

```bash
kubectl rollout restart -n stockviz deploy/stockviz-outbox-publisher
kubectl logs -f -n stockviz deploy/stockviz-outbox-publisher
```

Expect `outbox publisher claimed batch_size=…` followed by
`outbox published event_id=…`.

**Broker down —** fix Kafka first; the backlog drains on its own. No data
is at risk while it waits.

**Manual drain —** the CLI twin publishes one batch:

```bash
kubectl exec -n stockviz deploy/stockviz-api -- python -m stockviz.cli publish-outbox --once
```

**A single failing row —** `publish_batch` isolates failures per row: it
records `last_error`, increments `publish_attempts`, and moves on, so one
bad row does **not** block the others. If one row is stuck forever,
inspect its payload; a row that can never be produced can be marked
published to retire it, but that discards the event:

```sql
-- Discards the event. Be sure. Record why.
UPDATE outbox_events SET published_at = now(), last_error = 'manually retired: <reason>'
 WHERE id = '<event_id>';
```

## Validation

```bash
psql "$DATABASE_URL" -c \
  "SELECT count(*) FROM outbox_events WHERE published_at IS NULL;"   # trending down
kubectl logs -n stockviz deploy/stockviz-outbox-publisher --tail=20 | grep published
```

Then confirm consumers picked the events up — `kafka offset committed
result=applied` in a consumer's logs.

## Prevention

- Alert on **backlog age**, not count. A large backlog draining fast is
  fine; a small one that is an hour old is not.
- There is no attempt ceiling: a permanently failing row retries forever
  with no alert ([ADR-0002](../../adr/ADR-0002-transactional-outbox.md)).
- Published rows are never archived. Harmless now — the
  `ix_outbox_events_unpublished` partial index keeps the publisher's query
  fast regardless of history — but it grows forever.
