# Runbook — Postgres connection exhaustion

## Symptoms

- API returns 500s; logs show `OperationalError`, `too many clients
  already`, or `QueuePool limit … overflow … timed out`.
- `/health` returns 503 while `/live` returns 200.
- API pods leave the Service and may flap as readiness fails.
- Workers fail their handlers and rewind, so consumer lag grows too.

## Impact

Broad. Postgres is the system of record
([ADR-0001](../../adr/ADR-0001-postgres-as-system-of-record.md)), so
exhaustion degrades trading, reads, scheduled jobs, and every consumer at
once.

## Why this is plausible here

`db.py` builds one engine per process with SQLAlchemy defaults —
`pool_size=5`, `max_overflow=10`, so **up to ~15 connections per
process**. Count the processes:

| Process | Replicas | Worst-case connections |
| --- | --- | --- |
| API | 2–5 (HPA) | 30–75 |
| Scheduler | 1 | 15 |
| Outbox publisher | 1 | 15 |
| Consumers (6 kinds) | 1–3 each | 90–270 |

Postgres defaults to `max_connections = 100`. **There is no PgBouncer in
this repo.** The lab runs comfortably because replicas sit at their minima
and workers are mostly idle, but the ceiling is real and is reached by
scaling out, not by traffic.

## Initial checks

```bash
# How close to the ceiling, and who is holding connections?
psql "$DATABASE_URL" -c "SELECT count(*) FROM pg_stat_activity;"
psql "$DATABASE_URL" -c "SHOW max_connections;"
psql "$DATABASE_URL" -c "
  SELECT application_name, state, count(*)
    FROM pg_stat_activity GROUP BY 1,2 ORDER BY 3 DESC;"

# Long-running or idle-in-transaction sessions — the usual culprit
psql "$DATABASE_URL" -c "
  SELECT pid, state, now() - state_change AS age, left(query, 80)
    FROM pg_stat_activity
   WHERE state <> 'idle' ORDER BY age DESC LIMIT 10;"

# Blocked on a lock?
psql "$DATABASE_URL" -c "
  SELECT pid, wait_event_type, wait_event, left(query, 60)
    FROM pg_stat_activity WHERE wait_event_type = 'Lock';"

kubectl get hpa -n stockviz
kubectl top pods -n stockviz
```

`idle in transaction` with a growing age is the signature of a leaked
session and matters more than the raw count.

## Likely causes

| Cause | Signal | Fix |
| --- | --- | --- |
| Too many replicas × pool size | Count roughly equals replicas × 15 | Scale in, or lower `pool_size` |
| Long lock wait on a hot portfolio | `wait_event_type = Lock` on `portfolios` | Expected under concurrent writes to one portfolio; investigate if sustained |
| Leaked session | `idle in transaction`, age climbing | Find the code path that skipped a `with Session(...)` |
| Provider call inside a transaction | Handler holding a transaction across HTTP | Should not happen — consumers fetch *before* opening a session; verify if seen |
| A stuck advisory lock | Scheduler jobs skipping | Advisory locks release when the backend disconnects |

The "provider call inside a transaction" row is worth checking explicitly,
because it is the pattern that would most easily reintroduce this problem:
`market_ingest_consumer.py::process_payload` deliberately calls
`fetch_bars_for_event` **before** `with Session(engine)`. Keep it that way.

## Recovery

Immediate relief — reduce demand:

```bash
kubectl scale -n stockviz deploy/stockviz-api --replicas=2
kubectl scale -n stockviz deploy/stockviz-market-ingest --replicas=1
```

Terminate a genuinely stuck session (identify it first):

```sql
SELECT pg_terminate_backend(<pid>);
```

Prefer `pg_cancel_backend` first — it cancels the query without dropping
the connection.

Do **not** restart every API pod reflexively. If `/live` is 200 and
`/health` is 503, the processes are fine and the database is the problem;
restarting adds a reconnect storm to an already saturated server.

## Validation

```bash
psql "$DATABASE_URL" -c "SELECT count(*) FROM pg_stat_activity;"
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:8000/health   # expect 200
kubectl get pods -n stockviz    # pods Ready again
```

## Prevention

- **PgBouncer in transaction mode** is the standard fix and the one this
  system would want first ([schema doc](../../database/schema.md)).
- Set `pool_size` / `max_overflow` explicitly in `db.py` and size them
  against `max_connections ÷ expected processes`, rather than inheriting
  defaults.
- Raise `max_connections` only with matching memory headroom — each
  backend costs memory; a connection pooler is usually the better answer.
- Keep provider I/O outside transactions.
