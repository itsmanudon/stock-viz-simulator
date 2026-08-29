# StockViz documentation

Entry point for the engineering knowledge base. StockViz is a two-app
pnpm + uv monorepo: a Next.js 16 web app (`apps/web`) and a FastAPI +
SQLModel API (`apps/api`), with PostgreSQL as the system of record, Kafka
for asynchronous market/news/activity processing, and a Kustomize +
Strimzi Kubernetes lab under `infra/k8s`.

New here? Read [Local setup](./SETUP.md), then
[Architecture overview](./architecture/overview.md), then
[Request lifecycle](./architecture/request-lifecycle.md).

## Getting started

| Doc | What it answers |
| --- | --- |
| [SETUP.md](./SETUP.md) | Install, env files, Postgres, migrations, seed, dev servers, ports, common issues |
| [Architecture overview](./architecture/overview.md) | What the pieces are and which process owns what |
| [Request lifecycle](./architecture/request-lifecycle.md) | Five end-to-end traces through real files and functions |

## Architecture

| Doc | What it answers |
| --- | --- |
| [Architecture overview](./architecture/overview.md) | Process inventory, service boundaries, sync vs async split |
| [Request lifecycle](./architecture/request-lifecycle.md) | Browser → Next.js → FastAPI → service → Postgres, and the ingest path |
| [EVENT_DRIVEN_ARCHITECTURE.md](./EVENT_DRIVEN_ARCHITECTURE.md) | Outbox/inbox, topics, keys, transaction boundaries, delivery semantics |
| [SIMULATION.md](./SIMULATION.md) | Execution kernel, determinism, replay sessions, forensics |

## Backend and domain

| Doc | What it answers |
| --- | --- |
| [apps/api/CLAUDE.md](../apps/api/CLAUDE.md) | API layout, scheduler jobs, trading domain rules, ingest contract |
| [apps/web/CLAUDE.md](../apps/web/CLAUDE.md) | Web layout, server/client boundaries, auth |
| [OPERATIONAL_TRADING.md](./OPERATIONAL_TRADING.md) | Trade, Orders, Watchlist, Alerts loop |
| [RESEARCH.md](./RESEARCH.md) | Compare, Backtest, Signals workspace |
| [SENTIMENT.md](./SENTIMENT.md) | Provider abstraction, wire contract, storage, aggregation |

## Data and persistence

| Doc | What it answers |
| --- | --- |
| [Schema and indexing](./database/schema.md) | Keys, indexes, the market-data model, and what gets slow at scale |
| [Market-data semantics](./database/market-data.md) | Timestamps, sessions, splits, adjusted prices, idempotent ingest |

## Infrastructure

| Doc | What it answers |
| --- | --- |
| [KUBERNETES.md](./KUBERNETES.md) | Process inventory, probes, HPA, PDB, Strimzi, kind walkthrough |
| [KAFKA_SCALING.md](./KAFKA_SCALING.md) | Measured consumer-group scaling, partition ceilings, methodology |
| [DEPLOYMENT.md](./DEPLOYMENT.md) | Render + Vercel deploy, secrets, verification, rollback |

## Operations

| Doc | What it answers |
| --- | --- |
| [Runbooks index](./operations/runbooks.md) | Which runbook to open for which symptom |
| [Consumer lag / stalled partition](./operations/runbooks/kafka-consumer-stalled.md) | A partition stops advancing |
| [Outbox backlog](./operations/runbooks/outbox-backlog.md) | `published_at` stays NULL and grows |
| [Stale market data](./operations/runbooks/stale-market-data.md) | Prices stop updating |
| [Postgres connection exhaustion](./operations/runbooks/postgres-connections.md) | API 500s under load |

## Observability

| Doc | What it answers |
| --- | --- |
| [Observability](./observability/overview.md) | What telemetry exists today, what does not, and how to debug without it |

## Architecture decisions

| Doc | Decision |
| --- | --- |
| [ADR index](./adr/README.md) | How ADRs are used here |
| [ADR-0001](./adr/ADR-0001-postgres-as-system-of-record.md) | PostgreSQL is the ledger; Kafka is not |
| [ADR-0002](./adr/ADR-0002-transactional-outbox.md) | Transactional outbox over dual writes |
| [ADR-0003](./adr/ADR-0003-consumer-inbox-idempotency.md) | Durable inbox keys for at-least-once consumers |
| [ADR-0004](./adr/ADR-0004-no-redis.md) | No Redis — and what fills its role instead |
| [ADR-0005](./adr/ADR-0005-rewind-on-handler-failure.md) | Rewind a failed record rather than skip it |

## Status and boundaries

| Doc | What it answers |
| --- | --- |
| [KNOWN_LIMITATIONS.md](./KNOWN_LIMITATIONS.md) | Code-verified boundaries — read before claiming a capability |
| [ENGINEERING_ROADMAP.md](./ENGINEERING_ROADMAP.md) | Honest production hardening that is *not* implemented |
| [TECHNICAL_AUDIT.md](./TECHNICAL_AUDIT.md) | Audit outcome for the last milestone |

## Interview preparation

Repository-grounded study material built *on top of* the docs above —
concepts, trade-offs, failure scenarios, and question banks, linking back
to canonical docs rather than restating them:

**[Interview Preparation Hub](./interview-prep/README.md)**

Also: [INTERVIEW_GUIDE.md](./INTERVIEW_GUIDE.md) (the original code-grounded
walkthrough) and [RESUME.md](./RESUME.md) (claim boundaries for portfolio copy).

## Documentation conventions

- **Canonical docs** (everything outside `interview-prep/`) describe the
  system as built, for contributors and operators. No interview questions,
  no study notes.
- **Interview-prep docs** teach transferable concepts and link back to
  canonical docs and source. They must not become a second, drifting copy
  of the architecture.
- Every claim should be checkable against a file path or a command. If
  rationale cannot be established from the repository, say so rather than
  inventing it.
- A change that makes a doc wrong is not finished until the doc changes too.
