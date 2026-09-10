# Explaining StockViz in interviews

Rehearsed answers at several lengths, plus the follow-ups that actually
get asked. **Every claim here is checkable in the repository.** The
original walkthrough in [INTERVIEW_GUIDE.md](../INTERVIEW_GUIDE.md)
covers the architecture narrative; this document is about *delivery* —
what to say, in what order, and where the traps are.

The rule that makes this credible: **never inflate.** The strongest
material here is the gaps you can name before the interviewer finds them.

---

## 30 seconds

> StockViz is a full-stack market-analytics and paper-trading app —
> Next.js, FastAPI, PostgreSQL, Kafka, deployed on Kubernetes. The
> interesting part is the split: the trading ledger is a synchronous
> Postgres transaction with row locks, and everything else — market data,
> news, sentiment — runs through a transactional outbox into Kafka with
> idempotent consumers. So a broker outage degrades data freshness but
> never blocks a trade.

Stop there. The last sentence is designed to invite the follow-up you
want.

---

## 2 minutes

> The browser talks to a Next.js server, which handles auth and makes
> server-side calls to a FastAPI backend. Postgres is the system of record
> for users, market data, portfolios, orders and trades.
>
> The financial path is synchronous. A trade locks the portfolio row,
> validates cash against reservations from pending orders, updates the
> ledger, and inserts an outbox row — all in one transaction. HTTP success
> happens after the commit, so Kafka isn't required for correctness.
>
> The async path starts from that outbox. A separate publisher claims rows
> with `SELECT … FOR UPDATE SKIP LOCKED`, produces to Kafka, and marks them
> published only after the broker acks. Consumers commit their database
> work *before* the Kafka offset, and write an inbox key in the same
> transaction, so replays are harmless. A singleton scheduler enqueues
> market and news refresh requests — it never calls providers itself, so a
> slow provider can't wedge it.
>
> On Kubernetes that's about ten Deployments: API and web behind Services
> with HPAs, a migration Job, a single-replica scheduler, the publisher,
> and six consumers. Kafka runs under Strimzi. I validated it on kind in
> CI and benchmarked consumer scaling over 100,000 events.

---

## 5 minutes (technical)

Add, in this order:

**Why Postgres is the ledger.** Cash, positions and reservations have
multi-row invariants that need one atomic decision. Kafka is great for
distributing committed facts, but it can't arbitrate buying power.

**The dual-write problem.** Commit-then-publish loses events on a crash;
publish-then-commit fabricates them on a rollback. The outbox makes the
event part of the same transaction.

**Why it's at-least-once.** The publisher marks `published_at` after the
broker ack. Crash in that window and it republishes. Producer idempotence
doesn't help — it dedupes broker retries within a session and knows
nothing about my database. So I get *effectively*-once by pairing
at-least-once delivery with idempotent consumers keyed
`(consumer_name, event_id)`.

**Partition keys as a correctness decision.** Trades key on
`portfolio_id`, market and news on `ticker`. That's what preserves per-key
ordering. And the consumer HPA maxes at 3 because the topic has 3
partitions — extra replicas would consume nothing.

**A bug I found and fixed.** (See the follow-ups below — this is your
strongest single answer.)

**What it isn't.** End-of-day data, not a live feed. Single-node kind lab,
not production Kubernetes. No metrics or alerting. Paper fills at the
daily close.

---

## Backend-focused version

Lead with correctness:

- One fill path (`apply_fill`) for both market orders and pending-order
  settlement — when they were separate, only one converted currency.
- Row lock **plus an ORM refresh**, because SQLAlchemy's identity map
  could hand back a pre-lock `cash_balance` and silently erase a
  concurrent debit.
- Validation before mutation, so a caught `InsufficientCash` leaves the
  session reusable and the settlement job can cancel one order and
  continue.
- A pure execution kernel (`evaluate_order`) with no Session, FX,
  settings, or wall clock — so fills are deterministic and testable, and
  every fill snapshots versioned provenance.
- Reservations: pending BUYs reserve cash, pending SELLs reserve shares,
  and a filling order can consume its own reservation but not another's.

---

## Infrastructure-focused version

- Ten processes, one image, per-workload commands. Migrations are a Job,
  not an initContainer, so five API replicas don't race on the schema.
- Liveness (`/live`) does **not** touch the database; readiness
  (`/health`) does and returns 503. If liveness probed Postgres, a blip
  would restart every API pod at once.
- The scheduler is `replicas: 1` **and** takes a Postgres advisory lock,
  because a rolling update can briefly run two pods — `replicas: 1` is
  approximately-one, not at-most-one.
- `maxUnavailable: 0` plus a PDB: the strategy covers deploys, the PDB
  covers node drains.
- Hardening: non-root, dropped capabilities, seccomp,
  `automountServiceAccountToken: false`.
- Honest gaps: no NetworkPolicies, base64 secrets in git for the lab, CPU
  autoscaling where lag would be correct.

---

## System-design version

Reframe as: *design a market-data ingestion and paper-trading system.*

| Requirement | Decision |
| --- | --- |
| Trades must be correct and immediately visible | Synchronous Postgres transaction, row locks |
| Market data is high-volume and provider-flaky | Async: outbox → Kafka → idempotent workers |
| Multiple consumers need the same events | Kafka consumer groups (analytics, sentiment, activity) |
| Ingest must survive retries | Natural key `(ticker, ts, interval)` + `ON CONFLICT` |
| Jobs must not double-fire | Advisory locks + single-replica scheduler |
| Providers must not block requests | Fetch outside the transaction, in a worker |

Then volunteer the trade-off: **at this volume a Postgres-backed job queue
would have been sufficient.** Kafka earns its place through consumer-group
fan-out and replay, not throughput. Saying this unprompted signals
judgement.

---

## Difficult follow-ups

### "Why did you build this?"
> To have one system where I'd made every layer's decisions myself —
> ledger correctness, event delivery, deployment — rather than a CRUD app
> with a queue bolted on. Paper trading was a good forcing function
> because money has invariants you can't hand-wave.

### "What was technically difficult?"
> Getting the transaction boundaries right across three processes. The
> rule that made it tractable: whatever you commit last is the thing you
> may repeat, so make repeating it safe. Outbox row commits with the
> ledger; `published_at` after the broker ack; database before the Kafka
> offset. Each one has a specific crash window, and the inbox key covers
> all of them.

### "What failed / what's your best bug?"
This is the strongest answer you have. Lead with it if given any opening:

> My Kafka dispatcher didn't commit the offset when a handler failed,
> which reads like a retry. But `poll()` advances the consumer's position
> whether or not you commit — so the next poll returned the *following*
> record, and once that one committed, the committed offset moved past the
> failed record and it was never redelivered. Silently dropped market bars,
> with a log line that said "offset not committed", which was true and
> gave exactly the wrong impression.
>
> Two things made it invisible: the only consumer tests needed a real
> broker, so the failure path had no coverage at all; and the symptom was
> *missing* data, which has no error to observe.
>
> I fixed it by seeking the partition back to the failed offset, and wrote
> a fake consumer that models the position/commit split so the regression
> is covered. It also made the docs true — they claimed a poison record
> stalls its partition, which is now actually what happens. The trade-off
> is deliberate: with no dead-letter topic, a loud stall beats a silent
> gap for financial data.

### "What would you redesign?"
> Observability first — there's no metrics or lag monitoring, so the
> failure mode above was invisible by construction. Then a dead-letter
> topic with bounded retries, so a poison record doesn't stall a
> partition. Then lag-based autoscaling instead of CPU.

### "How would you scale this 100×?"
> Partition `price_bars` by `ts`. PgBouncer, because with SQLAlchemy
> defaults each process holds ~15 connections and Postgres defaults to
> 100 — I'd hit that by scaling out, not by traffic. Read replicas for
> chart reads. More partitions **decided up front**, because rehashing a
> keyed topic breaks per-key ordering during the transition. And lag-based
> consumer autoscaling.

### "Why Postgres?"
> Multi-row invariants with an atomic decision point, plus row locking,
> constraints and rollback. And the constraints do real work: the
> `(ticker, ts, interval)` key is what makes ingest idempotent under
> at-least-once delivery.

### "Why no Redis?"
> Nothing needed it. Hot reads are precomputed into Postgres tables by
> scheduled jobs, the queue is the outbox, locks are Postgres advisory
> locks, and sessions are stateless JWTs. Adding Redis would have added a
> second consistency domain for no measured win. The honest cost is that
> my rate limiting is in-process, so with five API replicas the effective
> budget is 5×. If I added Redis, that's what I'd add it for — not caching.

### "Why Kafka, though? Isn't this over-engineered?"
> For the throughput, yes — a Postgres job queue would do. Kafka earns it
> on fan-out: three independent consumer groups read the same market
> events for different purposes, and I can replay history. I'd rather say
> that than pretend the volume justified it.

### "Why Kubernetes?"
> Ten processes with different scaling and failure characteristics, plus a
> strict singleton. Compose can run them; it can't express "never two
> replicas of this one", "scale these to the partition count", or
> "migrate once before anything starts". But it's a kind lab validated in
> CI — I'm not claiming production Kubernetes operations.

### "What concurrency problems exist?"
> Three, each solved differently: lost update on cash → row lock plus ORM
> refresh; two publishers claiming one outbox row → `SKIP LOCKED`; two
> schedulers double-firing settlement → advisory lock. Plus races I chose
> *not* to lock — first-portfolio creation is arbitrated by a unique
> constraint, and the loser re-reads the winner's row.

### "What reliability guarantees do you provide?"
> Trades are atomic and durable. Event delivery is at-least-once with
> effectively-once application via inbox keys. Consumers never write the
> ledger, so a duplicate can't move money. What I do **not** provide:
> exactly-once end-to-end, HA of any component, or bounded retry on a
> poison record.

### "What was your largest architecture mistake?"
> Building the async pipeline before any observability. The dropped-record
> bug existed because there was no lag metric, no alert, and no test on
> the failure path — the pipeline could fail silently by construction. I'd
> now treat "how will I know this is broken?" as part of shipping the
> component, not a later phase.

---

## Traps to avoid

| Don't say | Say instead |
| --- | --- |
| "Real-time market data" | "End-of-day bars; the live ticker is an explicitly labelled simulation" |
| "Exactly-once processing" | "At-least-once delivery, effectively-once application" |
| "Deployed on Kubernetes" | "Runs on a kind cluster validated in CI; Render and Vercel for hosting" |
| "Production-grade" | "Portfolio-grade with documented limitations" |
| "It's fully observable" | "Sentry and health endpoints; no metrics — that's my top gap" |
| "Handles millions of users" | "Benchmarked 100k events on one machine; here's where it'd break first" |

[KNOWN_LIMITATIONS.md](../KNOWN_LIMITATIONS.md) and
[RESUME.md](../RESUME.md#claim-boundaries) are the authority on claim
boundaries. Read both before an interview.
