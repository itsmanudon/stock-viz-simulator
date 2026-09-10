# Interview-worthy code patterns

Small, real extracts from this repository. For each: what it does, why
it's built that way, the general concept, how it fails, and how to talk
about it.

Full context lives in the canonical docs — this note is about the code.

---

## 1. Transactional outbox enqueue

**Location:** `apps/api/src/stockviz/events/outbox.py::enqueue_event`

```python
def enqueue_event(session: Session, *, event_id, event_type, ..., envelope) -> OutboxEvent:
    """Stage one outbox row. Does not commit."""
    row = OutboxEvent(id=event_id, event_type=event_type, ..., payload=envelope)
    session.add(row)
    return row
```

**Why this way.** The entire pattern rests on the docstring: *does not
commit*. It joins whatever transaction the caller has open, so the event
row and the ledger mutation are one atomic unit.

**Concept.** Transactional outbox — solving dual-write without distributed
transactions.

**Runtime.** One INSERT, no I/O, no broker dependency. The FastAPI process
never imports the Kafka producer.

**How it could break.** If a future caller wrapped this in its own
`session.commit()`, the event would commit separately from the ledger and
the pattern would silently degrade to a dual write — with no test failure.
The `Does not commit` docstring is the only guard.

**Interview framing.** "The load-bearing property isn't what the function
does, it's what it *doesn't* do. Committing here would quietly reintroduce
the exact problem the outbox exists to solve."

---

## 2. `SKIP LOCKED` queue claim with a dialect fallback

**Location:** `events/outbox.py::claim_unpublished`

```python
bind = session.get_bind()
if bind is not None and bind.dialect.name == "postgresql":
    stmt = stmt.with_for_update(skip_locked=True)
```

**Why this way.** `SKIP LOCKED` lets N publishers claim disjoint batches
instead of blocking on each other. SQLite (used by fast unit tests) has no
such clause, so the dialect check degrades gracefully and the Postgres
semantics are covered separately in `tests/test_pg_outbox_claim.py`.

**Concept.** Queue-in-a-table; pessimistic locking without serialising
workers.

**Possible bug.** The fallback means unit tests exercise *different*
concurrency semantics than production. That's an accepted trade — fast
tests plus a real-Postgres test for the part that matters — but it must be
a conscious one.

**Interview framing.** "Plain `FOR UPDATE` would have made my publishers
serialise. `SKIP LOCKED` is what makes the outbox horizontally scalable."

---

## 3. Idempotent handler with a SAVEPOINT

**Location:** `events/inbox.py::try_record_processed`

```python
try:
    with session.begin_nested():          # SAVEPOINT
        session.add(ConsumerInbox(consumer_name=consumer_name, event_id=event_id))
        session.flush()
except IntegrityError:
    return False
return True
```

**Why this way.** The unique constraint is the real guard against
duplicate processing. But an `IntegrityError` on the *outer* transaction
would abort everything — including the domain work this is protecting. The
SAVEPOINT scopes the failure so only the insert rolls back.

**Concept.** Idempotency keys; nested transactions; letting the database
arbitrate a race.

**Interview framing.** "The check-then-insert pair looks redundant, but
the read is only an optimisation — two workers can both pass it. The
constraint decides, and `begin_nested` is what stops the loser's failure
from taking down the winner's work."

---

## 4. The auth bridge

**Location:** `apps/web/lib/api/server.ts` + `apps/api/src/stockviz/auth.py`

```ts
import "server-only";                       // build error if imported client-side

async function mintToken(userId: string) {
  return new SignJWT({ sub: userId })
    .setProtectedHeader({ alg: "HS256" })
    .setExpirationTime("60s")
    .sign(signingKey());
}
```

```python
payload = jose_jwt.decode(token, settings.internal_api_token, algorithms=["HS256"])
return int(payload["sub"])
```

**Why this way.** It replaced an `X-Internal-Token` + `X-User-Id` header
pair. With headers, anyone who obtained the shared token could impersonate
**any** user by changing a header. As a signed claim, the user id is
covered by the signature and cannot be altered without the secret.

**Three deliberate details:**
- `import "server-only"` makes leaking the secret to the browser a *build*
  error, not a code-review responsibility.
- 60-second expiry bounds the replay window.
- `algorithms=["HS256"]` is pinned — omitting it is the classic JWT `alg`
  confusion vulnerability.

**Concept.** Symmetric-signed service-to-service tokens; capability vs
identity.

**Interview framing.** "The upgrade wasn't adding auth — it was moving the
user id from an attacker-controlled header into a signed claim."

---

## 5. Pessimistic lock that refreshes the ORM cache

**Location:** `services/trading/execute.py::apply_fill` → `lock_portfolio`

```python
portfolio = lock_portfolio(session, portfolio_id)   # FOR UPDATE + refresh
spendable = available_cash(session, portfolio, exclude_order_id=exclude_order_id)
if spendable < usd_cost:
    raise InsufficientCash(...)                     # nothing mutated yet
```

**Why this way.** Two things:
1. The **refresh** defeats SQLAlchemy's identity map. Without it the
   in-memory `cash_balance` could predate the lock, and writing it back
   would erase a concurrent debit.
2. Validation happens **before** any mutation, so a caller that catches
   `InsufficientCash` can keep using the same session — which is what lets
   the settlement job cancel one bad order and carry on with the rest.

**Concept.** Lost update; pessimistic concurrency; ORM caches as a
correctness hazard.

**Interview framing.** "Taking the lock wasn't enough. The ORM sat between
the lock and the value, so I had to refresh the instance as part of
acquiring it."

---

## 6. Rewind-on-failure

**Location:** `events/dispatcher.py::_rewind`

```python
def _rewind(consumer: ConfluentBrokerConsumer, msg: object) -> None:
    try:
        consumer.seek(msg)
    except Exception:
        logger.exception("failed to rewind partition; record may be skipped until restart")
```

**Why this way.** Not committing an offset does not mean "retry" —
`poll()` has already advanced the position. Without the seek, the record
is skipped and lost as soon as a later offset commits. The `try/except` is
deliberate: a seek failure must degrade to the old behaviour rather than
kill the worker loop.

**Concept.** Consumer position vs committed offset; failing loudly instead
of silently.

**Interview framing.** See
[failure scenarios §2](../distributed-systems/failure-scenarios.md).

---

## 7. Advisory lock decorator

**Location:** `scheduler.py::single_instance` / `_advisory_key`

```python
def _advisory_key(job_id: str) -> int:
    digest = hashlib.sha256(job_id.encode("utf-8")).digest()[:8]
    return int.from_bytes(digest, "big", signed=True)
```

**Why this way.** `pg_try_advisory_lock` needs a signed 64-bit integer, so
a job name is hashed and truncated. `try_` is non-blocking: a second
scheduler **skips** rather than queueing to run the job late — for order
settlement, running late is worse than not running.

**Concept.** Distributed mutual exclusion using an existing dependency
rather than a new one (no ZooKeeper, no Redis lock).

**Nuance worth raising.** Advisory locks are session-scoped and release on
disconnect, so a crashed scheduler doesn't deadlock the job. That
auto-release is exactly what a naive `locks` table would get wrong.

---

## 8. Rate-limit key selection

**Location:** `limiter.py::client_key`

```python
def client_key(request: Request) -> str:
    user = _user_id_from_authorization(request)      # opportunistic decode
    if user is not None:
        return user
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return f"ip:{forwarded.split(',')[0].strip()}"
    return f"ip:{get_remote_address(request)}"
```

**Why this way.** `get_remote_address` alone returns the *proxy's* address
behind a load balancer — one global bucket for every user on the planet.
The fallback chain fixes that. The JWT decode is opportunistic and never
raises, because rate limiting runs before the auth dependency; real
verification still happens in `auth.py`.

**Also worth knowing** (from the same module's docstring): slowapi reads
`RATELIMIT_ENABLED` itself and keeps the **raw string**, so the documented
`RATELIMIT_ENABLED=0` left `limiter.enabled == "0"` — truthy — and the
limiter stayed on. The module parses the flag and assigns a real bool
after construction.

**Honest limitation.** slowapi's default storage is in-memory, so limits
are **per-process**. With the API HPA at `maxReplicas: 5` the real budget
is up to 5×. See [ADR-0004](../../adr/ADR-0004-no-redis.md).

**Interview framing.** "Two bugs in one small module: a key that
collapsed every user into one bucket, and a feature flag that was a
truthy string. Both only show up under real deployment conditions."

---

## 9. Provider I/O outside the transaction

**Location:** `workers/market_ingest_consumer.py::process_payload`

```python
bars = fetch_bars_for_event(event)      # network I/O — no transaction open
with Session(engine) as session:        # transaction opens only now
    result = persist_market_refresh(session, event, bars)
    session.commit()
```

**Why this way.** A provider call can take seconds or hang. Holding a
Postgres transaction across it would pin a connection and, at scale,
exhaust the pool — see
[the runbook](../../operations/runbooks/postgres-connections.md).

**Concept.** Keeping transactions short; separating I/O from persistence.

**Structural support.** The dispatcher offers `process` (runs outside a
session) *and* `handlers` (runs inside one), and enforces exactly one:

```python
if (process is None) == (handlers is None):
    raise ValueError("provide exactly one of handlers or process")
```

**Interview framing.** "Transaction duration is a shared resource. A
worker that opens a transaction and then calls a third party is
borrowing a connection for as long as that third party feels like taking."

---

## 10. Chunked bulk upsert

**Location:** `services/ingest/prices.py::upsert_bars`

```python
UPSERT_CHUNK_ROWS = 1000
for start in range(0, len(rows), UPSERT_CHUNK_ROWS):
    chunk = rows[start:start + UPSERT_CHUNK_ROWS]
    stmt = pg_insert(PriceBar).values(chunk)
```

**Why this way.** `price_bars` binds 9 parameters per row and Postgres
caps a statement at **65535** bind parameters — about 7280 rows. A
full-history yfinance fetch is ~11k bars, so a single statement failed
outright.

**Concept.** Protocol limits as a real constraint; batch sizing.

**Interview framing.** "A bug you only hit with real data volume. The
fix is trivial; the lesson is that the wire protocol has limits your ORM
won't warn you about."
