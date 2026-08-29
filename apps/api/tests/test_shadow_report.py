"""Private JSON/Markdown shadow report tests."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from stockviz.services.ingest.bar_semantics import AdjustmentSemantics, SessionScope
from stockviz.services.ingest.prices import BarRecord
from stockviz.services.ingest.shadow import audit_volume_precision, compare_symbol
from stockviz.services.ingest.shadow_report import (
    SessionScopeSample,
    ShadowRun,
    write_shadow_report,
)


def _bar(source: str, close: str, *, scope: SessionScope) -> BarRecord:
    value = Decimal(close)
    return BarRecord(
        ticker="AAPL",
        ts=datetime(2025, 1, 2),
        interval="1d",
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal("1000.5000"),
        source=source,
        adjustment_semantics=AdjustmentSemantics.SPLIT_ADJUSTED,
        session_scope=scope,
    )


def _run() -> ShadowRun:
    reference = [_bar("yfinance", "100", scope=SessionScope.REGULAR)]
    candidate = [_bar("massive", "100.1", scope=SessionScope.PROVIDER_DAILY)]
    return ShadowRun(
        started_at=datetime(2025, 1, 3, 12, tzinfo=UTC),
        requested_start=date(2025, 1, 1),
        requested_end=date(2025, 1, 3),
        symbols={"AAPL": compare_symbol(reference, candidate, actions=[])},
        volume_precision=audit_volume_precision(candidate),
        session_scope_samples=[
            SessionScopeSample(
                ticker="AAPL",
                session_date=date(2025, 1, 2),
                price_max_relative_error=Decimal("0.0002"),
                volume_relative_error=Decimal("0.01"),
                passed=True,
            )
        ],
        blockers=["live clean-container workflow not run in this fixture"],
        technical_gate="not_evaluated",
        licensing_gate="not_approved_individual_subscription",
        cutover_recommendation="do_not_cut_over",
        verification={"unit_tests": "fixture"},
    )


def test_report_writes_private_json_and_markdown_without_credentials(tmp_path: Path) -> None:
    json_path, markdown_path = write_shadow_report(_run(), tmp_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")

    assert json_path.parent == tmp_path / "20250103T120000Z"
    assert payload["symbols"]["AAPL"]["common_sessions"] == 1
    assert payload["volume_precision"]["maximum_fractional_digits"] == 4
    assert "| AAPL |" in markdown
    for heading in (
        "Architecture changes",
        "Configuration and environment",
        "Canonical bar semantics",
        "Provider adapter design",
        "Shadow comparison methodology",
        "Per-symbol mismatch statistics",
        "Corporate-action findings",
        "Session-scope findings",
        "Tests",
        "Clean-container verification",
        "Blockers and licensing assumptions",
        "Technical provider gate",
        "Production/commercial licensing gate",
        "Cutover recommendation",
        "Deferred India domain changes",
    ):
        assert f"## {heading}" in markdown
    combined = json_path.read_text(encoding="utf-8") + markdown
    assert "secret" not in combined.lower()
    assert "api_key" not in combined.lower()


def test_report_refuses_to_overwrite_an_existing_run_directory(tmp_path: Path) -> None:
    write_shadow_report(_run(), tmp_path)

    try:
        write_shadow_report(_run(), tmp_path)
    except FileExistsError:
        pass
    else:
        raise AssertionError("expected immutable run directory")


def test_shadow_run_json_is_explicit_about_separate_gates() -> None:
    payload = _run().as_dict()

    assert payload["technical_gate"] == "not_evaluated"
    assert payload["licensing_gate"] == "not_approved_individual_subscription"
    assert payload["cutover_recommendation"] == "do_not_cut_over"
