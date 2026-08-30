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
| Testing strategy | 620 pytest, pg_scratch, Playwright, k8s smoke | [strategy](../testing/strategy.md) | [testing/](./testing/testing-distributed-systems.md) | ✅ | ✅ |
| Security & threat model | auth bridge, secrets, hardening | [security/](../security/threat-model.md) | [security/](./security/auth-and-threats.md) | ✅ | ✅ |
| System design | 3 exercises vs. real architecture | — | [system-design/](./system-design/README.md) | ✅ | ✅ |
| Docker | `apps/*/Dockerfile`, compose | [docker](../infrastructure/docker.md) | [docker/](./docker/images-and-layers.md) | ✅ | ✅ |
| Networking | Services, Ingress, CORS, proxy headers | [networking](../infrastructure/networking.md) | [networking/](./networking/service-discovery-and-proxies.md) | ✅ | ✅ |
| Performance | benchmark harness, 100k scaling matrix | [KAFKA_SCALING](../KAFKA_SCALING.md) | [performance/](./performance/reading-the-scaling-curve.md) | ✅ | ✅ |
| Frontend/backend boundary | server-only, two clients, retry policy | [boundary](../architecture/frontend-backend-boundary.md) | [frontend/](./frontend/server-client-boundary.md) | ✅ | ✅ |
| **Redis / caching** | **none in repo** | [ADR-0004](../adr/ADR-0004-no-redis.md) | — | ✅ | ➖ |

## Suggested next iterations

The breadth-first pass is complete: every major subsystem now has a
canonical doc and a study note. Remaining work is depth and upkeep.

1. **Close the open findings** in [FINDINGS.md](./FINDINGS.md). F-011
   (plausibility bounds on ingested prices) is **done** —
   `services/ingest/screening.py` rejects impossible bars and quarantines
   implausible ones. F-002 (DLQ) and F-003/F-012 (shared store for rate
   limits and login throttling) are the two remaining with real
   architectural substance.
2. **Observability** stays 🟡 until the system grows metrics. Adding
   consumer lag and outbox-backlog gauges would close both the biggest
   operational gap and the biggest curriculum gap at once.
3. **Rehearse out loud.** The material is written; the remaining work is
   delivery. Start with
   [explain-stockviz-in-interviews](./explain-stockviz-in-interviews.md),
   then the repository-specific question bank.
4. **Keep it honest.** Any change to auth, trading semantics, event
   contracts, or infrastructure must update the canonical doc in the same
   PR, or this hierarchy becomes the thing it was built to replace.

## Notes on scope

- **Redis is marked ➖ deliberately.** It does not exist in this
  repository. [ADR-0004](../adr/ADR-0004-no-redis.md) explains what fills
  its role and how to answer the question honestly.
- **Observability is 🟡 permanently** until the system grows metrics. The
  doc is written as a gap analysis, which is the accurate framing.
