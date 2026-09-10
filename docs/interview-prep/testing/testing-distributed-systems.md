# Testing a distributed pipeline

> **Before this note:** read [Testing strategy](../../testing/strategy.md).
> **Source:** `tests/conftest.py`, `tests/pg_scratch.py`,
> `tests/test_dispatcher_retry.py`, `.github/workflows/ci.yml`.

"How do you test a system with a database, a broker, and six workers?" is
a standard question, and StockViz has a real answer plus a real failure to
learn from.

## The speed/fidelity ladder

```
SQLite in-memory  →  real Postgres  →  real Kafka  →  browser  →  kind cluster
   ~600 tests          ~9 tests         ~5 tests      Playwright   smoke
   ~25 seconds         seconds          seconds       minutes      minutes
```

The principle: **run most tests at the cheapest tier that can express the
property, and re-test at a higher tier only what the cheap tier
structurally cannot.**

What SQLite structurally cannot express here: `FOR UPDATE`,
`SKIP LOCKED`, `ON CONFLICT` upsert semantics, advisory locks, partial
indexes, `JSONB`, and real concurrency. Every one of those has a
Postgres-tier test.

## The trap this repository actually fell into

A skipped test looks identical to a passing test in a summary line.

```
609 passed, 10 skipped
```

Those 10 skips are `DATABASE_URL is not PostgreSQL` — the Postgres and
Kafka tiers. Locally they never run. CI supplies both services, so they do
run there, and `STOCKVIZ_KAFKA_REQUIRED=1` converts a missing broker from
a skip into a failure.

But the dispatcher's **failure path** had no test at any tier. Its only
coverage would have come from the Kafka integration suite, which skips
locally — so a silent data-loss bug lived in the consumer loop unnoticed
([ADR-0005](../../adr/ADR-0005-rewind-on-handler-failure.md)).

**The lesson worth carrying into an interview:** wherever a tier skips,
assume the code is untested until proven otherwise. "It's covered by
integration tests" is only true if those tests actually run.

## Fakes that model semantics, not mocks that record calls

The fix's regression test needed to prove something subtle: that a failed
record is *skipped* rather than retried. A mock asserting `seek()` was
called would have tested the implementation, not the bug.

Instead, `test_dispatcher_retry.py` uses a fake that models the real
consumer's state machine:

```python
def poll_json(self, timeout):
    msg, payload = self._messages[self.position]
    self.position += 1        # advances whether or not we commit — like librdkafka
    return msg, payload

def commit(self, msg):  self.committed.append(msg.offset() + 1)
def seek(self, msg):    self.position = msg.offset()
```

Because the fake reproduces the **position/commit split**, the test can
assert the thing that actually matters:

```python
assert seen == [0, 0, 1]        # record 0 retried before record 1
assert consumer.committed == [1, 2]
```

Without the fix this fails with `committed == [2]` — proving offset 0 was
skipped forever.

This is the general principle: **a fake that models the dependency's
semantics catches design bugs; a mock that records calls only catches
refactors.** The `BrokerPublisher` / `BrokerConsumer` Protocols exist to
make such fakes injectable without librdkafka.

## Testability as an architectural property

Several StockViz decisions are testability decisions in disguise:

| Decision | Testing payoff |
| --- | --- |
| Pure execution kernel (no Session, FX, clock) | `test_execution_engine.py` needs no fixtures — inputs and expected `FillDecision`s |
| Injectable provider callables | Fixtures instead of `httpx` monkeypatching |
| Handlers stage writes but don't commit | A test controls the transaction boundary |
| `process` vs `handlers` split in the dispatcher | Provider I/O can be tested without a database |
| Every scheduled job has a CLI twin | Jobs are invokable without a scheduler |

If code is hard to test, that is usually a message about coupling. The
kernel's purity rule — no Session, FX, settings, Kafka, or wall-clock
reads — is enforced precisely so it stays trivially testable.

## Drift guards: tests that aren't about behaviour

Two CI steps catch a class of bug that unit tests structurally cannot:

- **`alembic check`** — a model changed but nobody generated a migration.
  `dev` once carried two Alembic heads and six columns of enum drift,
  invisible until deploy.
- **OpenAPI type sync** — regenerates the web client's `schema.d.ts` and
  fails on a diff, so an API contract change that nobody mirrored breaks
  the build instead of surfacing at runtime.

Both are *consistency* checks between artefacts, and both exist because of
real incidents. Worth citing — most candidates only discuss test pyramids.

## What is still missing

| Gap | What it would catch |
| --- | --- |
| Chaos / failure injection | Broker loss, Postgres loss, partial failures mid-transaction |
| Load testing | Connection-pool exhaustion, lock contention under concurrency |
| Property-based tests | FX rounding, kernel invariants across generated inputs |
| Mutation testing | Assertions that pass regardless of behaviour |
| Coverage threshold | Coverage is reported, not enforced |

## Interview questions

**Foundation — "How do you test code that depends on a database?"**
> Cheapest tier that expresses the property. Most tests use in-memory
> SQLite with dependency overrides; anything depending on Postgres-specific
> behaviour — row locks, `SKIP LOCKED`, upserts — gets a scratch Postgres
> database, because SQLite can't express those at all.

**Strong SWE — "How do you test a Kafka consumer without a broker?"**
> Put a Protocol at the boundary and inject a fake. The important part is
> that the fake models the real semantics — position advancing on poll
> independently of commits — because that split *is* where the bug lives.
> A mock that records `seek()` calls would have tested my implementation
> rather than the behaviour.

**Strong SWE — "Your suite says 609 passed, 10 skipped. Is that good?"**
> It's honest but incomplete. The skips are the Postgres and Kafka tiers,
> which only run in CI. A skip reads like a pass in the summary, and that's
> exactly how a data-loss bug survived in my consumer loop — its only
> possible coverage was in a tier that skips locally.

**Advanced — "How would you test that your outbox is actually atomic?"**
> Force a failure between the ledger write and the commit, and assert
> neither the trade nor the outbox row exists. Then force one between the
> broker ack and the `published_at` update, and assert the row republishes
> and the consumer's inbox makes it a no-op. The second needs real
> infrastructure and a fault-injection point — which is the chaos-testing
> gap I don't have today.

**Advanced — "Coverage is 85%. What does that tell you?"**
> That 15% never executed. It says nothing about whether the 85% has
> meaningful assertions — mutation testing would answer that. In this
> repository the dispatcher's failure path was *executed* by integration
> tests in CI, but no test asserted the record was retried, so the bug
> passed straight through.
