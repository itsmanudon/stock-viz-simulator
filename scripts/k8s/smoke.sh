#!/usr/bin/env bash
# Kubernetes smoke: workloads ready, probes, web page, Kafka topics.
set -euo pipefail
# shellcheck source=lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

need kubectl
need curl

fail=0
check() {
  local name="$1"
  shift
  if "$@"; then
    log "PASS ${name}"
  else
    log "FAIL ${name}"
    fail=1
  fi
}

check "namespace exists" kubectl get ns "${NAMESPACE}"
check "postgres ready" kubectl -n "${NAMESPACE}" wait --for=condition=ready pod -l app.kubernetes.io/component=postgres --timeout=60s
check "kafka ready" kubectl -n "${NAMESPACE}" wait kafka/stockviz --for=condition=Ready --timeout=60s
check "migrate job complete" kubectl -n "${NAMESPACE}" wait --for=condition=complete job/stockviz-migrate --timeout=60s

for deploy in \
  stockviz-api \
  stockviz-web \
  stockviz-scheduler \
  stockviz-outbox-publisher \
  stockviz-trade-activity \
  stockviz-market-ingest \
  stockviz-market-analytics \
  stockviz-news-ingest \
  stockviz-news-sentiment \
  stockviz-sentiment-aggregate
do
  check "${deploy} available" kubectl -n "${NAMESPACE}" wait --for=condition=available "deploy/${deploy}" --timeout=60s
done

API_PF_LOG="$(mktemp)"
WEB_PF_LOG="$(mktemp)"
cleanup() {
  kill "${API_PF_PID:-}" "${WEB_PF_PID:-}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

kubectl -n "${NAMESPACE}" port-forward svc/stockviz-api 18000:8000 >"${API_PF_LOG}" 2>&1 &
API_PF_PID=$!
kubectl -n "${NAMESPACE}" port-forward svc/stockviz-web 13000:3000 >"${WEB_PF_LOG}" 2>&1 &
WEB_PF_PID=$!

for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:18000/live" >/dev/null; then
    break
  fi
  sleep 1
done

check "GET /live" bash -c 'code=$(curl -s --max-time 10 -o /tmp/stockviz-live.json -w "%{http_code}" http://127.0.0.1:18000/live); test "$code" = "200"'
check "GET /health" bash -c 'code=$(curl -s --max-time 10 -o /tmp/stockviz-health.json -w "%{http_code}" http://127.0.0.1:18000/health); test "$code" = "200"'
check "GET web /api/health" bash -c 'code=$(curl -s --max-time 10 -o /tmp/stockviz-web-health.json -w "%{http_code}" http://127.0.0.1:13000/api/health); test "$code" = "200"'
check "GET web /" bash -c 'code=$(curl -s --max-time 30 -o /tmp/stockviz-web.html -w "%{http_code}" http://127.0.0.1:13000/); test "$code" = "200"'

if kubectl -n "${NAMESPACE}" get kafkatopic stockviz-trades-v1 >/dev/null 2>&1; then
  for t in stockviz-trades-v1 stockviz-market-v1 stockviz-news-v1; do
    check "topic ${t}" kubectl -n "${NAMESPACE}" get kafkatopic "${t}"
  done
else
  # Fall back to listing topics from the Kafka pod if Topic Operator is slow.
  kafka_pod="$(kubectl -n "${NAMESPACE}" get pods -l strimzi.io/cluster=stockviz,strimzi.io/kind=Kafka -o jsonpath='{.items[0].metadata.name}')"
  topics="$(kubectl -n "${NAMESPACE}" exec "${kafka_pod}" -c kafka -- \
    bin/kafka-topics.sh --bootstrap-server localhost:9092 --list)"
  for t in stockviz.trades.v1 stockviz.market.v1 stockviz.news.v1; do
    check "topic ${t}" bash -c "printf '%s\n' \"${topics}\" | grep -qx '${t}'"
  done
fi

if kubectl top pods -n "${NAMESPACE}" >/dev/null 2>&1; then
  log "PASS metrics API (kubectl top pods)"
else
  log "WARN metrics API not ready yet (HPA still installed; not a smoke failure)"
fi

if [[ "${fail}" -ne 0 ]]; then
  die "smoke test failed"
fi
log "smoke test passed"
