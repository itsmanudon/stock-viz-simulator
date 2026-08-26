# Kubernetes

StockViz is still a **modular monolith**: one API codebase, one web codebase.
Kubernetes is how we run the *processes* that already existed — not a set of
new microservices.

This document is the operator view. The event view remains
[`EVENT_DRIVEN_ARCHITECTURE.md`](./EVENT_DRIVEN_ARCHITECTURE.md).

## Why Kubernetes is justified *here*

| Problem in this repo | What Kubernetes gives us |
| --- | --- |
| FastAPI replicas must not all run Alembic | A Job runs `alembic upgrade head` once, then API pods start `uvicorn` only |
| FastAPI replicas must not all run APScheduler | `ENABLE_SCHEDULER=false` on API; a 1-replica scheduler Deployment |
| Market ingest, news sentiment, trade activity are independent bottlenecks | One Deployment per consumer group, scaled on its own |
| Outbox publisher is a singleton drain of Postgres | Its own Deployment, not stuffed into the API |
| Kafka topic partitions cap useful consumer replicas | HPA `maxReplicas: 3` on market-ingest matches `stockviz.market.v1`'s 3 partitions |
| Render's API image also migrates on boot | That CMD stays for Render; Kubernetes **overrides** it |

Kubernetes does **not** make the ledger distributed. Trades still commit in
FastAPI → PostgreSQL (+ outbox) → COMMIT. Kafka stays off that path.

## Process inventory

| Process | Image | Workload | Default replicas | Kafka | Requests | Limits | HPA |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Next.js | `stockviz-web` | Deployment + Service | 1 | — | 100m / 256Mi | 750m / 768Mi | no |
| FastAPI | `stockviz-api` | Deployment + Service | 2 | — | 100m / 256Mi | 750m / 768Mi | 2–5 CPU 70% |
| APScheduler | `stockviz-api` | Deployment | 1 | — | 50m / 128Mi | 500m / 512Mi | no |
| Outbox publisher | `stockviz-api` | Deployment | 1 | producer | 50m / 128Mi | 500m / 512Mi | no |
| Trade activity | `stockviz-api` | Deployment | 1 | `stockviz.trades.v1` / `stockviz.trade-activity.v1` | 50m / 128Mi | 500m / 512Mi | no |
| Market ingest | `stockviz-api` | Deployment | 1 | `stockviz.market.v1` / `stockviz.market-ingestion.v1` | 50m / 128Mi | 500m / 512Mi | 1–3 CPU 70% |
| Market analytics | `stockviz-api` | Deployment | 1 | `stockviz.market.v1` / `stockviz.market-analytics.v1` | 50m / 128Mi | 500m / 512Mi | no |
| News ingest | `stockviz-api` | Deployment | 1 | `stockviz.news.v1` / `stockviz.news-ingestion.v1` | 50m / 128Mi | 500m / 512Mi | no |
| News sentiment | `stockviz-api` | Deployment | 1 | `stockviz.news.v1` / `stockviz.news-sentiment.v1` | 50m / 128Mi | 500m / 512Mi | no |
| Sentiment aggregate | `stockviz-api` | Deployment | 1 | `stockviz.news.v1` / `stockviz.sentiment-aggregate.v1` | 50m / 128Mi | 500m / 512Mi | no |
| Migrate | `stockviz-api` | Job | 1 shot | — | 50m / 128Mi | 500m / 512Mi | — |
| Postgres | `postgres:16-alpine` | Deployment + Service | 1 | — | 50m / 256Mi | 500m / 512Mi | kind/CI only |
| Kafka | Strimzi 0.45.1 / Kafka 3.9.0 | Kafka + KafkaNodePool | 1 broker | KRaft | 100m / 512Mi | 1 CPU / 1Gi | kind/CI only |

Workers do **not** get Services. They do not expose HTTP.

## Deployment diagram

```
Kubernetes namespace stockviz
├── stockviz-web          Deployment/Service   :3000
├── stockviz-api          Deployment/Service   :8000   ENABLE_SCHEDULER=false
├── stockviz-scheduler    Deployment           python -m stockviz.workers.scheduler
├── stockviz-migrate      Job                  alembic upgrade head
├── stockviz-outbox-publisher
├── stockviz-trade-activity
├── stockviz-market-ingest          HPA max 3 (topic has 3 partitions)
├── stockviz-market-analytics
├── stockviz-news-ingest
├── stockviz-news-sentiment
├── stockviz-sentiment-aggregate
├── postgres              kind/CI only — production should be managed Postgres
└── Strimzi Kafka         kind/CI only — 1 KRaft node, RF=1
        └── topics: stockviz.trades.v1 / market.v1 / news.v1 (3 partitions)
                    stockviz.benchmark.v1 / benchmark-results.v1 (12 partitions)
```

kind is a **single machine**. It is not a production control plane.

## kind walkthrough

Prerequisites: Docker, kind, kubectl, Helm, ability to build the two images.

```bash
pnpm k8s:create     # kind cluster + metrics-server (kubelet-insecure-tls)
pnpm k8s:build      # stockviz-api:dev + stockviz-web:dev, kind load
pnpm k8s:deploy     # Strimzi → Kafka Ready → Postgres Ready → migrate Job → apps
pnpm k8s:smoke      # probes, web GET /, topic existence
pnpm k8s:destroy
```

`scripts/k8s/deploy.sh` applies **layers**, not one combined overlay:

1. namespace + Strimzi + Kafka
2. `overlays/kind/bootstrap` — config, split Secrets, Postgres
3. wait until Postgres is Ready (`log "Postgres Ready"`)
4. `overlays/kind/migrate` — `alembic upgrade head` Job (`restartPolicy: Never`)
5. wait until the Job is Complete (`log "Migration Complete"`). Failure stops the script.
6. assert application Deployments are absent on a fresh cluster
7. `log "Application rollout begins"` then `overlays/kind/app`
8. `overlays/kind/scale` — HPA / PDB
9. wait for application rollouts, then smoke

The bootstrap overlay must not create API, web, scheduler, outbox, or Kafka
consumers. `/health` is only `SELECT 1`, so a FastAPI pod can become Ready
against an unmigrated database — that is why migrate is a hard gate.

### Images

Local: `stockviz-api:dev` / `stockviz-web:dev`, `imagePullPolicy: Never`.

CI also tags `stockviz-api:${GITHUB_SHA}` and still loads `:dev` so the overlay
does not need a per-commit kustomize edit.

### NEXT_PUBLIC_API_URL vs API_URL

`NEXT_PUBLIC_API_URL` is baked into the browser bundle **at image build**.
For kind port-forward it must be `http://localhost:8000`. Cluster DNS
`http://stockviz-api:8000` is unreachable from the laptop.

`API_URL` is a **runtime** server-side env on the web pod:
`http://stockviz-api:8000`.

A real hosted deploy must rebuild the web image with the public API URL.

### Secrets

Kind dummy credentials are split by concern and annotated
`stockviz.io/scope: kind-dev-only`. Do not copy them to production.

| Secret | Keys | Who mounts them |
| --- | --- | --- |
| `stockviz-db` | `DATABASE_URL`, `POSTGRES_PASSWORD` | Postgres, migrate, API, web, scheduler, all DB-backed workers |
| `stockviz-auth` | `INTERNAL_API_TOKEN`, `AUTH_SECRET` | API (`INTERNAL_API_TOKEN` only), web (both) |
| `stockviz-market-provider` | `ALPHA_VANTAGE_KEY` | market-ingest |
| `stockviz-news-provider` | `NEWSDATA_KEY` | news-ingest |
| `stockviz-sentiment-provider` | `ANTHROPIC_API_KEY` | news-sentiment |

Workers no longer `envFrom` a single `stockviz-secrets` blob. Kafka bootstrap
is on the non-secret ConfigMap. Production belongs in a sealed secret store
that is out of scope for this milestone.

### Ingress

`infra/k8s/optional/ingress.yaml` is optional. CI does not install
ingress-nginx. Default access:

```bash
kubectl -n stockviz port-forward svc/stockviz-api 8000:8000
kubectl -n stockviz port-forward svc/stockviz-web 3000:3000
```

## Probes

| Probe | Endpoint | Depends on | Why |
| --- | --- | --- | --- |
| API liveness | `GET /live` | nothing | A Postgres blip must not kill the API process |
| API readiness | `GET /health` | PostgreSQL | Unready pods leave the Service until the DB is back |
| Web liveness/readiness | `GET /api/health` | nothing | Homepage SSR is not a probe; it fans out to `/v1` |

Render still uses `/health` as `healthCheckPath`. That contract is unchanged.

Kubernetes sets `HOSTNAME` to the pod name. Next's standalone server listens
on that env var, so the web image/command forces `HOSTNAME=0.0.0.0` or
kubelet probes to the pod IP never succeed.

## Scheduler separation

**Before:** FastAPI lifespan started APScheduler when `ENABLE_SCHEDULER=true`.
Two API replicas meant two schedulers; advisory locks were the only safety.

**After (Kubernetes):** API pods set `ENABLE_SCHEDULER=false`. A dedicated
Deployment runs `python -m stockviz.workers.scheduler` with `replicas: 1`.
Advisory locks remain defense-in-depth. Render can still run the scheduler
in-process.

The scheduler still only enqueues outbox control events for market/news.
It does not publish to Kafka and does not settle the ledger on Kafka.

## Migrations

Every API replica running `alembic upgrade head` races DDL. The Kubernetes
Job runs once, `restartPolicy: Never`, `backoffLimit: 4`. Application pods
start only after the Job is `complete`.

Render keeps migrate-on-boot because it has no Job primitive on the free
web service.

## Kafka (Strimzi)

- Operator: Helm chart `strimzi/strimzi-kafka-operator` **0.45.1** (pinned, not `latest`)
- Kafka **3.9.0**, KRaft, **no ZooKeeper**
- 1 combined controller+broker node, ephemeral storage, RF=1
- `auto.create.topics.enable: false`
- Topics via `KafkaTopic` CRs (domain 3 partitions, benchmark 12)
- Bootstrap inside the cluster: `stockviz-kafka-bootstrap:9092`

This is **not** HA Kafka. Production would be a multi-broker cluster with
RF≥3, managed disks, and a real secrets story.

Changing partition counts on keyed domain topics reshuffles
key→partition mapping. We did not bump `stockviz.market.v1` from 3 to 12
to make a graph look better. The 12-partition topic is `stockviz.benchmark.v1`
only. See [`KAFKA_SCALING.md`](./KAFKA_SCALING.md).

## HPA

- API: min 2 / max 5 / CPU 70%. CPU is a stand-in for request load.
- Market ingest: min 1 / max **3** / CPU 70%. Extra replicas beyond 3 partitions
  in the same consumer group sit idle.
- CPU is **not** Kafka lag. Production ingest scaling should use consumer lag
  (KEDA). KEDA is intentionally not in this milestone.

metrics-server is installed in kind with `--kubelet-insecure-tls` (required
on kind). `kubectl top pods -n stockviz` should work once it is Ready.

## PDB and rolling updates

API: `minAvailable: 1` (only makes sense because replicas ≥ 2).
API/web rolling update: `maxUnavailable: 0`, `maxSurge: 1`.
Workers: default RollingUpdate. Singleton workers do not get PDBs.

`terminationGracePeriodSeconds` is 30s (API/web) / 45s (Kafka workers).
Workers already handle SIGTERM (close consumer, flush producer).

## Security context

Application pods: `runAsNonRoot`, uid **10001** (matches both Dockerfiles),
`allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`,
`seccompProfile: RuntimeDefault`, `automountServiceAccountToken: false`.

`readOnlyRootFilesystem` is **not** enabled — Next.js and CPython images were
not verified against it.

Postgres uses the upstream image user (not 10001). Strimzi manages Kafka's
security context.

## CI

`.github/workflows/k8s-smoke.yml` is additive. Existing web/api/events/security/docker/e2e
jobs stay. The k8s job: kind → build+load images → metrics-server → Strimzi →
Kafka → Postgres → migrate Job → rollouts → smoke → **3k event** benchmark
at 1 and 2 replicas.

No yfinance / Newsdata / Anthropic keys are required.

## HPA demo (optional, not a CI gate)

`scripts/k8s/hpa-demo.sh` prints `kubectl get hpa` / `deploy` and hits `/live`
briefly. `/live` is too cheap to trip CPU HPA; that is expected. A serious
demo would use a load generator against an expensive route. Do not fake
screenshots.

## Validation

```bash
kubectl kustomize infra/k8s/overlays/kind/bootstrap >/tmp/kind-bootstrap.yaml
kubectl kustomize infra/k8s/overlays/kind/migrate >/tmp/kind-migrate.yaml
kubectl kustomize infra/k8s/overlays/kind/app >/tmp/kind-app.yaml
kubectl kustomize infra/k8s/overlays/kind/scale >/tmp/kind-scale.yaml
kubectl kustomize infra/k8s/kafka >/tmp/kafka.yaml
# Built-in kinds only (needs a cluster kubeconfig):
kubectl apply --dry-run=client -f /tmp/kind-bootstrap.yaml
```

Kafka `Kafka` / `KafkaTopic` CRs cannot be dry-run applied until the Strimzi
CRDs are installed. CI kustomize-builds each kind layer plus the Kafka
overlay, then dry-runs the kind layers after the cluster exists.
