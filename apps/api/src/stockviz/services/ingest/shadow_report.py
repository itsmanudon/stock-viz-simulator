"""Private JSON and Markdown evidence for market-data shadow runs."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from stockviz.services.ingest.semantic_acceptance import (
    TECHNICAL_RECOMMENDATIONS,
    DecimalStorageRecommendation,
    SessionScopeEvidence,
)
from stockviz.services.ingest.shadow import SymbolComparison, VolumePrecisionAudit


@dataclass(frozen=True, slots=True)
class SessionScopeSample:
    """Generic comparison of a daily aggregate with a regular-session probe."""

    ticker: str
    session_date: date
    price_max_relative_error: Decimal | None
    volume_relative_error: Decimal | None
    passed: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "session_date": self.session_date.isoformat(),
            "price_max_relative_error": (
                str(self.price_max_relative_error)
                if self.price_max_relative_error is not None
                else None
            ),
            "volume_relative_error": (
                str(self.volume_relative_error) if self.volume_relative_error is not None else None
            ),
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class ShadowRun:
    started_at: datetime
    requested_start: date
    requested_end: date
    symbols: Mapping[str, SymbolComparison]
    volume_precision: VolumePrecisionAudit
    session_scope_evidence: Sequence[SessionScopeEvidence] = field(default_factory=tuple)
    decimal_boundaries: Mapping[str, str] = field(default_factory=dict)
    decimal_storage_recommendation: DecimalStorageRecommendation | None = None
    reproducibility: Mapping[str, object] = field(default_factory=dict)
    blockers: Sequence[str] = field(default_factory=tuple)
    technical_recommendation: str = "DO NOT APPROVE pending unresolved discrepancies"
    licensing_gate: str = "not_approved_individual_subscription"
    verification: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.technical_recommendation not in TECHNICAL_RECOMMENDATIONS:
            raise ValueError("technical recommendation must be one approved acceptance outcome")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "started_at": self.started_at.isoformat(),
            "requested_start": self.requested_start.isoformat(),
            "requested_end": self.requested_end.isoformat(),
            "architecture": {
                "persisted_default_provider": "yfinance",
                "shadow_provider": "massive",
                "shadow_persistence": "disabled",
                "public_serving": "disabled",
                "provider_provenance_field": "source",
            },
            "canonical_semantics": {
                "price_basis": "split_adjusted_not_dividend_adjusted",
                "session_scope": "regular_us_equity_session",
                "session_timezone": "America/New_York",
                "timestamp": "naive_midnight_session_date_label",
                "volume": "exact_decimal_split_adjusted_share_equivalent",
                "missing_sessions": "not_synthesized",
                "completion": "strictly_before_current_new_york_date",
            },
            "methodology": {
                "join": "canonical_new_york_session_date",
                "price_thresholds_bps": [1, 5, 10, 50],
                "volume_thresholds_percent": ["0.01", "0.1", "1", "5"],
                "quantiles": "nearest_rank",
                "corporate_action_window": "two_common_sessions_before_and_after",
                "intraday_reconstruction": "09:30_inclusive_16:00_exclusive_America/New_York",
                "values_modified_to_match": False,
            },
            "symbols": {ticker: result.as_dict() for ticker, result in self.symbols.items()},
            "volume_precision": self.volume_precision.as_dict(),
            "session_scope_evidence": [sample.as_dict() for sample in self.session_scope_evidence],
            "decimal_boundaries": dict(self.decimal_boundaries),
            "decimal_storage_recommendation": (
                self.decimal_storage_recommendation.as_dict()
                if self.decimal_storage_recommendation is not None
                else None
            ),
            "reproducibility": _json_safe(dict(self.reproducibility)),
            "blockers": list(self.blockers),
            "technical_recommendation": self.technical_recommendation,
            "licensing_gate": self.licensing_gate,
            "verification": _json_safe(dict(self.verification)),
        }


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    return str(value)


def _scaled(value: Decimal | None, multiplier: Decimal) -> str:
    if value is None:
        return "n/a"
    return str(value * multiplier)


def _classification_summary(result: SymbolComparison) -> str:
    counts = Counter(item.classification for item in result.discrepancies)
    if not counts:
        return "none"
    return ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))


def _markdown(run: ShadowRun) -> str:
    lines = [
        "# Massive US market-data shadow report",
        "",
        f"Run time: `{run.started_at.isoformat()}`  ",
        f"Requested range: `{run.requested_start}` through `{run.requested_end}`",
        "",
        "This is private/local evaluation evidence. It must not be published, served by the",
        "application, copied into container images, or treated as redistribution approval.",
        "",
        "## Architecture changes",
        "",
        "yfinance remains the sole persisted/default market-data provider. Massive is called",
        "only by the shadow workflow, maps into canonical bars in memory, and has no API, web,",
        "database, Kafka-event, analytics, portfolio, screener, or backtest serving path.",
        "",
        "## Configuration and environment",
        "",
        "Shadow execution is explicitly enabled only for private runs. Credential values are",
        "kept in local environment configuration and are never written into this report.",
        "Explicit provider selection fails before provider work when required configuration is absent.",
        "",
        "## Canonical bar semantics",
        "",
        "Completed US daily OHLC is split-adjusted, not dividend-adjusted, and represents the",
        "regular US equity session. Dates are New York session dates stored as naive-midnight",
        "labels. Volume is an exact Decimal share-equivalent count. Missing sessions are not",
        "synthesized, and a same-New-York-date bar is excluded as incomplete.",
        "",
        "## Provider adapter design",
        "",
        "The Massive adapter owns vendor URLs, authentication, pagination, response keys, raw",
        "timestamps, and corporate-action identifiers. Only canonical `BarRecord` values cross",
        "the daily-bar boundary; `PriceBar.source` remains the provenance field.",
        "",
        "## Shadow comparison methodology",
        "",
        "Bars are joined by canonical session date. Absolute and relative OHLC/volume errors use",
        "exact Decimal inputs; quantiles use nearest rank. Ordinary sessions and the two sessions",
        "on either side of action dates are reported separately. No input is adjusted to improve a match.",
        "Selected completed sessions are independently reconstructed from adjusted one-minute bars",
        "using 09:30 inclusive through 16:00 exclusive in America/New_York.",
        "",
        "## Per-symbol mismatch statistics",
        "",
        "| Symbol | Reference | Candidate | Common | Ref only | Candidate only | Close p95 (bps) | Volume p95 (%) | Classifications |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for ticker, result in sorted(run.symbols.items()):
        lines.append(
            "| "
            + " | ".join(
                (
                    ticker,
                    str(result.reference_rows),
                    str(result.candidate_rows),
                    str(result.common_sessions),
                    str(len(result.reference_only_sessions)),
                    str(len(result.candidate_only_sessions)),
                    _scaled(result.fields["close"].p95_relative_error, Decimal("10000")),
                    _scaled(result.volume.p95_relative_error, Decimal("100")),
                    _classification_summary(result),
                )
            )
            + " |"
        )

    lines.extend(["", "## Corporate-action findings", ""])
    action_lines = []
    for ticker, result in sorted(run.symbols.items()):
        for action in result.actions:
            action_lines.append(
                f"- {ticker}: {action.kind} effective {action.effective_date.isoformat()}; "
                f"{result.corporate_action_sessions} joined action-window session(s)."
            )
    lines.extend(action_lines or ["No provider action dates were present in this run."])

    lines.extend(
        [
            "",
            "## Session-scope findings",
            "",
            "Massive daily aggregates remain `provider_daily`. Each selected session compares",
            "the daily aggregate, open-close result, exact-Decimal regular minute reconstruction,",
            "all-session minute reconstruction, and canonical yfinance bar without normalization.",
            "",
            "| Symbol | Session | Sample | Retrieval | Minutes | Classification |",
            "| --- | --- | --- | --- | ---: | --- |",
        ]
    )
    for sample in run.session_scope_evidence:
        lines.append(
            f"| {sample.ticker} | {sample.selection.session_date} | "
            f"{sample.selection.category} | {sample.retrieval_status} | "
            f"{sample.observed_regular_minutes}/{sample.expected_regular_minutes} | "
            f"{sample.classification} |"
        )
    if not run.session_scope_evidence:
        lines.append("| n/a | n/a | n/a | not evaluated | n/a | not evaluated |")

    lines.extend(
        [
            "",
            "| Symbol | Session | Comparison | Max price error (bps) | Volume error (%) | Result |",
            "| --- | --- | --- | ---: | ---: | --- |",
        ]
    )
    for sample in run.session_scope_evidence:
        for name, comparison in sorted(sample.comparisons.items()):
            price_relative = max(
                (
                    value.relative_error
                    for field_name, value in comparison.fields.items()
                    if field_name != "volume" and value.relative_error is not None
                ),
                default=None,
            )
            volume_relative = comparison.fields["volume"].relative_error
            lines.append(
                f"| {sample.ticker} | {sample.selection.session_date} | {name} | "
                f"{_scaled(price_relative, Decimal('10000'))} | "
                f"{_scaled(volume_relative, Decimal('100'))} | "
                f"{'pass' if comparison.passed else 'fail'} |"
            )

    lines.extend(["", "## Reproducibility", "", "```json"])
    lines.append(json.dumps(_json_safe(dict(run.reproducibility)), indent=2, sort_keys=True))
    lines.extend(["```", "", "## Decimal persistence recommendation", ""])
    if run.decimal_storage_recommendation is None:
        lines.append("Not evaluated.")
    else:
        recommendation = run.decimal_storage_recommendation
        lines.extend(
            [
                f"Recommended future database representation: `{recommendation.database_type}`.",
                f"Observed whole/scale: `{recommendation.observed_whole_digits}`/`{recommendation.observed_scale}`; "
                f"headroom: `{recommendation.magnitude_headroom_digits}` whole and `{recommendation.scale_headroom}` fractional digits.",
                "This is a recommendation only; persistence is unchanged and rounding is forbidden.",
            ]
        )

    lines.extend(["", "## Tests", ""])
    unit_evidence = run.verification.get("unit_tests", "not recorded")
    lines.append(f"Unit/regression evidence: `{unit_evidence}`.")

    lines.extend(["", "## Clean-container verification", ""])
    clean_evidence = run.verification.get("clean_container", "not run for this report")
    lines.append(f"Credential-free clean-build workflow: `{clean_evidence}`.")

    lines.extend(["", "## Blockers and licensing assumptions", ""])
    lines.extend([f"- {blocker}" for blocker in run.blockers] or ["- No runtime blocker recorded."])
    lines.append(
        "- Individual-subscription evidence is private/local only and supplies no production, "
        "commercial, end-user display, persistence, or redistribution permission."
    )

    lines.extend(
        [
            "",
            "## Technical recommendation",
            "",
            f"**{run.technical_recommendation}**",
            "",
            "This gate evaluates semantic mapping, coverage, action windows, timing, session scope,",
            "precision, and operational reliability. It is independent of commercial permission.",
            "",
            "## Production/commercial licensing gate",
            "",
            f"Status: `{run.licensing_gate}`.",
            "",
            "A separate agreement must explicitly permit StockViz's deployment, display, derived",
            "analytics, persistence, and redistribution model before production use.",
            "",
            "## Deferred India domain changes",
            "",
            "TrueData/NSE/BSE work is not implemented. A later milestone needs exchange-qualified",
            "instrument identity, provider instrument IDs and validity ranges, INR-aware asset and",
            "precision rules, NSE/BSE calendars and special sessions, venue-specific timezone and",
            "corporate-action policies, historical FX, and mixed-currency cash/P&L/backtest semantics.",
            "",
        ]
    )
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


def write_shadow_report(run: ShadowRun, output_dir: Path) -> tuple[Path, Path]:
    """Create one immutable, timestamped private evidence directory."""

    if run.started_at.tzinfo is None or run.started_at.utcoffset() is None:
        raise ValueError("shadow report started_at must be timezone-aware")
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = run.started_at.strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=False, exist_ok=False)
    json_path = run_dir / "report.json"
    markdown_path = run_dir / "report.md"
    _atomic_write(json_path, json.dumps(run.as_dict(), indent=2, sort_keys=True) + "\n")
    _atomic_write(markdown_path, _markdown(run))
    return json_path, markdown_path
