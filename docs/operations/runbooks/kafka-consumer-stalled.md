# Runbook — Kafka consumer stalled / lag growing

## Symptoms

- Consumer-group lag on one partition grows and never drains.
- Worker logs repeat `handler failed; offset not committed, rewinding and
  backing off` or `incompatible payload; … rewinding` for the same
  `event_id`.
- Downstream state stops updating for *some* tickers but not others
  (a single partition is stuck; the other two are fine).

## Impact

Scoped to the affected partition. Because market and news events are keyed
by `ticker`, a stalled partition freezes roughly a third of the universe:
those tickers stop getting fresh bars, metrics, alerts, or sentiment.
Trading is unaffected — the ledger does not depend on Kafka
([ADR-0001](../../adr/ADR-0001-postgres-as-system-of-record.md)).

## This is by design

Since [ADR-0005](../../adr/ADR-0005-rewind-on-handler-failure.md), a failed
record is rewound and retried rather than skipped. **A stall is the system
refusing to silently drop data.** The previous behaviour looked healthier
and quietly lost the record. Do not "fix" a stall by skipping the record
unless you have decided the data is genuinely disposable.

## Initial checks

1. Which group, which partition, how much lag?
2. Is the same `event_id` repeating in the logs? (Poison record.)
3. Or are many different `event_id`s failing? (Dependency outage.)

That distinction drives everything below.

## Useful commands

```bash
# Lag per group/partition — what is actually stuck
kubectl exec -n stockviz stockviz-kafka-0 -- bin/kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 --describe --group stockviz-market-ingest

# The failing record and its event_id, repeated once per retry
kubectl logs -n stockviz deploy/stockviz-market-ingest --tail=200 | grep -E 'failed|rewinding'

# Trace that event_id back to its origin
psql "$DATABASE_URL" -c \
  "SELECT event_type, topic, partition_key, occurred_at, payload
     FROM outbox_events WHERE id = '<event_id>';"

# Has any consumer already applied it?
psql "$DATABASE_URL" -c \
  "SELECT consumer_name, processed_at FROM consumer_inbox WHERE event_id = '<event_id>';"
```

## Likely causes

| Cause | Signal | Fix |
| --- | --- | --- |
| Provider down / rate-limited | Many different `event_id`s failing; HTTP errors from yfinance or Newsdata | Wait it out — retries are the correct behaviour. Confirm the provider, then let it drain. |
| Poison record — bad schema | Same `event_id`, `SchemaIncompatibleError`, `unsupported schema_version` | Fix the contract or the producer; see below. |
| Poison record — handler bug | Same `event_id`, a stack trace in domain code | Fix the handler, redeploy. The record retries automatically. |
| Postgres unreachable from the worker | `OperationalError` in the trace | [Postgres runbook](./postgres-connections.md) |
| Missing provider credential | News worker no-ops or errors; `NEWSDATA_KEY` unset | Set it in `infra/.env` — compose does **not** read `apps/api/.env`. |

## Recovery

**Dependency outage —** do nothing. The rewind-and-backoff loop is the
recovery. Lag drains once the provider returns.

**Handler bug —** fix, build, redeploy. The record is still at the head of
the partition and will be retried:

```bash
kubectl rollout restart -n stockviz deploy/stockviz-market-ingest
kubectl rollout status  -n stockviz deploy/stockviz-market-ingest
```

**Genuine poison record —** there is **no dead-letter topic**
([roadmap](../../ENGINEERING_ROADMAP.md)). The only way past it is to
decide, explicitly, to abandon that record by advancing the committed
offset:

```bash
# Scale to zero first — the group must have no members to reset offsets.
kubectl scale -n stockviz deploy/stockviz-market-ingest --replicas=0

kubectl exec -n stockviz stockviz-kafka-0 -- bin/kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 --group stockviz-market-ingest \
  --topic stockviz.market.v1:<partition> --reset-offsets --shift-by 1 --execute

kubectl scale -n stockviz deploy/stockviz-market-ingest --replicas=1
```

This **permanently discards** the record. For a `market.refresh.requested`
that is usually recoverable — the next scheduled refresh re-requests the
same ticker, or re-run the CLI twin by hand:

```bash
kubectl exec -n stockviz deploy/stockviz-api -- python -m stockviz.cli ingest AAPL
```

Record what you discarded and why.

## Validation

```bash
# Lag draining toward zero
kubectl exec -n stockviz stockviz-kafka-0 -- bin/kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 --describe --group stockviz-market-ingest

# Offsets committing again ("applied" or "duplicate", not "failed")
kubectl logs -n stockviz deploy/stockviz-market-ingest --tail=50 | grep 'offset committed'

# Data actually moved
psql "$DATABASE_URL" -c "SELECT ticker, max(ts) FROM price_bars GROUP BY ticker ORDER BY 2 LIMIT 10;"
```

`duplicate` is a healthy result — it means the inbox key caught a replay,
exactly as intended.

## Prevention

- A dead-letter topic with bounded retries is the real fix.
- A lag metric with an alert would turn this from "someone noticed" into a
  page. Neither exists yet — see
  [Observability](../../observability/overview.md).
- Consumer parallelism cannot exceed partitions (3), so adding replicas
  beyond `maxReplicas: 3` will not help drain lag.
