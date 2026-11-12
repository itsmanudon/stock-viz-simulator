"""Write and read fundamentals point-in-time (Phase 6.3).

``record_facts`` appends: a figure is written only when it is new, or its
value differs from the latest stored version for the same (source, concept,
period). Re-running an ingest writes nothing; a restatement writes one row.

``facts_as_of`` returns, for each (concept, period), the latest version known
on a date, preferring a point-in-time source (EDGAR) over one that is not
(yfinance) when both have the period.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlmodel import Session, col, select

from stockviz.models.fundamentals import FundamentalFact

SOURCE_RANK = {"edgar": 2, "yfinance": 1}


@dataclass(frozen=True)
class FactRecord:
    concept: str
    period_type: str  # annual | quarter | instant
    period_end: date
    value: Decimal
    unit: str
    available_at: date
    point_in_time: bool
    source: str
    source_concept: str
    currency: str | None = None
    period_start: date | None = None
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    form: str | None = None
    accession: str | None = None


def _key(source: str, concept: str, period_type: str, period_end: date) -> tuple:
    return (source, concept, period_type, period_end)


def record_facts(session: Session, instrument_id: int, records: list[FactRecord]) -> int:
    """Append new or changed figures. Returns rows written. Does not commit."""
    latest: dict[tuple, FundamentalFact] = {}
    for row in session.exec(
        select(FundamentalFact)
        .where(col(FundamentalFact.instrument_id) == instrument_id)
        .order_by(col(FundamentalFact.available_at))
    ).all():
        latest[_key(row.source, row.concept, row.period_type, row.period_end)] = row
    written = 0
    for rec in sorted(records, key=lambda r: r.available_at):
        key = _key(rec.source, rec.concept, rec.period_type, rec.period_end)
        stored = latest.get(key)
        if stored is not None and (
            stored.value == rec.value or stored.available_at >= rec.available_at
        ):
            continue
        row = FundamentalFact(
            instrument_id=instrument_id,
            concept=rec.concept,
            period_type=rec.period_type,
            period_start=rec.period_start,
            period_end=rec.period_end,
            fiscal_year=rec.fiscal_year,
            fiscal_period=rec.fiscal_period,
            value=rec.value,
            unit=rec.unit,
            currency=rec.currency,
            available_at=rec.available_at,
            point_in_time=rec.point_in_time,
            source=rec.source,
            source_concept=rec.source_concept,
            form=rec.form,
            accession=rec.accession,
        )
        session.add(row)
        latest[key] = row
        written += 1
    return written


def facts_as_of(
    session: Session,
    instrument_id: int,
    as_of: date,
    *,
    period_types: tuple[str, ...] = ("annual", "quarter", "instant"),
) -> dict[tuple[str, str, date], FundamentalFact]:
    """``(concept, period_type, period_end) -> the version known on as_of``."""
    rows = session.exec(
        select(FundamentalFact).where(
            col(FundamentalFact.instrument_id) == instrument_id,
            col(FundamentalFact.available_at) <= as_of,
            col(FundamentalFact.period_type).in_(period_types),
        )
    ).all()
    best: dict[tuple[str, str, date], FundamentalFact] = {}
    for row in rows:
        key = (row.concept, row.period_type, row.period_end)
        held = best.get(key)
        rank = (SOURCE_RANK.get(row.source, 0), row.available_at)
        if held is None or rank > (SOURCE_RANK.get(held.source, 0), held.available_at):
            best[key] = row
    return best
