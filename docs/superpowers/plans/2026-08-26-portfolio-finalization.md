# StockViz Portfolio Finalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce measured Kafka scaling evidence, accurate recruiter/interview documentation, genuine screenshots, a final correctness audit, and an unmerged PR to `dev` without changing StockViz's established architecture.

**Architecture:** Execute evidence first: validate the repository baseline, run the unchanged kind/Strimzi benchmark, preserve its JSON, and generate all benchmark presentation artifacts from that source. Then audit code against public claims, capture the real UI, rewrite the portfolio documentation, run every requested quality gate, and open the feature PR.

**Tech Stack:** Next.js 16, React 19, FastAPI, SQLModel, PostgreSQL 16, Kafka 3.9.0, Strimzi 0.45.1, kind/Kubernetes, Mermaid, Playwright, Python 3.12, pnpm, uv, Docker.

**Spec:** `docs/superpowers/specs/2026-08-26-portfolio-finalization-design.md`

## Global Constraints

- Work only on `feat/portfolio-finalization` based on the latest `origin/dev` merge of PR #60.
- Do not add infrastructure, services, financial products, strategies, predictive features, or LLM features.
- Keep FastAPI/PostgreSQL as the synchronous financial source of truth; Kafka stays outside the trade commit path.
- Keep delivery at least once and consumers idempotent; never claim exactly once.
- Use the existing benchmark methodology unchanged with 100,000 events and replica counts 1, 2, 4, and 8.
- Treat CPU/memory as measured values or `null`; never synthesize resource metrics.
- Describe kind/Strimzi as a local/CI lab, not production or HA.
- Do not merge the final PR.

---

### Task 1: Establish the clean baseline and audit inventory

**Files:**
- Read: `README.md`
- Read: `docs/*.md`
- Read: `apps/api/src/stockviz/**/*.py`
- Read: `apps/api/tests/**/*.py`
- Read: `apps/web/**/*.{ts,tsx}`
- Read: `infra/k8s/**/*.yaml`
- Read: `.github/workflows/*.yml`
- Read: `scripts/k8s/*.sh`

**Interfaces:**
- Consumes: merge commit `38853f4` and the approved design spec.
- Produces: a private audit checklist organized as stale claims, correctness evidence, benchmark evidence, screenshot targets, and required gates.

- [ ] **Step 1: Verify branch and baseline commit**

Run:

```powershell
git status --short --branch
git merge-base --is-ancestor 38853f4 HEAD
git log -1 --oneline origin/dev
```

Expected: clean `feat/portfolio-finalization`, the ancestry command exits 0,
and `origin/dev` contains PR #60.

- [ ] **Step 2: Install project dependencies in the worktree**

Run:

```powershell
pnpm install --frozen-lockfile
uv --directory apps/api sync --frozen
```

Expected: both commands exit 0 without changing lockfiles.

- [ ] **Step 3: Run fast baseline tests**

Run:

```powershell
pnpm --filter @stockviz/web test
uv --directory apps/api run pytest tests/test_benchmarks.py tests/test_k8s_layout.py -q
```

Expected: all selected tests pass.

- [ ] **Step 4: Build the claim inventory**

Run targeted `rg` searches for locking, outbox acknowledgement, offset
commits, inbox receipts, scheduler requests, probe implementations, secret
mounts, localhost dependencies, benchmark values, production wording, and
agent/process wording. Record file-and-line evidence before editing prose.

- [ ] **Step 5: Commit only if setup revealed a required repository fix**

No commit is expected for this task. Dependency caches and the private audit
checklist remain ignored.

### Task 2: Add benchmark artifact validation and chart generation

**Files:**
- Create: `apps/api/src/stockviz/benchmarks/report.py`
- Modify: `apps/api/tests/test_benchmarks.py`
- Modify: `artifacts/benchmarks/.gitignore`
- Modify: `artifacts/benchmarks/README.md`

**Interfaces:**
- Consumes: the existing top-level benchmark document with `runs`, `event_count_per_run`, `replica_schedule`, `topic`, and `partitions`.
- Produces: `validate_matrix(document: dict[str, Any]) -> list[str]`, `markdown_table(document: dict[str, Any]) -> str`, `render_throughput_svg(document: dict[str, Any]) -> str`, and a CLI that validates JSON, writes the SVG, and checks marked Markdown tables.

- [ ] **Step 1: Write failing matrix-validation tests**

Add tests using a four-run fixture with replicas `[1, 2, 4, 8]`. Assert a
valid fixture returns no errors, then mutate it to verify errors for a missing
replica, non-100k count, incomplete run, foreign record, non-positive duration,
and missing p50/p95/peak lag.

- [ ] **Step 2: Run the validation tests and confirm failure**

Run:

```powershell
uv --directory apps/api run pytest tests/test_benchmarks.py -q
```

Expected: import or assertion failure because `stockviz.benchmarks.report`
does not exist.

- [ ] **Step 3: Implement strict matrix validation**

Implement `validate_matrix` with exact replica order `[1, 2, 4, 8]`, exact
event/collection count `100000`, zero foreign records, `complete is True`,
positive numeric processing duration, and non-null throughput/p50/p95/peak
lag. Validate `event_count_per_run == 100000`, `partitions == 12`, and a
four-row `runs` list.

- [ ] **Step 4: Write failing rendering tests**

Assert the Markdown table contains all four replica rows with consistently
rounded throughput, latency, lag, CPU, and memory values. Assert the SVG has
four plotted points, replica labels 1/2/4/8, an events/sec axis label, and
source metadata derived from the run IDs.

- [ ] **Step 5: Implement deterministic renderers and CLI**

Use only the Python standard library. Format missing resources as `—`. The
CLI accepts `--input`, `--chart`, and repeated `--check-markdown` paths. It
exits non-zero on any hard-gate failure or benchmark marker block mismatch.

- [ ] **Step 6: Make the final 100k artifact committable**

Keep `kafka-scaling.json` ignored and allow only
`artifacts/benchmarks/kafka-scaling-100k.json`. Explain in the artifact README
that the committed file is measured evidence and the rolling filename remains
local/CI output.

- [ ] **Step 7: Run focused tests and static checks**

Run:

```powershell
uv --directory apps/api run pytest tests/test_benchmarks.py -q
uv --directory apps/api run ruff check src/stockviz/benchmarks tests/test_benchmarks.py
uv --directory apps/api run ruff format --check src/stockviz/benchmarks tests/test_benchmarks.py
```

Expected: all pass.

- [ ] **Step 8: Commit the validator**

```powershell
git add apps/api/src/stockviz/benchmarks/report.py apps/api/tests/test_benchmarks.py artifacts/benchmarks/.gitignore artifacts/benchmarks/README.md
git commit -m "test: validate portfolio benchmark evidence"
```

### Task 3: Run and preserve the full kind/Strimzi benchmark

**Files:**
- Create: `artifacts/benchmarks/kafka-scaling-100k.json`
- Create: `docs/images/kafka-consumer-throughput.svg`
- Read: `scripts/k8s/run-benchmark.sh`
- Read: `infra/k8s/kafka/kafka.yaml`
- Read: `infra/k8s/kafka/topics.yaml`

**Interfaces:**
- Consumes: unchanged `BENCHMARK_COUNT=100000` and `BENCHMARK_REPLICAS="1 2 4 8"` coordinator invocation.
- Produces: four hard-gated measured rows and one SVG generated from those rows.

- [ ] **Step 1: Verify local lab prerequisites**

Resolve Docker, Git Bash, kind, kubectl, and Helm. If kind or Helm is absent,
download the pinned official executables into an ignored worktree tool
directory; do not add repository dependencies or infrastructure manifests.

- [ ] **Step 2: Build and deploy the existing lab**

Run the equivalent of:

```bash
pnpm k8s:create
pnpm k8s:build
pnpm k8s:deploy
pnpm k8s:smoke
```

Expected: one kind node, Kafka Ready through Strimzi 0.45.1, migration Job
complete before applications, and smoke checks green.

- [ ] **Step 3: Record environment versions from the running lab**

Capture `kind version`, Kubernetes server version, Helm release/chart version,
Kafka CR version, node count, broker count, benchmark topic partition count,
and the local execution date for the benchmark document and final report.

- [ ] **Step 4: Execute the complete benchmark matrix unchanged**

Run:

```bash
BENCHMARK_COUNT=100000 BENCHMARK_REPLICAS="1 2 4 8" pnpm k8s:benchmark
```

Expected: the coordinator exits 0 and writes
`artifacts/benchmarks/kafka-scaling.json`.

- [ ] **Step 5: Validate and preserve the exact output**

Copy the generated file byte-for-byte to
`artifacts/benchmarks/kafka-scaling-100k.json`, run the report CLI against it,
and generate `docs/images/kafka-consumer-throughput.svg`. Do not hand-edit
either artifact.

- [ ] **Step 6: Inspect all hard gates programmatically**

Expected: exactly four rows; replicas `[1,2,4,8]`; every run has 100,000
events collected, zero foreign records, complete true, positive processing
duration, and present throughput/p50/p95/peak lag. Resource measurements may
be `null`.

- [ ] **Step 7: Commit measured evidence**

```powershell
git add artifacts/benchmarks/kafka-scaling-100k.json docs/images/kafka-consumer-throughput.svg
git commit -m "docs: record full Kafka scaling benchmark"
```

### Task 4: Capture and verify genuine application screenshots

**Files:**
- Create: `docs/images/markets.png`
- Create: `docs/images/stock-detail.png`
- Create: `docs/images/trading.png`
- Create: `docs/images/portfolio.png`
- Create: `docs/images/backtest.png` when the resulting screen is meaningful

**Interfaces:**
- Consumes: the running migrated application and seeded demo data.
- Produces: four to five real UI screenshots with no private or machine-specific data.

- [ ] **Step 1: Seed the running lab**

Run `stockviz.cli seed` and `stockviz.cli backfill` in an API pod, then verify
`/v1/symbols` and `/markets` return populated data.

- [ ] **Step 2: Port-forward the real API and web services**

Forward API port 8000 and web port 3000. Confirm `/live`, `/health`, and the
web health route before opening UI pages.

- [ ] **Step 3: Create isolated demo state**

Sign up with a disposable `example.com` address, create the default portfolio,
and submit a small paper trade so authenticated screens contain meaningful
but non-sensitive data.

- [ ] **Step 4: Capture selected pages at a consistent desktop viewport**

Capture markets, AAPL stock detail, trade form, portfolio, and a completed
backtest if the page renders a useful result. Prefer four strong images over
adding weak or repetitive screenshots.

- [ ] **Step 5: Inspect every image**

Open each PNG at full resolution and verify it contains no email address,
token, API key, local path, browser chrome, or private user information. Crop
or recapture rather than blurring fake content into the product UI.

- [ ] **Step 6: Commit screenshots**

```powershell
git add docs/images/*.png
git commit -m "docs: add genuine StockViz screenshots"
```

### Task 5: Rewrite recruiter-facing and architecture documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/EVENT_DRIVEN_ARCHITECTURE.md`
- Modify: `docs/KUBERNETES.md`
- Modify: `docs/KAFKA_SCALING.md`
- Modify: `docs/SETUP.md`
- Modify: `docs/DEPLOYMENT.md`

**Interfaces:**
- Consumes: measured JSON/table/chart, inspected screenshots, and code-backed architecture evidence.
- Produces: recruiter-first README, three focused Mermaid diagrams, and accurate deep-dive docs.

- [ ] **Step 1: Rewrite the README first screen**

Lead with the approved one-sentence product description, a compact screenshot
gallery, a `What makes this project interesting` section, and Diagram A inside
a Kubernetes boundary. Avoid historical rewrite narrative and unverified demo
claims.

- [ ] **Step 2: Explain financial correctness**

Document portfolio row locking, pending-order cash/share reservations,
rollback behavior, and the atomic trade-plus-outbox commit. State explicitly
that Kafka never executes or confirms trades.

- [ ] **Step 3: Explain event delivery and deployment**

Document transactional outbox, at-least-once delivery, consumer inbox,
portfolio/ticker keys, durable scheduler requests, singleton scheduler,
migration Job, independent workers, probes, HPA, Strimzi, and kind CI.

- [ ] **Step 4: Insert the generated benchmark table and chart**

Use a marked benchmark table block exactly matching `markdown_table()`. Link
to `docs/KAFKA_SCALING.md` and show the throughput chart. Do not describe the
curve until the measured rows are visible.

- [ ] **Step 5: Add three setup levels and CI evidence**

Show discoverable commands for simple Postgres/API/web development,
event-driven Compose with Kafka/workers, and the full kind lab. Summarize web,
API, migration, PostgreSQL concurrency, Kafka integration, Playwright, Docker,
and kind/Strimzi gates without fragile exact test counts.

- [ ] **Step 6: Add Diagram B and Diagram C**

Use a Mermaid sequence diagram for trade execution and a separate readable
flowchart for market/news event processing plus reconciliation. Ensure the
trade sequence shows HTTP success after PostgreSQL commit and the later Kafka
path separately.

- [ ] **Step 7: Replace the detailed benchmark result section**

Use the real 100k matrix as the primary table. Explain partition-bounded
parallelism, the unchanged three-partition domain topics, per-key ordering,
diminishing returns, rebalancing, peak versus final lag, and why CPU HPA is a
demonstration while KEDA is only a future possibility.

- [ ] **Step 8: Validate Mermaid and benchmark consistency**

Run Markdown formatting, the report CLI with README and Kafka docs checks,
and `git diff --check`. Inspect Mermaid blocks for GitHub-supported syntax.

- [ ] **Step 9: Commit public architecture documentation**

```powershell
git add README.md docs/EVENT_DRIVEN_ARCHITECTURE.md docs/KUBERNETES.md docs/KAFKA_SCALING.md docs/SETUP.md docs/DEPLOYMENT.md
git commit -m "docs: tell the final StockViz architecture story"
```

### Task 6: Add interview, resume, audit, roadmap, and limitation material

**Files:**
- Create: `docs/INTERVIEW_GUIDE.md`
- Create: `docs/RESUME.md`
- Create: `docs/TECHNICAL_AUDIT.md`
- Create: `docs/ENGINEERING_ROADMAP.md`
- Modify: `docs/KNOWN_LIMITATIONS.md`
- Modify: `docs/SENTIMENT.md` only if claim verification requires it
- Delete: `docs/CODEBASE_REVIEW.md`
- Delete: `docs/IDEAS.md`
- Delete: `REWRITE_PLAN.md`

**Interfaces:**
- Consumes: code-level audit evidence, measured benchmark results, and the final public architecture.
- Produces: owner-facing interview answers, verifiable resume copy, a current audit report, and current limitations only.

- [ ] **Step 1: Complete the reviewer-style code audit**

Trace every required trading, outbox, consumer, market/news, and Kubernetes
invariant to functions, manifests, and tests. Record the evidence and outcome
in `docs/TECHNICAL_AUDIT.md`. If a confirmed bug appears, pause this plan and
add an exact regression-test/minimal-fix amendment naming the affected files;
then run the failing test, implement the fix, rerun its integration boundary,
and document the verified outcome.

- [ ] **Step 2: Write the interview guide**

Answer every required question directly, including both crash windows, Kafka
and PostgreSQL outages, key choices, partition counts, singleton scheduler,
migration Job, readiness versus liveness, HPA limitations, and what a real
production deployment would add but this repository does not contain.

- [ ] **Step 3: Write resume and portfolio copy**

Provide the title, 20–30 word description, SWE/backend/quant variants, short
card copy, medium copy, and 150–200 word technical deep dive. Use only measured
benchmark numbers where the sentence benefits from a concrete result.

- [ ] **Step 4: Replace historical gap/idea material**

Create a concise engineering roadmap containing only remaining honest work,
then remove the stale code-review, idea parking lot, and rewrite-plan files.
Update all inbound links.

- [ ] **Step 5: Rewrite known limitations against current code**

Keep verified provider, options, fills, auth, operational, Kafka, scaling,
observability, cloud, and recommendation constraints. Remove the stale
no-screenshot claim and correct alert scheduling to the market analytics path.

- [ ] **Step 6: Search for stale and promotional wording**

Run case-insensitive searches for Cursor, agent-workflow language, sessions,
implementation phases, `f928`, review prompts, exactly-once, production-ready,
enterprise-grade, battle-tested, highly scalable, stale benchmark counts, and
old provider/scheduler/FX wording. Preserve legitimate provider names and
intentional repository guide files.

- [ ] **Step 7: Commit owner-facing documentation**

```powershell
git add README.md docs REWRITE_PLAN.md
git commit -m "docs: add interview and resume material"
```

### Task 7: Run all local quality and integration gates

**Files:**
- Modify: only files required by confirmed failures attributable to this branch.

**Interfaces:**
- Consumes: the complete feature branch.
- Produces: explicit PASS/FAIL evidence for every requested gate.

- [ ] **Step 1: Run frontend gates**

```powershell
pnpm lint
pnpm typecheck
pnpm --filter @stockviz/web test
pnpm build
```

- [ ] **Step 2: Run API static and unit gates**

```powershell
uv --directory apps/api run ruff check .
uv --directory apps/api run ruff format --check .
uv --directory apps/api run pyright
uv --directory apps/api run pytest
```

- [ ] **Step 3: Run migration gates on PostgreSQL**

```powershell
uv --directory apps/api run alembic upgrade head
uv --directory apps/api run alembic check
uv --directory apps/api run alembic heads
```

Expected: upgrade/check succeed and exactly one head is printed.

- [ ] **Step 4: Run PostgreSQL concurrency and Kafka integration suites**

Run the same files and environment used by the `events-integration` CI job:
`test_pg_concurrency.py`, `test_pg_outbox_claim.py`,
`test_event_contracts_market_news.py`, `test_market_news_pipeline.py`, and
`test_kafka_integration.py` against real PostgreSQL and Kafka.

- [ ] **Step 5: Run Playwright**

Build/start the same seeded application path used in CI and run `pnpm e2e`.
Expected: all browser tests pass.

- [ ] **Step 6: Build both Docker images**

```powershell
docker build -t stockviz-api:portfolio-finalization apps/api
docker build -f apps/web/Dockerfile -t stockviz-web:portfolio-finalization .
```

- [ ] **Step 7: Rerun kind/Strimzi smoke without changing benchmark evidence**

Run the existing smoke script against the deployed lab. The full benchmark
artifact remains the measured run from Task 3; do not replace it with a reduced
smoke result.

- [ ] **Step 8: Revalidate final artifact and docs**

Run the report CLI against the committed JSON, SVG, README, and Kafka scaling
document. Run `git diff --check` and inspect the final file list.

- [ ] **Step 9: Commit any verified gate fixes**

No commit is expected here. A confirmed correctness defect is handled through
the exact plan amendment required in Task 6, Step 1. Formatting-only changes
are included in the final documentation cleanup commit.

### Task 8: Final review, public-tree cleanup, and pull request

**Files:**
- Delete: `docs/superpowers/specs/2026-08-26-portfolio-finalization-design.md`
- Delete: `docs/superpowers/plans/2026-08-26-portfolio-finalization.md`
- Review: every changed file

**Interfaces:**
- Consumes: green local gates and complete measured/documentation artifacts.
- Produces: a clean public repository tree and an open, unmerged PR to `dev`.

- [ ] **Step 1: Perform acceptance-criteria diff review**

Compare the final diff with all 51 acceptance criteria. Confirm no new
infrastructure logo, service, direct Kafka trade publication, partition
change, or production/HA overstatement entered the branch.

- [ ] **Step 2: Remove internal workflow documents**

Delete this implementation plan and its design spec so the final public tree
contains no agent/process artifacts. Preserve the engineering audit and owner
interview guide because they are product documentation.

- [ ] **Step 3: Run final verification after cleanup**

Run `git diff --check`, the benchmark validator/docs check, stale-wording
searches, and the focused web/API tests most affected by documentation tooling.

- [ ] **Step 4: Commit final cleanup**

```powershell
git add -A
git commit -m "chore: finalize portfolio presentation"
```

- [ ] **Step 5: Push the feature branch**

```powershell
git push -u origin feat/portfolio-finalization
```

- [ ] **Step 6: Open the pull request**

Open `feat/portfolio-finalization -> dev` with a concise architecture,
benchmark, screenshots, audit, and CI summary. Do not add AI-agent promotional
boilerplate and do not merge.

- [ ] **Step 7: Wait for and inspect PR checks**

Report each CI job accurately. If a branch-caused failure occurs, fix and
rerun it. Do not mark a skipped, cancelled, or missing check as PASS.

- [ ] **Step 8: Deliver the final report**

Include the requested architecture, environment, full result table,
interpretation, recruiter/interview/resume changes, technical audit, current
limitations, explicit CI matrix, files changed, two repository-story versions,
and the unmerged PR link.
