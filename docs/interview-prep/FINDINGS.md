# Findings

Engineering issues found while building this curriculum. Each is
classified, and resolved into a **fix**, a **test**, **documentation**, or
a tracked follow-up. Resolved entries stay for the record but are marked;
this file is not an unbounded dump.

Severity: Critical · High · Medium · Low · Improvement
Category: correctness · reliability · performance · security ·
maintainability · observability · scalability · data quality ·
architecture · developer experience

---

## Resolved

### F-001 — Failed Kafka records were silently dropped ✅ FIXED

**Severity:** High · **Category:** reliability, data quality

**Problem.** `events/dispatcher.py::consume_once` did not commit the Kafka
offset when a handler raised, and logged "offset not committed" — implying
a retry. But `poll()` advances the consumer's in-memory position
regardless of commits, so the next poll returned the *following* record.
Once that record committed its offset, the committed position moved
**past** the failed record, which was then never redelivered.

**Evidence.**
- No `seek`, `pause`, or `assign` call existed anywhere in
  `events/` or `workers/`.
- `consume_once`'s failure path had **zero test coverage** — the only
  consumer tests (`test_kafka_integration.py`) require a live broker and
  skip without one.
- `KNOWN_LIMITATIONS.md` claimed a poison record "can stall its
  partition", which the code did not do.

**Impact.** Silently dropped price bars, news articles, and trade-activity
updates on any transient handler failure — a provider timeout was enough.
The symptom is *missing data*, which produces no error to observe, and the
log line actively pointed the wrong way.

**Fix.**
- `producer.py::ConfluentBrokerConsumer.seek` — rewinds the partition to a
  given message's offset.
- `dispatcher.py::_rewind` — called on both failure paths; swallows seek
  errors so a failed seek cannot kill the worker loop.

**Tests.** `apps/api/tests/test_dispatcher_retry.py` — 7 tests using a
fake consumer that models the position/commit split. Verified to fail
without the fix (3 failures, with `committed == [2]` proving offset 0 was
skipped) and pass with it.

**Docs.** [ADR-0005](../adr/ADR-0005-rewind-on-handler-failure.md);
`KNOWN_LIMITATIONS.md` corrected;
[runbook](../operations/runbooks/kafka-consumer-stalled.md);
[failure scenarios §2](./distributed-systems/failure-scenarios.md).

**Accepted consequence.** A genuinely poison record now stalls its
partition. Deliberate — with no DLQ, a loud stall beats a silent gap for
financial data. See F-002.

---

### F-005 — Documentation contradicted code ✅ FIXED

**Severity:** Low · **Category:** maintainability

`KNOWN_LIMITATIONS.md` described poison-record behaviour the code did not
implement. Corrected as part of F-001, and now accurate.

---

### F-009 — Auth bridge security properties were untested ✅ FIXED

**Severity:** Medium · **Category:** security, maintainability

**Problem.** The web→api bridge's guarantees had no test coverage. Router
tests covered the happy path plus two obvious rejections (missing header,
garbage string). Nothing verified the controls that make the bridge
*secure* rather than merely present.

**Evidence.** No test constructed a token signed with a different secret,
an expired token, or an `alg: none` token. A change to `require_user_id`
that passed `options={"verify_signature": False}` would have left the
entire suite green — confirmed by making exactly that change: 8 of 11 new
tests failed, but the pre-existing suite did not notice.

**Impact.** No live vulnerability — the implementation was correct. The
risk was regression: signature verification, expiry enforcement, and the
`algorithms=["HS256"]` pin are three one-line controls, each silently
removable.

**Fix.** Tests only; no production code changed.
`apps/api/tests/test_auth_bridge.py` — 11 tests covering wrong-secret
rejection, expiry, a valid-token control, hand-built `alg: none`,
missing and non-numeric `sub`, malformed headers, and `sub`-selects-user.
Verified to fail when the verifier is weakened.

**Docs.** [authentication](../security/authentication.md),
[threat model T1](../security/threat-model.md),
[security study note](./security/auth-and-threats.md).

---

### F-011 — No plausibility bounds on ingested prices ✅ FIXED

**Severity:** Medium · **Category:** data quality

**Problem.** Nothing validated provider data before it reached `price_bars`.
A negative, zero, `NaN`, or absurd close would be stored and flow into fills,
alerts, NAV, backtests, and replay. `Numeric(18, 6)` rejects non-numerics and
nothing else — not even `Decimal('NaN')`, which `Decimal(str(float('nan')))`
produces and yfinance emits for missing fields.

**Evidence.** No check for `low <= open, close <= high`, price sign,
finiteness, or any bound against the prior close anywhere in
`services/ingest/prices.py` or the `BarRecord` dataclass. Three builders
(`fetch_yfinance_daily`, `fetch_alpha_vantage_daily`, `backfill._parse_csv`)
and two write paths (`persist_bars`, `persist_market_refresh`) fed
`upsert_bars` unscreened.

**Fix.** New pure module `services/ingest/screening.py::screen_bar` with two
classes of check, applied inside `upsert_bars` (the one choke point every
write goes through):

- **Structural → reject** (drop + `WARNING`): O/H/L/C finite and `> 0`,
  `volume >= 0`, `low <= open, close <= high`.
- **Plausibility → quarantine** (new `price_bar_quarantine` table, not
  `price_bars`): `(high - low) / low > 0.60`, or
  `|close - prev_close| / prev_close > 0.60`. `prev_close` follows accepted
  bars in the batch and falls back to the latest stored bar; a quarantined
  bar does not advance it (fails toward review). Thresholds are tunable
  module constants.

`persist_market_refresh` screens too and derives the `market.bars.refreshed`
`bar_count` / `latest_close` from accepted bars only. New
`stockviz ingest-quarantine [--ticker] [--release ID ...]` CLI lists held
bars and releases them into `price_bars`.

**Why 60%.** Above essentially every organic single-day equity move; a
whole-row decimal-point error (~900%) is always caught. It interacts with the
*unadjusted* series (F-007 neighbourhood): splits ≥ 3:1 quarantine, which is
acceptable — nothing else detects splits and a human glance at a split date
is desirable.

**Tests.** `tests/test_ingest_screening.py` (14, pure), `tests/test_ingest_quarantine.py`
(7, writer end-to-end on SQLite), plus a `persist_market_refresh` case in
`tests/test_market_news_pipeline.py`. Migration `2c1a9603e92b`; `alembic check`
clean; full suite green against Postgres (649 passed).

**Docs.** [market-data semantics](../database/market-data.md#plausibility-screening);
[threat model T7](../security/threat-model.md).

**Accepted consequence.** A data error smaller than 60% still lands in
`price_bars`, and a genuine 60%+ move is held until an operator releases it.
Cross-provider reconciliation is still absent.

---

### F-013 — CSV export made every negative number a text cell ✅ FIXED

**Severity:** Low · **Category:** data quality

**Problem.** `apps/web/lib/csv.ts::neutralise` prefixed any field starting
with `=`, `+`, `-`, `@`, tab or CR with a single quote to block spreadsheet
formula injection. That guard is correct in principle, but `-` also starts
every negative number — so in the trades export, every negative realized
P&L became `'-12.50`: a **text cell that Excel will not sum or chart**,
which is the point of exporting to a spreadsheet.

**Evidence.** `app/api/export/trades/route.ts` emits
`Number(t.realized_pnl).toFixed(2)`, negative for any losing trade. The
old behaviour was deliberate and tested — the test read *"Trade-off we
accept: correctness beats prettiness for a leading '-'"* — but its inline
comment (*"Numbers pass through as numbers, so real negatives are
unaffected"*) contradicted the assertion directly beneath it, which
asserted `csvField(-12.5) === "'-12.5"`.

**Why the trade-off was avoidable.** It was framed as safety vs.
prettiness, but a narrower guard gives both. A field that parses entirely
as a finite number cannot carry a payload: `-12.50` evaluates to −12.5 and
nothing else. Anything a spreadsheet would treat as an expression
(`-1+1`, `-A1`, `-HYPERLINK(...)`) is **not** a number and is still
neutralised.

**Fix.** Exempt a leading `-` only when the whole field is a finite number.
`=`, `+`, `@`, tab and CR are never exempt — deliberately, since `+1234`
has no legitimate use here and the narrow exemption is easier to defend.

**Tests.** `apps/web/tests/unit/csv.test.ts` — the old expectation was
replaced with three cases: negatives stay numeric (`-12.50`, `-12.5`,
`-0`, `-1e3`); non-numeric leading `-` is still neutralised; and the other
prefixes are never exempt even for numeric-looking values. Verified an
over-broad exemption fails 2 tests.

---

## Open — tracked, not yet actioned

### F-002 — No dead-letter queue or retry ceiling

**Severity:** Medium · **Category:** reliability

Retries are unbounded and unattended: no attempt counter on the consumer
side, no DLQ, no alert. After F-001 a poison record stalls its partition
indefinitely, and the only signal is consumer lag — which nothing
monitors.

Already on the [roadmap](../ENGINEERING_ROADMAP.md) ("consumer retry/DLQ
policy"). **Not fixed here** because it needs a DLQ topic, a redrive path,
and alerting — more than a correctness fix should carry, and it is the
kind of architectural change that should be proposed rather than slipped
in.

*Proposed shape:* retry counter in the message header; after N attempts
produce to `stockviz.<domain>.dlq.v1` with the failure reason and commit
the offset; a redrive CLI twin; alert on DLQ depth > 0.

### F-003 — Rate limits are per-process while the API autoscales

**Severity:** Medium · **Category:** security, scalability

slowapi's default storage is in-memory, so each API replica keeps its own
buckets. With `maxReplicas: 5` the effective budget is up to 5× the
configured limit, and it resets on every pod restart.

Partially documented ("CPU-local rate limiting"), now explained with its
cause in [ADR-0004](../adr/ADR-0004-no-redis.md). **Not fixed** because
the fix is a shared store — the one genuine reason this project would add
Redis — which is an infrastructure decision, not a code cleanup.

### F-004 — Consumer autoscaling uses the wrong signal

**Severity:** Low · **Category:** scalability

`market-ingest-hpa.yaml` scales on CPU, but the consumer is I/O-bound on
provider HTTP: it can be badly backed up at low CPU and never scale out.

Already acknowledged in `KNOWN_LIMITATIONS.md` and `KAFKA_SCALING.md` as a
deliberate demonstration. Documented, not changed — lag-based scaling
needs KEDA, which is a real infrastructure addition.

*Worth noting the part that is right:* `maxReplicas: 3` correctly matches
`MARKET_TOPIC_PARTITIONS = 3`.

### F-006 — Connection-pool ceiling is reached by scaling out

**Severity:** Medium · **Category:** scalability

`db.py` uses SQLAlchemy defaults (~15 connections per process). At full
scale — 5 API + scheduler + publisher + 6 consumer types — worst-case
demand exceeds a default `max_connections = 100`. No PgBouncer.

Not currently hit, because replicas sit at their minima. Documented in
[schema](../database/schema.md#connection-pooling) and
[runbook](../operations/runbooks/postgres-connections.md). **Not fixed**
because setting pool sizes without measuring would be guessing; the real
answer is a pooler.

### F-007 — No exchange calendar; bar finality is timing-based

**Severity:** Low · **Category:** data quality

Nothing checks whether a session has closed before writing a bar. The
16:30 America/New_York schedule is the only guard, so a manual mid-session
`cli ingest` can store a partial bar (later overwritten). A market holiday
and a provider outage are indistinguishable in the logs — both produce
"provider returned no bars".

Documented in [market-data semantics](../database/market-data.md).

### F-008 — Missing index on `trades(portfolio_id, ts)`

**Severity:** Low · **Category:** performance

`portfolio_id` is indexed alone; trade history ordered by time filters
then sorts. Trivial at demo volume. **Not added** without an
`EXPLAIN ANALYZE` to justify it — the repository has no query-plan
evidence, and adding indexes on intuition is how you end up with unused
ones.

### F-010 — Stale bridge token for a deleted user returns 500

**Severity:** Low · **Category:** reliability

A correctly signed, unexpired token whose `sub` names a nonexistent user
raises `LookupError: User <id> not found` from
`buying_power.py::lock_user` (via `ensure_default_portfolio`), surfacing as
an uncaught 500 rather than a clean 401.

Not reachable by an attacker: forging a token requires the shared secret,
and the Next.js server only mints tokens for real sessions. It is reachable
by a **deleted user holding a live 60-second token**.

**Not fixed here.** The clean fix is at the boundary — an exception handler
mapping `LookupError` to 401 — but `ensure_default_portfolio` is called by
most authenticated routers, so changing its failure behaviour is a
cross-cutting change to the trading path. That is larger than a
contained fix and deserves its own change with its own tests, rather than
being folded into a documentation iteration.

*Observed while writing `test_auth_bridge.py`.*

### F-012 — No login throttling or account lockout

**Severity:** Medium · **Category:** security

The NextAuth credentials provider has no per-account rate limit, no
lockout, and no CAPTCHA. bcrypt's cost factor is the only barrier to
credential stuffing. The API's slowapi limits do not apply — the login
route is a Next.js route, not a `/v1` endpoint.

Mitigating factors: paper trading, no financial value at risk, and the
only PII is an email address.

**Not fixed here** because it needs a shared attempt store to be
meaningful across replicas — the same infrastructure decision as F-003.
Identified in [threat model T3](../security/threat-model.md) as the
highest-priority security gap.

---

## Noted as strengths

Worth recording, because knowing *why* something is right is as useful as
finding what's wrong:

- **Outbox + inbox + commit ordering** — textbook-correct, with the
  reasoning in docstrings rather than tribal knowledge.
- **`/live` vs `/health` split** — with the outage-amplification reasoning
  written down.
- **HPA ceiling pinned to partition count** — rarely got right.
- **Pure execution kernel** — no Session, FX, settings, or wall clock;
  deterministic and testable.
- **Provider I/O outside transactions**, structurally enforced by the
  dispatcher's `process` vs `handlers` split.
- **`lock_portfolio` refreshing the ORM instance** — the non-obvious half
  of a correct row lock.
- **Every scheduled job has a manual CLI twin** — makes every runbook
  recovery step trivially available.
- **SSE avoids the `yield`-dependency trap** — `routers/stream.py`
  deliberately does not take `get_session`, because FastAPI holds
  generator dependencies open for the response lifetime; with a 15-slot
  pool, ~15 concurrent viewers would have deadlocked the API.
- **No endpoint accepts a `user_id` parameter** — identity comes only from
  the signed claim, removing the largest IDOR surface by construction.
- **Ownership mismatches return 404, not 403** — the API does not confirm
  that another user's resource id exists.
- **CI drift guards** — `alembic check` catches a model change with no
  migration, and the OpenAPI type-sync check fails the build when the web
  client's types go stale. Both exist because of real incidents.
- **A narrowly suppressed CVE** — `PYSEC-2026-1325` is ignored with a
  recorded reason (it reaches the project only via python-jose's ES*
  algorithms, which the HS256 bridge never uses) rather than by disabling
  the audit.
- **`apiPost` does not retry** — with the reason in a comment: a timed-out
  POST may already have committed, and replaying it could duplicate a
  trade. The same idempotency question the Kafka pipeline answers "yes" to
  is correctly answered "no" on the HTTP write path.
- **`import "server-only"` on ten modules** — makes leaking
  `INTERNAL_API_TOKEN` into a client bundle a *build error* rather than
  something code review must catch.
- **`exec` in both container CMDs** — without it a shell stays PID 1 and
  SIGTERM never reaches the app, which would silently defeat the graceful
  shutdown handlers in `dispatcher.py::run_loop`.
- **`RUN test -f .../server.js`** — the web build asserts its own output,
  so an incomplete standalone trace fails the build instead of producing
  an image that crashes on boot.
- **`HOSTNAME=0.0.0.0` before starting Next** — Kubernetes sets `HOSTNAME`
  to the pod name, which Next's standalone server would otherwise try to
  bind to.
