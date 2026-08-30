# Runbook — Stale market data

## Symptoms

- Charts and quotes show an old date; "latest close" stops moving.
- Price alerts stop firing.
- Screener/recommendation values look frozen.
- Pending orders stay `PENDING` through a settlement window.

## Impact

User-visible staleness across the app, since **everything prices off the
latest `1d` close** ([market-data semantics](../../database/market-data.md)).

One thing that is *not* affected, by design: pending orders will not fill
against a stale close. `settle_pending_orders` takes a `session_date` and
leaves an order pending when the latest bar predates it. Orders stuck
pending is the safety mechanism working, not a second bug.

## Initial checks — walk the pipeline in order

The path has four hops, and the fastest diagnosis is to find the first one
that is empty:

```
scheduler → outbox_events → Kafka → market_ingest → price_bars
```

```bash
# 1. How stale, and is it uniform or per-ticker?
psql "$DATABASE_URL" -c "
  SELECT ticker, max(ts) AS latest FROM price_bars
   WHERE interval = '1d' GROUP BY ticker ORDER BY latest LIMIT 15;"

# 2. Did the scheduler enqueue anything today?
psql "$DATABASE_URL" -c "
  SELECT event_type, count(*), max(created_at) FROM outbox_events
   WHERE created_at > now() - interval '1 day' GROUP BY 1;"

# 3. Is the scheduler running at all?
kubectl get pods -n stockviz -l app.kubernetes.io/component=scheduler
kubectl logs -n stockviz deploy/stockviz-scheduler --tail=100

# 4. Is the ingest consumer applying?
kubectl logs -n stockviz deploy/stockviz-market-ingest --tail=100
```

**A uniformly stale universe** points at the scheduler or publisher.
**A few stale tickers** points at a stalled partition or provider issues
for those symbols.

## Likely causes

| Cause | Where it shows | Runbook / fix |
| --- | --- | --- |
| Weekend or market holiday | Latest bar is the last trading day | **Not a fault.** There is no exchange calendar; the provider simply returns no rows. |
| Scheduler not running | No new `outbox_events` rows | Start the scheduler Deployment |
| `ENABLE_SCHEDULER` wrong | Render: must be `true`; K8s API pods: must be `false` with a separate scheduler | Fix the env var |
| Publisher stopped | Rows enqueued, `published_at` NULL | [Outbox backlog](./outbox-backlog.md) |
| Consumer stalled | Lag on one partition | [Consumer stalled](./kafka-consumer-stalled.md) |
| Provider returned nothing | `provider returned no bars; marking request processed` | Provider-side; verify by hand |
| Advisory lock held by a dead session | Job logs "skipped, another instance holds the lock" | Check `pg_locks`; a killed backend releases on disconnect |

### The "no bars" case is deliberately not an error

`persist_market_refresh` logs `provider returned no bars; marking request
processed` and records the inbox receipt. This is correct on weekends and
holidays — retrying forever for a day that has no bar would stall the
partition. The cost is that a genuine provider outage looks the same as a
market holiday in the logs. Confirm by hand:

```bash
kubectl exec -n stockviz deploy/stockviz-api -- python -m stockviz.cli ingest AAPL
```

## Recovery

```bash
# Re-request refreshes through the normal path (enqueues outbox rows)
kubectl exec -n stockviz deploy/stockviz-api -- python -m stockviz.cli ingest AAPL MSFT

# Then rebuild what derives from bars
kubectl exec -n stockviz deploy/stockviz-api -- python -m stockviz.cli metrics
kubectl exec -n stockviz deploy/stockviz-api -- python -m stockviz.cli recommend
```

Every scheduled job has a CLI twin precisely for this. Re-running is safe:
bars upsert on `(ticker, ts, interval)` and jobs are idempotent.

If settlement was missed because prices were stale, re-run it **after**
bars are fresh — it is guarded by an advisory lock and will not double-fill.

## Validation

```bash
psql "$DATABASE_URL" -c \
  "SELECT max(ts) FROM price_bars WHERE interval = '1d';"
psql "$DATABASE_URL" -c \
  "SELECT count(*) FROM symbol_metrics WHERE updated_at > now() - interval '1 hour';"
curl -sS http://localhost:8000/v1/bars/AAPL | head -c 300
```

## Prevention

- Alert on `max(price_bars.ts)` falling more than one trading day behind —
  the single highest-value alert this system does not have.
- An exchange calendar would remove the holiday/outage ambiguity.
- The scheduler is a **single replica by design**; if it is down, nothing
  is enqueued. Its liveness is the pipeline's liveness.
