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
| _branch tip_ | **feat(market)** — plausibility screening on ingested prices (F-011): reject impossible bars, quarantine implausible ones into `price_bar_quarantine` |

No PR has been opened. Per `CLAUDE.md` the branching rule is
`main ← dev ← feat/*|fix/*|chore/*`, and **every PR targets `dev`, never
`main`**. This branch was cut from `main` (the session default), so check
`git log dev..HEAD` before opening a PR and rebase onto `dev` if needed.

## Production code changed

Kafka / auth / CSV work (as before):

```
apps/api/src/stockviz/events/dispatcher.py   +_rewind(), seek on both failure paths
apps/api/src/stockviz/events/producer.py     +BrokerConsumer Protocol, +seek()
apps/api/tests/test_dispatcher_retry.py      new — 7 tests
apps/api/tests/test_auth_bridge.py           new — 11 tests
apps/web/lib/csv.ts                          narrow the formula-injection guard
apps/web/tests/unit/csv.test.ts              replace one expectation with three
README.md                                    link to docs/README.md
```

F-011 plausibility screening:

```
apps/api/src/stockviz/services/ingest/screening.py   new — pure screen_bar()
apps/api/src/stockviz/services/ingest/prices.py      screen_bars/record_quarantined_bars/
                                                     write_accepted_bars; upsert_bars now screens
apps/api/src/stockviz/models/market.py               +QuarantinedPriceBar (price_bar_quarantine)
apps/api/src/stockviz/models/__init__.py             export it
apps/api/src/stockviz/events/handlers.py             persist_market_refresh screens; event
                                                     counts/close from accepted bars only
apps/api/src/stockviz/cli.py                          +ingest-quarantine (list / --release)
apps/api/migrations/versions/2c1a9603e92b_*.py        new table
apps/api/tests/test_ingest_screening.py              new — 14 pure tests
apps/api/tests/test_ingest_quarantine.py             new — 7 writer tests
apps/api/tests/test_ingest_prices.py                 plausible fixture; fake session filters INSERTs
apps/api/tests/test_market_news_pipeline.py          +1 handler test
docs/database/market-data.md, docs/security/threat-model.md, apps/api/CLAUDE.md   updated
```

## Verified commands

All of these were run and passed on this branch:

```bash
uv --directory apps/api run pytest -q          # 642 passed, 10 skipped (SQLite tier)
DATABASE_URL=postgres://... uv --directory apps/api run pytest -q   # 649 passed, 3 skipped
uv --directory apps/api run alembic upgrade head && alembic check   # clean, no drift
uv --directory apps/api run ruff check .
uv --directory apps/api run ruff format --check .
uv --directory apps/api run pyright            # 0 errors
pnpm install --frozen-lockfile
pnpm --filter @stockviz/web test               # 233 passed
pnpm lint && pnpm typecheck && pnpm build
```

**Postgres tier was run this session** against a local `stockviz-postgres`
container (`DATABASE_URL=postgres://stockviz:stockviz_dev@127.0.0.1:5434/stockviz`):
migration applied, `alembic check` clean, full suite 649 passed / 3 skipped.

**Not run here** — no Kafka broker, no browser:

- The 3 remaining skipped tests — the Kafka tier. CI supplies a broker.
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

   its partition deliberately. A DLQ with bounded retries is the real fix
   and is already on the roadmap. This is an architecture change — write a
   proposal before implementing.
2. **F-003 / F-012 — shared store for rate limits and login throttling.**
   Both need the same infrastructure decision. F-012 (no account lockout)
   is the highest-priority item in the
   [threat model](../security/threat-model.md).
3. **F-010 — stale bridge token for a deleted user returns 500.** Small,
   but the clean fix is cross-cutting (`ensure_default_portfolio` is called
   by most authed routers), so it deserves its own change and tests.
4. **F-011 follow-ups.** Cross-provider reconciliation (yfinance vs Alpha
   Vantage disagreement) and a scheduled alert on `price_bar_quarantine`
   depth > 0 are both still open. The quarantine table has a CLI but no UI.
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
  implemented** — see F-002, F-003, F-012. (F-011 was implemented this
  session: it needed a domain decision on thresholds, not new infra.)
