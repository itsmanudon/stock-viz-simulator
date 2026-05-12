"""`/v1/symbols/{ticker}/bars` — OHLCV history for charts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session, select

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import PriceBar, Symbol
from stockviz.schemas import BarOut

router = APIRouter(prefix="/v1/symbols", tags=["bars"])

SessionDep = Annotated[Session, Depends(get_session)]

MAX_BARS = 5000


@router.get("/{ticker}/bars", response_model=list[BarOut])
@limiter.limit("60/minute")
def get_bars(
    request: Request,
    ticker: str,
    session: SessionDep,
    interval: Annotated[str, Query(pattern=r"^(1d|1h)$")] = "1d",
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_BARS)] = 1000,
) -> list[PriceBar]:
    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")

    stmt = select(PriceBar).where(PriceBar.ticker == ticker, PriceBar.interval == interval)
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
