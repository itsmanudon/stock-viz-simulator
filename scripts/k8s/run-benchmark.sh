#!/usr/bin/env bash
# Reduced Kafka consumer-group scaling run for CI / local proof.
# Full 100k × 1/2/4/8 is opt-in: BENCHMARK_COUNT=100000 BENCHMARK_REPLICAS="1 2 4 8"
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

need kubectl

COUNT="${BENCHMARK_COUNT:-3000}"
REPLICAS_SPEC="${BENCHMARK_REPLICAS:-1 2}"
BOOTSTRAP="${KAFKA_BOOTSTRAP_SERVERS:-stockviz-kafka-bootstrap:9092}"
OUT_DIR="${ROOT}/artifacts/benchmarks"
mkdir -p "${OUT_DIR}"

log "applying benchmark consumer (image ${API_IMAGE})"
kubectl apply -f "${ROOT}/infra/k8s/benchmark/consumer-deployment.yaml"
kubectl -n "${NAMESPACE}" set image deploy/stockviz-benchmark-consumer "consumer=${API_IMAGE}" || true
kubectl -n "${NAMESPACE}" patch deploy/stockviz-benchmark-consumer --type=json -p='[
  {"op":"replace","path":"/spec/template/spec/containers/0/imagePullPolicy","value":"Never"}
]' >/dev/null || true

results='[]'
run_id="$(date -u +%Y%m%dT%H%M%SZ)"

for n in ${REPLICAS_SPEC}; do
  group="stockviz.benchmark.${run_id}.${n}r"
  log "=== replicas=${n} group=${group} events=${COUNT} ==="
  kubectl -n "${NAMESPACE}" set env deploy/stockviz-benchmark-consumer \
    --containers=consumer --overwrite \
    "BENCHMARK_GROUP=${group}" >/dev/null || true
  # The Deployment command hard-codes the group; patch the consume --group arg.
  kubectl -n "${NAMESPACE}" patch deploy/stockviz-benchmark-consumer --type=json -p="[
    {\"op\":\"replace\",\"path\":\"/spec/template/spec/containers/0/command\",\"value\":[\"python\",\"-m\",\"stockviz.benchmarks.kafka_scaling\",\"consume\",\"--group\",\"${group}\",\"--max-idle\",\"90\"]}
  ]"
  kubectl -n "${NAMESPACE}" scale deploy/stockviz-benchmark-consumer --replicas="${n}"
  kubectl -n "${NAMESPACE}" rollout status deploy/stockviz-benchmark-consumer --timeout=180s

  cpu_mem="$(kubectl top pods -n "${NAMESPACE}" -l app.kubernetes.io/component=benchmark-consumer 2>/dev/null || true)"

  # Produce from a one-shot pod using the API image (in-cluster bootstrap).
  kubectl -n "${NAMESPACE}" delete pod stockviz-benchmark-producer --ignore-not-found >/dev/null
  kubectl -n "${NAMESPACE}" run stockviz-benchmark-producer --restart=Never --image="${API_IMAGE}" \
    --image-pull-policy=Never \
    --env="KAFKA_BOOTSTRAP_SERVERS=${BOOTSTRAP}" \
    --command -- python -m stockviz.benchmarks.kafka_scaling produce --count "${COUNT}" --run-id "${run_id}-r${n}"
  kubectl -n "${NAMESPACE}" wait --for=condition=Succeeded pod/stockviz-benchmark-producer --timeout=180s
  kubectl -n "${NAMESPACE}" logs stockviz-benchmark-producer

  kubectl -n "${NAMESPACE}" delete pod stockviz-benchmark-collector --ignore-not-found >/dev/null
  kubectl -n "${NAMESPACE}" run stockviz-benchmark-collector --restart=Never --image="${API_IMAGE}" \
    --image-pull-policy=Never \
    --env="KAFKA_BOOTSTRAP_SERVERS=${BOOTSTRAP}" \
    --command -- python -m stockviz.benchmarks.kafka_scaling collect --group "${group}" --expect "${COUNT}" --timeout 180
  kubectl -n "${NAMESPACE}" wait --for=condition=Succeeded pod/stockviz-benchmark-collector --timeout=200s
  stats="$(kubectl -n "${NAMESPACE}" logs stockviz-benchmark-collector)"
  log "stats ${stats}"
  results="$(python3 - "${results}" "${n}" "${COUNT}" "${group}" "${stats}" "${cpu_mem}" <<'PY'
import json, sys
prev, n, count, group, stats, cpu = sys.argv[1:]
arr = json.loads(prev)
try:
    body = json.loads(stats)
except json.JSONDecodeError:
    body = {"raw": stats}
body.update({"replicas": int(n), "events": int(count), "group": group, "kubectl_top": cpu.strip()})
arr.append(body)
print(json.dumps(arr))
PY
)"
  kubectl -n "${NAMESPACE}" delete pod stockviz-benchmark-producer stockviz-benchmark-collector --ignore-not-found >/dev/null
done

python3 - "${results}" "${OUT_DIR}/kafka-scaling.json" "${COUNT}" "${REPLICAS_SPEC}" <<'PY'
import json, sys
from datetime import datetime, timezone
arr = json.loads(sys.argv[1])
path = sys.argv[2]
doc = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "event_count_per_run": int(sys.argv[3]),
    "replica_schedule": sys.argv[4].split(),
    "topic": "stockviz.benchmark.v1",
    "partitions": 12,
    "runs": arr,
    "note": "These numbers are from the environment that executed the script. They are not production SLOs.",
}
open(path, "w", encoding="utf-8").write(json.dumps(doc, indent=2) + "\n")
print(json.dumps(doc, indent=2))
PY

log "wrote ${OUT_DIR}/kafka-scaling.json"
