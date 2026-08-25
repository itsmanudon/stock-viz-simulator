from datetime import UTC, datetime, timedelta

from stockviz.benchmarks.kafka_scaling import (
    _symbol,
    current_run_event_ids,
    lag_summary,
    matches_run,
    percentile,
    processing_metrics,
    should_emit_completion,
    summarize_completions,
    validate_run_result,
)
from stockviz.benchmarks.topics import BENCHMARK_PARTITIONS, BENCHMARK_TOPIC

_T0 = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


def _iso(seconds: float) -> str:
    return (_T0 + timedelta(seconds=seconds)).isoformat()


def _completion(
    *,
    run_id: str,
    event_id: str,
    produced_at: float,
    consumed_at: float,
    latency_ms: float | None = None,
) -> dict:
    if latency_ms is None:
        latency_ms = (consumed_at - produced_at) * 1000
    return {
        "event_id": event_id,
        "run_id": run_id,
        "produced_at": _iso(produced_at),
        "consumed_at": _iso(consumed_at),
        "latency_ms": latency_ms,
    }


def test_benchmark_keys_cover_a_thousand_symbols() -> None:
    keys = {_symbol(i) for i in range(5_000)}
    assert len(keys) == 1000
    assert "SYM0000" in keys
    assert "SYM0999" in keys


def test_benchmark_topic_is_not_a_domain_topic() -> None:
    assert BENCHMARK_TOPIC.startswith("stockviz.benchmark")
    assert BENCHMARK_PARTITIONS == 12


def test_run_b_results_exclude_previous_run_event_ids() -> None:
    """Run A publishes first; Run B must not count those completions."""
    run_a = [
        _completion(run_id="run-a", event_id=f"a-{i}", produced_at=i, consumed_at=i + 0.2)
        for i in range(8)
    ]
    run_b = [
        _completion(run_id="run-b", event_id=f"b-{i}", produced_at=10 + i, consumed_at=10.1 + i)
        for i in range(5)
    ]
    mixed = run_a + run_b

    accepted = [row for row in mixed if should_emit_completion(row, "run-b")]
    assert current_run_event_ids(accepted, "run-b") == [f"b-{i}" for i in range(5)]
    assert not set(current_run_event_ids(accepted, "run-b")) & {f"a-{i}" for i in range(8)}

    isolated = summarize_completions(accepted, run_id="run-b", expect=5)
    assert isolated["collected"] == 5
    assert isolated["foreign_records"] == 0
    assert isolated["complete"] is True
    assert validate_run_result(isolated, require_lag=False) == []

    contaminated = summarize_completions(mixed, run_id="run-b", expect=5)
    assert contaminated["collected"] == 5
    assert contaminated["foreign_records"] == 8
    assert contaminated["complete"] is False
    errors = validate_run_result(contaminated, require_lag=False)
    assert any("contamination" in err for err in errors)


def test_consumer_skips_foreign_run_id_without_emitting() -> None:
    assert should_emit_completion({"run_id": "current"}, "current") is True
    assert should_emit_completion({"run_id": "previous"}, "current") is False
    assert matches_run({"run_id": "previous"}, "current") is False


def test_processing_throughput_uses_event_timestamps_not_collector_clock() -> None:
    records = [
        _completion(run_id="r1", event_id="e1", produced_at=0.0, consumed_at=1.0),
        _completion(run_id="r1", event_id="e2", produced_at=0.5, consumed_at=2.0),
    ]
    metrics = processing_metrics(records)
    # min(produced_at)=t0, max(consumed_at)=t0+2s → 2 events / 2s = 1 eps.
    # A collector that finished in 50ms would wrongly report 40 eps.
    assert metrics["processing_duration_seconds"] == 2.0
    assert metrics["consumer_events_per_second"] == 1.0


def test_latency_percentiles_use_current_run_only() -> None:
    previous = [
        _completion(
            run_id="old",
            event_id=f"old-{i}",
            produced_at=0,
            consumed_at=50,
            latency_ms=50_000,
        )
        for i in range(10)
    ]
    current = [
        _completion(
            run_id="new",
            event_id=f"new-{i}",
            produced_at=0,
            consumed_at=0.01 * (i + 1),
            latency_ms=10.0 * (i + 1),
        )
        for i in range(5)
    ]
    result = summarize_completions(previous + current, run_id="new", expect=5)
    assert result["p50_ms"] == percentile([10.0, 20.0, 30.0, 40.0, 50.0], 50)
    assert result["p95_ms"] == percentile([10.0, 20.0, 30.0, 40.0, 50.0], 95)
    assert result["p50_ms"] != 50_000
    assert result["p95_ms"] != 50_000


def test_peak_lag_uses_all_samples() -> None:
    summary = lag_summary([0, 12, 40, 7, 0])
    assert summary == {
        "initial_consumer_lag": 0,
        "peak_consumer_lag": 40,
        "final_consumer_lag": 0,
    }
    empty = lag_summary([])
    assert empty["peak_consumer_lag"] is None
    assert empty["initial_consumer_lag"] is None
    assert empty["final_consumer_lag"] is None


def test_validate_run_result_hard_gates() -> None:
    ok = summarize_completions(
        [_completion(run_id="r", event_id="e1", produced_at=0, consumed_at=1)],
        run_id="r",
        expect=1,
        lag_samples=[4, 9, 1],
    )
    assert validate_run_result(ok, require_lag=True) == []

    missing_lag = dict(ok)
    missing_lag["peak_consumer_lag"] = None
    assert any("peak_consumer_lag" in err for err in validate_run_result(missing_lag))

    bad_duration = dict(ok)
    bad_duration["processing_duration_seconds"] = 0
    bad_duration["consumer_events_per_second"] = None
    errors = validate_run_result(bad_duration, require_lag=True)
    assert any("processing_duration" in err for err in errors)
