"""`/v1/markets/summary` — everything the markets table needs, in one call.

The web `/markets` page previously issued one `listSymbols` call for the table,
a second for the sector filter list, and then one `getBars` call *per symbol*
for the inline sparkline — 34 backend requests for a 32-symbol universe, each
`cache: "no-store"`, growing linearly as symbols are added. With the public
rate limit at 60/minute that meant two page loads could exhaust the budget.

This endpoint answers the whole page with two queries: one for the symbol rows,
one window-function pass over `price_bars` for the recent closes of every
symbol at once.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func
from sqlmodel import Session, select

from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import PriceBar, Symbol
from stockviz.schemas import MarketsSummaryOut, MarketSummaryRowOut

router = APIRouter(prefix="/v1/markets", tags=["markets"])

SessionDep = Annotated[Session, Depends(get_session)]

MAX_SPARKLINE_DAYS = 120


def _recent_closes(
    session: Session, tickers: list[str], *, limit_per_ticker: int
) -> dict[str, list[Decimal]]:
    """Most recent ``limit_per_ticker`` closes per ticker, oldest first.

    One query for the whole universe: rank each ticker's bars newest-first and
    keep the top N. The per-ticker loop this replaces was the single biggest
    contributor to /markets latency.
    """
    if not tickers:
        return {}

    ranked = (
        select(
            PriceBar.ticker,
            PriceBar.ts,
            PriceBar.close,  # type: ignore[arg-type]
            func.row_number()
            .over(
                partition_by=PriceBar.ticker,  # type: ignore[arg-type]
                order_by=PriceBar.ts.desc(),  # type: ignore[attr-defined]
            )
            .label("rn"),
        )
        .where(
            PriceBar.ticker.in_(tickers),  # type: ignore[attr-defined]
            PriceBar.interval == "1d",
        )
        .subquery()
    )
    rows = session.exec(
        select(ranked.c.ticker, ranked.c.ts, ranked.c.close)  # type: ignore[call-overload]
        .where(ranked.c.rn <= limit_per_ticker)
        .order_by(ranked.c.ticker, ranked.c.ts)
    ).all()

    out: dict[str, list[Decimal]] = {}
    for ticker, _ts, close in rows:
        out.setdefault(ticker, []).append(close)
    return out


@router.get("/summary", response_model=MarketsSummaryOut)
@limiter.limit("60/minute")
def markets_summary(
    request: Request,
    session: SessionDep,
    sector: Annotated[str | None, Query()] = None,
    sparkline_days: Annotated[int, Query(ge=2, le=MAX_SPARKLINE_DAYS)] = 30,
) -> MarketsSummaryOut:
    """Symbol rows with last close, day change, and a sparkline series.

    ``sectors`` always covers the whole active universe, not just the filtered
    slice, so the filter control can render every option without a second call.
    """
    all_active = list(session.exec(select(Symbol).where(Symbol.is_active).order_by(Symbol.ticker)))
    sectors = sorted({s.sector for s in all_active if s.sector})

    symbols = [s for s in all_active if sector is None or s.sector == sector]
    closes_by_ticker = _recent_closes(
        session, [s.ticker for s in symbols], limit_per_ticker=sparkline_days
    )

    rows: list[MarketSummaryRowOut] = []
    for symbol in symbols:
        closes = closes_by_ticker.get(symbol.ticker, [])
        last = closes[-1] if closes else None
        prev = closes[-2] if len(closes) > 1 else None
        change_pct = (
            float((last - prev) / prev * 100)
            if last is not None and prev not in (None, 0)
            else None
        )
        rows.append(
            MarketSummaryRowOut(
                ticker=symbol.ticker,
                name=symbol.name,
                sector=symbol.sector,
                exchange=symbol.exchange,
                currency=symbol.currency or "USD",
                last_close=last,
                prev_close=prev,
                change_pct=change_pct,
                closes=closes,
            )
        )

    return MarketsSummaryOut(rows=rows, sectors=sectors)
