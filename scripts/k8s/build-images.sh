#!/usr/bin/env bash
# Build API + web images and load them into the kind cluster.
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

need docker
need kind

PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:8000}"

log "building ${API_IMAGE}"
docker build -t "${API_IMAGE}" -t "stockviz-api:dev" "${ROOT}/apps/api"

log "building ${WEB_IMAGE} (NEXT_PUBLIC_API_URL=${PUBLIC_API_URL})"
docker build \
  -f "${ROOT}/apps/web/Dockerfile" \
  --build-arg "NEXT_PUBLIC_API_URL=${PUBLIC_API_URL}" \
  -t "${WEB_IMAGE}" \
  -t "stockviz-web:dev" \
  "${ROOT}"

if kind get clusters | grep -qx "${CLUSTER_NAME}"; then
  log "loading images into kind ${CLUSTER_NAME}"
  kind load docker-image "${API_IMAGE}" "stockviz-api:dev" --name "${CLUSTER_NAME}"
  kind load docker-image "${WEB_IMAGE}" "stockviz-web:dev" --name "${CLUSTER_NAME}"
else
  log "kind cluster ${CLUSTER_NAME} not found; images built locally only"
fi
