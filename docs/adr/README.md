# Architecture decision records

Short records of decisions that shaped StockViz, written **from repository
evidence**. Where the original rationale cannot be established from code,
comments, or docs, the ADR says so rather than inventing one.

Format: Context · Decision · Alternatives considered · Consequences · Status.

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](./ADR-0001-postgres-as-system-of-record.md) | PostgreSQL is the ledger; Kafka is not | Accepted |
| [0002](./ADR-0002-transactional-outbox.md) | Transactional outbox instead of dual writes | Accepted |
| [0003](./ADR-0003-consumer-inbox-idempotency.md) | Durable inbox keys for at-least-once consumers | Accepted |
| [0004](./ADR-0004-no-redis.md) | No Redis | Accepted |
| [0005](./ADR-0005-rewind-on-handler-failure.md) | Rewind a failed record rather than skip it | Accepted |

These are retrospective records of decisions visible in the code. They are
not a changelog — see git history for that.
