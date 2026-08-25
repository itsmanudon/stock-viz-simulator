#!/usr/bin/env bash
# Install Strimzi, Kafka, Postgres, run migrations, then application workloads.
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

need kubectl
need helm

OVERLAY="${OVERLAY:-${ROOT}/infra/k8s/overlays/kind}"

kubectl apply -f "${ROOT}/infra/k8s/base/namespace.yaml"

log "installing Strimzi operator chart ${STRIMZI_CHART_VERSION}"
helm repo add strimzi https://strimzi.io/charts/ >/dev/null
helm repo update strimzi >/dev/null
helm upgrade --install strimzi-kafka-operator strimzi/strimzi-kafka-operator \
  --namespace "${NAMESPACE}" \
  --version "${STRIMZI_CHART_VERSION}" \
  --wait \
  --timeout 5m

log "waiting for Kafka CRDs"
kubectl wait --for=condition=Established crd/kafkas.kafka.strimzi.io --timeout=120s
kubectl wait --for=condition=Established crd/kafkatopics.kafka.strimzi.io --timeout=120s
if kubectl get crd kafkanodepools.kafka.strimzi.io >/dev/null 2>&1; then
  kubectl wait --for=condition=Established crd/kafkanodepools.kafka.strimzi.io --timeout=120s
fi

log "applying Kafka cluster + topics"
kubectl apply -k "${ROOT}/infra/k8s/kafka"
log "waiting for Kafka to become Ready (this is slow the first time)"
kubectl -n "${NAMESPACE}" wait kafka/stockviz --for=condition=Ready --timeout=600s

log "applying Postgres + application overlay ${OVERLAY}"
kubectl apply -k "${OVERLAY}"

log "waiting for Postgres"
kubectl -n "${NAMESPACE}" rollout status deploy/postgres --timeout=180s
kubectl -n "${NAMESPACE}" wait --for=condition=ready pod -l app.kubernetes.io/component=postgres --timeout=180s

# Recreate the migrate Job only after Postgres is Ready so early connection
# refused attempts do not exhaust backoffLimit.
log "running migration Job"
kubectl -n "${NAMESPACE}" delete job stockviz-migrate --ignore-not-found
kubectl apply -k "${OVERLAY}"
wait_job stockviz-migrate

log "waiting for application rollouts"
for deploy in \
  stockviz-api \
  stockviz-web \
  stockviz-scheduler \
  stockviz-outbox-publisher \
  stockviz-trade-activity \
  stockviz-market-ingest \
  stockviz-market-analytics \
  stockviz-news-ingest \
  stockviz-news-sentiment \
  stockviz-sentiment-aggregate
do
  wait_rollout "${deploy}"
done

log "deploy complete"
