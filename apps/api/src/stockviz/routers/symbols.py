"""`/v1/symbols` and `/v1/symbols/{ticker}`.

List endpoint supports basic ``sector`` / ``exchange`` filters; the detail
endpoint returns the symbol row plus its most-recent EOD close so the web
app can render a header without two round-trips.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session, select

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import PriceBar, Symbol
from stockviz.schemas import QuoteOut, SymbolDetailOut, SymbolOut

router = APIRouter(prefix="/v1/symbols", tags=["symbols"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("", response_model=list[SymbolOut])
@limiter.limit("60/minute")
def list_symbols(
    request: Request,
    session: SessionDep,
    sector: Annotated[str | None, Query()] = None,
    exchange: Annotated[str | None, Query()] = None,
    active_only: Annotated[bool, Query()] = True,
) -> list[Symbol]:
    stmt = select(Symbol)
    if sector is not None:
        stmt = stmt.where(Symbol.sector == sector)
    if exchange is not None:
        stmt = stmt.where(Symbol.exchange == exchange)
    if active_only:
        stmt = stmt.where(Symbol.is_active)
    stmt = stmt.order_by(Symbol.ticker)
    return list(session.exec(stmt).all())


@router.get("/{ticker}", response_model=SymbolDetailOut)
@limiter.limit("60/minute")
def get_symbol(request: Request, ticker: str, session: SessionDep) -> SymbolDetailOut:
    symbol = session.get(Symbol, ticker.upper())
    if symbol is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")

    latest_bar = session.exec(
        select(PriceBar)
        .where(PriceBar.ticker == symbol.ticker, PriceBar.interval == "1d")
        .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()

    latest = (
        QuoteOut(ticker=symbol.ticker, ts=latest_bar.ts, close=latest_bar.close)
        if latest_bar is not None
        else None
    )
    return SymbolDetailOut.model_validate({**symbol.model_dump(), "latest": latest})
