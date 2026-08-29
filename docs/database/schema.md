# Schema and indexing

PostgreSQL is the system of record for every domain object. Models live in
`apps/api/src/stockviz/models/`, one file per resource; migrations are
Alembic revisions under `apps/api/migrations/versions/`.

The entity map is maintained in
[apps/api/CLAUDE.md](../../apps/api/CLAUDE.md#data-model--the-load-bearing-relationships).
This document covers what that map does not: **why the keys are shaped the
way they are, which indexes serve which query, and what breaks at scale.**

## The tables that carry the design

### `price_bars` — the one that matters most

```python
# models/market.py
ticker:   str      primary_key, FK symbols.ticker
ts:       datetime primary_key
interval: str      primary_key           # "1d" today
__table_args__ = (Index("ix_price_bars_ticker_interval_ts",
                        "ticker", "interval", "ts"),)
```

| Question | Answer |
| --- | --- |
| Why is `interval` in the PK? | So `1h` bars can be added later without a schema migration. Only `1d` is written today. |
| What does the PK guarantee? | One bar per `(ticker, ts, interval)`. This is what makes ingest **idempotent** — a replayed Kafka event upserts identical rows instead of duplicating history. |
| Why a separate index when the PK already covers those columns? | Reads are `WHERE ticker = ? AND interval = ? ORDER BY ts DESC`. The PK's column order is `(ticker, ts, interval)`, which cannot serve that without a sort. The explicit index reorders to `(ticker, interval, ts)`. Postgres scans a btree in either direction, so ascending covers `DESC`. |
| What gets slow? | Row count grows as `symbols × trading days`. At a few dozen symbols this is trivial. At thousands of symbols × intraday intervals it becomes the obvious partition candidate — range-partition by `ts`, or move to a time-series extension. |

**Interview-worthy:** the comment in `models/market.py` explaining why the
PK is not enough is exactly the reasoning an interviewer wants to hear
about composite-index column order.

### `outbox_events` — the partial index

```python
Index("ix_outbox_events_unpublished", "created_at",
      postgresql_where=text("published_at IS NULL"))
```

The publisher only ever queries unpublished rows, oldest first. A full
index on `created_at` would grow forever; the **partial** index contains
only pending rows, so it stays small no matter how much history
accumulates. This is the right shape for any queue-in-a-table.

The claim query uses `FOR UPDATE SKIP LOCKED`
(`events/outbox.py::claim_unpublished`) so two publisher processes never
contend for the same row. SQLite has no `SKIP LOCKED`, so the code checks
the dialect and degrades to a plain `SELECT` for unit tests — the
Postgres behaviour is covered separately in `tests/test_pg_outbox_claim.py`.

### `consumer_inbox` — the idempotency key

```python
UniqueConstraint("consumer_name", "event_id", name="uq_consumer_inbox_name_event")
```

Identity is `(consumer_name, event_id)`, not `event_id` alone — each
consumer group processes the same event independently, so
`market_analytics` seeing an event must not stop `sentiment_aggregate`
from seeing it.

`try_record_processed` inserts inside `session.begin_nested()` (a
SAVEPOINT) and catches `IntegrityError`. The savepoint matters: without
it, a constraint violation would poison the whole outer transaction. The
**constraint** is the guard; the `already_processed` read before it is
only a cheap short-circuit that avoids wasted work.

### `portfolios` — one per user, enforced by the database

```python
user_id: int = Field(foreign_key="users.id", unique=True, index=True)
```

`ensure_default_portfolio` is called on the first `/v1/portfolio` request,
so two concurrent first requests race. Rather than locking pre-emptively,
the unique index arbitrates: the loser catches the violation and re-reads
the winner's row. Let the database decide the race — see
`tests/test_pg_concurrency.py`.

### `portfolio_snapshots` — note the parent

```python
UniqueConstraint("user_id", "date", name="uq_portfolio_snapshots_user_date")
```

**Gotcha:** snapshots hang off `users`, not `portfolios`. The
`(user_id, date)` uniqueness makes the daily NAV job idempotent — re-running
it for the same day updates rather than duplicating.

### `news_articles` — dedupe by URL

`url` is globally unique (`max_length=1024`). Re-ingesting the same
article from a second query or a retried event is a no-op. `ticker` is
nullable because general-market news is not tied to one symbol.

### `news_sentiment` — one row per `(article_id, model)`

Storing the model in the key means re-scoring with a new model adds a row
instead of destroying the old verdict. `news_articles.sentiment` stays as
a denormalised "current best" label that the badge reads — a deliberate
denormalisation to avoid a join on every list render.

## Money columns

Every monetary and quantity column is `Numeric(18, 6)`, never float.
`volume` is `BigInteger`. Prices on `trades` are in the **symbol's native
currency**; cash is **always USD**, converted at
`fx_rates.usd_rate` (USD per one unit, forward-filled over weekends).
Mixing those two up is the bug the codebase warns about most.

## Concurrency

| Mechanism | Where | Guards |
| --- | --- | --- |
| `SELECT … FOR UPDATE` + refresh | `lock_portfolio` | Lost update on `cash_balance` |
| `FOR UPDATE SKIP LOCKED` | `claim_unpublished` | Two publishers claiming one row |
| `pg_try_advisory_lock` | `scheduler.py::single_instance` | Two schedulers double-firing a money job |
| Unique constraint | `portfolios.user_id`, `consumer_inbox` | Races the app does not need to serialise |
| `SELECT … FOR UPDATE` | replay `advance` | Two clients advancing one replay clock |

The pattern to notice: **locks where an invariant spans rows, unique
constraints where it does not.**

## Connection pooling

`db.py` creates one engine with `pool_pre_ping=True` and otherwise
SQLAlchemy defaults (pool size 5, max overflow 10 — so ~15 connections per
process). With the API HPA at `maxReplicas: 5` plus scheduler, publisher,
and six consumers, worst-case connection demand is well over a hundred.
Postgres defaults to `max_connections = 100`. There is no PgBouncer in
this repo. See
[the runbook](../operations/runbooks/postgres-connections.md).

## Migrations

`alembic revision --autogenerate -m "..."` then **review the file** —
SQLModel metadata is not always right about indexes and relationships.
Parallel branches produce multiple heads; resolve with
`alembic merge heads`. Kubernetes runs migrations as a Job
(`infra/k8s/base/migrate/migrate-job.yaml`) so API replicas never migrate;
Render runs `alembic upgrade head` in the container's default command.

## What would need to change at 100×

| Pressure | First move |
| --- | --- |
| `price_bars` row count | Range-partition by `ts`; drop the FK to `symbols` on the partitioned table |
| Connection count | PgBouncer in transaction mode |
| Read load on charts | Read replica, or cache the latest-close lookup |
| `outbox_events` history | Periodic archival of published rows — the partial index already keeps writes cheap |
| Leaderboard/NAV queries | They already read the precomputed `portfolio_snapshots`, which is the right shape |
