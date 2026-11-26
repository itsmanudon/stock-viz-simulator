"""`GET /v1/symbols/{ticker}/avwap` (A3.3, M2.5): an anchored VWAP.

Public, 60/min like the other public reads. ``anchor=YYYY-MM-DD`` must lie
between the symbol's first and last stored daily bar (422 otherwise); the
sums start at the first daily bar on or after it (``anchor_bar``).
``interval=1d|1wk|1mo``: always computed from daily bars; on weekly and
monthly it is sampled at each period's last stored session, which is the
weekly/monthly bar's ``ts`` on the bars route. ``bands=0|1|2`` adds the
+-1 (and +-2) volume-weighted standard deviation bands. The maths is
``services/avwap.py`` (float64, rounded to 4 decimals here), the same code
the Rule DSL's ``avwap()`` runs.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session, col, select

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import PriceBar, Symbol
from stockviz.schemas import AvwapOut, AvwapPointOut
from stockviz.services import avwap
from stockviz.services.bars.resample import bar_date, period_start
from stockviz.services.drawings import bar_range
from stockviz.services.instruments import instrument_of, resolve_symbol
from stockviz.services.markets.calendar import venue_for_ticker

router = APIRouter(prefix="/v1/symbols", tags=["avwap"])

SessionDep = Annotated[Session, Depends(get_session)]


def _r(value: float) -> float | None:
    return None if not np.isfinite(value) else round(float(value), avwap.API_DECIMALS)


@router.get("/{ticker}/avwap", response_model=AvwapOut)
@limiter.limit("60/minute")
def get_avwap(
    request: Request,
    ticker: str,
    session: SessionDep,
    anchor: Annotated[date, Query(description="Anchor date, YYYY-MM-DD")],
    interval: Annotated[Literal["1d", "1wk", "1mo"], Query()] = "1d",
    bands: Annotated[int, Query(ge=0, le=2)] = 0,
) -> AvwapOut:
    ticker = ticker.upper()
    instrument = resolve_symbol(session, ticker)
    if session.get(Symbol, ticker) is None or instrument is None or instrument.id is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")
    first, last = bar_range(session, instrument.id, ticker)
    if first is None or last is None:
        raise HTTPException(status_code=422, detail=f"No stored daily bars for {ticker}")
    if not first <= anchor <= last:
        raise HTTPException(
            status_code=422,
            detail=(
                f"The anchor {anchor.isoformat()} must be between {first.isoformat()} and "
                f"{last.isoformat()} (the stored daily bars)"
            ),
        )
    venue = venue_for_ticker(ticker)
    rows = list(
        session.exec(
            select(PriceBar)
            .where(
                PriceBar.instrument_id == instrument_of(ticker),
                PriceBar.interval == "1d",
                col(PriceBar.ts) >= datetime.combine(anchor - timedelta(days=1), time.min),
            )
            .order_by(col(PriceBar.ts))
        ).all()
    )
    rows = [r for r in rows if bar_date(r.ts, venue) >= anchor]
    if not rows:  # pragma: no cover - the range check above makes this unreachable
        raise HTTPException(status_code=422, detail="No bar on or after the anchor")
    days = [bar_date(r.ts, venue) for r in rows]
    series = avwap.compute(
        days,
        np.array([float(r.high) for r in rows]),
        np.array([float(r.low) for r in rows]),
        np.array([float(r.close) for r in rows]),
        np.array([float(r.volume) for r in rows]),
        anchor,
    )
    if interval == "1d":
        picks = list(range(len(rows)))
    else:
        keys = [period_start(d, interval) for d in days]
        picks = [i for i, _v in avwap.sample_last_of_period(keys, series.vwap)]
    points: list[AvwapPointOut] = []
    for i in picks:
        vwap = _r(series.vwap[i])
        if vwap is None:
            continue  # no volume yet since the anchor
        point = AvwapPointOut(ts=rows[i].ts, vwap=vwap)
        if bands >= 1:
            point.upper1, point.lower1 = _r(series.band(1)[i]), _r(series.band(-1)[i])
        if bands >= 2:
            point.upper2, point.lower2 = _r(series.band(2)[i]), _r(series.band(-2)[i])
        points.append(point)
    return AvwapOut(
        ticker=ticker,
        anchor=anchor,
        anchor_bar=days[0],
        interval=interval,
        bands=bands,
        decimals=avwap.API_DECIMALS,
        points=points,
    )
