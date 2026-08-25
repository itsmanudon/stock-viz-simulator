"""Kafka consumer-group scaling experiment.

Not domain logic. Publishes synthetic events to ``stockviz.benchmark.v1``
and consumes them with a dedicated group. Results go to
``stockviz.benchmark-results.v1``.

    python -m stockviz.benchmarks.kafka_scaling produce --count 3000
    python -m stockviz.benchmarks.kafka_scaling consume --group stockviz.benchmark.ci-1
    python -m stockviz.benchmarks.kafka_scaling collect --group stockviz.benchmark.ci-1 --expect 3000
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import statistics
import sys
import time
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from stockviz.benchmarks.topics import (
    BENCHMARK_CONSUMER_GROUP_PREFIX,
    BENCHMARK_PARTITIONS,
    BENCHMARK_RESULTS_TOPIC,
    BENCHMARK_TOPIC,
)
from stockviz.events.producer import ensure_topic
from stockviz.settings import get_settings

logger = logging.getLogger(__name__)

_SYMBOL_COUNT = 1000
_stop = False


def _request_stop(_signum: int, _frame: object) -> None:
    global _stop
    _stop = True


def _bootstrap() -> str:
    return os.environ.get("KAFKA_BOOTSTRAP_SERVERS") or get_settings().kafka_bootstrap_servers


def _symbol(i: int) -> str:
    return f"SYM{i % _SYMBOL_COUNT:04d}"


def _kafka_timeouts() -> dict[str, int]:
    return {
        "socket.timeout.ms": 15000,
        "api.version.request.timeout.ms": 10000,
    }


def _payload(msg: Any) -> dict[str, Any]:
    raw = msg.value()
    if raw is None:
        raise ValueError("empty Kafka payload")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Kafka payload must be a JSON object")
    return payload


def produce(*, count: int, bootstrap: str, run_id: str) -> dict[str, Any]:
    from confluent_kafka import Producer

    ensure_topic(
        bootstrap_servers=bootstrap, topic=BENCHMARK_TOPIC, partitions=BENCHMARK_PARTITIONS
    )
    producer = Producer(
        {
            "bootstrap.servers": bootstrap,
            "acks": "all",
            "linger.ms": 5,
            "batch.size": 32768,
            "client.id": "stockviz-benchmark-producer",
            **_kafka_timeouts(),
        }
    )
    errors: list[str] = []

    def _on_delivery(err: object, _msg: object) -> None:
        if err is not None:
            errors.append(str(err))

    started = time.perf_counter()
    for seq in range(count):
        now = datetime.now(UTC).isoformat()
        key = _symbol(seq)
        value = {
            "event_id": str(uuid4()),
            "run_id": run_id,
            "seq": seq,
            "symbol": key,
            "produced_at": now,
            "payload": {"n": seq, "note": "synthetic-benchmark"},
        }
        producer.produce(
            BENCHMARK_TOPIC,
            key=key.encode("utf-8"),
            value=json.dumps(value, separators=(",", ":")).encode("utf-8"),
            on_delivery=_on_delivery,
        )
        if seq % 500 == 0:
            producer.poll(0)
    remaining = producer.flush(60)
    elapsed = time.perf_counter() - started
    if remaining:
        raise RuntimeError(f"producer flush timed out with {remaining} in flight")
    if errors:
        raise RuntimeError(f"produce errors: {errors[0]}")
    result = {
        "run_id": run_id,
        "produced": count,
        "elapsed_seconds": round(elapsed, 4),
        "events_per_second": round(count / elapsed, 2) if elapsed else count,
    }
    logger.info("produced %s", result)
    return result


def consume(*, group: str, bootstrap: str, max_idle: float) -> int:
    from confluent_kafka import Consumer, KafkaError, KafkaException, Producer

    ensure_topic(
        bootstrap_servers=bootstrap, topic=BENCHMARK_TOPIC, partitions=BENCHMARK_PARTITIONS
    )
    ensure_topic(
        bootstrap_servers=bootstrap,
        topic=BENCHMARK_RESULTS_TOPIC,
        partitions=BENCHMARK_PARTITIONS,
    )
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": group,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
            "client.id": f"stockviz-benchmark-{group}",
        }
    )
    producer = Producer({"bootstrap.servers": bootstrap, "acks": "all", "linger.ms": 5})
    consumer.subscribe([BENCHMARK_TOPIC])
    processed = 0
    last_msg = time.monotonic()
    try:
        while not _stop:
            msg = consumer.poll(1.0)
            if msg is None:
                if processed and (time.monotonic() - last_msg) > max_idle:
                    break
                continue
            err = msg.error()
            if err:
                if err.code() == KafkaError._PARTITION_EOF:
                    continue
                raise KafkaException(err)
            payload = _payload(msg)
            consumed_at = datetime.now(UTC).isoformat()
            produced_at = payload.get("produced_at")
            latency_ms = None
            if isinstance(produced_at, str):
                try:
                    start = datetime.fromisoformat(produced_at)
                    latency_ms = (datetime.now(UTC) - start).total_seconds() * 1000
                except ValueError:
                    latency_ms = None
            result = {
                "event_id": payload.get("event_id"),
                "run_id": payload.get("run_id"),
                "seq": payload.get("seq"),
                "symbol": payload.get("symbol"),
                "produced_at": produced_at,
                "consumed_at": consumed_at,
                "latency_ms": latency_ms,
                "group": group,
                "partition": msg.partition(),
            }
            producer.produce(
                BENCHMARK_RESULTS_TOPIC,
                key=str(payload.get("symbol", "")).encode("utf-8"),
                value=json.dumps(result, separators=(",", ":")).encode("utf-8"),
            )
            producer.poll(0)
            consumer.commit(message=msg, asynchronous=False)
            processed += 1
            last_msg = time.monotonic()
    finally:
        producer.flush(15)
        consumer.close()
    logger.info("consumer group=%s processed=%s", group, processed)
    return processed


def _lag(bootstrap: str, group: str) -> int:
    from confluent_kafka import Consumer, TopicPartition
    from confluent_kafka.admin import AdminClient

    admin = AdminClient({"bootstrap.servers": bootstrap})
    metadata = admin.list_topics(topic=BENCHMARK_TOPIC, timeout=10)
    topic = metadata.topics.get(BENCHMARK_TOPIC)
    if topic is None:
        return 0
    partitions = list(topic.partitions.keys())
    tps = [TopicPartition(BENCHMARK_TOPIC, p) for p in partitions]
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": group,
            "enable.auto.commit": False,
        }
    )
    try:
        committed = consumer.committed(tps, timeout=10)
        lag = 0
        for tp in committed:
            low, high = consumer.get_watermark_offsets(tp, timeout=10)
            offset = tp.offset if tp.offset is not None and tp.offset >= 0 else low
            lag += max(0, high - offset)
        return lag
    finally:
        consumer.close()


def collect(*, group: str, bootstrap: str, expect: int, timeout: float) -> dict[str, Any]:
    from confluent_kafka import Consumer, KafkaError, KafkaException

    ensure_topic(
        bootstrap_servers=bootstrap,
        topic=BENCHMARK_RESULTS_TOPIC,
        partitions=BENCHMARK_PARTITIONS,
    )
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": f"{group}.collector.{uuid4().hex[:8]}",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([BENCHMARK_RESULTS_TOPIC])
    latencies: list[float] = []
    seen = 0
    deadline = time.monotonic() + timeout
    started = time.perf_counter()
    try:
        while seen < expect and time.monotonic() < deadline and not _stop:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            err = msg.error()
            if err:
                if err.code() == KafkaError._PARTITION_EOF:
                    continue
                raise KafkaException(err)
            payload = _payload(msg)
            if payload.get("group") != group:
                continue
            ms = payload.get("latency_ms")
            if isinstance(ms, int | float):
                latencies.append(float(ms))
            seen += 1
            consumer.commit(message=msg, asynchronous=False)
    finally:
        consumer.close()
    elapsed = time.perf_counter() - started
    latencies.sort()

    def _pct(p: float) -> float | None:
        if not latencies:
            return None
        idx = min(len(latencies) - 1, max(0, round((p / 100) * (len(latencies) - 1))))
        return round(latencies[idx], 3)

    lag = _lag(bootstrap, group)
    result = {
        "group": group,
        "expected": expect,
        "collected": seen,
        "elapsed_seconds": round(elapsed, 4),
        "events_per_second": round(seen / elapsed, 2) if elapsed else seen,
        "p50_ms": _pct(50),
        "p95_ms": _pct(95),
        "p99_ms": _pct(99),
        "mean_ms": round(statistics.fmean(latencies), 3) if latencies else None,
        "consumer_lag": lag,
        "complete": seen >= expect,
    }
    logger.info("collect %s", result)
    return result


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    parser = argparse.ArgumentParser(description="Kafka consumer-group scaling experiment")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_prod = sub.add_parser("produce", help="Publish synthetic benchmark events")
    p_prod.add_argument("--count", type=int, default=3000)
    p_prod.add_argument("--run-id", default="")
    p_prod.add_argument("--bootstrap", default="")

    p_cons = sub.add_parser("consume", help="Join a consumer group and process events")
    p_cons.add_argument("--group", required=True)
    p_cons.add_argument("--max-idle", type=float, default=15.0)
    p_cons.add_argument("--bootstrap", default="")

    p_col = sub.add_parser("collect", help="Read completion records and print JSON stats")
    p_col.add_argument("--group", required=True)
    p_col.add_argument("--expect", type=int, required=True)
    p_col.add_argument("--timeout", type=float, default=180.0)
    p_col.add_argument("--bootstrap", default="")

    args = parser.parse_args(argv)
    bootstrap = args.bootstrap or _bootstrap()
    if args.cmd == "produce":
        run_id = args.run_id or uuid4().hex[:12]
        print(json.dumps(produce(count=args.count, bootstrap=bootstrap, run_id=run_id)))
        return 0
    if args.cmd == "consume":
        if not args.group.startswith(BENCHMARK_CONSUMER_GROUP_PREFIX):
            logger.warning("group %s is outside the benchmark prefix", args.group)
        n = consume(group=args.group, bootstrap=bootstrap, max_idle=args.max_idle)
        print(json.dumps({"processed": n, "group": args.group}))
        return 0
    print(
        json.dumps(
            collect(
                group=args.group,
                bootstrap=bootstrap,
                expect=args.expect,
                timeout=args.timeout,
            )
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
