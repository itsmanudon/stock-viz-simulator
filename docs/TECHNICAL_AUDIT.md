# Final technical audit

Audit date: 2026-08-26. Scope: trading correctness, transactional outbox, Kafka consumers, market/news processing, Kubernetes manifests/scripts, CI, and public documentation. This is a repository review, not a production security or capacity certification.

## Outcome

No new financial or event-delivery correctness defect was found. The implemented invariants remain intact. The issues discovered were presentation/evidence defects: stale in-process-scheduler wording, obsolete 3,000-event benchmark rows, historical phase/process documents exposed as current guidance, and hosting language that did not clearly separate source-controlled intent from the demonstrated kind environment. Those documentation issues were corrected in this milestone.

## Trading

| Check                                 | Result   | Evidence in design                                                                                                             |
| ------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Cash mutations use required locking   | Verified | Trading, order fill/cancel, dividend, option, and expiry paths lock the portfolio before changing cash.                        |
| Reservations prevent overcommit       | Verified | Pending buys reduce available buying power; pending sells reserve available shares. Fill and cancellation re-check under lock. |
| Cancellation/fill races are safe      | Verified | Competing paths lock the relevant portfolio/order state and revalidate status before mutation.                                 |
| Trading routes publish Kafka directly | No       | Routes call the synchronous service; the transaction writes an outbox row.                                                     |
| Trade and outbox are atomic           | Verified | Ledger mutations, trade insert, and `trade.executed` outbox insert share the request transaction and rollback boundary.        |

## Outbox

| Check                                         | Result                                                                     |
| --------------------------------------------- | -------------------------------------------------------------------------- |
| Publication is at least once                  | Verified; duplicate publication is possible after ack-before-update crash. |
| `published_at` follows broker acknowledgement | Verified.                                                                  |
| Failures remain retryable                     | Verified; an unacknowledged row is not marked published.                   |
| Publisher concurrency is safe                 | Verified; row claiming uses database locking with skip-locked behavior.    |

## Consumers

| Check                                                       | Result                                                               |
| ----------------------------------------------------------- | -------------------------------------------------------------------- |
| Database commit precedes offset commit                      | Verified.                                                            |
| Inbox idempotency is durable and atomic with derived writes | Verified.                                                            |
| Derived consumers mutate cash, positions, or orders         | No; financial source-of-truth state stays outside derived consumers. |

## Market and news

| Check                                      | Result                                                                                  |
| ------------------------------------------ | --------------------------------------------------------------------------------------- |
| Scheduler emits durable requests           | Verified; market/news refresh commands enter the PostgreSQL outbox.                     |
| Provider calls are outside financial paths | Verified.                                                                               |
| Ingestion data plus output event is atomic | Verified; persisted results and their domain-event intent share a database transaction. |
| Intended reconciliation exists             | Verified for symbol metrics and sentiment aggregates.                                   |

## Kubernetes

| Check                                                 | Result                                                           |
| ----------------------------------------------------- | ---------------------------------------------------------------- |
| Migration completes before application rollout        | Verified in deployment orchestration.                            |
| Scheduler is singleton and separate from API replicas | Verified.                                                        |
| `/live` and `/health` semantics are distinct          | Verified; liveness is process-only, readiness checks PostgreSQL. |
| Worker secrets are scoped by role                     | Verified in workload manifests.                                  |
| Market-ingest HPA respects partition ceiling          | Verified; maximum three replicas for three domain partitions.    |
| Application images assume localhost dependencies      | No; cluster endpoints come from configuration.                   |

## Issues fixed in this milestone

- Replaced stale README language implying all background work runs inside the API with the actual split scheduler/worker architecture.
- Replaced obsolete reduced benchmark numbers and empty 4/8 rows with a validated 100,000-event matrix.
- Added generated-table validation so README and benchmark documentation cannot silently drift from the JSON artifact.
- Reframed kind, Strimzi, Render, and Vercel statements to distinguish demonstrated local/CI behavior from configured deployment intent.
- Retired public rewrite/review/idea work logs and replaced their useful forward-looking content with a concise current roadmap and limitations.
- Made the Playwright base URL and web-server command overridable while retaining CI defaults, so local port collisions do not route tests to an unrelated application.

## Deliberately unchanged

The audit did not move trade execution to Kafka, change domain topic partitions, add infrastructure, refactor speculative code, or alter delivery semantics. PostgreSQL remains the financial source of truth and Kafka remains an at-least-once asynchronous transport.
