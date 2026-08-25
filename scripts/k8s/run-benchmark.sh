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
# Overlay workloads use :dev, which kind load always tags. A SHA tag can exist
# too, but kubectl-run one-shots were waiting on a Pod condition that pods
# never set (Succeeded), so the step timed out even after a good run.
BENCH_IMAGE="${BENCH_IMAGE:-stockviz-api:dev}"
OUT_DIR="${ROOT}/artifacts/benchmarks"
mkdir -p "${OUT_DIR}"

log "applying benchmark consumer (image ${BENCH_IMAGE})"
kubectl apply -f "${ROOT}/infra/k8s/benchmark/consumer-deployment.yaml"
kubectl -n "${NAMESPACE}" set image deploy/stockviz-benchmark-consumer "consumer=${BENCH_IMAGE}" || true
kubectl -n "${NAMESPACE}" patch deploy/stockviz-benchmark-consumer --type=json -p='[
  {"op":"replace","path":"/spec/template/spec/containers/0/imagePullPolicy","value":"Never"}
]' >/dev/null || true

# Run a one-shot python module as a Job. Jobs expose condition=complete;
# Pods do not have condition=Succeeded, so `kubectl wait --for=condition=Succeeded
# pod/…` always hits the timeout even when the container already exited 0.
run_bench_job() {
  local name="$1"
  local timeout="$2"
  shift 2
  local args_json
  args_json="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$@")"
  kubectl -n "${NAMESPACE}" delete job "${name}" --ignore-not-found --wait=true >/dev/null
  python3 - "${NAMESPACE}" "${name}" "${BENCH_IMAGE}" "${args_json}" <<'PY' | kubectl apply -f -
import json, sys
namespace, name, image, args_json = sys.argv[1:]
args = json.loads(args_json)
doc = {
    "apiVersion": "batch/v1",
    "kind": "Job",
    "metadata": {
        "name": name,
        "namespace": namespace,
        "labels": {
            "app.kubernetes.io/name": "stockviz",
            "app.kubernetes.io/component": "benchmark",
            "app.kubernetes.io/part-of": "stockviz",
        },
    },
    "spec": {
        "backoffLimit": 0,
        "ttlSecondsAfterFinished": 600,
        "template": {
            "metadata": {
                "labels": {
                    "app.kubernetes.io/name": "stockviz",
                    "app.kubernetes.io/component": "benchmark",
                    "app.kubernetes.io/part-of": "stockviz",
                }
            },
            "spec": {
                "restartPolicy": "Never",
                "automountServiceAccountToken": False,
                "securityContext": {
                    "runAsNonRoot": True,
                    "runAsUser": 10001,
                    "runAsGroup": 10001,
                    "seccompProfile": {"type": "RuntimeDefault"},
                },
                "containers": [
                    {
                        "name": "bench",
                        "image": image,
                        "imagePullPolicy": "Never",
                        "command": ["python", "-m", "stockviz.benchmarks.kafka_scaling", *args],
                        "envFrom": [
                            {"configMapRef": {"name": "stockviz-config"}},
                            {"secretRef": {"name": "stockviz-secrets"}},
                        ],
                        "resources": {
                            "requests": {"cpu": "50m", "memory": "128Mi"},
                            "limits": {"cpu": "500m", "memory": "512Mi"},
                        },
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "capabilities": {"drop": ["ALL"]},
                            "runAsNonRoot": True,
                            "runAsUser": 10001,
                            "runAsGroup": 10001,
                            "seccompProfile": {"type": "RuntimeDefault"},
                        },
                    }
                ],
            },
        },
    },
}
json.dump(doc, sys.stdout)
print()
PY
  if ! kubectl -n "${NAMESPACE}" wait --for=condition=complete "job/${name}" --timeout="${timeout}"; then
    log "job ${name} did not complete; dumping diagnostics"
    kubectl -n "${NAMESPACE}" get job,pod -l job-name="${name}" -o wide || true
    kubectl -n "${NAMESPACE}" describe "job/${name}" || true
    kubectl -n "${NAMESPACE}" logs -l "job-name=${name}" --tail=200 || true
    die "benchmark job ${name} failed"
  fi
}

results='[]'
run_id="$(date -u +%Y%m%dT%H%M%SZ)"

for n in ${REPLICAS_SPEC}; do
  group="stockviz.benchmark.${run_id}.${n}r"
  log "=== replicas=${n} group=${group} events=${COUNT} ==="
  kubectl -n "${NAMESPACE}" patch deploy/stockviz-benchmark-consumer --type=json -p="[
    {\"op\":\"replace\",\"path\":\"/spec/template/spec/containers/0/command\",\"value\":[\"python\",\"-m\",\"stockviz.benchmarks.kafka_scaling\",\"consume\",\"--group\",\"${group}\",\"--max-idle\",\"90\"]}
  ]"
  kubectl -n "${NAMESPACE}" scale deploy/stockviz-benchmark-consumer --replicas="${n}"
  kubectl -n "${NAMESPACE}" rollout status deploy/stockviz-benchmark-consumer --timeout=180s

  cpu_mem="$(kubectl top pods -n "${NAMESPACE}" -l app.kubernetes.io/component=benchmark-consumer 2>/dev/null || true)"

  run_bench_job stockviz-benchmark-producer 180s produce --count "${COUNT}" --run-id "${run_id}-r${n}" --bootstrap "${BOOTSTRAP}"
  produce_logs="$(kubectl -n "${NAMESPACE}" logs "job/stockviz-benchmark-producer")"
  log "produce ${produce_logs}"

  run_bench_job stockviz-benchmark-collector 240s collect --group "${group}" --expect "${COUNT}" --timeout 180 --bootstrap "${BOOTSTRAP}"
  stats="$(kubectl -n "${NAMESPACE}" logs "job/stockviz-benchmark-collector")"
  log "stats ${stats}"
  results="$(python3 - "${results}" "${n}" "${COUNT}" "${group}" "${stats}" "${cpu_mem}" <<'PY'
import json, sys
prev, n, count, group, stats, cpu = sys.argv[1:]
arr = json.loads(prev)
# Job logs may include multiple lines; use the last JSON object.
body = None
for line in reversed(stats.splitlines()):
    line = line.strip()
    if not line:
        continue
    try:
        body = json.loads(line)
        break
    except json.JSONDecodeError:
        continue
if body is None:
    body = {"raw": stats}
body.update({"replicas": int(n), "events": int(count), "group": group, "kubectl_top": cpu.strip()})
arr.append(body)
print(json.dumps(arr))
PY
)"
  kubectl -n "${NAMESPACE}" delete job stockviz-benchmark-producer stockviz-benchmark-collector --ignore-not-found --wait=true >/dev/null
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
