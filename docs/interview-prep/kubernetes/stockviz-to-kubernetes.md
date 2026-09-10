# Kubernetes, mapped to StockViz

> **Before this note:** read [KUBERNETES.md](../../KUBERNETES.md) (the
> canonical manifest walkthrough) and
> [Architecture overview](../../architecture/overview.md).
> **Source:** `infra/k8s/` — `base/app/`, `base/scale/`, `base/migrate/`,
> `kafka/`, `overlays/kind/`.

Kubernetes here is a **kind lab**, validated in CI
(`.github/workflows/k8s-smoke.yml`), not a production control plane. Say
that plainly in interviews; the manifests are real and the honesty is
worth more than an inflated claim.

## Why Kubernetes is justified for this system

The usual objection — "you have one app, you don't need Kubernetes" — does
not apply cleanly here, and knowing why is the point:

StockViz is **ten independent processes** with different scaling
characteristics, different failure modes, and a strict singleton
(`Architecture overview`). Compose can run them; it cannot express "this
one must never have two replicas", "these scale on load up to the
partition count", "migrations run once before anything else starts", or
"drain this pod without dropping requests". Those are the constraints
Kubernetes objects exist to encode.

## Workload → object mapping

| StockViz process | Object | Replicas | Why this object |
| --- | --- | --- | --- |
| API | Deployment + Service + HPA + PDB | 2–5 | Stateless, load-scaled, needs stable in-cluster DNS |
| Web | Deployment + Service | fixed | Stateless |
| Scheduler | Deployment | **1, never more** | Cron singleton — see below |
| Outbox publisher | Deployment | 1 | Safe to scale (`SKIP LOCKED`), but 1 is enough |
| 6 Kafka consumers | Deployment each | 1–3 | Independent failure and scaling per stream |
| Migrations | **Job** | run-once | Must complete before app pods; not a long-running process |
| Kafka | Strimzi `Kafka` CR | 1 broker | Operator owns a stateful system |
| Postgres (kind only) | Deployment + PVC | 1 | Lab only; production uses managed Postgres |

### Why migrations are a Job, not an initContainer

If every API pod ran `alembic upgrade head` at startup, five replicas
would race on the same schema. As a Job it runs **once**, and the
Kustomize layering (`bootstrap → migrate → app → scale`) enforces the
ordering. The API image's default command *does* include the migration —
that's for Render, where there is one instance — and Kubernetes
deliberately **overrides the command per workload** so API pods neither
migrate nor schedule.

**Interview-worthy:** one image, different commands per workload, with
the risky startup behaviour overridden where replica count makes it
unsafe.

### Why the scheduler cannot scale

APScheduler fires in-process. Two replicas = two firings of
`pending_orders_settlement` = **the same order filled twice**. Real money
semantics, in a system that models money.

Two defences, deliberately layered:

1. **Deployment with `replicas: 1`** — the structural guarantee.
2. **Postgres advisory locks** (`scheduler.py::single_instance`,
   `pg_try_advisory_lock(sha256(job_id))`) — defence in depth.

The second exists because Kubernetes' guarantee is weaker than it looks: a
Deployment can briefly run two pods during a rolling update or a node
partition. `replicas: 1` is not mutual exclusion. This is the answer to
"is `replicas: 1` enough?" — **no**, and knowing why separates people who
have run this from people who have read about it.

(A StatefulSet would give at-most-one semantics more strictly, but the
advisory lock is cheaper and the scheduler has no need for stable identity
or storage.)

## Probes

```yaml
livenessProbe:  { httpGet: { path: /live,   port: http } }
readinessProbe: { httpGet: { path: /health, port: http } }
```

| Probe | Endpoint | Touches DB? | Failure means |
| --- | --- | --- | --- |
| Liveness | `/live` | **No** | Process is wedged → restart |
| Readiness | `/health` | Yes (`SELECT 1`) | Can't serve → leave the Service, **don't** restart |

**This split is the single most interview-valuable thing in the K8s
config.** If liveness probed the database, a Postgres blip would restart
every API pod at once — turning a recoverable dependency failure into a
self-inflicted outage, and adding a reconnect storm to an already
struggling database. The distinction is written into the endpoint
docstrings in `routers/health.py`.

What's missing: **no `startupProbe`.** With
`initialDelaySeconds: 10` on liveness, a slow first boot could be killed
before it finishes. Not a problem at current startup times, but it's the
honest gap to name if asked.

## Rolling updates and disruption

```yaml
strategy:
  rollingUpdate: { maxUnavailable: 0, maxSurge: 1 }
terminationGracePeriodSeconds: 30
```

`maxUnavailable: 0` means capacity never dips during a deploy — a new pod
must be Ready before an old one goes. Combined with readiness gating on
the database, a deploy into a broken database stalls rather than replacing
healthy pods with unhealthy ones. That is the correct failure mode.

A **PodDisruptionBudget** (`base/scale/api-pdb.yaml`) protects against
*voluntary* disruption — node drains, cluster upgrades — which the
Deployment strategy does not cover. Two different mechanisms for two
different kinds of disruption; conflating them is a common interview
stumble.

### Graceful shutdown

Workers install SIGTERM/SIGINT handlers (`dispatcher.py::run_loop`) that
set a stop flag, finish the current record, and close the consumer — which
triggers a clean group leave rather than waiting for a session timeout.
That is what makes the 30-second grace period meaningful rather than
decorative.

## Configuration and secrets

| Kind | Object | Contents |
| --- | --- | --- |
| Non-secret | ConfigMap `stockviz-config` | Kafka bootstrap, feature flags, `ENABLE_SCHEDULER` |
| Secret | `stockviz-db`, `stockviz-auth`, `stockviz-market`, `stockviz-news`, `stockviz-sentiment` | `DATABASE_URL`, `INTERNAL_API_TOKEN`, provider keys |

These are **base64 in git for the kind lab** — not encrypted, not managed.
Say so. Production wants External Secrets Operator or Sealed Secrets, and
this is in [KNOWN_LIMITATIONS.md](../../KNOWN_LIMITATIONS.md).

Secrets are split by concern, so a worker that needs a news key does not
receive the database URL. That is real least-privilege, cheaply done.

## Security context

```yaml
automountServiceAccountToken: false
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  seccompProfile: { type: RuntimeDefault }
  allowPrivilegeEscalation: false
  capabilities: { drop: [ALL] }
```

Every one of these is a real hardening default, and
`automountServiceAccountToken: false` is the one most projects forget —
none of these pods talks to the Kubernetes API, so mounting a token only
creates an escalation path from a compromised container.

**Missing:** `NetworkPolicy`. Any pod can reach Postgres and Kafka
directly. In a namespace this small it is low-risk, but naming it is
better than being caught by it.

## What is genuinely absent

| Absent | Honest position |
| --- | --- |
| Multi-node / multi-zone HA | Single kind node; RF=1 Kafka. No HA claim |
| NetworkPolicies | Not present |
| RBAC beyond defaults | Not needed — token automount is off |
| Managed secrets | Base64 in git, lab only |
| Ingress in the default path | `optional/ingress.yaml` exists; kind uses port-forward |
| Lag-based autoscaling | CPU only; wrong signal for I/O-bound consumers |
| Canary / blue-green | Rolling updates only |

## Interview questions

**Foundation — "Why a Deployment rather than bare Pods?"**
> ReplicaSet-managed lifecycle: declarative replica count, rescheduling on
> node loss, and rolling updates with rollback. A bare Pod that dies stays
> dead.

**Strong SWE — "Why is your scheduler `replicas: 1`, and is that enough?"**
> It's a cron singleton — two replicas would settle the same pending order
> twice. And no, it isn't enough: a rolling update or node partition can
> briefly run two pods. So every job also takes a Postgres advisory lock.
> Kubernetes gives me *approximately* one; the lock gives me *at most* one.

**Strong SWE — "Why do your two probes hit different endpoints?"**
> Liveness must not depend on an external dependency. If `/live` touched
> Postgres, a database blip would restart every API pod simultaneously and
> hammer it with reconnects. Readiness *should* depend on it, so a pod
> without a database leaves the Service and comes back when it recovers —
> no restart.

**Advanced — "Your consumer HPA maxes at 3. Why not 10?"**
> The topic has 3 partitions and a consumer group can't have more active
> members than partitions. Pods 4–10 would consume nothing while still
> holding Postgres connections. The HPA ceiling is deliberately pinned to
> `MARKET_TOPIC_PARTITIONS`.

**Advanced — "How would you make this production-ready?"**
> Managed Postgres and Kafka with real replication; multi-zone nodes;
> NetworkPolicies; External Secrets; lag-based autoscaling via KEDA; a
> startupProbe; and metrics/alerting, which is the biggest gap — today
> there's no lag or backlog signal at all.

## Memorise vs understand

**Memorise:** liveness ≠ readiness; consumers ≤ partitions;
`maxUnavailable: 0`; PDB covers voluntary disruption; Job for migrations.

**Understand:** why `replicas: 1` is not mutual exclusion; why probing a
dependency in liveness is an outage amplifier; why one image with
per-workload commands beats one image with one risky startup script.
