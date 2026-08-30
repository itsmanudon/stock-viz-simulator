# Session handoff

Working state for whoever picks this up next. **Durable state lives in
[PROGRESS.md](./PROGRESS.md) (what is covered) and
[FINDINGS.md](./FINDINGS.md) (open issues).** This file carries only what
those two do not: branch state, verified commands, and what could not be
run here.

Delete or rewrite this file once the work it describes is merged.

## Branch

```
claude/stockviz-audit-curriculum-pwqwr2   ← 3 commits ahead of main, pushed, tree clean
```

| Commit | What |
| --- | --- |
| `21efc99` | **fix(events)** — rewind failed Kafka records instead of dropping them |
| `94e3f0c` | **test(api)** — cover the auth bridge's security properties |
| `b7a3515` | **fix(web)** — keep negative numbers numeric in the CSV export |

No PR has been opened. Per `CLAUDE.md` the branching rule is
`main ← dev ← feat/*|fix/*|chore/*`, and **every PR targets `dev`, never
`main`**. This branch was cut from `main` (the session default), so check
`git log dev..HEAD` before opening a PR and rebase onto `dev` if needed.

## Production code changed (7 files; everything else is docs)

```
apps/api/src/stockviz/events/dispatcher.py   +_rewind(), seek on both failure paths
apps/api/src/stockviz/events/producer.py     +BrokerConsumer Protocol, +seek()
apps/api/tests/test_dispatcher_retry.py      new — 7 tests
apps/api/tests/test_auth_bridge.py           new — 11 tests
apps/web/lib/csv.ts                          narrow the formula-injection guard
apps/web/tests/unit/csv.test.ts              replace one expectation with three
README.md                                    link to docs/README.md
```

## Verified commands

All of these were run and passed on this branch:

```bash
uv --directory apps/api run pytest -q          # 620 passed, 10 skipped
uv --directory apps/api run ruff check .
uv --directory apps/api run ruff format --check .
uv --directory apps/api run pyright            # 0 errors
pnpm install --frozen-lockfile
pnpm --filter @stockviz/web test               # 233 passed
pnpm lint && pnpm typecheck && pnpm build
```

**Not run here** — no Postgres, no Kafka, no browser:

- The 10 skipped tests (`DATABASE_URL is not PostgreSQL`) — the Postgres
  and Kafka tiers. CI supplies both.
- Playwright e2e — needs a built web app plus a live API on a migrated,
  seeded database.
- The kind + Strimzi smoke workflow.

Anything touching the Kafka dispatcher change should ideally be confirmed
against a real broker before merge, since the fix is about librdkafka's
position/commit semantics and the unit tests use a fake.

## Markdown link check

There is no CI gate for documentation links. This one-liner was used
throughout and is worth re-running after doc edits:

```bash
python3 - <<'PY'
import pathlib, re, sys
root = pathlib.Path("."); bad = []
files = list(root.glob("docs/**/*.md")) + [root/"README.md"]
pat = re.compile(r'\[([^\]]*)\]\((?!https?://|mailto:)([^)#]+)(#[^)]*)?\)')
for f in files:
    for m in pat.finditer(f.read_text()):
        if not (f.parent / m.group(2)).resolve().exists():
            bad.append(f"{f}: [{m.group(1)}] -> {m.group(2)}")
print(f"checked {len(files)} files")
if bad: [print("  "+b) for b in bad]; sys.exit(1)
print("ok")
PY
```

Wiring this into the `web` CI job is a small, worthwhile chore.

## Where to pick up

In priority order. Full context for each is in
[FINDINGS.md](./FINDINGS.md).

1. **F-011 — plausibility bounds on ingested prices.** Highest value. A
   negative or absurd close is stored and flows into fills, alerts, NAV,
   backtests, and replay. Left open because thresholds are a domain
   decision. Suggested shape: reject bars violating `low ≤ open,close ≤ high`
   outright; route implausibly large moves to a quarantine table rather
   than dropping them. Touch `services/ingest/prices.py::upsert_bars` or
   the `BarRecord` construction, and add tier-1 tests.
2. **F-002 — dead-letter queue.** Since `21efc99` a poison record stalls
   its partition deliberately. A DLQ with bounded retries is the real fix
   and is already on the roadmap. This is an architecture change — write a
   proposal before implementing.
3. **F-003 / F-012 — shared store for rate limits and login throttling.**
   Both need the same infrastructure decision. F-012 (no account lockout)
   is the highest-priority item in the
   [threat model](../security/threat-model.md).
4. **F-010 — stale bridge token for a deleted user returns 500.** Small,
   but the clean fix is cross-cutting (`ensure_default_portfolio` is called
   by most authed routers), so it deserves its own change and tests.
5. **Observability.** Consumer lag and outbox-backlog gauges would close
   the biggest operational gap and the biggest curriculum gap at once —
   [observability](../observability/overview.md) is written as a gap
   analysis for that reason.

## Conventions this work followed

- Canonical docs (`docs/*`) describe the system as built. Interview-prep
  docs link back to them and add concepts, trade-offs, and questions —
  **never a second copy of the architecture.**
- Claims are checkable against a file path or a command. Where rationale
  could not be established from the repository, the docs say so.
- Fixes stayed contained: smallest correct change, a test that fails
  without it, and the canonical doc updated in the same commit.
- Larger architectural changes were **recorded as findings, not
  implemented** — see F-002, F-003, F-011, F-012.
