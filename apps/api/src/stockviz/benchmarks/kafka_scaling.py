"""Kafka consumer-group scaling experiment.

Not domain logic. Publishes synthetic events to ``stockviz.benchmark.v1``
and consumes them with a dedicated group. Results go to
``stockviz.benchmark-results.v1``.

Isolation: each run has a unique ``run_id``. The coordinator seeks the
consumer group to the topic end **before** producing, then consumers skip
and commit any leftover records whose ``run_id`` does not match.

Throughput: consumer_events_per_second uses
``(max(consumed_at) - min(produced_at))`` over **current-run** events only.
That is not producer flush time and not collector wall-clock.
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


def parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        ts = datetime.fromisoformat(value)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts


def matches_run(payload: dict[str, Any], run_id: str) -> bool:
    return bool(run_id) and payload.get("run_id") == run_id


def should_emit_completion(payload: dict[str, Any], run_id: str) -> bool:
    """Foreign ``run_id`` records must be committed/skipped, never counted."""
    return matches_run(payload, run_id)


def current_run_event_ids(records: list[dict[str, Any]], run_id: str) -> list[str]:
    return [str(r["event_id"]) for r in records if matches_run(r, run_id) and r.get("event_id")]


def latency_ms(produced_at: object, consumed_at: object) -> float | None:
    start = parse_ts(produced_at)
    end = parse_ts(consumed_at)
    if start is None or end is None:
        return None
    return (end - start).total_seconds() * 1000


def percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, max(0, round((p / 100) * (len(sorted_vals) - 1))))
    return round(sorted_vals[idx], 3)


def processing_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Consumer pipeline duration from first produce to last consume.

    Uses current-run completion records only. Collector wall-clock is ignored.
    """
    produced = [parse_ts(r.get("produced_at")) for r in records]
    consumed = [parse_ts(r.get("consumed_at")) for r in records]
    starts = [t for t in produced if t is not None]
    ends = [t for t in consumed if t is not None]
    if not starts or not ends:
        return {
            "processing_duration_seconds": None,
            "consumer_events_per_second": None,
        }
    duration = (max(ends) - min(starts)).total_seconds()
    if duration <= 0:
        return {
            "processing_duration_seconds": duration,
            "consumer_events_per_second": None,
        }
    return {
        "processing_duration_seconds": round(duration, 4),
        "consumer_events_per_second": round(len(records) / duration, 2),
    }


def lag_summary(samples: list[int]) -> dict[str, int | None]:
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


def summarize_completions(
    records: list[dict[str, Any]],
    *,
    run_id: str,
    expect: int,
    replicas: int | None = None,
    producer_events_per_second: float | None = None,
    lag_samples: list[int] | None = None,
    cpu: object = None,
    memory: object = None,
) -> dict[str, Any]:
    foreign = [r for r in records if not matches_run(r, run_id)]
    current = [r for r in records if matches_run(r, run_id)]
    latencies = sorted(
        float(r["latency_ms"]) for r in current if isinstance(r.get("latency_ms"), int | float)
    )
    metrics = processing_metrics(current)
    lag = lag_summary(lag_samples or [])
    result = {
        "run_id": run_id,
        "replicas": replicas,
        "events": expect,
        "partitions": BENCHMARK_PARTITIONS,
        "collected": len(current),
        "foreign_records": len(foreign),
        "producer_events_per_second": producer_events_per_second,
        "processing_duration_seconds": metrics["processing_duration_seconds"],
        "consumer_events_per_second": metrics["consumer_events_per_second"],
        "p50_ms": percentile(latencies, 50),
        "p95_ms": percentile(latencies, 95),
        "p99_ms": percentile(latencies, 99),
        "mean_ms": round(statistics.fmean(latencies), 3) if latencies else None,
        "initial_consumer_lag": lag["initial_consumer_lag"],
        "peak_consumer_lag": lag["peak_consumer_lag"],
        "final_consumer_lag": lag["final_consumer_lag"],
        "cpu": cpu,
        "memory": memory,
        "complete": len(current) == expect and not foreign and len(latencies) == expect,
    }
    return result


def validate_run_result(result: dict[str, Any], *, require_lag: bool = True) -> list[str]:
    errors: list[str] = []
    expect = result.get("events")
    collected = result.get("collected")
    if collected != expect:
        errors.append(f"collected {collected} != expected {expect}")
    if result.get("foreign_records"):
        errors.append(f"run_id contamination: {result['foreign_records']} foreign records")
    duration = result.get("processing_duration_seconds")
    if not isinstance(duration, int | float) or duration <= 0:
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
        "producer_events_per_second": round(count / elapsed, 2) if elapsed else count,
    }
    logger.info("produced %s", result)
    return result


def seek_group_to_end(*, bootstrap: str, group: str) -> dict[str, Any]:
    """Commit the group's offsets to the current high-water mark.

    Call this **before** producing the current run so a new group does not
    replay retained messages from earlier runs (``auto.offset.reset=earliest``).
    """
    from confluent_kafka import Consumer, TopicPartition

    ensure_topic(
        bootstrap_servers=bootstrap, topic=BENCHMARK_TOPIC, partitions=BENCHMARK_PARTITIONS
    )
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": group,
            "enable.auto.commit": False,
            "auto.offset.reset": "latest",
            **_kafka_timeouts(),
        }
    )
    try:
        metadata = consumer.list_topics(BENCHMARK_TOPIC, timeout=10)
        topic = metadata.topics.get(BENCHMARK_TOPIC)
        if topic is None:
            raise RuntimeError(f"topic {BENCHMARK_TOPIC} missing")
        tps = [TopicPartition(BENCHMARK_TOPIC, p) for p in topic.partitions]
        consumer.assign(tps)
        committed: list[Any] = []
        offsets: dict[int, int] = {}
        for tp in tps:
            _low, high = consumer.get_watermark_offsets(tp, timeout=10)
            tp.offset = high
            committed.append(tp)
            offsets[int(tp.partition)] = int(high)
        consumer.commit(offsets=committed, asynchronous=False)
        logger.info("seek-end group=%s offsets=%s", group, offsets)
        return {"group": group, "end_offsets": offsets}
    finally:
        consumer.close()


def consume(
    *,
    group: str,
    bootstrap: str,
    run_id: str,
    expect: int,
    max_idle: float,
) -> int:
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
            "auto.offset.reset": "latest",
            "enable.auto.commit": False,
            "client.id": f"stockviz-benchmark-{group}",
            **_kafka_timeouts(),
        }
    )
    producer = Producer(
        {"bootstrap.servers": bootstrap, "acks": "all", "linger.ms": 5, **_kafka_timeouts()}
    )
    consumer.subscribe([BENCHMARK_TOPIC])
    matched = 0
    skipped = 0
    last_msg = time.monotonic()
    try:
        while not _stop:
            if matched >= expect:
                break
            msg = consumer.poll(1.0)
            if msg is None:
                if matched and (time.monotonic() - last_msg) > max_idle:
                    break
                continue
            err = msg.error()
            if err:
                if err.code() == KafkaError._PARTITION_EOF:
                    continue
                raise KafkaException(err)
            payload = _payload(msg)
            if not should_emit_completion(payload, run_id):
                # Advance past leftover retained records from earlier runs.
                consumer.commit(message=msg, asynchronous=False)
                skipped += 1
                continue
            consumed_at = datetime.now(UTC).isoformat()
            result = {
                "event_id": payload.get("event_id"),
                "run_id": payload.get("run_id"),
                "seq": payload.get("seq"),
                "symbol": payload.get("symbol"),
                "produced_at": payload.get("produced_at"),
                "consumed_at": consumed_at,
                "latency_ms": latency_ms(payload.get("produced_at"), consumed_at),
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
            matched += 1
            last_msg = time.monotonic()
    finally:
        producer.flush(15)
        consumer.close()
    logger.info("consumer group=%s matched=%s skipped=%s", group, matched, skipped)
    return matched


def group_lag(bootstrap: str, group: str) -> int:
    from confluent_kafka import Consumer, TopicPartition

    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": group,
            "enable.auto.commit": False,
            **_kafka_timeouts(),
        }
    )
    try:
        metadata = consumer.list_topics(BENCHMARK_TOPIC, timeout=10)
        topic = metadata.topics.get(BENCHMARK_TOPIC)
        if topic is None:
            return 0
        tps = [TopicPartition(BENCHMARK_TOPIC, p) for p in topic.partitions]
        committed = consumer.committed(tps, timeout=10)
        lag = 0
        for tp in committed:
            low, high = consumer.get_watermark_offsets(tp, timeout=10)
            offset = tp.offset if tp.offset is not None and tp.offset >= 0 else low
            lag += max(0, high - offset)
        return lag
    finally:
        consumer.close()


def sample_lag(*, bootstrap: str, group: str, interval: float, max_seconds: float) -> list[int]:
    samples: list[int] = []
    deadline = time.monotonic() + max_seconds
    while not _stop and time.monotonic() < deadline:
        lag = group_lag(bootstrap, group)
        samples.append(lag)
        print(json.dumps({"lag": lag, "ts": datetime.now(UTC).isoformat()}), flush=True)
        time.sleep(interval)
    return samples


def collect(
    *,
    group: str,
    bootstrap: str,
    run_id: str,
    expect: int,
    timeout: float,
) -> dict[str, Any]:
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
            **_kafka_timeouts(),
        }
    )
    consumer.subscribe([BENCHMARK_RESULTS_TOPIC])
    current: list[dict[str, Any]] = []
    foreign: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout
    try:
        while len(current) < expect and time.monotonic() < deadline and not _stop:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            err = msg.error()
            if err:
                if err.code() == KafkaError._PARTITION_EOF:
                    continue
                raise KafkaException(err)
            payload = _payload(msg)
            consumer.commit(message=msg, asynchronous=False)
            if payload.get("group") != group:
                continue
            if matches_run(payload, run_id):
                current.append(payload)
            else:
                foreign.append(payload)
    finally:
        consumer.close()
    result = summarize_completions(current + foreign, run_id=run_id, expect=expect)
    result["group"] = group
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

    p_seek = sub.add_parser("seek-end", help="Commit a consumer group to the topic end")
    p_seek.add_argument("--group", required=True)
    p_seek.add_argument("--bootstrap", default="")

    p_cons = sub.add_parser("consume", help="Join a consumer group and process one run")
    p_cons.add_argument("--group", required=True)
    p_cons.add_argument("--run-id", required=True)
    p_cons.add_argument("--expect", type=int, required=True)
    p_cons.add_argument("--max-idle", type=float, default=15.0)
    p_cons.add_argument("--bootstrap", default="")

    p_lag = sub.add_parser("sample-lag", help="Print lag JSON lines until timeout")
    p_lag.add_argument("--group", required=True)
    p_lag.add_argument("--interval", type=float, default=0.5)
    p_lag.add_argument("--max-seconds", type=float, default=120.0)
    p_lag.add_argument("--bootstrap", default="")

    p_col = sub.add_parser("collect", help="Read completion records and print JSON stats")
    p_col.add_argument("--group", required=True)
    p_col.add_argument("--run-id", required=True)
    p_col.add_argument("--expect", type=int, required=True)
    p_col.add_argument("--timeout", type=float, default=180.0)
    p_col.add_argument("--bootstrap", default="")

    args = parser.parse_args(argv)
    bootstrap = args.bootstrap or _bootstrap()
    if args.cmd == "produce":
        run_id = args.run_id or uuid4().hex[:12]
        print(json.dumps(produce(count=args.count, bootstrap=bootstrap, run_id=run_id)))
        return 0
    if args.cmd == "seek-end":
        print(json.dumps(seek_group_to_end(bootstrap=bootstrap, group=args.group)))
        return 0
    if args.cmd == "consume":
        if not args.group.startswith(BENCHMARK_CONSUMER_GROUP_PREFIX):
            logger.warning("group %s is outside the benchmark prefix", args.group)
        n = consume(
            group=args.group,
            bootstrap=bootstrap,
            run_id=args.run_id,
            expect=args.expect,
            max_idle=args.max_idle,
        )
        print(json.dumps({"processed": n, "group": args.group, "run_id": args.run_id}))
        return 0 if n >= args.expect else 1
    if args.cmd == "sample-lag":
        sample_lag(
            bootstrap=bootstrap,
            group=args.group,
            interval=args.interval,
            max_seconds=args.max_seconds,
        )
        return 0
    result = collect(
        group=args.group,
        bootstrap=bootstrap,
        run_id=args.run_id,
        expect=args.expect,
        timeout=args.timeout,
    )
    print(json.dumps(result))
    errors = validate_run_result(result, require_lag=False)
    if errors:
        logger.error("collect validation failed: %s", "; ".join(errors))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
