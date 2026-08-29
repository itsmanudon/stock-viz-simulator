import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
from stockviz.benchmarks.report import (
    check_markdown_table,
    markdown_table,
    render_throughput_svg,
    validate_matrix,
)
from stockviz.benchmarks.report import (
    main as report_main,
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


def _portfolio_matrix() -> dict:
    runs = []
    for replicas, throughput, p50, p95, cpu, memory in (
        (1, 500.4, 120.4, 800.6, None, None),
        (
            2,
            800.0,
            100.0,
            650.2,
            {"peak_millicores_per_pod": 105, "source": "kubectl_top_during_workload"},
            {"peak_mi_per_pod": 26, "source": "kubectl_top_during_workload"},
        ),
        (
            4,
            1100.12,
            80.1,
            500.0,
            {"peak_millicores_per_pod": 210, "source": "kubectl_top_during_workload"},
            {"peak_mi_per_pod": 31, "source": "kubectl_top_during_workload"},
        ),
        (
            8,
            900.5,
            95.5,
            710.7,
            {"peak_millicores_per_pod": 240, "source": "kubectl_top_during_workload"},
            {"peak_mi_per_pod": 35, "source": "kubectl_top_during_workload"},
        ),
    ):
        runs.append(
            {
                "run_id": f"measured-r{replicas}",
                "replicas": replicas,
                "events": 100_000,
                "partitions": 12,
                "collected": 100_000,
                "foreign_records": 0,
                "producer_events_per_second": 20_000.0,
                "processing_duration_seconds": 100_000 / throughput,
                "consumer_events_per_second": throughput,
                "p50_ms": p50,
                "p95_ms": p95,
                "p99_ms": p95 + 100,
                "initial_consumer_lag": 0,
                "peak_consumer_lag": 100_000,
                "final_consumer_lag": 0,
                "cpu": cpu,
                "memory": memory,
                "complete": True,
            }
        )
    return {
        "generated_at": "2026-08-26T12:00:00+00:00",
        "event_count_per_run": 100_000,
        "replica_schedule": ["1", "2", "4", "8"],
        "topic": "stockviz.benchmark.v1",
        "partitions": 12,
        "runs": runs,
    }


def test_portfolio_matrix_requires_exact_complete_100k_runs() -> None:
    document = _portfolio_matrix()
    assert validate_matrix(document) == []

    mutations = {
        "replicas": lambda doc: doc["runs"].pop(),
        "events": lambda doc: doc["runs"][0].update(events=99_999),
        "collected": lambda doc: doc["runs"][0].update(collected=99_999),
        "foreign_records": lambda doc: doc["runs"][0].update(foreign_records=1),
        "complete": lambda doc: doc["runs"][0].update(complete=False),
        "processing_duration_seconds": lambda doc: doc["runs"][0].update(
            processing_duration_seconds=0
        ),
        "consumer_events_per_second": lambda doc: doc["runs"][0].update(
            consumer_events_per_second=None
        ),
        "p50_ms": lambda doc: doc["runs"][0].update(p50_ms=None),
        "p95_ms": lambda doc: doc["runs"][0].update(p95_ms=None),
        "peak_consumer_lag": lambda doc: doc["runs"][0].update(peak_consumer_lag=None),
    }
    for field, mutate in mutations.items():
        changed = _portfolio_matrix()
        mutate(changed)
        assert any(field in error for error in validate_matrix(changed)), field


def test_portfolio_matrix_accepts_present_zero_latency_values() -> None:
    document = _portfolio_matrix()
    document["runs"][0]["p50_ms"] = 0
    document["runs"][0]["p95_ms"] = 0
    assert validate_matrix(document) == []


def test_markdown_table_formats_measured_values_without_inventing_resources() -> None:
    table = markdown_table(_portfolio_matrix())
    assert table == "\n".join(
        [
            "| Replicas | Events | Consumer events/sec | p50 | p95 | Peak lag | Peak CPU/pod | Peak memory/pod |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            "| 1 | 100,000 | 500.40 | 120.4 ms | 800.6 ms | 100,000 | — | — |",
            "| 2 | 100,000 | 800.00 | 100.0 ms | 650.2 ms | 100,000 | 105m | 26Mi |",
            "| 4 | 100,000 | 1,100.12 | 80.1 ms | 500.0 ms | 100,000 | 210m | 31Mi |",
            "| 8 | 100,000 | 900.50 | 95.5 ms | 710.7 ms | 100,000 | 240m | 35Mi |",
        ]
    )


def test_throughput_svg_plots_every_measured_replica_and_names_source_runs() -> None:
    svg = render_throughput_svg(_portfolio_matrix())
    assert svg.count("<circle ") == 4
    assert "Consumer events/sec" in svg
    assert "Consumer replicas" in svg
    assert all(f">{replicas}<" in svg for replicas in (1, 2, 4, 8))
    assert "measured-r1, measured-r2, measured-r4, measured-r8" in svg


def test_markdown_check_compares_the_generated_table_block(tmp_path: Path) -> None:
    table = markdown_table(_portfolio_matrix())
    path = tmp_path / "README.md"
    path.write_text(
        "# Test\n\n<!-- kafka-benchmark-table:start -->\n"
        f"{table}\n"
        "<!-- kafka-benchmark-table:end -->\n",
        encoding="utf-8",
    )
    assert check_markdown_table(path, table) == []

    path.write_text(path.read_text(encoding="utf-8").replace("500.40", "999.99"), encoding="utf-8")
    assert check_markdown_table(path, table) == [f"{path}: benchmark table does not match JSON"]


def test_report_cli_validates_docs_and_writes_chart(tmp_path: Path) -> None:
    document = _portfolio_matrix()
    artifact = tmp_path / "kafka-scaling-100k.json"
    chart = tmp_path / "kafka-consumer-throughput.svg"
    readme = tmp_path / "README.md"
    artifact.write_text(json.dumps(document), encoding="utf-8")
    readme.write_text(
        "<!-- kafka-benchmark-table:start -->\n"
        f"{markdown_table(document)}\n"
        "<!-- kafka-benchmark-table:end -->\n",
        encoding="utf-8",
    )

    assert (
        report_main(
            [
                "--input",
                str(artifact),
                "--chart",
                str(chart),
                "--check-markdown",
                str(readme),
            ]
        )
        == 0
    )
    assert chart.read_text(encoding="utf-8") == render_throughput_svg(document)
