"""`/v1/symbols/{ticker}/bars` — OHLCV history for charts.

``interval=1d`` returns stored daily bars. ``1wk`` and ``1mo`` (A1.4a) are
resampled on read from them (``services/bars/resample.py``): ``limit`` counts
output bars, ``from``/``to`` select bars by their timestamp (the period's
last stored session) and every bar covers its whole period. The newest bar
carries ``partial: true`` while its week or month is not over at the venue.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session, select

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import PriceBar, Symbol
from stockviz.schemas import BarOut
from stockviz.services.bars.load import load_resampled
from stockviz.services.bars.resample import ResampledBar
from stockviz.services.instruments import instrument_of

router = APIRouter(prefix="/v1/symbols", tags=["bars"])

SessionDep = Annotated[Session, Depends(get_session)]

MAX_BARS = 5000


@router.get("/{ticker}/bars", response_model=list[BarOut])
@limiter.limit("60/minute")
def get_bars(
    request: Request,
    ticker: str,
    session: SessionDep,
    interval: Annotated[str, Query(pattern=r"^(1d|1wk|1mo)$")] = "1d",
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_BARS)] = 1000,
) -> list[PriceBar] | list[BarOut]:
    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")

    if interval != "1d":
        bars = load_resampled(
            session,
            ticker,
            interval,
            bars_wanted=limit,
            to=to.date() if to is not None else None,
        )
        if from_ is not None:
            bars = [b for b in bars if b.ts.date() >= from_.date()]
        if to is not None:
            bars = [b for b in bars if b.ts.date() <= to.date()]
        return [_out(b) for b in bars[-limit:]]

    stmt = select(PriceBar).where(
        PriceBar.instrument_id == instrument_of(ticker), PriceBar.interval == interval
    )
    if from_ is not None:
        stmt = stmt.where(PriceBar.ts >= from_)
    if to is not None:
        stmt = stmt.where(PriceBar.ts <= to)
    # Newest-first so a ``limit`` returns the most recent bars; reverse for the
    # client so charts get oldest-first.
    stmt = stmt.order_by(PriceBar.ts.desc()).limit(limit)  # type: ignore[attr-defined]

    rows = list(session.exec(stmt).all())
    rows.reverse()
    return rows


def _out(bar: ResampledBar) -> BarOut:
    return BarOut(
        ts=bar.ts,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        source=bar.source,
        adjustment_semantics=bar.adjustment_semantics,
        sessions=bar.sessions,
        partial=bar.partial,
    )
