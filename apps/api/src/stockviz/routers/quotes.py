"""`/v1/quotes` — batch latest-close lookup.

Used by the home page / watchlists to render many tickers without N HTTP
calls. ``tickers`` is a comma-separated list, capped at 50 so the SQL stays
predictable.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func
from sqlmodel import Session, col, select

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import PriceBar
from stockviz.schemas import QuoteOut
from stockviz.services.instruments import instruments_of

router = APIRouter(prefix="/v1", tags=["quotes"])

SessionDep = Annotated[Session, Depends(get_session)]

MAX_TICKERS_PER_REQUEST = 50


@router.get("/quotes", response_model=list[QuoteOut])
@limiter.limit("60/minute")
def batch_quotes(
    request: Request,
    session: SessionDep,
    tickers: Annotated[str, Query(description="Comma-separated tickers, e.g. AAPL,MSFT")],
) -> list[QuoteOut]:
    requested = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not requested:
        raise HTTPException(status_code=400, detail="At least one ticker is required")
    if len(requested) > MAX_TICKERS_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"At most {MAX_TICKERS_PER_REQUEST} tickers per request",
        )

    # Per-instrument latest timestamp, joined back to grab the close (Phase
    # 4.4: bars are read by instrument; the ticker on the row is display).
    latest_ts = (
        select(PriceBar.instrument_id, func.max(PriceBar.ts).label("ts"))
        .where(
            col(PriceBar.instrument_id).in_(instruments_of(requested)),
            PriceBar.interval == "1d",
        )
        .group_by(col(PriceBar.instrument_id))
        .subquery()
    )
    stmt = select(PriceBar).join(
        latest_ts,
        and_(
            col(PriceBar.instrument_id) == latest_ts.c.instrument_id,
            col(PriceBar.ts) == latest_ts.c.ts,
            col(PriceBar.interval) == "1d",
        ),
    )

    return [
        QuoteOut(ticker=bar.ticker, ts=bar.ts, close=bar.close) for bar in session.exec(stmt).all()
    ]
