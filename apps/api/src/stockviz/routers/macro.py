"""`/v1/macro` (A9.7, M1.10, M3.5): stored FRED series and the spreads.

Read-only and public like `/v1/markets`. Nothing here calls FRED: the data
comes from `stockviz.cli macro-sync`.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session

from stockviz._time import utcnow
from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.schemas import (
    MacroObservationOut,
    MacroOverviewOut,
    MacroPointOut,
    MacroSeriesDetailOut,
    MacroSeriesOut,
    MacroSpreadOut,
)
from stockviz.services.macro import view
from stockviz.services.macro.catalogue import BY_ID, GROUPS

router = APIRouter(prefix="/v1/macro", tags=["macro"])

SessionDep = Annotated[Session, Depends(get_session)]

THIRD_PARTY_NOTE = (
    "Series marked third party are republished by FRED from their owners (ICE, CBOE, Moody's). "
    "They are shown for personal research and need a licence check before anyone else sees them."
)
METHOD = (
    "Values as FRED publishes them, fetched weekly. Changes compare the newest value with the "
    "last one on or before the same date a month and a year earlier. A spread is the first "
    "series minus the second on the first's dates, the second taken as of that date and at most "
    "7 days old."
)


def _point(p: view.Point | None) -> MacroPointOut | None:
    return MacroPointOut(day=p.day, value=p.value) if p else None


def _series_out(s: view.SeriesSummary) -> MacroSeriesOut:
    meta = s.meta
    return MacroSeriesOut(
        series_id=s.entry.series_id,
        group=s.entry.group,
        label=s.entry.label,
        title=meta.title if meta else None,
        units=meta.units if meta else None,
        frequency=meta.frequency if meta else None,
        third_party=s.entry.third_party,
        fetched=meta is not None,
        fetched_at=meta.fetched_at if meta else None,
        latest=_point(s.latest),
        change_month=view.change(s, "month"),
        change_year=view.change(s, "year"),
        stale=s.stale,
        spark=[MacroPointOut(day=p.day, value=p.value) for p in s.spark],
        source_url=f"https://fred.stlouisfed.org/series/{s.entry.series_id}",
    )


@router.get("", response_model=MacroOverviewOut)
@limiter.limit("60/minute")
def macro_overview(request: Request, session: SessionDep) -> MacroOverviewOut:
    today = utcnow().date()
    summaries = view.overview(session, today)
    since = today - timedelta(days=365 * 3)
    spreads_out: list[MacroSpreadOut] = []
    for sp in view.spreads(session, since):
        latest = sp.points[-1] if sp.points else None
        year_ago = (
            view.value_on_or_before(sp.points, latest.day - timedelta(days=365)) if latest else None
        )
        spreads_out.append(
            MacroSpreadOut(
                key=sp.spread.key,
                label=sp.spread.label,
                a=sp.spread.a,
                b=sp.spread.b,
                units=sp.spread.units,
                note=sp.spread.note,
                latest=_point(latest),
                year_ago=_point(year_ago),
                points=[MacroPointOut(day=p.day, value=p.value) for p in view.thin(sp.points)],
                reason=sp.reason,
            )
        )
    fetched = [s.meta.fetched_at for s in summaries if s.meta and s.meta.fetched_at]
    return MacroOverviewOut(
        groups=list(GROUPS),
        series=[_series_out(s) for s in summaries],
        spreads=spreads_out,
        last_fetched_at=max(fetched) if fetched else None,
        source="FRED, Federal Reserve Bank of St. Louis",
        third_party_note=THIRD_PARTY_NOTE,
        method=METHOD,
    )


@router.get("/{series_id}", response_model=MacroSeriesDetailOut)
@limiter.limit("60/minute")
def macro_series(
    request: Request,
    session: SessionDep,
    series_id: str,
    since: Annotated[date | None, Query(alias="from")] = None,
) -> MacroSeriesDetailOut:
    entry = BY_ID.get(series_id.upper())
    if entry is None:
        raise HTTPException(status_code=404, detail="Not a series StockViz keeps.")
    today = utcnow().date()
    rows = view.observations(session, entry.series_id, since)
    return MacroSeriesDetailOut(
        series=_series_out(view.summarise(session, entry, today)),
        observations=[
            MacroObservationOut(day=d, value=float(v) if v is not None else None) for d, v in rows
        ],
    )
