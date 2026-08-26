#!/usr/bin/env bash
# Optional HPA demonstration. Not a CI gate.
# Generates CPU load against the API Service and prints HPA / Deployment state.
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

need kubectl

log "current HPA"
kubectl -n "${NAMESPACE}" get hpa
log "current API deploy"
kubectl -n "${NAMESPACE}" get deploy stockviz-api

log "starting a short in-cluster busy loop against /live (60s)"
kubectl -n "${NAMESPACE}" delete pod stockviz-hpa-load --ignore-not-found >/dev/null
kubectl -n "${NAMESPACE}" run stockviz-hpa-load --restart=Never --image=busybox:1.36 \
  --command -- /bin/sh -c 'i=0; while [ $i -lt 60 ]; do wget -q -O- http://stockviz-api:8000/live >/dev/null; i=$((i+1)); done'
sleep 15
kubectl -n "${NAMESPACE}" get hpa stockviz-api
kubectl -n "${NAMESPACE}" get deploy stockviz-api
kubectl -n "${NAMESPACE}" delete pod stockviz-hpa-load --ignore-not-found >/dev/null
log "CPU HPA may not fire on /live (too cheap). That is expected; see docs/KUBERNETES.md."
