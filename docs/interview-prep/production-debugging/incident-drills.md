# Incident drills

Practice scenarios. Work the diagnosis yourself before reading the
walkthrough. The [runbooks](../../operations/runbooks.md) are the
operational procedures; this note is about the **reasoning**.

The general shape:

```
symptom → which signal narrows it → hypothesis → command → root cause → fix → prevention
```

The hard part in this system is step two, because
[observability is thin](../../observability/overview.md): no metrics, no
tracing, no alerting. You have logs, `psql`, and `kubectl`.

---

## Drill 1 — "Charts stopped updating yesterday"

**Think first:** what is the *first* place in the pipeline that could be
empty?

<details><summary>Walkthrough</summary>

The path is `scheduler → outbox → Kafka → consumer → price_bars`. Bisect
it rather than guessing.

```bash
# Is it all symbols or some? Uniform => upstream. Partial => partition/provider.
psql "$DATABASE_URL" -c "SELECT ticker, max(ts) FROM price_bars
                          WHERE interval='1d' GROUP BY ticker ORDER BY 2 LIMIT 15;"

# Did the scheduler enqueue?
psql "$DATABASE_URL" -c "SELECT event_type, count(*), max(created_at) FROM outbox_events
                          WHERE created_at > now() - interval '1 day' GROUP BY 1;"

# Did the publisher publish?
psql "$DATABASE_URL" -c "SELECT count(*) FROM outbox_events WHERE published_at IS NULL;"
```

| Finding | Root cause | Fix |
| --- | --- | --- |
| No new outbox rows | Scheduler down, or `ENABLE_SCHEDULER` wrong | Start it / fix env |
| Rows exist, unpublished | Publisher or broker down | [Outbox backlog](../../operations/runbooks/outbox-backlog.md) |
| Published, bars stale | Consumer stalled | [Consumer stalled](../../operations/runbooks/kafka-consumer-stalled.md) |
| Only some tickers stale | One partition stuck, or provider issue | Check lag per partition |

**Check first:** is it a weekend or market holiday? There's no exchange
calendar — the provider just returns no rows, and ingest logs "provider
returned no bars" and marks it processed. That is correct behaviour and
looks identical to an outage.

**Prevention:** alert on `max(price_bars.ts)` falling more than one
trading day behind. Highest-value alert this system doesn't have.
</details>

---

## Drill 2 — "Consumer lag is growing on one partition only"

**Think first:** why does *one* partition matter more than all three?

<details><summary>Walkthrough</summary>

One partition = a specific record is stuck. All partitions = dependency
outage or under-capacity. That single distinction drives everything.

```bash
kubectl logs -n stockviz deploy/stockviz-market-ingest --tail=200 | grep -E 'failed|rewinding'
```

**Same `event_id` repeating** → poison record. Since
[ADR-0005](../../adr/ADR-0005-rewind-on-handler-failure.md), the record
rewinds and retries rather than being skipped, so the partition stalls by
design. Fix the handler or the data; if the record is genuinely
undeliverable, explicitly reset the offset past it and record why.

**Many different `event_id`s** → provider outage or Postgres unreachable.
Retries are the correct behaviour; lag drains when the dependency returns.

**Trap:** adding replicas won't help. Three partitions means at most three
active consumers, and a stalled *record* isn't a capacity problem anyway.
</details>

---

## Drill 3 — "API 500s under load; pods flapping"

<details><summary>Walkthrough</summary>

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:8000/live    # 200?
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:8000/health  # 503?
```

`/live` 200 + `/health` 503 = **the process is fine, the database isn't.**
That's the probe split doing its job. Do not restart the API.

```bash
psql "$DATABASE_URL" -c "SELECT count(*) FROM pg_stat_activity;"
psql "$DATABASE_URL" -c "SHOW max_connections;"
psql "$DATABASE_URL" -c "SELECT state, count(*) FROM pg_stat_activity GROUP BY 1;"
```

Root cause is usually arithmetic, not traffic: ~15 connections per process
× (5 API + scheduler + publisher + consumers) against a default
`max_connections = 100`. Scaling out is what exhausts it.

Look for `idle in transaction` with a climbing age — that's a leaked
session, and it matters more than the raw count.

**Fix:** scale in for relief; PgBouncer as the real answer. See
[the runbook](../../operations/runbooks/postgres-connections.md).
</details>

---

## Drill 4 — "A user says their cash balance is wrong"

<details><summary>Walkthrough</summary>

Reconstruct from the ledger — it's the source of truth, and every fill
leaves provenance.

```sql
SELECT id, ticker, side, quantity, price, ts FROM trades
 WHERE portfolio_id = :pid ORDER BY ts;

SELECT * FROM simulated_executions WHERE trade_id IN (...);   -- SIM-04 provenance

SELECT status, cancel_reason, quantity, limit_price FROM pending_orders
 WHERE portfolio_id = :pid;
```

Most likely explanations, in order:

1. **Reservations, not a bug.** Pending BUYs reserve cash, so *available*
   buying power is below `cash_balance`. The UI showing one and the user
   expecting the other is the usual answer.
2. **Currency.** `trades.price` is in the symbol's **native** currency;
   cash is always USD, converted at the FX rate. A non-USD symbol will not
   reconcile if you multiply naively.
3. **Options.** Premiums debit the USD bucket, and open contracts are
   marked to Black-Scholes value in NAV.
4. **Dividends.** Check `portfolio_dividends` for credits.

A genuine ledger bug would need a lost update, which is what the row lock
plus ORM refresh prevents — and `tests/test_pg_concurrency.py` covers it.

**Note:** trades before SIM-04 have no provenance row. Absence isn't
evidence of a problem.
</details>

---

## Drill 5 — "A pod is in CrashLoopBackOff"

<details><summary>Walkthrough</summary>

```bash
kubectl describe pod -n stockviz <pod>          # events, exit code, OOMKilled?
kubectl logs -n stockviz <pod> --previous       # logs from the crashed instance
kubectl get events -n stockviz --sort-by=.lastTimestamp | tail -20
```

`--previous` is the one people forget — the current container may have no
logs yet.

| Signal | Cause |
| --- | --- |
| `OOMKilled`, exit 137 | Over the 768Mi limit |
| `CreateContainerConfigError` | Missing Secret/ConfigMap key |
| Traceback on missing env | Config not wired for this workload |
| Connection refused to `localhost:9092` | `KAFKA_BOOTSTRAP_SERVERS` unset — the default is `localhost:9092`, but in-cluster it must be the broker Service |
| Exits immediately, `--once` in args | Not a crash — a one-shot run |
| DB connection refused at boot | Migration Job hasn't completed |

The last one is why migrations are a Job and why the Kustomize layering is
`bootstrap → migrate → app → scale`.
</details>

---

## Drill 6 — "Duplicate rows appeared in a derived table"

<details><summary>Walkthrough</summary>

This one is diagnostic of a *design* break, not an operational blip.

```sql
SELECT consumer_name, event_id, count(*) FROM consumer_inbox
 GROUP BY 1,2 HAVING count(*) > 1;      -- should be impossible (unique constraint)

SELECT count(*) FROM consumer_inbox WHERE event_id = '<id>';
```

If duplicates exist in a derived table but the inbox has one row, the
handler applied its side effect **outside** the transaction that wrote the
receipt, or committed before recording it. The invariant is: *domain
change and inbox receipt commit together, and the Kafka offset commits
after both.*

If the inbox itself has duplicates, the unique constraint is missing —
check the migration actually applied.

**Prevention:** every new consumer must follow the
`already_processed → apply → try_record_processed` shape in
`events/handlers.py`. It's a convention, not something the type system
enforces — which is worth flagging as a real weakness.
</details>

---

## What to take into an interview

When asked "how would you debug X in production", answer in this order:

1. **What's the blast radius?** (Is trading affected, or only freshness?)
2. **Which signal narrows it fastest?** (Not "check the logs" — *which*
   log line, *which* query.)
3. **Bisect the pipeline**, don't guess.
4. **What would have told me sooner?** (The alert that doesn't exist yet.)

Step 4 is what separates a debugger from an engineer, and this repository
gives you an honest answer for it every time.
