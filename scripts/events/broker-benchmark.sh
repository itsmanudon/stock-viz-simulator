#!/usr/bin/env bash
# Local consumer-group scaling run against one broker (Phase 7.6 Camus trial).
#
# The same steps as scripts/k8s/run-benchmark.sh, without Kubernetes: for each
# consumer count, seek the group to the topic end, start N consumers, produce
# COUNT events for one run_id, collect the results. Throughput is
# min(produced_at) -> max(consumed_at) over this run's events.
#
#   BOOTSTRAP=127.0.0.1:9092 BROKER=kafka COUNT=100000 REPLICAS="1 2 4" \
#     MEM_CMD='docker stats --no-stream --format {{.MemUsage}} stockviz-kafka' \
#     bash scripts/events/broker-benchmark.sh > out.jsonl
#
# MEM_CMD (optional) prints the broker's memory; it is sampled after each run.
set -euo pipefail

BOOTSTRAP="${BOOTSTRAP:?set BOOTSTRAP}"
BROKER="${BROKER:-broker}"
COUNT="${COUNT:-100000}"
REPLICAS="${REPLICAS:-1 2 4}"
API_DIR="$(cd "$(dirname "$0")/../../apps/api" && pwd)"
bench() { uv --directory "$API_DIR" run --quiet python -m stockviz.benchmarks.kafka_scaling "$@"; }
log() { printf '%s %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }

for n in $REPLICAS; do
  run_id="$(uuidgen | tr 'A-Z' 'a-z')"
  group="bench-${BROKER}-${n}-${run_id:0:8}"
  log "=== ${BROKER} consumers=${n} events=${COUNT} run_id=${run_id} ==="
  bench seek-end --group "$group" --bootstrap "$BOOTSTRAP" >&2
  pids=()
  for _ in $(seq "$n"); do
    bench consume --group "$group" --run-id "$run_id" --expect "$COUNT" --max-idle 60 \
      --bootstrap "$BOOTSTRAP" >/dev/null 2>&1 &
    pids+=("$!")
  done
  sleep 8 # let the group settle before producing
  produce_json="$(bench produce --count "$COUNT" --run-id "$run_id" --bootstrap "$BOOTSTRAP" | tail -1)"
  collect_json="$(bench collect --group "$group" --run-id "$run_id" --expect "$COUNT" \
    --timeout "$((COUNT / 50 + 120))" --bootstrap "$BOOTSTRAP" | tail -1)"
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  mem="$(eval "${MEM_CMD:-echo n/a}" 2>/dev/null | tail -1 || echo n/a)"
  python3 - "$BROKER" "$n" "$COUNT" "$produce_json" "$collect_json" "$mem" <<'PY'
import json, sys
broker, n, count, produce, collect, mem = sys.argv[1:]
print(json.dumps({"broker": broker, "consumers": int(n), "events": int(count),
                  "produce": json.loads(produce), "collect": json.loads(collect),
                  "broker_memory_after": mem}))
PY
done
