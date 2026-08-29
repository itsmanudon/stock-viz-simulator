#!/usr/bin/env bash
# Reduced Kafka consumer-group scaling run for CI / local proof.
# Full 100k × 1/2/4/8 is opt-in: BENCHMARK_COUNT=100000 BENCHMARK_REPLICAS="1 2 4 8"
#
# Isolation: seek the group to the topic end, then produce this run_id only.
# Consumers skip/commit non-matching run_id records. Throughput is
# min(produced_at)→max(consumed_at) on current-run completions, not collector
# wall-clock.
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

need kubectl

COUNT="${BENCHMARK_COUNT:-3000}"
REPLICAS_SPEC="${BENCHMARK_REPLICAS:-1 2}"
BOOTSTRAP="${KAFKA_BOOTSTRAP_SERVERS:-stockviz-kafka-bootstrap:9092}"
BENCH_IMAGE="${BENCH_IMAGE:-stockviz-api:dev}"
OUT_DIR="${ROOT}/artifacts/benchmarks"
mkdir -p "${OUT_DIR}"

log "applying benchmark consumer (image ${BENCH_IMAGE})"
kubectl apply -f "${ROOT}/infra/k8s/benchmark/consumer-deployment.yaml"
kubectl -n "${NAMESPACE}" set image deploy/stockviz-benchmark-consumer "consumer=${BENCH_IMAGE}" || true
kubectl -n "${NAMESPACE}" patch deploy/stockviz-benchmark-consumer --type=json -p='[
  {"op":"replace","path":"/spec/template/spec/containers/0/imagePullPolicy","value":"Never"}
]' >/dev/null || true

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

last_json() {
  python3 -c '
import json,sys
body=None
for line in sys.stdin.read().splitlines():
    line=line.strip()
    if not line:
        continue
    try:
        body=json.loads(line)
    except json.JSONDecodeError:
        continue
if body is None:
    raise SystemExit("no JSON object in logs")
print(json.dumps(body))
'
}

results='[]'
stamp="$(date -u +%Y%m%dT%H%M%SZ)"

for n in ${REPLICAS_SPEC}; do
  run_id="${stamp}-r${n}"
  group="stockviz.benchmark.${run_id}"
  log "=== replicas=${n} run_id=${run_id} events=${COUNT} ==="

  run_bench_job stockviz-benchmark-seek 120s seek-end --group "${group}" --bootstrap "${BOOTSTRAP}"

  kubectl -n "${NAMESPACE}" patch deploy/stockviz-benchmark-consumer --type=json -p="[
    {\"op\":\"replace\",\"path\":\"/spec/template/spec/containers/0/command\",\"value\":[\"python\",\"-m\",\"stockviz.benchmarks.kafka_scaling\",\"consume\",\"--group\",\"${group}\",\"--run-id\",\"${run_id}\",\"--expect\",\"${COUNT}\",\"--max-idle\",\"90\"]}
  ]"
  kubectl -n "${NAMESPACE}" scale deploy/stockviz-benchmark-consumer --replicas="${n}"
  kubectl -n "${NAMESPACE}" rollout status deploy/stockviz-benchmark-consumer --timeout=180s

  cpu_log="$(mktemp)"
  (
    while true; do
      kubectl top pods -n "${NAMESPACE}" -l app.kubernetes.io/component=benchmark-consumer --no-headers \
        >>"${cpu_log}" 2>/dev/null || true
      sleep 2
    done
  ) &
  cpu_pid=$!

  kubectl -n "${NAMESPACE}" delete job stockviz-benchmark-lag --ignore-not-found --wait=true >/dev/null
  LAG_MAX_SECONDS="${BENCHMARK_LAG_SECONDS:-$((COUNT / 20 + 180))}"
  python3 - "${NAMESPACE}" "${BENCH_IMAGE}" "${group}" "${BOOTSTRAP}" "${LAG_MAX_SECONDS}" <<'PY' | kubectl apply -f -
import json, sys
namespace, image, group, bootstrap, max_seconds = sys.argv[1:]
doc = {
    "apiVersion": "batch/v1",
    "kind": "Job",
    "metadata": {"name": "stockviz-benchmark-lag", "namespace": namespace},
    "spec": {
        "backoffLimit": 0,
        "template": {
            "spec": {
                "restartPolicy": "Never",
                "automountServiceAccountToken": False,
                "securityContext": {
                    "runAsNonRoot": True,
                    "runAsUser": 10001,
                    "runAsGroup": 10001,
                    "seccompProfile": {"type": "RuntimeDefault"},
                },
                "containers": [{
                    "name": "lag",
                    "image": image,
                    "imagePullPolicy": "Never",
                    "command": [
                        "python", "-m", "stockviz.benchmarks.kafka_scaling",
                        "sample-lag", "--group", group, "--bootstrap", bootstrap,
                        "--interval", "0.5", "--max-seconds", max_seconds,
                    ],
                    "envFrom": [{"configMapRef": {"name": "stockviz-config"}}],
                    "securityContext": {
                        "allowPrivilegeEscalation": False,
                        "capabilities": {"drop": ["ALL"]},
                        "runAsNonRoot": True,
                        "runAsUser": 10001,
                        "runAsGroup": 10001,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                }],
            }
        }
    },
}
json.dump(doc, sys.stdout)
print()
PY
  if ! kubectl -n "${NAMESPACE}" wait --for=condition=Ready pod -l job-name=stockviz-benchmark-lag --timeout=60s; then
    kubectl -n "${NAMESPACE}" logs -l job-name=stockviz-benchmark-lag --tail=80 || true
    die "lag sampler did not become Ready"
  fi

  produce_wait="$((COUNT / 40 + 180))s"
  collect_timeout="$((COUNT / 15 + 180))"
  collect_wait="$((collect_timeout + 60))s"
  run_bench_job stockviz-benchmark-producer "${produce_wait}" produce --count "${COUNT}" --run-id "${run_id}" --bootstrap "${BOOTSTRAP}"
  produce_json="$(kubectl -n "${NAMESPACE}" logs "job/stockviz-benchmark-producer" | last_json)"
  log "produce ${produce_json}"

  run_bench_job stockviz-benchmark-collector "${collect_wait}" collect --group "${group}" --run-id "${run_id}" --expect "${COUNT}" --timeout "${collect_timeout}" --bootstrap "${BOOTSTRAP}"
  collect_json="$(kubectl -n "${NAMESPACE}" logs "job/stockviz-benchmark-collector" | last_json)"
  log "collect ${collect_json}"

  kill "${cpu_pid}" >/dev/null 2>&1 || true
  wait "${cpu_pid}" >/dev/null 2>&1 || true
  lag_logs="$(kubectl -n "${NAMESPACE}" logs job/stockviz-benchmark-lag 2>/dev/null || true)"
  kubectl -n "${NAMESPACE}" delete job stockviz-benchmark-lag --ignore-not-found --wait=true >/dev/null || true

  results="$(python3 - "${results}" "${n}" "${COUNT}" "${run_id}" "${group}" "${collect_json}" "${produce_json}" "${lag_logs}" "${cpu_log}" <<'PY'
import json, re, sys
from pathlib import Path

prev, n, count, run_id, group, collect_s, produce_s, lag_logs, cpu_path = sys.argv[1:]
arr = json.loads(prev)
body = json.loads(collect_s)
produce = json.loads(produce_s)


def lag_summary(samples):
    if not samples:
        return {
            "initial_consumer_lag": None,
            "peak_consumer_lag": None,
            "final_consumer_lag": None,
        }
    return {
        "initial_consumer_lag": samples[0],
        "peak_consumer_lag": max(samples),
        "final_consumer_lag": samples[-1],
    }


def validate_run_result(result, *, require_lag=True):
    errors = []
    expect = result.get("events")
    collected = result.get("collected")
    if collected != expect:
        errors.append(f"collected {collected} != expected {expect}")
    if result.get("foreign_records"):
        errors.append(f"run_id contamination: {result['foreign_records']} foreign records")
    duration = result.get("processing_duration_seconds")
    if not isinstance(duration, (int, float)) or duration <= 0:
        errors.append(f"invalid processing_duration_seconds: {duration}")
    if result.get("consumer_events_per_second") is None:
        errors.append("missing consumer_events_per_second")
    if result.get("p50_ms") is None or result.get("p95_ms") is None:
        errors.append("missing current-run p50/p95")
    if not result.get("complete"):
        errors.append("result is incomplete")
    if require_lag and result.get("peak_consumer_lag") is None:
        errors.append("missing peak_consumer_lag")
    return errors


lag_samples = []
for line in lag_logs.splitlines():
    line = line.strip()
    if not line:
        continue
    try:
        row = json.loads(line)
    except json.JSONDecodeError:
        continue
    if isinstance(row.get("lag"), int):
        lag_samples.append(row["lag"])

cpu_peak = None
mem_peak = None
cpu_re = re.compile(r"(\d+)m")
mem_re = re.compile(r"(\d+)Mi")
cpu_path_obj = Path(cpu_path)
if cpu_path_obj.exists():
    for line in cpu_path_obj.read_text(encoding="utf-8").splitlines():
        cm = cpu_re.search(line)
        mm = mem_re.search(line)
        if cm:
            val = int(cm.group(1))
            cpu_peak = val if cpu_peak is None else max(cpu_peak, val)
        if mm:
            val = int(mm.group(1))
            mem_peak = val if mem_peak is None else max(mem_peak, val)

lag = lag_summary(lag_samples)
body["replicas"] = int(n)
body["events"] = int(count)
body["run_id"] = run_id
body["group"] = group
body["producer_events_per_second"] = produce.get("producer_events_per_second")
body["initial_consumer_lag"] = lag["initial_consumer_lag"]
body["peak_consumer_lag"] = lag["peak_consumer_lag"]
body["final_consumer_lag"] = lag["final_consumer_lag"]
# Peak of any sampled pod during the workload. Missing metrics stay null.
body["cpu"] = (
    {"peak_millicores_per_pod": cpu_peak, "source": "kubectl_top_during_workload"}
    if cpu_peak is not None
    else None
)
body["memory"] = (
    {"peak_mi_per_pod": mem_peak, "source": "kubectl_top_during_workload"}
    if mem_peak is not None
    else None
)
errors = validate_run_result(body, require_lag=True)
if errors:
    raise SystemExit("benchmark hard gate failed: " + "; ".join(errors))
arr.append(body)
print(json.dumps(arr))
PY
)"
  kubectl -n "${NAMESPACE}" delete job stockviz-benchmark-producer stockviz-benchmark-collector stockviz-benchmark-seek --ignore-not-found --wait=true >/dev/null
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
    "methodology": {
        "isolation": "seek-end then produce; consumers skip/commit non-matching run_id",
        "consumer_events_per_second": "current_run_count / (max(consumed_at) - min(produced_at))",
        "producer_events_per_second": "produce flush wall-clock",
        "lag": "sampled during the workload via committed offset vs watermark",
        "cpu_memory": "peak kubectl top during the workload; null if metrics-server unavailable",
    },
    "runs": arr,
    "note": "These numbers are from the environment that executed the script. They are not production SLOs.",
}
open(path, "w", encoding="utf-8").write(json.dumps(doc, indent=2) + "\n")
print(json.dumps(doc, indent=2))
PY

log "wrote ${OUT_DIR}/kafka-scaling.json"
