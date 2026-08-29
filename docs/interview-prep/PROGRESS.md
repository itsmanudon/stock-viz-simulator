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
| Docker | `apps/*/Dockerfile`, compose | [DEPLOYMENT](../DEPLOYMENT.md) | ⬜ | ⬜ | 🟡 |
| Networking | Services, Ingress, CORS, proxy headers | [KUBERNETES](../KUBERNETES.md) | ⬜ | ⬜ | ⬜ |
| Performance | benchmark harness | [KAFKA_SCALING](../KAFKA_SCALING.md) | ⬜ | ⬜ | 🟡 |
| **Redis / caching** | **none in repo** | [ADR-0004](../adr/ADR-0004-no-redis.md) | — | ✅ | ➖ |

## Suggested next iterations

1. **Networking** — Services and cluster DNS, `--proxy-headers` and the
   forwarded chain, CORS configuration, Ingress, and the north-south vs.
   east-west distinction.
2. **Docker study note** — multi-stage `uv` builds, one image with
   per-workload commands, and why the web image refuses dev secrets under
   `NODE_ENV=production`.
3. **Performance** — read [KAFKA_SCALING.md](../KAFKA_SCALING.md) closely;
   the 1→2→4→8 replica curve (including the 5.6% regression at eight) is
   good material for a "how do you know?" conversation.
4. **Frontend/backend boundary** — server components, the `server-only`
   boundary, and where rendering happens. Weakest area of the curriculum.
5. **Close the open findings** in [FINDINGS.md](./FINDINGS.md) — F-002
   (DLQ) and F-003 (shared rate-limit store) are the two with real
   engineering substance.

## Notes on scope

- **Redis is marked ➖ deliberately.** It does not exist in this
  repository. [ADR-0004](../adr/ADR-0004-no-redis.md) explains what fills
  its role and how to answer the question honestly.
- **Observability is 🟡 permanently** until the system grows metrics. The
  doc is written as a gap analysis, which is the accurate framing.
