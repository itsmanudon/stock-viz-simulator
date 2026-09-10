# Testing strategy

StockViz runs **620 API tests**, a web unit suite, Playwright e2e, and a
kind + Strimzi smoke deployment. The organising idea is a **speed/fidelity
ladder**: most tests run in-memory in seconds, and the properties that
in-memory cannot express are re-tested against real infrastructure.

## The ladder

| Tier | Runs against | Count | Runtime | Catches |
| --- | --- | --- | --- | --- |
| Unit / router | SQLite in-memory | ~600 | ~25 s | Logic, HTTP contracts, domain rules |
| Postgres-backed | Real Postgres (scratch DB) | ~9 | seconds | Row locks, `SKIP LOCKED`, migrations |
| Kafka integration | Real broker + Postgres | ~5 | seconds | Outbox → broker → consumer, inbox dedupe |
| Web unit | Vitest | — | — | Components, formatting, client logic |
| E2E | Built web + live API + Postgres | — | minutes | User journeys through the real stack |
| K8s smoke | kind + Strimzi | — | minutes | Manifests, probes, migration Job, scaling |

Locally, `uv --directory apps/api run pytest` runs the first tier and
**skips** the Postgres/Kafka tiers with an explicit reason
(`DATABASE_URL is not PostgreSQL`). CI supplies both services, so nothing
is skipped there.

## Tier 1 — in-memory, per-test isolation

`tests/conftest.py` gives each test a fresh SQLite engine:

```python
eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                    poolclass=StaticPool)
SQLModel.metadata.create_all(eng)
```

`StaticPool` is required, not cosmetic: SQLite's in-memory database is
per-connection, so without it the TestClient's connection would see a
different (empty) database than the fixture's.

The `client` fixture overrides FastAPI's `get_session` dependency so the
app and the test share one session. That is what makes router tests
transactionally coherent without a real database.

`conftest` also sets `RATELIMIT_ENABLED=0` at import time, **before**
`stockviz.main` is imported — the limiter reads it at construction.

### What tier 1 cannot test

Being explicit about this is the point of the ladder:

| Property | Why SQLite can't |
| --- | --- |
| `SELECT … FOR UPDATE` | No row locks |
| `FOR UPDATE SKIP LOCKED` | Not supported — `claim_unpublished` checks the dialect and degrades |
| `ON CONFLICT DO UPDATE` on a composite key | Different semantics from Postgres' upsert |
| `pg_try_advisory_lock` | Postgres-only |
| Partial indexes, `JSONB` | Postgres-only |
| Real concurrency | One shared connection |

Each of these has a tier-2 test. The rule: **when production behaviour
depends on Postgres, the fast test is not evidence.**

## Tier 2 — real PostgreSQL

`tests/pg_scratch.py` creates a throwaway database per test run, applies
the schema, yields an engine, then terminates connections and drops it.

Two details worth noting:

- It **skips only when `DATABASE_URL` is absent or non-Postgres.**
  Connection or DDL failures propagate as errors. A test infrastructure
  that silently skips on failure is worse than no test — it reports green
  for a suite that never ran.
- `str(sqlalchemy.engine.URL)` masks the password as `***`, so engines are
  built from the URL object rather than its string form. That is a real
  bug this harness already had to fix.

Covered here: `test_pg_concurrency.py` (lost update on cash, first-portfolio
race), `test_pg_outbox_claim.py` (`SKIP LOCKED`),
`test_pg_replay_concurrency.py`, and the migration tests.

## Tier 3 — real Kafka

`test_kafka_integration.py` runs the full path: enqueue outbox → publish →
consume → assert the domain write and the `consumer_inbox` receipt.

It skips when no broker is reachable, but CI sets
`STOCKVIZ_KAFKA_REQUIRED=1`, which turns a missing broker into a failure
rather than a skip. That flag is what stops the integration tier from
silently disappearing.

## Notable test-design choices

**Injectable provider I/O.** `services/ingest/prices.py` takes a callable
for the network step, so tests pass fixtures rather than monkeypatching
`httpx`. Same in `market_ingest_consumer.fetch_bars_for_event`, whose
docstring says "Tests monkeypatch this."

**No real network calls in tests**, ever. Mock at the httpx layer.

**The execution kernel is pure**, so `test_execution_engine.py` needs no
database, no clock, and no fixtures — just inputs and expected
`FillDecision`s. That purity is a testability decision as much as an
architectural one.

**Fake broker clients over mocks.** `BrokerPublisher` and `BrokerConsumer`
are Protocols precisely so tests can inject a fake without librdkafka.
`test_dispatcher_retry.py`'s fake consumer *models the real semantics* —
`poll_json` advances a position, `commit` records `offset + 1`, `seek`
moves the position back — which is how it can prove a record was skipped.
A mock asserting "seek was called" would not have caught the original bug.

## CI

`.github/workflows/ci.yml` runs six jobs:

| Job | What it adds beyond the tiers above |
| --- | --- |
| `web` | Lint, typecheck, unit tests, build — **and an OpenAPI type-sync check** |
| `api` | Ruff lint + format, pyright, `uv lock --check`, pytest with coverage, **`alembic check`** |
| `events-integration` | Postgres + Kafka tiers in isolation |
| `security` | `pnpm audit --audit-level high --prod` and `pip-audit` on the locked set |
| `docker` | Both images build |
| `e2e` | Migrate + seed + backfill + recommend, start API, build web, run Playwright |

Two of these are drift guards rather than tests, and they exist because of
real incidents:

- **`alembic check`** catches a model change that never got a migration.
  `dev` once carried two Alembic heads and six columns of enum drift,
  invisible until deploy.
- **OpenAPI type sync** regenerates `apps/web/lib/api/schema.d.ts` and
  fails on a diff, so a backend schema change that nobody mirrored into
  the client breaks the build instead of surfacing at runtime.

`.github/workflows/k8s-smoke.yml` stands up kind + Strimzi, runs the
migration Job, smoke-tests the deployment, and runs a reduced Kafka
benchmark.

## Known gaps

Honest, and worth reading before claiming coverage:

| Gap | Consequence |
| --- | --- |
| Thin e2e path | Playwright covers markets, signup, research, an equity buy, and the trading loop — not every option, backtest, screener, or leaderboard path |
| No load testing | Financial and provider paths have never been run under sustained load |
| No mutation testing | Coverage percentage is not evidence that assertions are meaningful |
| No property-based tests | The execution kernel and FX conversion are natural candidates |
| No chaos/failure-injection in CI | Broker loss, Postgres loss, and partial failures are reasoned about, not exercised |
| Coverage is reported, not enforced | No minimum threshold gate |

The dispatcher bug ([ADR-0005](../adr/ADR-0005-rewind-on-handler-failure.md))
came from the first row of that table's underlying cause: a code path whose
only tests required infrastructure that local runs skip. Where a tier
skips, assume the code is untested until proven otherwise.

## Adding a test — which tier?

```
Does it depend on Postgres-specific behaviour?   → tier 2 (pg_scratch)
Does it cross the broker?                        → tier 3 (kafka integration)
Does it need a browser?                          → Playwright
Otherwise                                        → tier 1 (SQLite + fixtures)
```

For a new resource, follow the chain in
[apps/api/CLAUDE.md](../../apps/api/CLAUDE.md#adding-a-feature-end-to-end):
`test_<resource>_router.py` plus service-level tests.
