#!/usr/bin/env bash
# Create (or reuse) the kind cluster named stockviz and install metrics-server.
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

need docker
need kind
need kubectl

if kind get clusters | grep -qx "${CLUSTER_NAME}"; then
  log "kind cluster ${CLUSTER_NAME} already exists"
else
  log "creating kind cluster ${CLUSTER_NAME}"
  kind create cluster --name "${CLUSTER_NAME}" --config "${ROOT}/infra/k8s/kind/cluster.yaml"
fi

kubectl cluster-info --context "kind-${CLUSTER_NAME}" >/dev/null
log "installing metrics-server ${METRICS_SERVER_VERSION}"
kubectl apply -f "https://github.com/kubernetes-sigs/metrics-server/releases/download/${METRICS_SERVER_VERSION}/components.yaml"
if kubectl -n kube-system get deploy metrics-server -o jsonpath='{.spec.template.spec.containers[0].args}' | grep -q kubelet-insecure-tls; then
  log "metrics-server already has kubelet-insecure-tls"
else
  kubectl -n kube-system patch deploy metrics-server --type=json -p='[
    {"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}
  ]'
fi
kubectl -n kube-system rollout status deploy/metrics-server --timeout=180s
log "kind cluster ready"
