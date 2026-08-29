# Curriculum progress

Status of the interview-prep curriculum. Update as topics are covered.

**Legend:** ✅ done · 🟡 partial · ⬜ not started · ➖ not applicable to this repo

## Coverage

| Topic | Repo mapping | Canonical doc | Study note | Questions | Status |
| --- | --- | --- | --- | --- | --- |
| Architecture & boundaries | 10 processes, sync/async split | [overview](../architecture/overview.md) | in canonical | ✅ | ✅ |
| Request lifecycle | 5 traced flows | [request-lifecycle](../architecture/request-lifecycle.md) | in canonical | ✅ | ✅ |
| Outbox / dual write | `events/outbox.py` | [ADR-0002](../adr/ADR-0002-transactional-outbox.md) | [kafka/](./kafka/outbox-and-delivery.md) | ✅ | ✅ |
| Idempotency / inbox | `events/inbox.py`, `handlers.py` | [ADR-0003](../adr/ADR-0003-consumer-inbox-idempotency.md) | [kafka/](./kafka/outbox-and-delivery.md#the-inbox-half) | ✅ | ✅ |
| Partitions / keys / lag | `events/contracts/`, HPA | [KAFKA_SCALING](../KAFKA_SCALING.md) | [kafka/](./kafka/partitions-and-consumer-groups.md) | ✅ | ✅ |
| Kubernetes | `infra/k8s/` | [KUBERNETES](../KUBERNETES.md) | [kubernetes/](./kubernetes/stockviz-to-kubernetes.md) | ✅ | ✅ |
| Indexes & keys | `models/` | [schema](../database/schema.md) | [databases/](./databases/indexes-and-keys.md) | ✅ | ✅ |
| Transactions & locking | `services/trading/execute.py` | [schema](../database/schema.md#concurrency) | [databases/](./databases/transactions-and-locking.md) | ✅ | ✅ |
| Market-data semantics | `services/ingest/prices.py` | [market-data](../database/market-data.md) | in canonical | ✅ | ✅ |
| Distributed-systems failures | dispatcher, scheduler, ledger | [ADR-0005](../adr/ADR-0005-rewind-on-handler-failure.md) | [distributed-systems/](./distributed-systems/failure-scenarios.md) | ✅ | ✅ |
| Code patterns | 10 extracts | — | [code-patterns/](./code-patterns/README.md) | ✅ | ✅ |
| Production debugging | 6 drills | [runbooks](../operations/runbooks.md) | [production-debugging/](./production-debugging/incident-drills.md) | ✅ | ✅ |
| Project deep dive | whole repo | — | [explain-…](./explain-stockviz-in-interviews.md) | ✅ | ✅ |
| Observability | Sentry + probes only | [observability](../observability/overview.md) | ⬜ | 🟡 | 🟡 |
| Docker | `apps/*/Dockerfile`, compose | [DEPLOYMENT](../DEPLOYMENT.md) | ⬜ | ⬜ | 🟡 |
| Networking | Services, Ingress, CORS, proxy headers | [KUBERNETES](../KUBERNETES.md) | ⬜ | ⬜ | ⬜ |
| Security / threat model | auth bridge, secrets, securityContext | ⬜ | ⬜ | 🟡 | ⬜ |
| Testing strategy | ~300 pytest, Playwright, CI | ⬜ | ⬜ | ⬜ | ⬜ |
| System design exercises | — | ⬜ | ⬜ | ⬜ | ⬜ |
| Performance | benchmark harness | [KAFKA_SCALING](../KAFKA_SCALING.md) | ⬜ | ⬜ | 🟡 |
| **Redis / caching** | **none in repo** | [ADR-0004](../adr/ADR-0004-no-redis.md) | — | ✅ | ➖ |

## Suggested next iterations

1. **Testing strategy** (`docs/testing/strategy.md` + study note) — the
   repo has ~300 pytest tests, a Postgres-scratch harness, Playwright
   e2e, and a k8s smoke workflow. Currently undocumented as a strategy,
   and "how do you test a distributed pipeline?" is a common question.
2. **Security / threat model** (`docs/security/`) — the auth bridge,
   secret handling, rate limiting, and container hardening exist but
   there's no consolidated threat model.
3. **System-design exercises** — design market-data ingestion, real-time
   price delivery, and a backtesting service, then compare each against
   what StockViz actually does.
4. **Networking** — Services, DNS, `--proxy-headers`, CORS, Ingress.
5. **Docker study note** — multi-stage uv builds, one image with
   per-workload commands, and why the web image refuses dev secrets in
   production.

## Notes on scope

- **Redis is marked ➖ deliberately.** It does not exist in this
  repository. [ADR-0004](../adr/ADR-0004-no-redis.md) explains what fills
  its role and how to answer the question honestly.
- **Observability is 🟡 permanently** until the system grows metrics. The
  doc is written as a gap analysis, which is the accurate framing.
