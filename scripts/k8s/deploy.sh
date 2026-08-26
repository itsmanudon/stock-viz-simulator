#!/usr/bin/env bash
# Install Strimzi, Kafka, Postgres, run migrations, THEN application workloads.
#
# Apply order is the contract:
#   bootstrap (ns/config/secrets/postgres) → Postgres Ready
#   → migrate Job → Migration Complete
#   → application Deployments → HPA/PDB → rollouts
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

need kubectl
need helm

KIND_OVERLAY="${KIND_OVERLAY:-${ROOT}/infra/k8s/overlays/kind}"
BOOTSTRAP_OVERLAY="${BOOTSTRAP_OVERLAY:-${KIND_OVERLAY}/bootstrap}"
MIGRATE_OVERLAY="${MIGRATE_OVERLAY:-${KIND_OVERLAY}/migrate}"
APP_OVERLAY="${APP_OVERLAY:-${KIND_OVERLAY}/app}"
SCALE_OVERLAY="${SCALE_OVERLAY:-${KIND_OVERLAY}/scale}"

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

log "applying bootstrap (namespace, config, secrets, Postgres)"
kubectl apply -k "${BOOTSTRAP_OVERLAY}"

log "waiting for Postgres Ready"
kubectl -n "${NAMESPACE}" rollout status deploy/postgres --timeout=180s
kubectl -n "${NAMESPACE}" wait --for=condition=ready pod -l app.kubernetes.io/component=postgres --timeout=180s
log "Postgres Ready"

# Recreate the migrate Job only after Postgres is Ready so early connection
# refused attempts do not exhaust backoffLimit.
log "applying migration Job"
kubectl -n "${NAMESPACE}" delete job stockviz-migrate --ignore-not-found
kubectl apply -k "${MIGRATE_OVERLAY}"
wait_job stockviz-migrate
log "Migration Complete"

assert_apps_absent_if_fresh
log "Application rollout begins"
kubectl apply -k "${APP_OVERLAY}"
log "applying HPA / PDB"
kubectl apply -k "${SCALE_OVERLAY}"

log "waiting for application rollouts"
for deploy in "${APP_DEPLOYS[@]}"; do
  wait_rollout "${deploy}"
done

log "deploy complete"
