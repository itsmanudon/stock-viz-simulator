# StockViz Portfolio Finalization Design

## Objective

Turn the existing StockViz implementation into a recruiter-readable and
interviewer-ready portfolio project using measured evidence, accurate
architecture documentation, genuine product screenshots, and a final
correctness audit. The application architecture and financial source-of-truth
boundaries remain unchanged.

## Scope and constraints

- Start from `origin/dev` at the merge of PR #60 and work on
  `feat/portfolio-finalization`.
- Do not add infrastructure, services, financial products, strategies,
  predictive features, or LLM features.
- Keep trading synchronous in FastAPI and PostgreSQL. Kafka remains outside
  the financial commit path.
- Preserve at-least-once publication and idempotent consumption semantics.
- Use a single-node kind cluster, one Strimzi-managed Kafka 3.9.0 broker, and
  the existing 12-partition benchmark topic for the full experiment.
- Describe the Kubernetes implementation as a local/CI deployment reference,
  not a demonstrated production platform.
- Open a pull request to `dev`; do not merge it.

## Evidence-first execution

The full benchmark runs before benchmark copy is finalized. The existing
coordinator runs 100,000 events for consumer replica counts 1, 2, 4, and 8.
It retains the corrected seek-to-end and `run_id` isolation methodology,
current-run timestamp throughput, sampled lag, and `kubectl top` resource
sampling.

Each result must pass these hard gates:

- `events == collected == 100000`
- `foreign_records == 0`
- `complete == true`
- positive `processing_duration_seconds`
- non-null consumer throughput, p50, p95, and peak lag
- resource measurements are either genuine samples or `null`

The generated JSON is preserved as a versioned 100k evidence artifact while
the rolling local output remains ignored. A standard-library Python utility
validates the four-run matrix, generates a clean static throughput chart, and
checks that the README and detailed benchmark tables match the JSON. It does
not recalculate or massage results.

## Public documentation structure

The README is reorganized for three reading depths:

1. The first screen explains the product, the correctness/distributed-systems
   angle, shows genuine screenshots, and includes the system overview.
2. The middle explains financial correctness, Kafka semantics, Kubernetes
   process separation, and concise measured scaling results.
3. The remainder covers features, stack, three setup levels, CI evidence,
   tradeoffs, and known limitations.

Three focused Mermaid diagrams remain distinct:

- system overview: browser, Next.js, FastAPI, PostgreSQL, outbox, Kafka,
  workers, and the Kubernetes boundary;
- trade execution sequence: row lock, reservation validation, ledger writes,
  trade/outbox atomic commit, later publication and derived consumption;
- market/news pipeline: scheduler request outbox, Kafka ingestion, PostgreSQL
  domain writes/events, analytics/sentiment, and scheduled reconciliation.

Detailed public artifacts include:

- `docs/KAFKA_SCALING.md` for methodology and honest interpretation;
- `docs/EVENT_DRIVEN_ARCHITECTURE.md` for event boundaries and sequences;
- `docs/KUBERNETES.md` for the deployment/operator view;
- `docs/INTERVIEW_GUIDE.md` for failure-mode and design walkthroughs;
- `docs/RESUME.md` for verified resume bullets and portfolio copy;
- `docs/KNOWN_LIMITATIONS.md` for current constraints only;
- `docs/TECHNICAL_AUDIT.md` for the reviewer-style final audit;
- `docs/ENGINEERING_ROADMAP.md` for remaining work, replacing stale historical
  gap and idea material where useful.

Historical rewrite/review material that reads as implementation-process noise
is retired from the final public tree. Provider names such as Anthropic Claude
remain where they describe actual configured behavior; agent-workflow wording
does not.

## Screenshots and visuals

Run the real application against migrated, seeded demo data. Create a fresh
non-sensitive demo account for authenticated screens. Capture four to six
useful views from the actual UI, prioritizing markets, stock detail, trading,
portfolio, and backtest results. Inspect every image for emails, tokens, keys,
machine paths, and private data before committing it under `docs/images/`.

The benchmark throughput chart is generated directly from the preserved JSON.
It uses consumer replicas on the x-axis and consumer events per second on the
y-axis. Peak lag and resource measurements stay in tables rather than being
combined into an unreadable chart.

## Correctness audit

The audit traces code and tests rather than trusting existing prose.

- Trading: portfolio locking for all cash mutations, reservation accounting,
  cancellation/fill serialization, no direct Kafka publication, atomic trade
  and outbox insertion.
- Outbox: claim concurrency, broker acknowledgement before `published_at`,
  retry behavior, and duplicate-publication failure window.
- Consumers: transaction boundaries, inbox receipts, DB commit before offset
  commit, and separation from financial source-of-truth state.
- Market/news: durable scheduler requests, provider calls outside financial
  paths, atomic domain writes/output events, and reconciliation jobs.
- Kubernetes: migration ordering, singleton scheduler, probe semantics,
  least-privilege secret mounting, HPA partition ceiling, and non-localhost
  in-cluster dependencies.

Only confirmed correctness defects are fixed. Documentation inaccuracies are
corrected directly and recorded in the technical audit.

## Verification

Run the requested local gates for frontend lint/typecheck/unit/build, API
ruff/format/pyright/pytest, Alembic upgrade/check/heads, PostgreSQL concurrency,
trade/market/news Kafka integration, Playwright, both Docker images, kind and
Strimzi smoke, and the full benchmark. Capture command output or PR check links
as evidence. A failure is reported as a failure until corrected and rerun.

After all local evidence is green, inspect the final diff for stale claims,
internal process wording, accidental infrastructure additions, fabricated
metrics, and production overstatement. Push the feature branch, open the PR
against `dev`, wait for required checks, and leave the PR unmerged.

