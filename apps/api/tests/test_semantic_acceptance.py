from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from stockviz.services.ingest.bar_semantics import AdjustmentSemantics, SessionScope
from stockviz.services.ingest.prices import BarRecord
from stockviz.services.ingest.semantic_acceptance import (
    APPROVE_CANONICAL,
    APPROVE_DIFFERENT_RETRIEVAL,
    DO_NOT_APPROVE,
    SessionSampleSelection,
    audit_decimal_boundaries,
    build_session_evidence,
    recommend_decimal_storage,
    select_session_samples,
    technical_recommendation,
)
from stockviz.services.ingest.shadow import ActionWindow, audit_volume_precision, compare_symbol


def _bar(
    source: str,
    *,
    session_date: date = date(2025, 1, 2),
    close: str = "100.125",
    volume: str = "1000.5000",
    scope: SessionScope = SessionScope.REGULAR,
) -> BarRecord:
    value = Decimal(close)
    return BarRecord(
        ticker="AAPL",
        ts=datetime.combine(session_date, datetime.min.time()),
        interval="1d",
        open=value,
        high=value + Decimal("1.125"),
        low=value - Decimal("1.250"),
        close=value,
        volume=Decimal(volume),
        source=source,
        adjustment_semantics=AdjustmentSemantics.SPLIT_ADJUSTED,
        session_scope=scope,
    )


def test_sampling_is_deterministic_and_separates_ordinary_from_action_windows() -> None:
    sessions = [date(2025, 1, 1) + timedelta(days=index) for index in range(10)]
    actions = [
        ActionWindow(kind="split", effective_date=sessions[4]),
        ActionWindow(kind="dividend", effective_date=sessions[7]),
    ]

    samples = select_session_samples(sessions, actions)

    assert [(item.session_date, item.category) for item in samples] == [
        (sessions[0], "ordinary"),
        (sessions[2], "ordinary"),
        (sessions[3], "corporate_action"),
        (sessions[4], "corporate_action"),
        (sessions[5], "corporate_action"),
        (sessions[6], "corporate_action"),
        (sessions[7], "corporate_action"),
        (sessions[8], "corporate_action"),
        (sessions[9], "ordinary"),
    ]
    assert samples[3].action_kind == "split"
    assert samples[7].action_kind == "dividend"


def test_session_evidence_keeps_exact_decimal_errors_and_identifies_extended_hours() -> None:
    selection = SessionSampleSelection(date(2025, 1, 2), "ordinary")
    regular = _bar("massive_intraday_reconstruction", volume="1000.5000")
    all_session = _bar(
        "massive_intraday_reconstruction", volume="1010.6250", scope=SessionScope.PROVIDER_DAILY
    )
    daily = _bar("massive", volume="1010.6250", scope=SessionScope.PROVIDER_DAILY)
    yfinance = _bar("yfinance", volume="1000.5000")
    open_close = _bar("massive_open_close", volume="1000.5000")

    evidence = build_session_evidence(
        selection=selection,
        daily=daily,
        intraday_regular=regular,
        intraday_all_session=all_session,
        open_close=open_close,
        yfinance=yfinance,
        retrieval_status="complete",
        expected_regular_minutes=390,
        observed_regular_minutes=389,
        absence_reason_counts={"no_qualifying_trade": 1},
        request={"endpoint": "https://api.massive.com/example", "adjusted": True},
    )

    volume = evidence.comparisons["daily_vs_intraday_regular"].fields["volume"]
    assert volume.absolute_error == Decimal("10.1250")
    assert volume.relative_error == Decimal("10.1250") / Decimal("1000.5000")
    assert evidence.classification == "extended_hours_activity"
    assert evidence.comparisons["daily_vs_intraday_all_session"].passed is True
    assert evidence.comparisons["yfinance_vs_intraday_regular"].passed is True
    assert all(
        not isinstance(value, float)
        for value in (
            volume.reference_value,
            volume.candidate_value,
            volume.absolute_error,
            volume.relative_error,
        )
    )


def test_technical_recommendation_uses_exactly_one_allowed_outcome() -> None:
    reference = [_bar("yfinance")]
    daily = [_bar("massive", scope=SessionScope.PROVIDER_DAILY)]
    comparison = compare_symbol(reference, daily, actions=[])
    selection = SessionSampleSelection(date(2025, 1, 2), "ordinary")

    regular_evidence = build_session_evidence(
        selection=selection,
        daily=daily[0],
        intraday_regular=reference[0],
        intraday_all_session=reference[0],
        open_close=reference[0],
        yfinance=reference[0],
        retrieval_status="complete",
        expected_regular_minutes=390,
        observed_regular_minutes=390,
        absence_reason_counts={},
        request={},
    )
    assert technical_recommendation({"AAPL": comparison}, [regular_evidence]) == APPROVE_CANONICAL

    extended = build_session_evidence(
        selection=selection,
        daily=_bar("massive", volume="1020", scope=SessionScope.PROVIDER_DAILY),
        intraday_regular=reference[0],
        intraday_all_session=_bar(
            "massive_intraday_reconstruction", volume="1020", scope=SessionScope.PROVIDER_DAILY
        ),
        open_close=reference[0],
        yfinance=reference[0],
        retrieval_status="complete",
        expected_regular_minutes=390,
        observed_regular_minutes=390,
        absence_reason_counts={},
        request={},
    )
    assert technical_recommendation({"AAPL": comparison}, [extended]) == APPROVE_DIFFERENT_RETRIEVAL

    unavailable = build_session_evidence(
        selection=selection,
        daily=daily[0],
        intraday_regular=None,
        intraday_all_session=None,
        open_close=reference[0],
        yfinance=reference[0],
        retrieval_status="provider_data_unavailable",
        expected_regular_minutes=390,
        observed_regular_minutes=0,
        absence_reason_counts={"provider_data_unavailable": 390},
        request={},
    )
    assert technical_recommendation({"AAPL": comparison}, [unavailable]) == DO_NOT_APPROVE


def test_decimal_recommendation_adds_policy_headroom_and_audits_current_boundaries() -> None:
    bars = [
        _bar("massive", volume="12345678.1234", scope=SessionScope.PROVIDER_DAILY),
        _bar("massive", volume="1.2", scope=SessionScope.PROVIDER_DAILY),
    ]

    recommendation = recommend_decimal_storage(audit_volume_precision(bars))
    boundaries = audit_decimal_boundaries()

    assert recommendation.database_type == "NUMERIC(38,12)"
    assert recommendation.precision == 38
    assert recommendation.scale == 12
    assert recommendation.whole_digit_capacity == 26
    assert recommendation.scale_headroom == 8
    assert recommendation.magnitude_headroom_digits == 18
    assert recommendation.rounding_permitted is False
    assert boundaries["canonical_bar_record"] == "Decimal"
    assert boundaries["price_bars_database"] == "BIGINT"
    assert boundaries["price_bar_orm"] == "int"
    assert boundaries["public_bar_schema"] == "int"
    assert boundaries["artifact_decimal_encoding"] == "string"
