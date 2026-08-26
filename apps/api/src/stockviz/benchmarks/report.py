"""Validate and present the measured portfolio benchmark artifact."""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

EXPECTED_REPLICAS = [1, 2, 4, 8]
EXPECTED_EVENTS = 100_000
EXPECTED_PARTITIONS = 12
TABLE_START = "<!-- kafka-benchmark-table:start -->"
TABLE_END = "<!-- kafka-benchmark-table:end -->"


def _positive_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and value > 0


def _non_negative_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and value >= 0


def validate_matrix(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if document.get("event_count_per_run") != EXPECTED_EVENTS:
        errors.append(
            f"event_count_per_run must equal {EXPECTED_EVENTS}, "
            f"got {document.get('event_count_per_run')!r}"
        )
    if document.get("partitions") != EXPECTED_PARTITIONS:
        errors.append(
            f"partitions must equal {EXPECTED_PARTITIONS}, got {document.get('partitions')!r}"
        )
    schedule = document.get("replica_schedule")
    if schedule != [str(value) for value in EXPECTED_REPLICAS]:
        errors.append(f"replica_schedule must be ['1', '2', '4', '8'], got {schedule!r}")

    runs = document.get("runs")
    if not isinstance(runs, list):
        return [*errors, "runs must be a list"]
    replicas = [run.get("replicas") for run in runs if isinstance(run, dict)]
    if replicas != EXPECTED_REPLICAS:
        errors.append(f"replicas must be exactly {EXPECTED_REPLICAS}, got {replicas!r}")
    if len(runs) != len(EXPECTED_REPLICAS):
        errors.append(f"runs must contain exactly four rows, got {len(runs)}")

    for index, run in enumerate(runs):
        if not isinstance(run, dict):
            errors.append(f"run {index} must be an object")
            continue
        label = f"run replicas={run.get('replicas')!r}"
        if run.get("events") != EXPECTED_EVENTS:
            errors.append(f"{label} events must equal {EXPECTED_EVENTS}")
        if run.get("collected") != EXPECTED_EVENTS:
            errors.append(f"{label} collected must equal {EXPECTED_EVENTS}")
        if run.get("foreign_records") != 0:
            errors.append(f"{label} foreign_records must equal 0")
        if run.get("complete") is not True:
            errors.append(f"{label} complete must be true")
        if not _positive_number(run.get("processing_duration_seconds")):
            errors.append(f"{label} processing_duration_seconds must be positive")
        if not _positive_number(run.get("consumer_events_per_second")):
            errors.append(f"{label} consumer_events_per_second must be present and positive")
        if not _non_negative_number(run.get("p50_ms")):
            errors.append(f"{label} p50_ms must be present")
        if not _non_negative_number(run.get("p95_ms")):
            errors.append(f"{label} p95_ms must be present")
        if not isinstance(run.get("peak_consumer_lag"), int):
            errors.append(f"{label} peak_consumer_lag must be present")
    return errors


def _require_valid(document: dict[str, Any]) -> list[dict[str, Any]]:
    errors = validate_matrix(document)
    if errors:
        raise ValueError("; ".join(errors))
    return document["runs"]


def _resource(run: dict[str, Any], field: str, value_key: str, suffix: str) -> str:
    resource = run.get(field)
    if not isinstance(resource, dict):
        return "—"
    value = resource.get(value_key)
    return f"{value:,}{suffix}" if isinstance(value, int | float) else "—"


def markdown_table(document: dict[str, Any]) -> str:
    runs = _require_valid(document)
    rows = [
        "| Replicas | Events | Consumer events/sec | p50 | p95 | Peak lag | Peak CPU/pod | Peak memory/pod |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for run in runs:
        rows.append(
            "| {replicas} | {events:,} | {throughput:,.2f} | {p50:,.1f} ms | "
            "{p95:,.1f} ms | {lag:,} | {cpu} | {memory} |".format(
                replicas=run["replicas"],
                events=run["events"],
                throughput=run["consumer_events_per_second"],
                p50=run["p50_ms"],
                p95=run["p95_ms"],
                lag=run["peak_consumer_lag"],
                cpu=_resource(run, "cpu", "peak_millicores_per_pod", "m"),
                memory=_resource(run, "memory", "peak_mi_per_pod", "Mi"),
            )
        )
    return "\n".join(rows)


def _chart_ceiling(values: list[float]) -> float:
    raw = max(values) * 1.15
    magnitude = 10 ** math.floor(math.log10(raw))
    for multiple in (1, 2, 2.5, 5, 10):
        candidate = multiple * magnitude
        if candidate >= raw:
            return candidate
    return 10 * magnitude


def render_throughput_svg(document: dict[str, Any]) -> str:
    runs = _require_valid(document)
    width, height = 1200, 675
    left, right, top, bottom = 130, 70, 90, 115
    plot_width = width - left - right
    plot_height = height - top - bottom
    throughputs = [float(run["consumer_events_per_second"]) for run in runs]
    ceiling = _chart_ceiling(throughputs)
    xs = [left + plot_width * index / (len(runs) - 1) for index in range(len(runs))]
    ys = [top + plot_height * (1 - value / ceiling) for value in throughputs]
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys, strict=True))
    source_runs = ", ".join(str(run["run_id"]) for run in runs)

    grid: list[str] = []
    for index in range(5):
        value = ceiling * index / 4
        y = top + plot_height * (1 - index / 4)
        grid.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}" '
            'stroke="#dce3ea" stroke-width="1"/>'
        )
        grid.append(
            f'<text x="{left - 18}" y="{y + 6:.1f}" text-anchor="end" '
            f'class="tick">{value:,.0f}</text>'
        )

    marks: list[str] = []
    for run, x, y, throughput in zip(runs, xs, ys, throughputs, strict=True):
        marks.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9" fill="#136f63" '
            'stroke="#ffffff" stroke-width="4"/>'
        )
        marks.append(
            f'<text x="{x:.1f}" y="{y - 20:.1f}" text-anchor="middle" '
            f'class="value">{throughput:,.0f}</text>'
        )
        marks.append(
            f'<text x="{x:.1f}" y="{height - bottom + 38}" text-anchor="middle" '
            f'class="tick">{run["replicas"]}</text>'
        )

    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
            '<title id="title">Kafka consumer throughput by replica count</title>',
            '<desc id="desc">Measured consumer events per second for 100,000 events across 1, 2, 4, and 8 replicas.</desc>',
            f"<metadata>Source runs: {html.escape(source_runs)}</metadata>",
            "<style>.title{font:700 28px system-ui,sans-serif;fill:#17212b}.subtitle{font:16px system-ui,sans-serif;fill:#52606d}.tick{font:15px system-ui,sans-serif;fill:#52606d}.value{font:700 16px system-ui,sans-serif;fill:#17212b}.axis{font:600 17px system-ui,sans-serif;fill:#364152}</style>",
            f'<rect width="{width}" height="{height}" rx="18" fill="#f7f9fb"/>',
            f'<text x="{left}" y="42" class="title">Kafka consumer-group scaling</text>',
            f'<text x="{left}" y="70" class="subtitle">100,000 events · 12 partitions · single-node kind / one Kafka broker</text>',
            *grid,
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" stroke="#8795a1" stroke-width="2"/>',
            f'<line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" stroke="#8795a1" stroke-width="2"/>',
            f'<polyline points="{points}" fill="none" stroke="#136f63" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>',
            *marks,
            f'<text x="{left + plot_width / 2:.1f}" y="{height - 28}" text-anchor="middle" class="axis">Consumer replicas</text>',
            f'<text x="32" y="{top + plot_height / 2:.1f}" text-anchor="middle" class="axis" transform="rotate(-90 32 {top + plot_height / 2:.1f})">Consumer events/sec</text>',
            "</svg>",
            "",
        ]
    )


def check_markdown_table(path: Path, expected_table: str) -> list[str]:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"{re.escape(TABLE_START)}\s*(.*?)\s*{re.escape(TABLE_END)}",
        re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        return [f"{path}: benchmark table markers are missing"]
    if match.group(1).strip() != expected_table.strip():
        return [f"{path}: benchmark table does not match JSON"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and present the full Kafka benchmark.")
    parser.add_argument("--input", type=Path, required=True, help="Measured benchmark JSON")
    parser.add_argument("--chart", type=Path, required=True, help="SVG output path")
    parser.add_argument(
        "--check-markdown",
        type=Path,
        action="append",
        default=[],
        help="Markdown file containing the generated benchmark table block",
    )
    args = parser.parse_args(argv)

    document = json.loads(args.input.read_text(encoding="utf-8"))
    errors = validate_matrix(document)
    if errors:
        for error in errors:
            print(f"benchmark validation: {error}", file=sys.stderr)
        return 1

    table = markdown_table(document)
    for path in args.check_markdown:
        errors.extend(check_markdown_table(path, table))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    args.chart.parent.mkdir(parents=True, exist_ok=True)
    args.chart.write_text(render_throughput_svg(document), encoding="utf-8")
    print(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
