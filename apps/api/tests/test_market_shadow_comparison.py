"""Hand-calculable tests for provider-neutral shadow statistics."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

import pytest

from stockviz.services.ingest.bar_semantics import AdjustmentSemantics, SessionScope
from stockviz.services.ingest.prices import DAILY_INTERVAL, BarRecord
from stockviz.services.ingest.shadow import (
    ActionWindow,
    RawLatestSessions,
    audit_volume_precision,
    compare_symbol,
)


def _bar(
    session: str,
    *,
    close: str = "100",
    volume: str = "1000",
    source: str = "yfinance",
    session_scope: SessionScope = SessionScope.REGULAR,
    adjustment: AdjustmentSemantics = AdjustmentSemantics.SPLIT_ADJUSTED,
) -> BarRecord:
    close_value = Decimal(close)
    return BarRecord(
        ticker="AAPL",
        ts=datetime.fromisoformat(session),
        interval=DAILY_INTERVAL,
        open=close_value,
        high=close_value,
        low=close_value,
        close=close_value,
        volume=Decimal(volume),
        source=source,
        adjustment_semantics=adjustment,
        session_scope=session_scope,
    )


def _reference() -> list[BarRecord]:
    return [
        _bar("2025-01-02", close="100", volume="1000"),
        _bar("2025-01-03", close="101", volume="1100"),
        _bar("2025-01-04", close="100", volume="1000"),
        _bar("2025-01-07", close="100", volume="1000"),
    ]


def _candidate() -> list[BarRecord]:
    return [
        _bar(
            "2025-01-02",
            close="100",
            volume="1000",
            source="massive",
            session_scope=SessionScope.PROVIDER_DAILY,
        ),
        _bar(
            "2025-01-04",
            close="100.2",
            volume="1020",
            source="massive",
            session_scope=SessionScope.PROVIDER_DAILY,
        ),
        _bar(
            "2025-01-06",
            close="99",
            volume="900",
            source="massive",
            session_scope=SessionScope.PROVIDER_DAILY,
        ),
        _bar(
            "2025-01-07",
            close="100",
            volume="1000",
            source="massive",
            session_scope=SessionScope.PROVIDER_DAILY,
        ),
    ]


def test_compare_symbol_quantifies_sessions_and_errors() -> None:
    result = compare_symbol(
        _reference(),
        _candidate(),
        actions=[],
        raw_latest=RawLatestSessions(
            reference=date(2025, 1, 8),
            candidate=date(2025, 1, 9),
        ),
    )

    assert result.reference_rows == 4
    assert result.candidate_rows == 4
    assert result.common_sessions == 3
    assert result.reference_only_sessions == [date(2025, 1, 3)]
    assert result.candidate_only_sessions == [date(2025, 1, 6)]
    assert result.newest_completed_reference == date(2025, 1, 7)
    assert result.newest_completed_candidate == date(2025, 1, 7)
    assert result.newest_raw_reference == date(2025, 1, 8)
    assert result.newest_raw_candidate == date(2025, 1, 9)
    assert result.fields["close"].maximum_absolute_error == Decimal("0.2")
    assert result.fields["close"].over_10_bps == 1
    assert result.fields["close"].over_50_bps == 0
    assert result.volume.over_1_percent == 1
    assert result.volume.over_5_percent == 0


def test_nearest_rank_quantiles_and_zero_reference_are_deterministic() -> None:
    reference = [_bar(f"2025-01-0{day}", close="0" if day == 2 else "100") for day in (2, 3, 4)]
    candidate = [
        _bar("2025-01-02", close="1", source="massive"),
        _bar("2025-01-03", close="101", source="massive"),
        _bar("2025-01-04", close="103", source="massive"),
    ]

    stats = compare_symbol(reference, candidate, actions=[]).fields["close"]

    assert stats.observations == 3
    assert stats.relative_observations == 2
    assert stats.median_absolute_error == Decimal("1")
    assert stats.p95_absolute_error == Decimal("3")
    assert stats.p99_absolute_error == Decimal("3")


def test_action_window_statistics_are_separate_without_changing_values() -> None:
    result = compare_symbol(
        _reference(),
        _candidate(),
        actions=[ActionWindow("split", date(2025, 1, 6))],
    )

    assert result.corporate_action_sessions == 3
    assert result.ordinary_sessions == 0
    assert result.ordinary_sessions + result.corporate_action_sessions == result.common_sessions
    assert result.corporate_action_fields["close"].maximum_absolute_error == Decimal("0.2")
    assert any(item.classification == "corporate_action" for item in result.discrepancies)


def test_semantic_mismatch_is_classified_not_massaged() -> None:
    result = compare_symbol(_reference(), _candidate(), actions=[])

    close_issue = next(
        item
        for item in result.discrepancies
        if item.session_date == date(2025, 1, 4) and item.field == "close"
    )
    assert close_issue.classification == "provider_eligibility_session_scope"
    assert close_issue.reference_value == Decimal("100")
    assert close_issue.candidate_value == Decimal("100.2")


def test_one_day_shift_with_identical_values_is_classified_as_session_normalization() -> None:
    reference = [_bar("2025-01-02")]
    candidate = [_bar("2025-01-03", source="massive")]

    result = compare_symbol(reference, candidate, actions=[])

    assert {item.classification for item in result.discrepancies} == {
        "session_timezone_normalization"
    }


def test_comparison_serializes_to_json_safe_values() -> None:
    payload = compare_symbol(_reference(), _candidate(), actions=[]).as_dict()

    encoded = json.dumps(payload)

    assert '"maximum_absolute_error": "0.2"' in encoded
    assert payload["reference_only_sessions"] == ["2025-01-03"]


def test_duplicate_sessions_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        compare_symbol([_bar("2025-01-02"), _bar("2025-01-02")], _candidate(), actions=[])


def test_volume_precision_preserves_provider_exponent() -> None:
    bars = [
        _bar("2025-01-02", volume="10", source="massive"),
        _bar("2025-01-03", volume="25933.6000", source="massive"),
    ]

    audit = audit_volume_precision(bars)

    assert audit.maximum_whole_number_digits == 5
    assert audit.maximum_fractional_digits == 4
    assert audit.scale_counts == {0: 1, 4: 1}
    assert audit.recommended_precision == 23
    assert audit.recommended_scale == 4
    assert [(item.ticker, item.session_date) for item in audit.maximum_scale_observations] == [
        ("AAPL", date(2025, 1, 3))
    ]
    assert json.loads(json.dumps(audit.as_dict()))["scale_counts"] == {"0": 1, "4": 1}


def test_volume_precision_rejects_invalid_volume() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        audit_volume_precision([_bar("2025-01-02", volume="-0.1")])
