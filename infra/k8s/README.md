# Kubernetes manifests

Kind / CI lab for StockViz. This is **not** a production control plane.

Operator guide: [`docs/KUBERNETES.md`](../../docs/KUBERNETES.md).

```
base/app/        API, web, scheduler, Kafka workers, Services
base/migrate/    alembic Job (applied only after Postgres is Ready)
base/scale/      API HPA + PDB, market-ingest HPA
overlays/kind/bootstrap/  Postgres + split dummy Secrets + config
overlays/kind/migrate/    kind image pull policy for the Job
overlays/kind/app/        kind image pull policy for Deployments
overlays/kind/scale/      HPA/PDB (after apps exist)
overlays/ci/     notes that CI uses deploy.sh layers (no combined overlay)
kafka/           Strimzi Kafka + KafkaTopic CRs (apply after the operator)
optional/        Ingress (CI does not install ingress-nginx)
kind/            kind cluster config
benchmark/       synthetic consumer-group scaling Deployment
```

```bash
pnpm k8s:create && pnpm k8s:build && pnpm k8s:deploy && pnpm k8s:smoke
```
