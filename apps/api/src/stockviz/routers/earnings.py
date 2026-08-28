"""Authenticated earnings calendar.

The route only reads events already ingested by an operator job. It never
calls yfinance during a user request and applies holding/watchlist scope
against the authenticated user's own rows.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, col, select

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import EarningsEvent, Portfolio, Position, Symbol, Watchlist, WatchlistItem
from stockviz.schemas import EarningsEventOut

router = APIRouter(prefix="/v1/earnings", tags=["earnings"])
SessionDep = Annotated[Session, Depends(get_session)]
Scope = Literal["all", "holdings", "watchlist"]


def _month_window(today: date) -> tuple[date, date]:
    start = today.replace(day=1)
    if start.month == 12:
        next_month = date(start.year + 1, 1, 1)
    else:
        next_month = date(start.year, start.month + 1, 1)
    return start, next_month - timedelta(days=1)


def _event_result(event: EarningsEvent) -> Literal["beat", "miss", "in_line", "unknown"]:
    if event.eps_actual is None or event.eps_estimate is None:
        return "unknown"
    if event.eps_actual > event.eps_estimate:
        return "beat"
    if event.eps_actual < event.eps_estimate:
        return "miss"
    return "in_line"


@router.get("", response_model=list[EarningsEventOut])
def list_earnings(
    session: SessionDep,
    user_id: UserIdDep,
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
    scope: Annotated[Scope, Query()] = "all",
) -> list[EarningsEventOut]:
    default_from, default_to = _month_window(date.today())
    start = from_date or default_from
    end = to_date or default_to
    if start > end:
        raise HTTPException(status_code=422, detail="from must be on or before to")
    if end - start > timedelta(days=366):
        raise HTTPException(status_code=422, detail="earnings range cannot exceed 366 days")

    ticker_filter: set[str] | None = None
    if scope == "holdings":
        portfolio = session.exec(select(Portfolio).where(Portfolio.user_id == user_id)).first()
        ticker_filter = set()
        if portfolio is not None:
            ticker_filter = set(
                session.exec(
                    select(Position.ticker).where(Position.portfolio_id == portfolio.id)
                ).all()
            )
    elif scope == "watchlist":
        watchlists = select(Watchlist.id).where(Watchlist.user_id == user_id)
        ticker_filter = set(
            session.exec(
                select(WatchlistItem.ticker).where(col(WatchlistItem.watchlist_id).in_(watchlists))
            ).all()  # type: ignore[attr-defined]
        )

    stmt = (
        select(EarningsEvent, Symbol.name)
        .join(Symbol, Symbol.ticker == EarningsEvent.ticker)  # type: ignore[arg-type]
        .where(EarningsEvent.event_date >= start, EarningsEvent.event_date <= end)
        .order_by(col(EarningsEvent.event_date), col(EarningsEvent.ticker))
    )
    if ticker_filter is not None:
        if not ticker_filter:
            return []
        stmt = stmt.where(EarningsEvent.ticker.in_(ticker_filter))  # type: ignore[attr-defined]

    return [
        EarningsEventOut(
            id=event.id,  # type: ignore[arg-type]
            ticker=event.ticker,
            name=name,
            event_date=event.event_date,
            report_time=event.report_time,
            fiscal_period=event.fiscal_period or None,
            eps_estimate=event.eps_estimate,
            eps_actual=event.eps_actual,
            surprise_pct=event.surprise_pct,
            result=_event_result(event),
            source=event.source,
            fetched_at=event.fetched_at,
        )
        for event, name in session.exec(stmt).all()
    ]
