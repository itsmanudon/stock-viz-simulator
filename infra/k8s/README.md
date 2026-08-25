# Kubernetes manifests

Kind / CI lab for StockViz. This is **not** a production control plane.

Operator guide: [`docs/KUBERNETES.md`](../../docs/KUBERNETES.md).

```
base/            API, web, migrate Job, scheduler, Kafka workers, HPA, PDB
overlays/kind/   in-cluster Postgres (emptyDir) + dummy Secret + Never pull
overlays/ci/     points at the kind overlay
kafka/           Strimzi Kafka + KafkaTopic CRs (apply after the operator)
optional/        Ingress (CI does not install ingress-nginx)
kind/            kind cluster config
benchmark/       synthetic consumer-group scaling Deployment
```

```bash
pnpm k8s:create && pnpm k8s:build && pnpm k8s:deploy && pnpm k8s:smoke
```
