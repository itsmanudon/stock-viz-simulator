"""Private JSON/Markdown shadow report tests."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from stockviz.services.ingest.bar_semantics import AdjustmentSemantics, SessionScope
from stockviz.services.ingest.prices import BarRecord
from stockviz.services.ingest.semantic_acceptance import (
    DO_NOT_APPROVE,
    SessionSampleSelection,
    audit_decimal_boundaries,
    build_session_evidence,
    recommend_decimal_storage,
)
from stockviz.services.ingest.shadow import audit_volume_precision, compare_symbol
from stockviz.services.ingest.shadow_report import ShadowRun, write_shadow_report


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
    precision = audit_volume_precision(candidate)
    intraday = _bar("massive_intraday_reconstruction", "100", scope=SessionScope.REGULAR)
    evidence = build_session_evidence(
        selection=SessionSampleSelection(date(2025, 1, 2), "ordinary"),
        daily=candidate[0],
        intraday_regular=intraday,
        intraday_all_session=intraday,
        open_close=intraday,
        yfinance=reference[0],
        retrieval_status="complete",
        expected_regular_minutes=390,
        observed_regular_minutes=390,
        absence_reason_counts={},
        request={
            "endpoint": "https://api.massive.com/v2/aggs/ticker/AAPL/range/1/minute/2025-01-02/2025-01-02",
            "params": {"adjusted": "true", "sort": "asc", "limit": "50000"},
        },
    )
    return ShadowRun(
        started_at=datetime(2025, 1, 3, 12, tzinfo=UTC),
        requested_start=date(2025, 1, 1),
        requested_end=date(2025, 1, 3),
        symbols={"AAPL": compare_symbol(reference, candidate, actions=[])},
        volume_precision=precision,
        session_scope_evidence=[evidence],
        decimal_boundaries=audit_decimal_boundaries(),
        decimal_storage_recommendation=recommend_decimal_storage(precision),
        reproducibility={
            "historical_date_range": {"from": "2025-01-01", "to": "2025-01-03"},
            "timezone": "America/New_York",
            "regular_session": "09:30 inclusive to 16:00 exclusive",
            "sampling_rule": "oldest/middle/newest ordinary plus latest split/dividend windows",
            "endpoints": [
                {
                    "purpose": "daily",
                    "endpoint": "https://api.massive.com/v2/aggs/ticker/AAPL/range/1/day/2025-01-01/2025-01-03",
                    "params": {"adjusted": "true", "sort": "asc", "limit": "50000"},
                }
            ],
        },
        blockers=["live clean-container workflow not run in this fixture"],
        technical_recommendation=DO_NOT_APPROVE,
        licensing_gate="not_approved_individual_subscription",
        verification={"unit_tests": "fixture"},
    )


def test_report_writes_private_json_and_markdown_without_credentials(tmp_path: Path) -> None:
    json_path, markdown_path = write_shadow_report(_run(), tmp_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")

    assert json_path.parent == tmp_path / "20250103T120000Z"
    assert payload["symbols"]["AAPL"]["common_sessions"] == 1
    assert payload["volume_precision"]["maximum_fractional_digits"] == 4
    assert payload["session_scope_evidence"][0]["expected_regular_minutes"] == 390
    assert payload["decimal_storage_recommendation"]["database_type"] == "NUMERIC(38,12)"
    assert payload["reproducibility"]["timezone"] == "America/New_York"
    assert payload["reproducibility"]["endpoints"][0]["params"]["adjusted"] == "true"
    assert "| AAPL |" in markdown
    assert "daily_vs_intraday_regular" in markdown
    assert "yfinance_vs_intraday_regular" in markdown
    assert "## Reproducibility" in markdown
    assert "## Decimal persistence recommendation" in markdown
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
        "Technical recommendation",
        "Production/commercial licensing gate",
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

    assert payload["technical_recommendation"] == DO_NOT_APPROVE
    assert payload["licensing_gate"] == "not_approved_individual_subscription"
    assert "technical_gate" not in payload
    assert "cutover_recommendation" not in payload
