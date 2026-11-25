"""`/v1/checklist` and `/v1/symbols/{ticker}/checklist` (A2.4, M4.4).

Read the nightly ``checklist_scores`` (the ``checklist`` job) and the weekly
``checklist_evidence``. Every response carries each dimension's formula (the
setup version's canonical text and its conditions), its latest evidence grade
with the sample it was measured on and the universe's survivorship stamp, and
a neutral disclaimer. Public, 60/min.

On a fresh database the dimension setups do not exist until a job or
``seed`` writes them; the first read seeds them (idempotent).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func
from sqlmodel import Session, col, select

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import ChecklistEvidence, ChecklistScore, InstrumentIdentifier, Symbol
from stockviz.models.instrument import SCHEME_YAHOO
from stockviz.schemas import (
    ChecklistConditionDefOut,
    ChecklistDimensionOut,
    ChecklistEvidenceOut,
    ChecklistOut,
    ChecklistResultOut,
    ChecklistRowOut,
    ChecklistVariantOut,
    SymbolChecklistOut,
    UniverseOut,
)
from stockviz.services.backtest.universe import evidence_universe, screen_universe
from stockviz.services.checklist.dimensions import (
    DIMENSION_BY_KEY,
    DIMENSIONS,
    Variant,
    load_variants,
)
from stockviz.services.instruments import is_index_ticker
from stockviz.services.markets.calendar import venue_for_ticker

router = APIRouter(prefix="/v1", tags=["checklist"])

SessionDep = Annotated[Session, Depends(get_session)]

TOTAL = len(DIMENSIONS)
STALE_DAYS = 5
DISCLAIMER = (
    "The Checklist counts how many of six published conditions a symbol meets "
    "on its latest stored session. It is not a recommendation to buy, sell or "
    "hold anything. Evidence grades measure what followed in the past on a "
    "survivorship-biased universe, net of modelled fees; past association is "
    "not a forecast."
)


def _variants(session: Session) -> dict[tuple[str, str], Variant]:
    try:
        return load_variants(session, seed=False)
    except LookupError:
        return load_variants(session, seed=True)


def _evidence(session: Session, version_ids: list[int]) -> dict[int, ChecklistEvidenceOut]:
    if not version_ids:
        return {}
    rows = session.exec(
        select(ChecklistEvidence)
        .where(col(ChecklistEvidence.setup_version_id).in_(version_ids))
        .order_by(col(ChecklistEvidence.computed_at).desc(), col(ChecklistEvidence.id).desc())
    ).all()
    stamp = evidence_universe()
    out: dict[int, ChecklistEvidenceOut] = {}
    for row in rows:
        if row.setup_version_id in out:
            continue
        out[row.setup_version_id] = ChecklistEvidenceOut(
            grade=row.grade,  # type: ignore[arg-type]
            n_events=row.n_events,
            symbols=row.symbols,
            horizon=row.horizon,
            window_start=row.window_start,
            window_end=row.window_end,
            mean_excess=row.mean_excess,
            t_stat=row.t_stat,
            hit_rate=row.hit_rate,
            mean_net_return=row.mean_net_return,
            base_rate=row.base_rate,
            overlapping_skipped=row.overlapping_skipped,
            fee_schedules={k: int(v) for k, v in (row.fee_schedules or {}).items()},
            universe=UniverseOut(
                name=row.universe,
                point_in_time=row.point_in_time,
                survivorship_biased=row.survivorship_biased,
                note=stamp.note,
            ),
            computed_at=row.computed_at,
        )
    return out


def _dimensions(session: Session) -> list[ChecklistDimensionOut]:
    variants = _variants(session)
    evidence = _evidence(session, [v.version.id for v in variants.values() if v.version.id])
    out: list[ChecklistDimensionOut] = []
    for d in DIMENSIONS:
        items: list[ChecklistVariantOut] = []
        for scope in d.scopes:
            v = variants[(d.key, scope)]
            assert v.setup.id is not None and v.version.id is not None
            items.append(
                ChecklistVariantOut(
                    scope=scope,  # type: ignore[arg-type]
                    setup_id=v.setup.id,
                    setup_version_id=v.version.id,
                    version=v.version.version,
                    canonical=v.version.canonical_text,
                    hash=v.version.rule_hash,
                    conditions=[
                        ChecklistConditionDefOut(label=c.label, rule=r.canonical_text)
                        for c, r in v.conditions
                    ],
                    evidence=evidence.get(v.version.id),
                )
            )
        out.append(
            ChecklistDimensionOut(
                key=d.key, name=d.name, summary=d.summary, source=d.source, variants=items
            )
        )
    return out


def _latest_rows(session: Session, instrument_id: int | None = None):
    latest = select(
        col(ChecklistScore.instrument_id).label("instrument_id"),
        func.max(ChecklistScore.session_date).label("session_date"),
    ).group_by(col(ChecklistScore.instrument_id))
    if instrument_id is not None:
        latest = latest.where(col(ChecklistScore.instrument_id) == instrument_id)
    sub = latest.subquery()
    stmt = (
        select(ChecklistScore, Symbol)
        .join(
            sub,
            (col(ChecklistScore.instrument_id) == sub.c.instrument_id)
            & (col(ChecklistScore.session_date) == sub.c.session_date),
        )
        .join(
            InstrumentIdentifier,
            (col(InstrumentIdentifier.instrument_id) == col(ChecklistScore.instrument_id))
            & (col(InstrumentIdentifier.scheme) == SCHEME_YAHOO)
            & col(InstrumentIdentifier.valid_to).is_(None),
        )
        .join(Symbol, col(Symbol.ticker) == col(InstrumentIdentifier.value))
        .where(col(Symbol.is_active))
    )
    return [
        (row, symbol)
        for row, symbol in session.exec(stmt).all()
        if not is_index_ticker(symbol.ticker)
    ]


def _row_out(row: ChecklistScore, symbol: Symbol) -> ChecklistRowOut:
    return ChecklistRowOut(
        ticker=symbol.ticker,
        name=symbol.name,
        sector=symbol.sector,
        currency=symbol.currency,
        session_date=row.session_date,
        met=row.met_count,
        evaluated=row.evaluated_count,
        total=TOTAL,
        results=[ChecklistResultOut.model_validate(d) for d in row.dimensions],
        computed_at=row.computed_at,
    )


def _mark_stale(rows: list[ChecklistRowOut], newest: dict[str, date]) -> None:
    for row in rows:
        peak = newest.get(venue_for_ticker(row.ticker))
        row.stale = peak is not None and (peak - row.session_date).days > STALE_DAYS


def _newest_by_venue(session: Session) -> dict[str, date]:
    newest: dict[str, date] = {}
    for row, symbol in _latest_rows(session):
        venue = venue_for_ticker(symbol.ticker)
        newest[venue] = max(newest.get(venue, row.session_date), row.session_date)
    return newest


@router.get("/checklist", response_model=ChecklistOut)
@limiter.limit("60/minute")
def list_checklist(
    request: Request,
    session: SessionDep,
    min_met: Annotated[int, Query(ge=0, le=TOTAL)] = 0,
    dimension: Annotated[
        str | None, Query(description="Only symbols that meet this dimension (its key)")
    ] = None,
    sort: Literal["met", "ticker"] = "met",
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChecklistOut:
    """Every active symbol's latest checklist, most dimensions met first."""
    if dimension is not None and dimension not in DIMENSION_BY_KEY:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown dimension {dimension!r}; one of {', '.join(DIMENSION_BY_KEY)}",
        )
    dimensions = _dimensions(session)
    pairs = _latest_rows(session)
    rows = [_row_out(r, s) for r, s in pairs]
    newest: dict[str, date] = {}
    for row in rows:
        venue = venue_for_ticker(row.ticker)
        newest[venue] = max(newest.get(venue, row.session_date), row.session_date)
    _mark_stale(rows, newest)
    rows = [r for r in rows if r.met >= min_met]
    if dimension is not None:
        rows = [r for r in rows if any(x.key == dimension and x.status == "met" for x in r.results)]
    if sort == "ticker":
        rows.sort(key=lambda r: r.ticker)
    else:
        rows.sort(key=lambda r: (-r.met, -r.evaluated, r.ticker))
    return ChecklistOut(
        dimensions=dimensions,
        rows=rows[offset : offset + limit],
        total=len(rows),
        universe=screen_universe(),
        disclaimer=DISCLAIMER,
    )


@router.get("/symbols/{ticker}/checklist", response_model=SymbolChecklistOut)
@limiter.limit("60/minute")
def symbol_checklist(request: Request, ticker: str, session: SessionDep) -> SymbolChecklistOut:
    """One symbol's latest checklist with every dimension's formula and grade."""
    ticker = ticker.upper()
    symbol = session.get(Symbol, ticker)
    if symbol is None or is_index_ticker(ticker):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Symbol {ticker!r} not found")
    from stockviz.services.instruments import instrument_ids

    instrument_id = instrument_ids(session, [ticker]).get(ticker)
    found = _latest_rows(session, instrument_id) if instrument_id is not None else []
    row = _row_out(*found[0]) if found else None
    if row is not None:
        _mark_stale([row], _newest_by_venue(session))
    return SymbolChecklistOut(
        ticker=ticker,
        dimensions=_dimensions(session),
        row=row,
        universe=screen_universe(),
        disclaimer=DISCLAIMER,
    )
