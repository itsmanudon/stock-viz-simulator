"""Provider-neutral, deterministic market-data shadow comparison statistics."""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, Decimal

from stockviz.services.ingest.prices import BarRecord

PRICE_THRESHOLDS = {
    "over_1_bps": Decimal("0.0001"),
    "over_5_bps": Decimal("0.0005"),
    "over_10_bps": Decimal("0.001"),
    "over_50_bps": Decimal("0.005"),
}
VOLUME_THRESHOLDS = {
    "over_0_01_percent": Decimal("0.0001"),
    "over_0_1_percent": Decimal("0.001"),
    "over_1_percent": Decimal("0.01"),
    "over_5_percent": Decimal("0.05"),
}


@dataclass(frozen=True, slots=True)
class ActionWindow:
    kind: str
    effective_date: date


@dataclass(frozen=True, slots=True)
class RawLatestSessions:
    reference: date | None = None
    candidate: date | None = None


def _decimal_json(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


@dataclass(frozen=True, slots=True)
class MetricStatistics:
    observations: int
    relative_observations: int
    mean_absolute_error: Decimal | None
    median_absolute_error: Decimal | None
    p95_absolute_error: Decimal | None
    p99_absolute_error: Decimal | None
    maximum_absolute_error: Decimal | None
    mean_relative_error: Decimal | None
    median_relative_error: Decimal | None
    p95_relative_error: Decimal | None
    p99_relative_error: Decimal | None
    maximum_relative_error: Decimal | None
    threshold_counts: Mapping[str, int]

    @property
    def over_1_bps(self) -> int:
        return self.threshold_counts.get("over_1_bps", 0)

    @property
    def over_5_bps(self) -> int:
        return self.threshold_counts.get("over_5_bps", 0)

    @property
    def over_10_bps(self) -> int:
        return self.threshold_counts.get("over_10_bps", 0)

    @property
    def over_50_bps(self) -> int:
        return self.threshold_counts.get("over_50_bps", 0)

    @property
    def over_0_01_percent(self) -> int:
        return self.threshold_counts.get("over_0_01_percent", 0)

    @property
    def over_0_1_percent(self) -> int:
        return self.threshold_counts.get("over_0_1_percent", 0)

    @property
    def over_1_percent(self) -> int:
        return self.threshold_counts.get("over_1_percent", 0)

    @property
    def over_5_percent(self) -> int:
        return self.threshold_counts.get("over_5_percent", 0)

    def as_dict(self) -> dict[str, object]:
        return {
            "observations": self.observations,
            "relative_observations": self.relative_observations,
            "mean_absolute_error": _decimal_json(self.mean_absolute_error),
            "median_absolute_error": _decimal_json(self.median_absolute_error),
            "p95_absolute_error": _decimal_json(self.p95_absolute_error),
            "p99_absolute_error": _decimal_json(self.p99_absolute_error),
            "maximum_absolute_error": _decimal_json(self.maximum_absolute_error),
            "mean_relative_error": _decimal_json(self.mean_relative_error),
            "median_relative_error": _decimal_json(self.median_relative_error),
            "p95_relative_error": _decimal_json(self.p95_relative_error),
            "p99_relative_error": _decimal_json(self.p99_relative_error),
            "maximum_relative_error": _decimal_json(self.maximum_relative_error),
            **dict(self.threshold_counts),
        }


@dataclass(frozen=True, slots=True)
class Discrepancy:
    kind: str
    classification: str
    session_date: date
    field: str | None = None
    reference_value: Decimal | None = None
    candidate_value: Decimal | None = None
    relative_error: Decimal | None = None
    candidate_session_date: date | None = None
    detail: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "classification": self.classification,
            "session_date": self.session_date.isoformat(),
            "candidate_session_date": (
                self.candidate_session_date.isoformat()
                if self.candidate_session_date is not None
                else None
            ),
            "field": self.field,
            "reference_value": _decimal_json(self.reference_value),
            "candidate_value": _decimal_json(self.candidate_value),
            "relative_error": _decimal_json(self.relative_error),
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class SymbolComparison:
    ticker: str
    reference_source: str
    candidate_source: str
    reference_rows: int
    candidate_rows: int
    common_sessions: int
    reference_only_sessions: list[date]
    candidate_only_sessions: list[date]
    newest_completed_reference: date | None
    newest_completed_candidate: date | None
    newest_raw_reference: date | None
    newest_raw_candidate: date | None
    ordinary_sessions: int
    corporate_action_sessions: int
    fields: Mapping[str, MetricStatistics]
    volume: MetricStatistics
    ordinary_fields: Mapping[str, MetricStatistics]
    ordinary_volume: MetricStatistics
    corporate_action_fields: Mapping[str, MetricStatistics]
    corporate_action_volume: MetricStatistics
    actions: list[ActionWindow]
    discrepancies: list[Discrepancy]

    def as_dict(self) -> dict[str, object]:
        def optional_date(value: date | None) -> str | None:
            return value.isoformat() if value is not None else None

        return {
            "ticker": self.ticker,
            "reference_source": self.reference_source,
            "candidate_source": self.candidate_source,
            "reference_rows": self.reference_rows,
            "candidate_rows": self.candidate_rows,
            "common_sessions": self.common_sessions,
            "reference_only_sessions": [
                value.isoformat() for value in self.reference_only_sessions
            ],
            "candidate_only_sessions": [
                value.isoformat() for value in self.candidate_only_sessions
            ],
            "newest_completed_reference": optional_date(self.newest_completed_reference),
            "newest_completed_candidate": optional_date(self.newest_completed_candidate),
            "newest_raw_reference": optional_date(self.newest_raw_reference),
            "newest_raw_candidate": optional_date(self.newest_raw_candidate),
            "ordinary_sessions": self.ordinary_sessions,
            "corporate_action_sessions": self.corporate_action_sessions,
            "fields": {name: stats.as_dict() for name, stats in self.fields.items()},
            "volume": self.volume.as_dict(),
            "ordinary_fields": {
                name: stats.as_dict() for name, stats in self.ordinary_fields.items()
            },
            "ordinary_volume": self.ordinary_volume.as_dict(),
            "corporate_action_fields": {
                name: stats.as_dict() for name, stats in self.corporate_action_fields.items()
            },
            "corporate_action_volume": self.corporate_action_volume.as_dict(),
            "actions": [
                {"kind": action.kind, "effective_date": action.effective_date.isoformat()}
                for action in self.actions
            ],
            "discrepancies": [item.as_dict() for item in self.discrepancies],
        }


@dataclass(frozen=True, slots=True)
class VolumePrecisionObservation:
    ticker: str
    session_date: date
    value: Decimal
    scale: int

    def as_dict(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "session_date": self.session_date.isoformat(),
            "value": str(self.value),
            "scale": self.scale,
        }


@dataclass(frozen=True, slots=True)
class VolumePrecisionAudit:
    observations: int
    maximum_whole_number_digits: int
    maximum_fractional_digits: int
    scale_counts: Mapping[int, int]
    maximum_scale_observations: list[VolumePrecisionObservation]

    def as_dict(self) -> dict[str, object]:
        return {
            "observations": self.observations,
            "maximum_whole_number_digits": self.maximum_whole_number_digits,
            "maximum_fractional_digits": self.maximum_fractional_digits,
            "scale_counts": {str(scale): count for scale, count in self.scale_counts.items()},
            "maximum_scale_observations": [
                item.as_dict() for item in self.maximum_scale_observations
            ],
        }


def _nearest_rank(values: Sequence[Decimal], percentile: Decimal) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(
        1,
        int((percentile * Decimal(len(ordered))).to_integral_value(rounding=ROUND_CEILING)),
    )
    return ordered[rank - 1]


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, start=Decimal(0)) / Decimal(len(values))


def _relative_error(reference: Decimal, candidate: Decimal) -> Decimal | None:
    if reference == 0:
        return None
    return abs(candidate - reference) / abs(reference)


def _metric_statistics(
    pairs: Iterable[tuple[Decimal, Decimal]],
    *,
    thresholds: Mapping[str, Decimal],
) -> MetricStatistics:
    materialized = list(pairs)
    absolute = [abs(candidate - reference) for reference, candidate in materialized]
    relative = [
        error
        for reference, candidate in materialized
        if (error := _relative_error(reference, candidate)) is not None
    ]
    return MetricStatistics(
        observations=len(materialized),
        relative_observations=len(relative),
        mean_absolute_error=_mean(absolute),
        median_absolute_error=_nearest_rank(absolute, Decimal("0.50")),
        p95_absolute_error=_nearest_rank(absolute, Decimal("0.95")),
        p99_absolute_error=_nearest_rank(absolute, Decimal("0.99")),
        maximum_absolute_error=max(absolute, default=None),
        mean_relative_error=_mean(relative),
        median_relative_error=_nearest_rank(relative, Decimal("0.50")),
        p95_relative_error=_nearest_rank(relative, Decimal("0.95")),
        p99_relative_error=_nearest_rank(relative, Decimal("0.99")),
        maximum_relative_error=max(relative, default=None),
        threshold_counts={
            name: sum(error > threshold for error in relative)
            for name, threshold in thresholds.items()
        },
    )


def _bar_map(bars: Sequence[BarRecord], *, role: str) -> dict[date, BarRecord]:
    mapped: dict[date, BarRecord] = {}
    for bar in bars:
        if bar.interval != "1d":
            raise ValueError(f"{role} comparison accepts daily bars only")
        if bar.ts.tzinfo is not None or bar.ts.time().isoformat() != "00:00:00":
            raise ValueError(f"{role} bar timestamp must be a canonical naive-midnight label")
        session_date = bar.ts.date()
        if session_date in mapped:
            raise ValueError(f"duplicate {role} session: {session_date.isoformat()}")
        mapped[session_date] = bar
    return mapped


def _action_session_dates(
    common_dates: Sequence[date],
    actions: Sequence[ActionWindow],
) -> set[date]:
    selected: set[date] = set()
    for action in actions:
        index = bisect_left(common_dates, action.effective_date)
        before = common_dates[max(0, index - 2) : index]
        if index < len(common_dates) and common_dates[index] == action.effective_date:
            after_start = index + 1
            selected.add(common_dates[index])
        else:
            after_start = index
        selected.update(before)
        selected.update(common_dates[after_start : after_start + 2])
    return selected


def _semantic_classification(
    reference: BarRecord,
    candidate: BarRecord,
    *,
    in_action_window: bool,
) -> str:
    if in_action_window:
        return "corporate_action"
    if reference.adjustment_semantics != candidate.adjustment_semantics:
        return "adjusted_unadjusted_basis"
    if reference.session_scope != candidate.session_scope:
        return "provider_eligibility_session_scope"
    return "actual_provider_disagreement"


def _same_values(reference: BarRecord, candidate: BarRecord) -> bool:
    return all(
        getattr(reference, field) == getattr(candidate, field)
        for field in ("open", "high", "low", "close", "volume")
    )


def _shifted_pairs(
    reference_only: Sequence[date],
    candidate_only: Sequence[date],
    reference: Mapping[date, BarRecord],
    candidate: Mapping[date, BarRecord],
) -> tuple[list[tuple[date, date]], set[date], set[date]]:
    pairs: list[tuple[date, date]] = []
    used_reference: set[date] = set()
    used_candidate: set[date] = set()
    for reference_date in reference_only:
        for candidate_date in candidate_only:
            if candidate_date in used_candidate:
                continue
            if abs((candidate_date - reference_date).days) != 1:
                continue
            if not _same_values(reference[reference_date], candidate[candidate_date]):
                continue
            pairs.append((reference_date, candidate_date))
            used_reference.add(reference_date)
            used_candidate.add(candidate_date)
            break
    return pairs, used_reference, used_candidate


def _field_statistics(
    dates: Iterable[date],
    reference: Mapping[date, BarRecord],
    candidate: Mapping[date, BarRecord],
) -> tuple[dict[str, MetricStatistics], MetricStatistics]:
    materialized = list(dates)
    fields = {
        field: _metric_statistics(
            (
                (getattr(reference[session], field), getattr(candidate[session], field))
                for session in materialized
            ),
            thresholds=PRICE_THRESHOLDS,
        )
        for field in ("open", "high", "low", "close")
    }
    volume = _metric_statistics(
        ((reference[session].volume, candidate[session].volume) for session in materialized),
        thresholds=VOLUME_THRESHOLDS,
    )
    return fields, volume


def compare_symbol(
    reference: Sequence[BarRecord],
    candidate: Sequence[BarRecord],
    *,
    actions: Sequence[ActionWindow],
    raw_latest: RawLatestSessions | None = None,
) -> SymbolComparison:
    """Join canonical bars by session and quantify, never alter, mismatches."""

    reference_map = _bar_map(reference, role="reference")
    candidate_map = _bar_map(candidate, role="candidate")
    tickers = {bar.ticker for bar in [*reference, *candidate]}
    if len(tickers) > 1:
        raise ValueError("comparison bars must all have the same ticker")
    ticker = next(iter(tickers), "")
    reference_sources = {bar.source for bar in reference}
    candidate_sources = {bar.source for bar in candidate}
    if len(reference_sources) > 1 or len(candidate_sources) > 1:
        raise ValueError("each comparison side must use one provider source")

    reference_dates = set(reference_map)
    candidate_dates = set(candidate_map)
    common_dates = sorted(reference_dates & candidate_dates)
    reference_only = sorted(reference_dates - candidate_dates)
    candidate_only = sorted(candidate_dates - reference_dates)
    action_dates = _action_session_dates(common_dates, actions)
    ordinary_dates = [value for value in common_dates if value not in action_dates]
    corporate_action_dates = [value for value in common_dates if value in action_dates]

    fields, volume = _field_statistics(common_dates, reference_map, candidate_map)
    ordinary_fields, ordinary_volume = _field_statistics(
        ordinary_dates, reference_map, candidate_map
    )
    corporate_fields, corporate_volume = _field_statistics(
        corporate_action_dates, reference_map, candidate_map
    )

    discrepancies: list[Discrepancy] = []
    for session_date in common_dates:
        reference_bar = reference_map[session_date]
        candidate_bar = candidate_map[session_date]
        classification = _semantic_classification(
            reference_bar,
            candidate_bar,
            in_action_window=session_date in action_dates,
        )
        for field in ("open", "high", "low", "close"):
            reference_value = getattr(reference_bar, field)
            candidate_value = getattr(candidate_bar, field)
            relative = _relative_error(reference_value, candidate_value)
            if not (
                (relative is None and reference_value != candidate_value)
                or (relative is not None and relative > PRICE_THRESHOLDS["over_10_bps"])
            ):
                continue
            discrepancies.append(
                Discrepancy(
                    kind="price",
                    classification=classification,
                    session_date=session_date,
                    field=field,
                    reference_value=reference_value,
                    candidate_value=candidate_value,
                    relative_error=relative,
                )
            )
        relative_volume = _relative_error(reference_bar.volume, candidate_bar.volume)
        if (relative_volume is None and reference_bar.volume != candidate_bar.volume) or (
            relative_volume is not None and relative_volume > VOLUME_THRESHOLDS["over_1_percent"]
        ):
            discrepancies.append(
                Discrepancy(
                    kind="volume",
                    classification=classification,
                    session_date=session_date,
                    field="volume",
                    reference_value=reference_bar.volume,
                    candidate_value=candidate_bar.volume,
                    relative_error=relative_volume,
                )
            )

    shifted, shifted_reference, shifted_candidate = _shifted_pairs(
        reference_only, candidate_only, reference_map, candidate_map
    )
    discrepancies.extend(
        Discrepancy(
            kind="session",
            classification="session_timezone_normalization",
            session_date=reference_date,
            candidate_session_date=candidate_date,
            detail="identical OHLCV appears on adjacent provider session labels",
        )
        for reference_date, candidate_date in shifted
    )
    newest_union = max(reference_dates | candidate_dates, default=None)
    for session_date in reference_only:
        if session_date in shifted_reference:
            continue
        classification = (
            "provider_timing"
            if newest_union is not None and session_date == newest_union
            else "actual_provider_disagreement"
        )
        discrepancies.append(
            Discrepancy(
                kind="missing_session",
                classification=classification,
                session_date=session_date,
                detail="session exists only in the reference provider",
            )
        )
    for session_date in candidate_only:
        if session_date in shifted_candidate:
            continue
        classification = (
            "provider_timing"
            if newest_union is not None and session_date == newest_union
            else "actual_provider_disagreement"
        )
        discrepancies.append(
            Discrepancy(
                kind="extra_session",
                classification=classification,
                session_date=session_date,
                detail="session exists only in the candidate provider",
            )
        )

    latest = raw_latest or RawLatestSessions()
    if latest.reference != latest.candidate:
        newest_raw = max(
            (value for value in (latest.reference, latest.candidate) if value is not None),
            default=None,
        )
        if newest_raw is not None:
            newest_completed = max(
                (
                    value
                    for value in (
                        max(reference_dates, default=None),
                        max(candidate_dates, default=None),
                    )
                    if value is not None
                ),
                default=None,
            )
            classification = (
                "incomplete_latest_session"
                if newest_completed is None or newest_raw > newest_completed
                else "provider_timing"
            )
            discrepancies.append(
                Discrepancy(
                    kind="newest_raw_session",
                    classification=classification,
                    session_date=newest_raw,
                    detail="providers expose different newest raw session dates",
                )
            )

    return SymbolComparison(
        ticker=ticker,
        reference_source=next(iter(reference_sources), ""),
        candidate_source=next(iter(candidate_sources), ""),
        reference_rows=len(reference),
        candidate_rows=len(candidate),
        common_sessions=len(common_dates),
        reference_only_sessions=reference_only,
        candidate_only_sessions=candidate_only,
        newest_completed_reference=max(reference_dates, default=None),
        newest_completed_candidate=max(candidate_dates, default=None),
        newest_raw_reference=latest.reference,
        newest_raw_candidate=latest.candidate,
        ordinary_sessions=len(ordinary_dates),
        corporate_action_sessions=len(corporate_action_dates),
        fields=fields,
        volume=volume,
        ordinary_fields=ordinary_fields,
        ordinary_volume=ordinary_volume,
        corporate_action_fields=corporate_fields,
        corporate_action_volume=corporate_volume,
        actions=list(actions),
        discrepancies=discrepancies,
    )


def _finite_decimal_exponent(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        raise ValueError("volume precision audit requires finite Decimal values")
    return exponent


def _whole_number_digits(value: Decimal) -> int:
    if value == 0:
        return 1
    digits = len(value.as_tuple().digits)
    exponent = _finite_decimal_exponent(value)
    return max(1, digits + exponent)


def audit_volume_precision(bars: Sequence[BarRecord]) -> VolumePrecisionAudit:
    """Measure provider volume exponents without normalizing or rounding."""

    observations: list[VolumePrecisionObservation] = []
    maximum_whole_digits = 0
    counts: Counter[int] = Counter()
    for bar in bars:
        value = bar.volume
        if not value.is_finite() or value < 0:
            raise ValueError("volume precision audit requires finite non-negative Decimal values")
        exponent = _finite_decimal_exponent(value)
        scale = max(0, -exponent)
        counts[scale] += 1
        maximum_whole_digits = max(maximum_whole_digits, _whole_number_digits(value))
        observations.append(
            VolumePrecisionObservation(
                ticker=bar.ticker,
                session_date=bar.ts.date(),
                value=value,
                scale=scale,
            )
        )
    maximum_scale = max(counts, default=0)
    maximum_observations = [item for item in observations if item.scale == maximum_scale]
    return VolumePrecisionAudit(
        observations=len(observations),
        maximum_whole_number_digits=maximum_whole_digits,
        maximum_fractional_digits=maximum_scale,
        scale_counts=dict(sorted(counts.items())),
        maximum_scale_observations=maximum_observations,
    )
