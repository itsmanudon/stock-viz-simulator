# Indexes and key design

> **Before this note:** read [Schema and indexing](../../database/schema.md)
> — it lists every table and index. This note covers only the *reasoning*.
> **Source:** `apps/api/src/stockviz/models/`.

Four key-design decisions in this repository, each teaching a different
general principle.

## 1. Composite PK column order ≠ index column order

```python
# models/market.py — PriceBar
ticker, ts, interval          # primary key, in that order
Index("ix_price_bars_ticker_interval_ts", "ticker", "interval", "ts")
```

Every read is `WHERE ticker = ? AND interval = ? ORDER BY ts DESC`.

A btree index is only usable as a **leftmost prefix**. The PK's order
places `ts` in the middle, so `(ticker, interval)` equality cannot be
combined with an ordered `ts` range using the PK alone — Postgres would
filter and then sort. The extra index reorders so all three are consumed
in order: two equality columns, then the ordered one.

**The general rule:** equality columns first, range/sort column last.

The follow-up an interviewer will reach for: *"you index `ts` ascending
but query `DESC` — doesn't that need a second index?"* No. A btree is a
doubly linked structure and Postgres can scan it backwards at the same
cost. A separate `DESC` index is only needed for **mixed** orderings
(`ORDER BY a ASC, b DESC`).

## 2. Partial indexes for queue tables

```python
Index("ix_outbox_events_unpublished", "created_at",
      postgresql_where=text("published_at IS NULL"))
```

The publisher only ever asks for unpublished rows, oldest first. A full
index on `created_at` would grow with all history forever, even though
the pending set stays small.

A **partial index** contains only rows matching the predicate. So this
index is sized by the *backlog*, not by total events — publisher latency
is independent of how much history has accumulated.

**The general rule:** when a query always carries the same filter, put the
filter in the index. The classic cases are soft deletes (`WHERE deleted_at
IS NULL`) and exactly this — queue-in-a-table.

The trade-off: the planner must prove the query implies the predicate. A
query without `WHERE published_at IS NULL` cannot use it at all.

## 3. Natural vs surrogate keys

StockViz uses both, deliberately:

| Table | Key | Why |
| --- | --- | --- |
| `symbols` | `ticker` (natural) | Stable, meaningful, already unique; every FK reads better as `AAPL` than `4471` |
| `price_bars` | `(ticker, ts, interval)` (natural, composite) | The key **is** the identity of a bar — which is what makes upsert idempotent |
| `trades`, `positions`, `orders` | surrogate `id` | No stable natural key; a user can trade the same symbol repeatedly in a day |
| `consumer_inbox` | surrogate `id` + unique `(consumer_name, event_id)` | Constraint carries the meaning; the surrogate is just a handle |

The natural key on `price_bars` is doing real work: because the identity
of a bar is `(ticker, ts, interval)`, `ON CONFLICT DO UPDATE` makes
re-ingest a no-op. With a surrogate `id`, replaying a Kafka event would
insert a *second* bar for the same day, and the pipeline's at-least-once
delivery would become a data-corruption bug.

**The general rule:** if the domain has a true identity, a natural key
buys you idempotent writes for free. `symbols.ticker` shows the cost:
ticker changes (mergers, re-listings) are not modelled, because the
natural key can't express them.

## 4. Unique constraints as concurrency control

```python
portfolios.user_id      unique   # one portfolio per user
news_articles.url       unique   # global dedupe
consumer_inbox          unique (consumer_name, event_id)
portfolio_snapshots     unique (user_id, date)
```

Each replaces application logic with a database guarantee:

| Constraint | Replaces |
| --- | --- |
| `portfolios.user_id` | A lock around "check then create" |
| `news_articles.url` | A pre-read that would race anyway |
| `consumer_inbox` | Distributed coordination between consumer replicas |
| `(user_id, date)` | Making the daily NAV job re-runnable by hand |

**The general rule:** a check-then-act in application code is a race. If a
constraint can express the invariant, let the database arbitrate and
handle the violation — it cannot be bypassed by a future code path or a
manual write.

## What is missing

Honest gaps, worth naming before an interviewer finds them:

- **No index on `trades(portfolio_id, ts)`.** `portfolio_id` is indexed
  alone; trade history ordered by time will filter then sort. Fine at demo
  volume, the obvious first addition under load.
- **No covering / `INCLUDE` indexes.** Every index requires a heap fetch.
- **No partitioning.** `price_bars` is the candidate — range-partition by
  `ts` — but at a few dozen symbols it would be premature.
- **No query-plan evidence in the repo.** No `EXPLAIN ANALYZE` output is
  recorded, so index choices are reasoned rather than measured. Say that
  honestly.

## Interview questions

**Foundation — "When is an index not used?"**
> When the query can't use a leftmost prefix, when a function or implicit
> cast wraps the column, when the predicate doesn't imply a partial
> index's `WHERE`, or when the planner estimates a seq scan is cheaper —
> which is usually right on a small table.

**Strong SWE — "Your PK is `(ticker, ts, interval)` and you added an index on `(ticker, interval, ts)`. Redundant?"**
> No. Reads filter on ticker and interval and order by ts. The PK puts
> `ts` in the middle, so it can't serve equality-equality-then-ordered
> without a sort. The extra index reorders so all three columns are used.

**Strong SWE — "Why a partial index on the outbox?"**
> The publisher only ever queries `published_at IS NULL`. A partial index
> is sized by the backlog rather than by all history, so publish latency
> doesn't degrade as events accumulate.

**Advanced — "Why is `price_bars` keyed naturally instead of by an id?"**
> Because the key *is* the bar's identity, which makes the write
> idempotent via `ON CONFLICT`. My delivery is at-least-once, so a
> replayed event has to rewrite the same row rather than insert a second
> one. A surrogate key would have turned redelivery into duplicate market
> data.

**Advanced — "`price_bars` hits a billion rows. What do you do?"**
> Range-partition by `ts` so old partitions can be detached and archived
> and queries prune to recent ones. I'd drop the FK to `symbols` on the
> partitioned table, and expect the composite index to be rebuilt per
> partition. Before any of that I'd want `EXPLAIN ANALYZE` on the real
> access pattern — I don't have that evidence today.

## Memorise vs understand

**Memorise:** leftmost-prefix; equality-then-range; btrees scan backwards;
partial indexes need the predicate in the query.

**Understand:** why a natural key gives idempotent writes; why a unique
constraint beats a check-then-act; why an index that's right at demo scale
may be wrong at production scale.
