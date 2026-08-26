#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

need kind
log "deleting kind cluster ${CLUSTER_NAME}"
kind delete cluster --name "${CLUSTER_NAME}"
