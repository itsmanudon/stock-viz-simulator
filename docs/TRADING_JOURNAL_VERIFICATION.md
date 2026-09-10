# Trading Journal implementation and verification

Verified locally on September 6, 2026. This continues and completes the existing
unfinished Journal implementation. The subsequent migration review and commit
handoff are recorded below. No deployment or normal application database
migration was performed.

## Delivered behavior

Portfolio now includes Journal in its established tab workspace. The monthly
realized-P&L calendar supports month/year controls, Today, weekly aggregates,
day and week drill-down, paged execution details, and ticker links. Desktop
detail reserves space on the right; mobile uses a modal sheet. URL history,
refresh, keyboard navigation, focus restoration, reduced motion, localized
errors/retries, empty states, and bounded client caching are implemented.

The existing fonts, financial colors, numerical formatting, authentication
bridge, portfolio loader, ORM, API serialization, and testing tools are reused.
There are no new runtime dependencies or production sample trades.

## Architecture and accounting

The complete contract and accounting rationale are in
[Trading Journal architecture](TRADING_JOURNAL.md).

- Flow: Portfolio server loader / browser proxy → authenticated FastAPI router
  → owned portfolio range queries → Decimal aggregation → calendar and inspector.
- A trade means one closing equity fill or terminal option event with recorded
  P&L. Partial equity closes count separately; buys and pending orders do not.
- Equity P&L uses the existing weighted-average ledger and closing FX. New fills
  preserve native average cost before position mutation. Legacy cost remains null.
- Option realizations are persisted at close/settlement. Physical calls realize
  premium loss and preserve strike basis in the shares; physical puts include
  the disposed shares' gain once. See the architecture's event table.
- New York execution dates, including DST, determine day/month attribution.
  They are not reconstructed price-bar dates or foreign-exchange sessions.
- Monthly percentage is labeled “% of prior NAV,” not portfolio return.
  Dividends, deposits, unrealized movement, and replay activity are excluded.
- No signal-at-entry values are reconstructed from current or closing-time data.

The main frontend components are JournalPanel, JournalSummary, PnlCalendar,
PnlCalendarDay, WeeklySummaryCell, JournalInspector, and JournalExecutionRow.
The backend lives in services/journal (model, query, aggregate, view functions).

Routes:
- `/portfolio?tab=journal&month=YYYY-MM`, optional `date=YYYY-MM-DD` or `week=YYYY-MM-DD`.
- `GET /v1/portfolio/journal/months/{year}/{month}`.
- `GET /v1/portfolio/journal/days/{day}?offset=0&limit=100`.
- `GET /v1/portfolio/journal/weeks/{start}`.
- Matching authenticated Next `/api/journal/...` proxies.

## Persistence and performance

Apply Alembic through `b6e8a20f4c31` before deploying:
- `a4d7c19f6e02`: option proceeds/realization, deterministic worthless-expiry
  backfill, and indexes on trades(portfolio_id, ts) and options(user_id, settled_at).
- `b6e8a20f4c31`: nullable trades.avg_cost_at_fill. Separate migration supports
  environments that already applied the first unfinished migration.

Month reads scan the selected account and period, not its full history. The
month payload contains aggregates only; day responses default to 100 executions
(maximum 200). A 1,000-execution test verifies bounded responses and exact totals.
Day statistics currently fold all rows for that day before slicing the response.

An actual PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)` on the browser fixture selected
`ix_trades_portfolio_ts`, with both timestamp bounds in the index condition.
Seven closing rows took 0.094 ms execution time on this small local fixture.
That confirms index eligibility, not a production throughput benchmark.

Redis remains absent per ADR-0004. Future caching belongs around Journal view
functions, with owner/portfolio/period keys and post-commit invalidation.
The frontend keeps at most six months and revalidates on revisit, focus, or Refresh.

## Verification commands and results

Commands below are the final verification invocations. Paths are relative to
the stated working directory. Direct executable entrypoints avoid this Windows
checkout's blocked PowerShell pnpm wrapper / incompatible generated CMD shims.

From repository root:

```powershell
$env:DATABASE_URL='postgresql+psycopg://stockviz:stockviz_dev@127.0.0.1:5434/stockviz'
$env:UV_NO_SYNC='1'
$env:UV_CACHE_DIR='D:/Github Repos/stock-viz-simulator/artifacts/private/uv-cache'
.\apps\api\.venv\Scripts\python.exe -m pytest apps/api/tests -q -p no:cacheprovider --basetemp=artifacts/private/journal-pg-pytest-20260906
```

**768 passed, 3 skipped** in 75.65 s. The three skips require an unreachable
Kafka broker. PostgreSQL concurrency and migration tests ran against the
repository's disposable scratch databases.

After the final SQLModel typing corrections:

```powershell
$env:DATABASE_URL='postgresql+psycopg://stockviz:stockviz_dev@127.0.0.1:5434/stockviz'
.\apps\api\.venv\Scripts\python.exe -m pytest apps/api/tests/test_journal.py apps/api/tests/test_journal_migration.py apps/api/tests/test_options.py -q -p no:cacheprovider --basetemp=artifacts/private/journal-final-typed
node node_modules/@biomejs/biome/bin/biome check apps/web
git diff --check
```

**61 passed** in 2.95 s; Biome checked **287 files**, no issues; diff whitespace
check passed (Git only reported existing CRLF normalization notices).

From `apps/api`:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pyright --pythonpath .venv/Scripts/python.exe
$env:DATABASE_URL='postgresql+psycopg://stockviz:stockviz_dev@127.0.0.1:5434/stockviz_journal_verify_20260906_v2'
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Ruff passed. Pyright: **0 errors, 0 warnings**. The complete Alembic chain was
applied to the isolated verification database; SQL subsequently confirmed head
`b6e8a20f4c31`. Separate tests exercise upgrade, downgrade, and re-upgrade with
legacy records on SQLite and PostgreSQL enum columns.

From `apps/web`:

```powershell
node node_modules/typescript/bin/tsc --noEmit
node node_modules/vitest/vitest.mjs run
node node_modules/next/dist/bin/next build
```

TypeScript passed. Vitest: **278 passed in 41 files** (18.31 s). Production
build passed, including TypeScript, all route generation, and Journal proxies.

Final focused frontend verification:

```powershell
node node_modules/vitest/vitest.mjs run tests/unit/journal-panel.test.tsx tests/unit/journal-view-model.test.ts
```

**38 passed in 2 files** (27.58 s).

Added coverage includes positive/negative/scratch/no-trade days, multiple symbols,
Decimal precision, month and clipped-week boundaries, UTC and DST attribution,
partial closes and scale-in, option cash/physical/worthless settlement, delayed
expiry pricing, missing historical accounting, authenticated ownership, and
stable detail pagination. UI cases cover URL state, abort/revisit races, late
responses, localized errors, empty states, keyboard navigation, and native-price
currency versus USD P&L.

The generated API contract was refreshed from the local FastAPI OpenAPI schema:

```powershell
node apps/web/node_modules/openapi-typescript/bin/cli.js artifacts/private/journal-openapi.json -o apps/web/lib/api/schema.d.ts
```

Generation succeeded and `schema-check.ts` compiled with the new month/day/week
contracts.

Browser verification ran against the built web server on 3010 and API on 8010,
both pointed at the isolated `stockviz_journal_verify_20260906_v2` database,
with the scheduler disabled and local-only authentication configuration:

```powershell
$env:PLAYWRIGHT_BASE_URL='http://127.0.0.1:3010'
$env:JOURNAL_TEST_DATABASE_URL='postgresql+psycopg://stockviz:stockviz_dev@127.0.0.1:5434/stockviz_journal_verify_20260906_v2'
node node_modules/@playwright/test/cli.js test tests/e2e/journal.spec.ts
```

**1 passed** in 8.9 s, after rebuilding the final UI. This single journey creates
an account, generates historical fills through actual apply_fill accounting,
and checks month navigation, day switching, week extremes, browser back,
refresh restoration, Escape, empty month, mobile modal semantics, restored
focus, and no page overflow at 390px and 320px. Other Playwright suites were
not rerun; the full frontend unit suite and backend suite were run.

Initial checks exposed and resolved stale fetches, focus behavior, fixture
foreign-key ordering, and SQLModel typing issues. The first Pyright invocation
needed an explicit venv Python path; Ruff must run from apps/api so its relative
source roots resolve correctly. Tests were not weakened to mask failures.

## Visual review

All seven generated screenshots were manually inspected:
- Profitable month: restrained, differing gain intensities and correct week sums.
- Mixed month: gains, losses, and a neutral zero-P&L execution.
- Empty month: quiet grid with explanatory copy.
- Day inspector: exact cost, exit, quantity, timestamp, and P&L beside the calendar.
- Week inspector: totals, win rate, profit factor, daily breakdown, best/worst trades.
- Mobile calendar: compact figures, usable controls, no page-level overflow.
- Mobile sheet: readable details, scrim, close control, and restored focus.

Screenshots are local Playwright artifacts under
`apps/web/test-results/journal-journal-calendar-drill-down-history-and-mobile-sheet-chromium/`.
They are intentionally not committed as application assets.

## Limitations and follow-ups

The live engine remains long-only, with no fees, partial option closes, or
multi-leg order model. Options use theoretical pricing. New option purchases
require USD underlyings because the previous option engine lacked FX accounting.
Unknown historical realizations are excluded and flagged in month/day/week
views; undated historical events cannot be assigned to a period.

Future work should add persisted opening-decision provenance before signal
analytics, properly modeled foreign-option FX, exchange session metadata,
and SQL rollups/cursor pagination if measured day volumes warrant them.
Historical physical settlements cannot be safely reconstructed automatically.

## Migration review and commit handoff

The b6 migration was reviewed against PostgreSQL's documented DDL behavior and
tested for old-row/old-writer compatibility, absence of default and heap rewrite,
rollback data loss, exclusive-lock contention, atomic timeout, and successful retry.
Its runtime DDL is unchanged. See the production rollout section in
[TRADING_JOURNAL.md](TRADING_JOURNAL.md), including the heavier preceding a4 migration.

Fresh review verification from apps/api:

```powershell
$env:DATABASE_URL='postgresql+psycopg://stockviz:stockviz_dev@127.0.0.1:5434/stockviz'
.\.venv\Scripts\python.exe -m pytest tests/test_journal_migration.py tests/test_journal.py tests/test_options.py -q -p no:cacheprovider --basetemp=../../artifacts/private/journal-migration-review
```

**62 passed** in 2.63 seconds, including the new PostgreSQL locking test.
Commits are separated into accounting persistence, settlement safety,
Journal backend, Journal frontend, and documentation, in dependency order.

- `82d2bd8` — accounting persistence, migrations, and migration tests.
- `d5304c7` — duplicate settlement, expiry pricing, and boundary regression tests.
- `de99252` — aggregation, authenticated APIs, and backend tests.
- `3db51f5` — calendar, inspectors, route integration, and frontend/browser tests.
- `docs(journal): add accounting and verification notes` — this handoff and domain docs.

The review also reran Ruff (passed), Pyright with the venv interpreter (zero
errors/warnings), Biome (287 files, passed), TypeScript (passed), and the complete
frontend suite (278 tests in 41 files, passed in 40.07 s). After a formatting-only
test cleanup, the three migration tests passed again in 0.74 s:

```powershell
# apps/api, with the same local PostgreSQL DATABASE_URL above
.\.venv\Scripts\python.exe -m pytest tests/test_journal_migration.py -q -p no:cacheprovider --basetemp=../../artifacts/private/journal-migration-reviewed-final
```

The prior full backend/build/browser results above remain the implementation
verification; this review changed migration comments, tests, and rollout docs,
not application behavior or migration DDL.

## Materially changed files

This list includes the completed prior agent's unfinished files and this
continuation's corrections.

- [`apps/api/migrations/versions/a4d7c19f6e02_add_options_realization_and_journal_indexes.py`](../apps/api/migrations/versions/a4d7c19f6e02_add_options_realization_and_journal_indexes.py)
- [`apps/api/migrations/versions/b6e8a20f4c31_capture_equity_fill_cost_basis.py`](../apps/api/migrations/versions/b6e8a20f4c31_capture_equity_fill_cost_basis.py)
- [`apps/api/src/stockviz/main.py`](../apps/api/src/stockviz/main.py)
- [`apps/api/src/stockviz/models/option.py`](../apps/api/src/stockviz/models/option.py)
- [`apps/api/src/stockviz/models/portfolio.py`](../apps/api/src/stockviz/models/portfolio.py)
- [`apps/api/src/stockviz/routers/journal.py`](../apps/api/src/stockviz/routers/journal.py)
- [`apps/api/src/stockviz/schemas.py`](../apps/api/src/stockviz/schemas.py)
- [`apps/api/src/stockviz/services/journal/__init__.py`](../apps/api/src/stockviz/services/journal/__init__.py)
- [`apps/api/src/stockviz/services/journal/aggregate.py`](../apps/api/src/stockviz/services/journal/aggregate.py)
- [`apps/api/src/stockviz/services/journal/model.py`](../apps/api/src/stockviz/services/journal/model.py)
- [`apps/api/src/stockviz/services/journal/query.py`](../apps/api/src/stockviz/services/journal/query.py)
- [`apps/api/src/stockviz/services/options/trade.py`](../apps/api/src/stockviz/services/options/trade.py)
- [`apps/api/src/stockviz/services/trading/execute.py`](../apps/api/src/stockviz/services/trading/execute.py)
- [`apps/api/tests/test_journal.py`](../apps/api/tests/test_journal.py)
- [`apps/api/tests/test_journal_migration.py`](../apps/api/tests/test_journal_migration.py)
- [`apps/api/tests/test_options.py`](../apps/api/tests/test_options.py)
- [`apps/web/app/(product)/(authed)/portfolio/page.tsx`](../apps/web/app/(product)/(authed)/portfolio/page.tsx)
- [`apps/web/app/api/journal/days/[date]/route.ts`](../apps/web/app/api/journal/days/[date]/route.ts)
- [`apps/web/app/api/journal/months/[year]/[month]/route.ts`](../apps/web/app/api/journal/months/[year]/[month]/route.ts)
- [`apps/web/app/api/journal/weeks/[date]/route.ts`](../apps/web/app/api/journal/weeks/[date]/route.ts)
- [`apps/web/app/globals.css`](../apps/web/app/globals.css)
- [`apps/web/components/journal/journal-execution-row.tsx`](../apps/web/components/journal/journal-execution-row.tsx)
- [`apps/web/components/journal/journal-inspector.tsx`](../apps/web/components/journal/journal-inspector.tsx)
- [`apps/web/components/journal/journal-panel.tsx`](../apps/web/components/journal/journal-panel.tsx)
- [`apps/web/components/journal/journal-summary.tsx`](../apps/web/components/journal/journal-summary.tsx)
- [`apps/web/components/journal/pnl-calendar-day.tsx`](../apps/web/components/journal/pnl-calendar-day.tsx)
- [`apps/web/components/journal/pnl-calendar.tsx`](../apps/web/components/journal/pnl-calendar.tsx)
- [`apps/web/components/journal/weekly-summary-cell.tsx`](../apps/web/components/journal/weekly-summary-cell.tsx)
- [`apps/web/components/portfolio-tabs.tsx`](../apps/web/components/portfolio-tabs.tsx)
- [`apps/web/components/portfolio-workspace.tsx`](../apps/web/components/portfolio-workspace.tsx)
- [`apps/web/lib/api/journal.ts`](../apps/web/lib/api/journal.ts)
- [`apps/web/lib/api/schema-check.ts`](../apps/web/lib/api/schema-check.ts)
- [`apps/web/lib/api/schema.d.ts`](../apps/web/lib/api/schema.d.ts)
- [`apps/web/lib/journal-view-model.ts`](../apps/web/lib/journal-view-model.ts)
- [`apps/web/lib/portfolio-data.ts`](../apps/web/lib/portfolio-data.ts)
- [`apps/web/lib/portfolio-view-model.ts`](../apps/web/lib/portfolio-view-model.ts)
- [`apps/web/tests/e2e/journal-seed.py`](../apps/web/tests/e2e/journal-seed.py)
- [`apps/web/tests/e2e/journal.spec.ts`](../apps/web/tests/e2e/journal.spec.ts)
- [`apps/web/tests/unit/journal-panel.test.tsx`](../apps/web/tests/unit/journal-panel.test.tsx)
- [`apps/web/tests/unit/journal-view-model.test.ts`](../apps/web/tests/unit/journal-view-model.test.ts)
- [`apps/web/tests/unit/portfolio-data.test.ts`](../apps/web/tests/unit/portfolio-data.test.ts)
- [`apps/web/tests/unit/portfolio-tabs.test.tsx`](../apps/web/tests/unit/portfolio-tabs.test.tsx)
- [`apps/web/tests/unit/portfolio-workspace.test.tsx`](../apps/web/tests/unit/portfolio-workspace.test.tsx)
- [`docs/README.md`](../docs/README.md)
- [`docs/TRADING_JOURNAL.md`](../docs/TRADING_JOURNAL.md)
- [`docs/TRADING_JOURNAL_VERIFICATION.md`](../docs/TRADING_JOURNAL_VERIFICATION.md)
- [`docs/database/schema.md`](../docs/database/schema.md)
- [`docs/superpowers/specs/2026-09-05-trading-journal-pnl-calendar-design.md`](../docs/superpowers/specs/2026-09-05-trading-journal-pnl-calendar-design.md)
