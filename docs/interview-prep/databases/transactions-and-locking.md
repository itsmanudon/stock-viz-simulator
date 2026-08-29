# Transactions, locking, and concurrency

> **Before this note:** read [Schema and indexing](../../database/schema.md)
> and [Request lifecycle §1](../../architecture/request-lifecycle.md).
> **Source:** `services/trading/execute.py`, `services/trading/orders.py`,
> `scheduler.py::single_instance`, `tests/test_pg_concurrency.py`.

StockViz models money, so this is where correctness is decided.

## The invariant

A BUY must, atomically:
1. verify **available** cash (balance − other pending orders' reservations),
2. debit cash,
3. create or update the position with a new weighted-average cost,
4. insert the trade,
5. stage the outbox event.

Any interleaving that lets two requests both pass step 1 before either
does step 2 produces a **double spend**.

## Pattern 1 — pessimistic lock with an identity-map refresh

```python
# services/trading/execute.py::apply_fill
portfolio = lock_portfolio(session, portfolio_id)   # SELECT … FOR UPDATE
spendable = available_cash(session, portfolio, exclude_order_id=...)
if spendable < usd_cost:
    raise InsufficientCash(...)
portfolio.cash_balance = (portfolio.cash_balance - usd_cost).quantize(MICROS)
```

`lock_portfolio` takes the row lock **and refreshes the instance**. The
refresh is the subtle part, and it is ORM-specific:

> SQLAlchemy's identity map caches objects per session. If the portfolio
> was loaded *before* the lock was taken, `portfolio.cash_balance` is a
> pre-lock value. Writing it back overwrites whatever the concurrent
> transaction committed in between — a **lost update**, and a lock that
> looks correct while doing nothing.

This is a genuinely good interview story: the lock alone was not enough,
because the ORM sat between the lock and the value.

`tests/test_pg_concurrency.py` covers it against real Postgres — SQLite
cannot exercise `FOR UPDATE`.

### Why pessimistic and not optimistic

| | Fit |
| --- | --- |
| Pessimistic (chosen) | Contention on one portfolio is *self*-contention — a single user's own orders. Serialising them is desirable. Blocking is bounded and short |
| Optimistic (version column) | Better for low contention across many rows. Here it would mean retry loops on a hot row, and a user seeing spurious conflicts on their own actions |

The contention profile decides it: **conflicts are rare across users and
expected within a user.**

## Pattern 2 — let a unique constraint arbitrate

```python
user_id: int = Field(foreign_key="users.id", unique=True, index=True)
```

`ensure_default_portfolio` runs on the first `/v1/portfolio` request, so
two concurrent first requests race. Rather than lock pre-emptively, the
unique index decides: the loser catches the violation and re-reads the
winner's row.

The general rule this illustrates: **lock when an invariant spans rows;
use a constraint when it does not.** A constraint is cheaper, cannot be
forgotten by a future code path, and is enforced even by a direct `psql`
write.

## Pattern 3 — `FOR UPDATE SKIP LOCKED` for queue claims

```python
stmt = select(OutboxEvent).where(OutboxEvent.published_at.is_(None)) \
       .order_by(OutboxEvent.created_at).limit(limit)
if bind.dialect.name == "postgresql":
    stmt = stmt.with_for_update(skip_locked=True)
```

Plain `FOR UPDATE` would make a second publisher **block** on rows the
first holds — serialising the publishers. `SKIP LOCKED` makes it *skip*
to unlocked rows, so N publishers get disjoint batches and scale
linearly. This is the canonical queue-in-a-table idiom.

Note the dialect check: SQLite has no `SKIP LOCKED`, so unit tests fall
back to a plain select and the Postgres behaviour is covered separately in
`tests/test_pg_outbox_claim.py`. Being explicit about *which* semantics
your fast tests do not cover is a good habit to be able to describe.

## Pattern 4 — advisory locks for job mutual exclusion

```python
# scheduler.py
def _advisory_key(job_id: str) -> int:
    digest = hashlib.sha256(job_id.encode()).digest()[:8]
    return int.from_bytes(digest, "big", signed=True)
```

`pg_try_advisory_lock` is a **session-scoped, application-defined** lock
tied to no row. `try_` makes it non-blocking: a second scheduler skips the
job rather than queueing to run it late.

Two details worth knowing:
- The key must be a signed 64-bit int, hence the hash-and-truncate.
- The lock releases automatically when the backend disconnects, so a
  crashed scheduler does not deadlock the job forever.

Why this exists at all: APScheduler fires in-process, so on Render with
`ENABLE_SCHEDULER=true` two API instances would both fire order
settlement. See
[the Kubernetes note](../kubernetes/stockviz-to-kubernetes.md#why-the-scheduler-cannot-scale).

## Transaction boundaries — who commits

| Function | Commits? | Why |
| --- | --- | --- |
| `apply_fill` | **No** | So the settlement job can batch many fills in one transaction |
| `execute_trade` | Yes | It is the request's unit of work |
| `enqueue_*` (outbox) | No | Must join the caller's transaction — that is the whole pattern |
| `persist_market_refresh` and other handlers | No | The dispatcher owns the boundary, and must commit before the Kafka offset |

**The rule:** the layer that *owns* the unit of work commits; helpers
never do. Getting this wrong is how an outbox row ends up committed
separately from its ledger mutation, which silently reintroduces the
dual-write problem the pattern exists to prevent.

## Isolation level

Everything runs at PostgreSQL's default **READ COMMITTED**. StockViz does
not rely on `REPEATABLE READ` or `SERIALIZABLE`; it takes explicit locks
instead. That is the pragmatic choice — explicit `FOR UPDATE` is easier to
reason about and does not force retry handling for serialization failures.

Worth knowing for the follow-up: under READ COMMITTED, each statement sees
a fresh snapshot, which is exactly why the identity-map refresh in
`lock_portfolio` matters — the lock gives you the current row, but only if
you actually re-read it.

## Interview questions

**Foundation — "What does `SELECT … FOR UPDATE` do?"**
> Takes a row-level exclusive lock held to end of transaction. Other
> transactions wanting the same row block until commit or rollback.

**Strong SWE — "You have a lock and still had a lost update. How?"**
> The ORM identity map. The object was loaded before the lock, so the
> in-memory `cash_balance` predated the concurrent commit; writing it back
> clobbered that commit. The fix is refreshing the instance as part of
> taking the lock — which is what `lock_portfolio` does.

**Strong SWE — "Why `SKIP LOCKED` on the outbox?"**
> So publishers scale. Plain `FOR UPDATE` would block a second publisher
> on the first's rows, serialising them. `SKIP LOCKED` hands each a
> disjoint batch.

**Advanced — "Why not serialise everything with SERIALIZABLE?"**
> It would work, and it would push failure into serialization errors that
> every call site has to retry. My contention is concentrated on one row
> per user, so an explicit row lock is cheaper, more predictable, and
> local to the code that needs it.

**Advanced — "Two users buy the same stock simultaneously. Contention?"**
> None. They lock different `portfolios` rows; there's no shared mutable
> state — `price_bars` is read-only on that path. Contention only appears
> within a single portfolio, where serialising is the desired behaviour.

## Memorise vs understand

**Memorise:** `FOR UPDATE` blocks, `SKIP LOCKED` skips; advisory locks are
session-scoped and auto-release; READ COMMITTED is the default.

**Understand:** why an ORM cache can defeat a correct lock; when a
constraint beats a lock; why helpers must not commit.
