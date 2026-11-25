"""Load parsed NSE rows into ``eod_raw`` and ``eod_extras`` (A1.1).

Only the series in ``LOAD_SERIES`` are loaded. A row is matched to an
instrument by its current ``isin`` identifier first, else by the Yahoo ticker
``<SYMBOL>.NS``; matched by ticker with an ISIN, the ISIN is recorded on the
instrument (once). A row whose ticker match already carries a different
current ISIN is an ``isin_conflict`` and is skipped: either the listing's
ISIN changed (a split) or the symbol now names another company, and this
batch decides neither. Rows with no instrument are counted and skipped; this
batch adds no instruments (universe work is A1.4).

``plan_load`` only reads; ``apply_load`` writes the plan, upserting on the
key (instrument, session, series), so loading the same rows again changes
nothing. The caller commits (one transaction per file).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.models.eod import EodExtras, EodRaw
from stockviz.models.instrument import SCHEME_ISIN, InstrumentIdentifier
from stockviz.services.instruments import instrument_ids
from stockviz.services.nse.parse import CmRow, ParsedFile, SecRow

LOAD_SERIES = frozenset({"EQ", "BE", "BZ", "SM", "ST"})
"""Equity series loaded: EQ (rolling), BE and BZ (trade-for-trade), SM and ST (SME)."""

YAHOO_SUFFIX = ".NS"
_RAW_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "last",
    "prev_close",
    "volume",
    "turnover",
    "trades",
    "isin",
)
_EXTRA_FIELDS = ("deliverable_qty", "delivery_pct")
_SHOWN_UNMATCHED = 10


@dataclass
class LoadPlan:
    rows_total: int = 0
    in_series: int = 0
    unmatched: int = 0
    incomplete: int = 0  # in series but missing a price or the volume
    isin_conflicts: int = 0
    duplicates: int = 0  # a second row for the same key in one file
    unmatched_symbols: list[str] = field(default_factory=list)
    # (instrument_id, session_date, series) -> the row
    rows: dict[tuple[int, date, str], CmRow | SecRow] = field(default_factory=dict)
    isins_to_record: dict[int, str] = field(default_factory=dict)

    @property
    def matched(self) -> int:
        return len(self.rows)


@dataclass
class LoadResult:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    isins_recorded: int = 0

    @property
    def loaded(self) -> int:
        return self.inserted + self.updated + self.unchanged


def _current_isins(session: Session, *, values=None, instrument_ids_=None) -> list[tuple[int, str]]:
    query = select(InstrumentIdentifier.instrument_id, InstrumentIdentifier.value).where(
        col(InstrumentIdentifier.scheme) == SCHEME_ISIN,
        col(InstrumentIdentifier.valid_to).is_(None),
    )
    if values is not None:
        query = query.where(col(InstrumentIdentifier.value).in_(sorted(values)))
    if instrument_ids_ is not None:
        query = query.where(col(InstrumentIdentifier.instrument_id).in_(sorted(instrument_ids_)))
    return [(int(i), str(v)) for i, v in session.exec(query).all()]


def _is_complete(row: CmRow | SecRow) -> bool:
    if isinstance(row, SecRow):
        return True
    return None not in (row.open, row.high, row.low, row.close, row.volume)


def plan_load(session: Session, parsed: ParsedFile) -> LoadPlan:
    """Match rows to instruments and decide what would be written. Read-only."""
    plan = LoadPlan(rows_total=len(parsed.rows))
    wanted = [r for r in parsed.rows if r.series in LOAD_SERIES]
    plan.in_series = len(wanted)
    isins = {r.isin for r in wanted if isinstance(r, CmRow) and r.isin}
    by_isin = {value: iid for iid, value in _current_isins(session, values=isins)} if isins else {}
    by_ticker = instrument_ids(session, [r.symbol + YAHOO_SUFFIX for r in wanted])
    held = dict(_current_isins(session, instrument_ids_=set(by_ticker.values())))

    unmatched: set[str] = set()
    for row in wanted:
        isin = row.isin if isinstance(row, CmRow) else None
        iid = by_isin.get(isin) if isin else None
        if iid is None:
            iid = by_ticker.get(row.symbol + YAHOO_SUFFIX)
            if iid is None:
                plan.unmatched += 1
                unmatched.add(row.symbol)
                continue
            if isin:
                current = held.get(iid) or plan.isins_to_record.get(iid)
                if current is not None and current != isin:
                    plan.isin_conflicts += 1
                    continue
                if current is None:
                    plan.isins_to_record[iid] = isin
        if not _is_complete(row):
            plan.incomplete += 1
            continue
        key = (iid, row.trading_date, row.series)
        if key in plan.rows:
            plan.duplicates += 1
        plan.rows[key] = row
    plan.unmatched_symbols = sorted(unmatched)[:_SHOWN_UNMATCHED]
    return plan


def _record_isins(session: Session, isins: dict[int, str]) -> int:
    """Add each ISIN as the instrument's current ``isin`` identifier.

    Same rule as ``ingest.history.record_identifier`` (``valid_from`` = the
    day it was recorded, ``valid_to`` open). An instrument that already has a
    current ``isin`` is left alone.
    """
    if not isins:
        return 0
    held = {iid for iid, _ in _current_isins(session, instrument_ids_=set(isins))}
    today = date.today()
    added = 0
    for iid, value in sorted(isins.items()):
        if iid in held:
            continue
        session.add(
            InstrumentIdentifier(
                instrument_id=iid, scheme=SCHEME_ISIN, value=value, valid_from=today
            )
        )
        added += 1
    return added


def apply_load(session: Session, plan: LoadPlan, *, data_file_id: int, source: str) -> LoadResult:
    """Write the plan: upsert ``eod_raw`` (CM rows) or ``eod_extras`` (sec rows)."""
    result = LoadResult(isins_recorded=_record_isins(session, plan.isins_to_record))
    if not plan.rows:
        return result
    sample = next(iter(plan.rows.values()))
    model, fields = (
        (EodExtras, _EXTRA_FIELDS) if isinstance(sample, SecRow) else (EodRaw, _RAW_FIELDS)
    )
    ids = {iid for iid, _, _ in plan.rows}
    days = {day for _, day, _ in plan.rows}
    existing = {
        (row.instrument_id, row.session_date, row.series): row
        for row in session.exec(
            select(model).where(
                col(model.instrument_id).in_(sorted(ids)),
                col(model.session_date).in_(sorted(days)),
            )
        ).all()
    }
    now = utcnow()
    for key, row in plan.rows.items():
        values = {name: getattr(row, name) for name in fields}
        stored = existing.get(key)
        if stored is None:
            iid, day, series = key
            extra = {} if model is EodExtras else {"source": source}
            session.add(
                model(
                    instrument_id=iid,
                    session_date=day,
                    series=series,
                    data_file_id=data_file_id,
                    loaded_at=now,
                    **extra,
                    **values,
                )
            )
            result.inserted += 1
            continue
        if all(getattr(stored, name) == value for name, value in values.items()):
            result.unchanged += 1
            continue
        for name, value in values.items():
            setattr(stored, name, value)
        stored.data_file_id = data_file_id
        stored.loaded_at = now
        if isinstance(stored, EodRaw):
            stored.source = source
        session.add(stored)
        result.updated += 1
    session.flush()
    return result
