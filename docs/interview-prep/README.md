# Interview preparation hub

A repository-grounded engineering curriculum. Every topic is taught
through StockViz first, then generalised.

**This is the learning layer.** It does not re-explain the architecture —
the [canonical docs](../README.md) do that. Each study note links to the
canonical doc and the source file, then adds what documentation
deliberately leaves out: why the design works, what the alternatives were,
how it fails, and how to talk about it.

```
Source code  →  Canonical docs (/docs)  →  Interview docs (you are here)
```

## Start here

1. [Explain StockViz in interviews](./explain-stockviz-in-interviews.md) —
   30-second, 2-minute, and 5-minute versions plus hostile follow-ups.
2. [Architecture overview](../architecture/overview.md) and
   [Request lifecycle](../architecture/request-lifecycle.md) — you cannot
   discuss any of the rest without these.
3. [FINDINGS.md](./FINDINGS.md) — real problems found in this repository
   and what was done about them. The single most credible interview
   material here, because it is work you actually did.

## Roadmap

Study in this order. "Importance" is how often the topic decides a
backend/infra interview outcome.

### Stage 1 — Understand the system (prerequisite for everything)

| Topic | Study note | Canonical doc | Importance |
| --- | --- | --- | --- |
| Architecture and boundaries | — | [overview](../architecture/overview.md) | ★★★ |
| Request lifecycle | — | [request-lifecycle](../architecture/request-lifecycle.md) | ★★★ |
| What the system does *not* do | — | [KNOWN_LIMITATIONS](../KNOWN_LIMITATIONS.md) | ★★★ |

### Stage 2 — Backend foundations

| Topic | Study note | Canonical doc | Importance |
| --- | --- | --- | --- |
| Schema, keys, indexes | [databases/](./databases/indexes-and-keys.md) | [schema](../database/schema.md) | ★★★ |
| Transactions, locking, concurrency | [databases/](./databases/transactions-and-locking.md) | [schema](../database/schema.md#concurrency) | ★★★ |
| Market-data correctness | — | [market-data](../database/market-data.md) | ★★ |
| Auth bridge | [security/](./security/auth-and-threats.md) | [authentication](../security/authentication.md) | ★★ |

### Stage 3 — Distributed systems and messaging

| Topic | Study note | Canonical doc | Importance |
| --- | --- | --- | --- |
| Outbox / dual-write | [kafka/](./kafka/outbox-and-delivery.md) | [ADR-0002](../adr/ADR-0002-transactional-outbox.md) | ★★★ |
| Idempotency and inbox | [kafka/](./kafka/outbox-and-delivery.md#the-inbox-half) | [ADR-0003](../adr/ADR-0003-consumer-inbox-idempotency.md) | ★★★ |
| Partitions, keys, ordering, lag | [kafka/](./kafka/partitions-and-consumer-groups.md) | [KAFKA_SCALING](../KAFKA_SCALING.md) | ★★★ |
| Failure semantics | [distributed-systems/](./distributed-systems/failure-scenarios.md) | [ADR-0005](../adr/ADR-0005-rewind-on-handler-failure.md) | ★★★ |

### Stage 4 — Infrastructure

| Topic | Study note | Canonical doc | Importance |
| --- | --- | --- | --- |
| Kubernetes mapped to StockViz | [kubernetes/](./kubernetes/stockviz-to-kubernetes.md) | [KUBERNETES](../KUBERNETES.md) | ★★★ |
| Probes, scaling, disruption | [kubernetes/](./kubernetes/stockviz-to-kubernetes.md#probes) | [KUBERNETES](../KUBERNETES.md#probes) | ★★★ |
| Docker images and layers | [docker/](./docker/images-and-layers.md) | [docker](../infrastructure/docker.md) | ★★ |
| Service discovery and proxies | [networking/](./networking/service-discovery-and-proxies.md) | [networking](../infrastructure/networking.md) | ★★★ |

### Stage 5 — Production engineering

| Topic | Study note | Canonical doc | Importance |
| --- | --- | --- | --- |
| Observability gaps | — | [observability](../observability/overview.md) | ★★ |
| Incident debugging | [production-debugging/](./production-debugging/incident-drills.md) | [runbooks](../operations/runbooks.md) | ★★★ |
| Testing distributed systems | [testing/](./testing/testing-distributed-systems.md) | [strategy](../testing/strategy.md) | ★★★ |
| Security and threat reasoning | [security/](./security/auth-and-threats.md) | [threat model](../security/threat-model.md) | ★★ |
| Reading a scaling curve | [performance/](./performance/reading-the-scaling-curve.md) | [KAFKA_SCALING](../KAFKA_SCALING.md) | ★★ |
| Server/client boundary | [frontend/](./frontend/server-client-boundary.md) | [boundary](../architecture/frontend-backend-boundary.md) | ★★ |

### Stage 6 — System design

| Topic | Study note | Importance |
| --- | --- | --- |
| Market-data ingestion | [system-design/](./system-design/market-data-ingestion.md) | ★★★ |
| Real-time price delivery | [system-design/](./system-design/real-time-price-delivery.md) | ★★★ |
| Stock alerts at scale | [system-design/](./system-design/stock-alerts.md) | ★★ |

### Stage 7 — Interview delivery

| Topic | Study note |
| --- | --- |
| Project deep dive | [explain-stockviz-in-interviews.md](./explain-stockviz-in-interviews.md) |
| Question bank | [interview-questions/](./interview-questions/README.md) |

## Honest scope

Two things this curriculum will **not** teach you from this repository,
because they are not here:

- **Redis.** There is none. See
  [ADR-0004](../adr/ADR-0004-no-redis.md) for what fills its role and how
  to answer "why no Redis?" — which is a better answer than a bolted-on
  cache would have been.
- **Production observability.** Sentry and health endpoints only. The
  [observability doc](../observability/overview.md) is written as a gap
  analysis for exactly this reason.

Do not claim either in an interview. "We don't have it, here's what we use
instead, and here's what I'd add first" is a stronger answer than a
fabricated one — and an interviewer will find the gap in sixty seconds.

## Progress

See [PROGRESS.md](./PROGRESS.md) for topic coverage and
[FINDINGS.md](./FINDINGS.md) for open engineering issues.
[HANDOFF.md](./HANDOFF.md) carries the current branch's working state.
