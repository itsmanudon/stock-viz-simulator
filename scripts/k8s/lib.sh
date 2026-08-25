#!/usr/bin/env bash
# Shared helpers for scripts/k8s/*.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CLUSTER_NAME="${CLUSTER_NAME:-stockviz}"
NAMESPACE="${NAMESPACE:-stockviz}"
IMAGE_TAG="${IMAGE_TAG:-dev}"
API_IMAGE="${API_IMAGE:-stockviz-api:${IMAGE_TAG}}"
WEB_IMAGE="${WEB_IMAGE:-stockviz-web:${IMAGE_TAG}}"
STRIMZI_CHART_VERSION="${STRIMZI_CHART_VERSION:-0.45.1}"
METRICS_SERVER_VERSION="${METRICS_SERVER_VERSION:-v0.7.2}"

log() { printf '[k8s] %s\n' "$*"; }
die() { printf '[k8s] ERROR: %s\n' "$*" >&2; exit 1; }

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

wait_rollout() {
  local deploy="$1"
  log "waiting for rollout ${deploy}"
  if kubectl -n "${NAMESPACE}" rollout status "deployment/${deploy}" --timeout=300s; then
    return 0
  fi
  log "rollout failed for ${deploy}; dumping diagnostics"
  kubectl -n "${NAMESPACE}" get pods,deploy,job -o wide || true
  kubectl -n "${NAMESPACE}" describe "deploy/${deploy}" || true
  kubectl -n "${NAMESPACE}" logs "deploy/${deploy}" --tail=150 || true
  kubectl -n "${NAMESPACE}" logs "deploy/${deploy}" --previous --tail=150 || true
  die "rollout timed out: ${deploy}"
}

wait_job() {
  local job="$1"
  log "waiting for job ${job}"
  if kubectl -n "${NAMESPACE}" wait --for=condition=complete "job/${job}" --timeout=300s; then
    return 0
  fi
  log "job ${job} failed; dumping diagnostics"
  kubectl -n "${NAMESPACE}" describe "job/${job}" || true
  kubectl -n "${NAMESPACE}" logs -l "job-name=${job}" --tail=150 || true
  die "job did not complete: ${job}"
}
