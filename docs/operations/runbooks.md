# Runbooks

Operational procedures for StockViz. Each runbook follows the same shape:
Symptoms → Impact → Initial checks → Useful commands → Likely causes →
Recovery → Validation → Prevention.

Before using these, read [Observability](../observability/overview.md) —
it states which signals actually exist, which is short. Most diagnosis here
is logs plus SQL.

| Symptom | Runbook |
| --- | --- |
| A consumer stops advancing; lag grows on one partition | [Kafka consumer stalled](./runbooks/kafka-consumer-stalled.md) |
| `outbox_events` unpublished count keeps growing | [Outbox backlog](./runbooks/outbox-backlog.md) |
| Prices/charts stop updating; alerts stop firing | [Stale market data](./runbooks/stale-market-data.md) |
| API 500s, `OperationalError`, pods flapping under load | [Postgres connection exhaustion](./runbooks/postgres-connections.md) |

## Quick triage

```bash
# Is the API healthy, and is its database reachable?
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:8000/health   # 503 => DB down
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:8000/live     # 200 => process fine

# What is running, and is anything restarting?
kubectl get pods -n stockviz
kubectl get events -n stockviz --sort-by=.lastTimestamp | tail -20

# The two queues, both of which fail silently
psql "$DATABASE_URL" -c "SELECT count(*) FROM outbox_events WHERE published_at IS NULL;"
kubectl exec -n stockviz stockviz-kafka-0 -- bin/kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 --describe --all-groups
```

`/live` returning 200 while `/health` returns 503 is the designed
signal that **the process is fine and its database is not** — do not
restart the API for that.

## Escalation

This is a portfolio/lab system with no on-call rotation. "Escalation"
means: capture the failing `event_id`, the worker logs, and the relevant
row counts before restarting anything, because a restart usually destroys
the evidence — in-memory rate-limit state, the position of a stalled
consumer, and any un-flushed logs.
