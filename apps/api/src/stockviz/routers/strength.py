"""Relative strength and delivery for the stock page (A3.5, M2.7).

`GET /v1/symbols/{ticker}/relative-strength`: RS percentiles over 1, 3, 6
and 12 months against the symbol's market and the distance from the
52-week high, from ``symbol_metrics`` (``services/relative_strength.py``).

`GET /v1/symbols/{ticker}/delivery`: delivery % and its 20-session
average from ``eod_extras`` (``services/delivery_pct.py``); NSE and BSE
only. Both public, 60/min.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import Symbol
from stockviz.schemas import (
    DeliveryOut,
    DeliveryPointOut,
    RelativeStrengthOut,
    RelativeStrengthPeriodOut,
    RelativeStrengthUniverseOut,
)
from stockviz.services import delivery_pct
from stockviz.services.relative_strength import (
    BENCHMARK_NAMES,
    UNIVERSE_NOTE,
    is_indian,
    relative_strength,
)

router = APIRouter(prefix="/v1", tags=["symbols"])

SessionDep = Annotated[Session, Depends(get_session)]

RS_METHOD = (
    "Price return over 21, 63, 126 and 252 sessions, ranked within the market's symbols on "
    "the newest metrics date: the share of the others with a lower return (ties half). Every "
    "symbol of a market is divided by the same index, so this ranks the RS line's change."
)


def _symbol(session: Session, ticker: str) -> Symbol:
    symbol = session.get(Symbol, ticker.upper())
    if symbol is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")
    return symbol


@router.get("/symbols/{ticker}/relative-strength", response_model=RelativeStrengthOut)
@limiter.limit("60/minute")
def get_relative_strength(
    request: Request, ticker: str, session: SessionDep
) -> RelativeStrengthOut:
    symbol = _symbol(session, ticker)
    rs = relative_strength(session, symbol.ticker)
    return RelativeStrengthOut(
        ticker=rs.ticker,
        market=rs.market,  # pyright: ignore[reportArgumentType]
        benchmark=rs.benchmark,
        benchmark_name=BENCHMARK_NAMES.get(rs.benchmark or ""),
        as_of=rs.as_of,
        periods=[
            RelativeStrengthPeriodOut(
                period=p.period,  # pyright: ignore[reportArgumentType]
                sessions=p.sessions,
                return_pct=p.return_pct,
                percentile=p.percentile,
            )
            for p in rs.periods
        ],
        method=RS_METHOD,
        universe=RelativeStrengthUniverseOut(
            market=rs.market,  # pyright: ignore[reportArgumentType]
            size=rs.universe_size,
            as_of=rs.as_of,
            note=UNIVERSE_NOTE,
        ),
        high_52w=rs.high_52w,
        last_close=rs.last_close,
        distance_from_high_52w_pct=rs.distance_from_high_pct,
        reason=rs.reason,
    )


@router.get("/symbols/{ticker}/delivery", response_model=DeliveryOut)
@limiter.limit("60/minute")
def get_delivery(
    request: Request,
    ticker: str,
    session: SessionDep,
    interval: Literal["1d", "1wk", "1mo"] = "1d",
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: Annotated[date | None, Query()] = None,
) -> DeliveryOut:
    symbol = _symbol(session, ticker)
    applicable = is_indian(symbol.ticker)
    if not applicable:
        return DeliveryOut(
            ticker=symbol.ticker,
            interval=interval,
            applicable=False,
            has_data=False,
            avg_sessions=delivery_pct.AVG_SESSIONS,
            points=[],
            note="Delivery figures are published by NSE and BSE only.",
        )
    points, has_data = delivery_pct.delivery_series(
        session, symbol.ticker, interval=interval, start=from_, end=to
    )
    return DeliveryOut(
        ticker=symbol.ticker,
        interval=interval,
        applicable=True,
        has_data=has_data,
        avg_sessions=delivery_pct.AVG_SESSIONS,
        points=[
            DeliveryPointOut(
                ts=p.day,
                delivery_pct=round(p.delivery_pct, 4),
                avg_20=None if p.avg_20 is None else round(p.avg_20, 4),
            )
            for p in points
        ],
        note=None if has_data else "No delivery data yet: NSE delivery files have not been loaded.",
    )
