"""`GET /v1/symbols/{ticker}/events`: the chart's markers (A3.5, M2.8).

Public and rate-limited. One merged, typed list of news clusters, earnings,
ex-dividend dates and splits; with a verified Bearer token (the web server's
authed call) it adds the caller's own fills, and only theirs. Anonymous
calls never see a fill, and a token that does not verify is a 401.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session

from stockviz.auth import OptionalUserIdDep
from stockviz.db import get_session
from stockviz.limiter import limiter
from stockviz.models import Symbol
from stockviz.routers.book_query import BookQuery
from stockviz.schemas import (
    DividendEventOut,
    EarningsMarkerOut,
    FillEventOut,
    NewsEventOut,
    NewsHeadlineOut,
    SplitEventOut,
    SymbolEventsOut,
)
from stockviz.services.symbol_events import EVENT_TYPES, PUBLIC_TYPES, SymbolEvent, symbol_events
from stockviz.services.trading.books import resolve_book

router = APIRouter(prefix="/v1", tags=["events"])

SessionDep = Annotated[Session, Depends(get_session)]

DEFAULT_DAYS = 365
MAX_DAYS = 366 * 25

NEWS_RULE = (
    "One marker per UTC day of the documents' available_at, the date /v1/symbols/{t}/news "
    "orders by; count = the linked documents that day. Titles, sources and links only."
)


def _out(event: SymbolEvent):
    if event.type == "news":
        return NewsEventOut(
            date=event.date,
            count=event.count or 0,
            sources=event.sources,
            headlines=[NewsHeadlineOut(**h.__dict__) for h in event.headlines],
        )
    if event.type == "earnings":
        return EarningsMarkerOut(
            date=event.date,
            report_time=event.report_time,
            fiscal_period=event.fiscal_period,
            eps_estimate=event.eps_estimate,
            eps_actual=event.eps_actual,
            surprise_pct=event.surprise_pct,
        )
    if event.type == "dividend":
        return DividendEventOut(
            date=event.date,
            amount=event.amount if event.amount is not None else Decimal(0),
            currency=event.currency or "USD",
        )
    if event.type == "split":
        return SplitEventOut(
            date=event.date,
            ratio_from=event.ratio_from or Decimal(1),
            ratio_to=event.ratio_to or Decimal(1),
        )
    assert event.ts is not None and event.quantity is not None and event.price is not None
    return FillEventOut(
        date=event.date,
        ts=event.ts,
        side=event.side or "",
        quantity=event.quantity,
        price=event.price,
        r_multiple=event.r_multiple,
        book_id=event.book_id,
    )


@router.get(
    "/symbols/{ticker}/events",
    response_model=SymbolEventsOut,
    response_model_by_alias=True,
)
@limiter.limit("60/minute")
def events_for_symbol(
    request: Request,
    ticker: str,
    session: SessionDep,
    user_id: OptionalUserIdDep,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: Annotated[date | None, Query()] = None,
    types: Annotated[
        str | None,
        Query(
            max_length=100,
            description=(
                "Comma-separated: news, earnings, dividend, split, fill. Default: every public "
                "type, plus fill with a Bearer token. fill needs a token."
            ),
        ),
    ] = None,
    book: BookQuery = None,
) -> SymbolEventsOut:
    """``?book=`` limits fills to one of the caller's books (A5.1); default all books."""
    ticker = ticker.upper()
    if book is not None and user_id is not None:
        resolve_book(session, user_id, book)  # 404 unless it is the caller's
    if session.get(Symbol, ticker) is None:
        raise HTTPException(status_code=404, detail=f"Symbol {ticker!r} not found")
    end = to or date.today()
    start = from_ or end - timedelta(days=DEFAULT_DAYS)
    if start > end:
        raise HTTPException(status_code=400, detail="from must be on or before to")
    if (end - start).days > MAX_DAYS:
        raise HTTPException(status_code=400, detail="The range is limited to 25 years")
    if types is None:
        wanted = PUBLIC_TYPES + (("fill",) if user_id is not None else ())
    else:
        parts = [t.strip().lower() for t in types.split(",") if t.strip()]
        unknown = sorted({p for p in parts if p not in EVENT_TYPES})
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown event type(s): {', '.join(unknown)}. Use {', '.join(EVENT_TYPES)}",
            )
        wanted = tuple(t for t in EVENT_TYPES if t in parts)
    events = symbol_events(
        session, ticker, start=start, end=end, types=wanted, user_id=user_id, book_id=book
    )
    return SymbolEventsOut(
        ticker=ticker,
        from_date=start,
        to_date=end,
        types=list(wanted),  # pyright: ignore[reportArgumentType]
        fills_included="fill" in wanted and user_id is not None,
        news_rule=NEWS_RULE,
        events=[_out(e) for e in events],
    )
