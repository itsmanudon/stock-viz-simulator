"""Private, provider-neutral evidence for Massive semantic acceptance."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import get_type_hints

from stockviz.models import PriceBar
from stockviz.schemas import BarOut
from stockviz.services.ingest.prices import BarRecord
from stockviz.services.ingest.shadow import ActionWindow, SymbolComparison, VolumePrecisionAudit

APPROVE_CANONICAL = "APPROVE Massive for canonical US market-data integration"
APPROVE_DIFFERENT_RETRIEVAL = (
    "APPROVE Massive but require a different regular-session retrieval strategy"
)
DO_NOT_APPROVE = "DO NOT APPROVE pending unresolved discrepancies"
TECHNICAL_RECOMMENDATIONS = frozenset(
    (APPROVE_CANONICAL, APPROVE_DIFFERENT_RETRIEVAL, DO_NOT_APPROVE)
)

PRICE_TOLERANCE = Decimal("0.001")
VOLUME_TOLERANCE = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class SessionSampleSelection:
    session_date: date
    category: str
    action_kind: str | None = None
    action_effective_date: date | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "session_date": self.session_date.isoformat(),
            "category": self.category,
            "action_kind": self.action_kind,
            "action_effective_date": (
                self.action_effective_date.isoformat() if self.action_effective_date else None
            ),
        }


@dataclass(frozen=True, slots=True)
class DecimalDifference:
    reference_value: Decimal
    candidate_value: Decimal
    absolute_error: Decimal
    relative_error: Decimal | None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "reference_value": str(self.reference_value),
            "candidate_value": str(self.candidate_value),
            "absolute_error": str(self.absolute_error),
            "relative_error": str(self.relative_error) if self.relative_error is not None else None,
        }


@dataclass(frozen=True, slots=True)
class OhlcvComparison:
    reference: str
    candidate: str
    fields: Mapping[str, DecimalDifference]
    passed: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "reference": self.reference,
            "candidate": self.candidate,
            "fields": {name: value.as_dict() for name, value in self.fields.items()},
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class SessionScopeEvidence:
    ticker: str
    selection: SessionSampleSelection
    retrieval_status: str
    expected_regular_minutes: int
    observed_regular_minutes: int
    absence_reason_counts: Mapping[str, int]
    request: Mapping[str, object]
    comparisons: Mapping[str, OhlcvComparison]
    classification: str

    def as_dict(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "selection": self.selection.as_dict(),
            "retrieval_status": self.retrieval_status,
            "expected_regular_minutes": self.expected_regular_minutes,
            "observed_regular_minutes": self.observed_regular_minutes,
            "absence_reason_counts": dict(self.absence_reason_counts),
            "request": dict(self.request),
            "comparisons": {
                name: comparison.as_dict() for name, comparison in self.comparisons.items()
            },
            "classification": self.classification,
        }


@dataclass(frozen=True, slots=True)
class DecimalStorageRecommendation:
    database_type: str
    sqlalchemy_type: str
    precision: int
    scale: int
    whole_digit_capacity: int
    observed_whole_digits: int
    observed_scale: int
    magnitude_headroom_digits: int
    scale_headroom: int
    rounding_permitted: bool
    policy: str

    def as_dict(self) -> dict[str, object]:
        return {
            "database_type": self.database_type,
            "sqlalchemy_type": self.sqlalchemy_type,
            "precision": self.precision,
            "scale": self.scale,
            "whole_digit_capacity": self.whole_digit_capacity,
            "observed_whole_digits": self.observed_whole_digits,
            "observed_scale": self.observed_scale,
            "magnitude_headroom_digits": self.magnitude_headroom_digits,
            "scale_headroom": self.scale_headroom,
            "rounding_permitted": self.rounding_permitted,
            "policy": self.policy,
        }


def select_session_samples(
    common_sessions: Sequence[date],
    actions: Sequence[ActionWindow],
) -> list[SessionSampleSelection]:
    """Choose deterministic ordinary and latest-per-kind action samples."""

    sessions = sorted(set(common_sessions))
    if not sessions:
        return []
    latest_by_kind: dict[str, ActionWindow] = {}
    for action in actions:
        current = latest_by_kind.get(action.kind)
        if current is None or action.effective_date > current.effective_date:
            latest_by_kind[action.kind] = action
    selected: dict[date, SessionSampleSelection] = {}
    for action in sorted(
        latest_by_kind.values(), key=lambda item: (item.effective_date, item.kind)
    ):
        index = bisect_left(sessions, action.effective_date)
        anchor = min(index, len(sessions) - 1)
        for sample_index in range(max(0, anchor - 1), min(len(sessions), anchor + 2)):
            sample_date = sessions[sample_index]
            selected[sample_date] = SessionSampleSelection(
                session_date=sample_date,
                category="corporate_action",
                action_kind=action.kind,
                action_effective_date=action.effective_date,
            )
    ordinary = [value for value in sessions if value not in selected]
    if ordinary:
        for index in sorted({0, len(ordinary) // 2, len(ordinary) - 1}):
            sample_date = ordinary[index]
            selected[sample_date] = SessionSampleSelection(sample_date, "ordinary")
    return [selected[value] for value in sorted(selected)]


def _difference(reference: Decimal, candidate: Decimal) -> DecimalDifference:
    absolute = abs(candidate - reference)
    relative = None if reference == 0 else absolute / abs(reference)
    return DecimalDifference(reference, candidate, absolute, relative)


def _compare(reference: BarRecord, candidate: BarRecord) -> OhlcvComparison:
    fields = {
        name: _difference(getattr(reference, name), getattr(candidate, name))
        for name in ("open", "high", "low", "close", "volume")
    }
    passed = all(
        difference.relative_error is not None
        and difference.relative_error <= (VOLUME_TOLERANCE if name == "volume" else PRICE_TOLERANCE)
        for name, difference in fields.items()
    )
    return OhlcvComparison(reference.source, candidate.source, fields, passed)


def build_session_evidence(
    *,
    selection: SessionSampleSelection,
    daily: BarRecord,
    intraday_regular: BarRecord | None,
    intraday_all_session: BarRecord | None,
    open_close: BarRecord | None,
    yfinance: BarRecord,
    retrieval_status: str,
    expected_regular_minutes: int,
    observed_regular_minutes: int,
    absence_reason_counts: Mapping[str, int],
    request: Mapping[str, object],
) -> SessionScopeEvidence:
    comparisons: dict[str, OhlcvComparison] = {}
    if intraday_regular is not None:
        comparisons["daily_vs_intraday_regular"] = _compare(intraday_regular, daily)
        comparisons["yfinance_vs_intraday_regular"] = _compare(intraday_regular, yfinance)
        if open_close is not None:
            comparisons["open_close_vs_intraday_regular"] = _compare(intraday_regular, open_close)
    if intraday_all_session is not None:
        comparisons["daily_vs_intraday_all_session"] = _compare(intraday_all_session, daily)

    if retrieval_status != "complete" or intraday_regular is None:
        classification = "provider_data_unavailable"
    elif (
        not comparisons["daily_vs_intraday_regular"].passed
        and comparisons.get("daily_vs_intraday_all_session") is not None
        and comparisons["daily_vs_intraday_all_session"].passed
    ):
        classification = "extended_hours_activity"
    elif comparisons["daily_vs_intraday_regular"].passed:
        unequal = any(
            value.absolute_error != 0
            for value in comparisons["daily_vs_intraday_regular"].fields.values()
        )
        classification = (
            "rounding_or_small_provider_difference" if unequal else "regular_session_consistent"
        )
    elif selection.category == "corporate_action":
        classification = "adjustment_methodology_or_provider_disagreement"
    else:
        classification = "qualifying_trade_rules_or_provider_disagreement"

    return SessionScopeEvidence(
        ticker=daily.ticker,
        selection=selection,
        retrieval_status=retrieval_status,
        expected_regular_minutes=expected_regular_minutes,
        observed_regular_minutes=observed_regular_minutes,
        absence_reason_counts=dict(absence_reason_counts),
        request=dict(request),
        comparisons=comparisons,
        classification=classification,
    )


def _historical_daily_passes(result: SymbolComparison) -> bool:
    return (
        result.common_sessions > 0
        and not result.reference_only_sessions
        and not result.candidate_only_sessions
        and not any(stats.over_10_bps for stats in result.fields.values())
        and result.volume.over_1_percent == 0
    )


def technical_recommendation(
    comparisons: Mapping[str, SymbolComparison],
    samples: Sequence[SessionScopeEvidence],
) -> str:
    if not comparisons or not samples:
        return DO_NOT_APPROVE
    if any(sample.retrieval_status != "complete" for sample in samples):
        return DO_NOT_APPROVE
    if any(
        "yfinance_vs_intraday_regular" not in sample.comparisons
        or not sample.comparisons["yfinance_vs_intraday_regular"].passed
        for sample in samples
    ):
        return DO_NOT_APPROVE
    unresolved = {
        "provider_data_unavailable",
        "adjustment_methodology_or_provider_disagreement",
        "qualifying_trade_rules_or_provider_disagreement",
        "rounding_or_small_provider_difference",
    }
    if any(sample.classification in unresolved for sample in samples):
        return DO_NOT_APPROVE
    daily_regular_passes = all(
        sample.comparisons.get("daily_vs_intraday_regular") is not None
        and sample.comparisons["daily_vs_intraday_regular"].passed
        for sample in samples
    )
    open_close_passes = all(
        sample.comparisons.get("open_close_vs_intraday_regular") is not None
        and sample.comparisons["open_close_vs_intraday_regular"].passed
        for sample in samples
    )
    historical_passes = all(_historical_daily_passes(result) for result in comparisons.values())
    if daily_regular_passes and open_close_passes and historical_passes:
        return APPROVE_CANONICAL
    return APPROVE_DIFFERENT_RETRIEVAL


def recommend_decimal_storage(audit: VolumePrecisionAudit) -> DecimalStorageRecommendation:
    """Apply explicit policy headroom rather than copying the sample maximum."""

    scale = max(12, audit.maximum_fractional_digits + 4)
    whole_digits = max(26, audit.maximum_whole_number_digits + 8)
    precision = whole_digits + scale
    return DecimalStorageRecommendation(
        database_type=f"NUMERIC({precision},{scale})",
        sqlalchemy_type=f"Numeric({precision}, {scale}, asdecimal=True)",
        precision=precision,
        scale=scale,
        whole_digit_capacity=whole_digits,
        observed_whole_digits=audit.maximum_whole_number_digits,
        observed_scale=audit.maximum_fractional_digits,
        magnitude_headroom_digits=whole_digits - audit.maximum_whole_number_digits,
        scale_headroom=scale - audit.maximum_fractional_digits,
        rounding_permitted=False,
        policy=(
            "minimum 38-digit interoperability envelope with at least 12 fractional "
            "digits, four fractional digits beyond observation, and eight whole digits "
            "beyond observed magnitude"
        ),
    )


def _type_name(value: object) -> str:
    return getattr(value, "__name__", str(value))


def audit_decimal_boundaries() -> dict[str, str]:
    """Record current application boundaries without mutating persistence."""

    return {
        "canonical_bar_record": _type_name(get_type_hints(BarRecord)["volume"]),
        "price_bars_database": str(PriceBar.__table__.c.volume.type).upper(),  # pyright: ignore[reportAttributeAccessIssue]
        "price_bar_orm": _type_name(PriceBar.model_fields["volume"].annotation),
        "public_bar_schema": _type_name(BarOut.model_fields["volume"].annotation),
        "artifact_decimal_encoding": "string",
        "arithmetic": "exact Decimal; no float coercion, truncation, or rounding",
    }
