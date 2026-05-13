"""`/v1/portfolio` and `/v1/trades` — paper-trading endpoints.

These mutate user data so they're gated on the internal-token dependency
(see ``stockviz.auth``). The web app's Next.js server is the only caller
that should know the token; the browser never sees it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import PortfolioSnapshot, Trade, TradeSide
from stockviz.models.dividend import Dividend, PortfolioDividend
from stockviz.schemas import (
    DividendCreditOut,
    DividendSummaryOut,
    PortfolioHistoryPointOut,
    PortfolioOut,
    PositionOut,
    ProjectedDividendOut,
    TradeIn,
    TradeOut,
)
from stockviz.services.trading import (
    InsufficientCash,
    InsufficientPosition,
    NoMarketDataError,
    SymbolNotFound,
    TradeExecutionError,
    compute_portfolio,
    ensure_default_portfolio,
    execute_trade,
)

router = APIRouter(prefix="/v1", tags=["trading"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/portfolio", response_model=PortfolioOut)
def get_portfolio(session: SessionDep, user_id: UserIdDep) -> PortfolioOut:
    portfolio = ensure_default_portfolio(session, user_id)
    snap = compute_portfolio(session, portfolio)
    return PortfolioOut(
        portfolio_id=snap.portfolio_id,
        cash_balance=snap.cash_balance,
        market_value=snap.market_value,
        total_value=snap.total_value,
        total_cost_basis=snap.total_cost_basis,
        unrealized_pl=snap.unrealized_pl,
        positions=[
            PositionOut(
                ticker=p.ticker,
                name=p.name,
                quantity=p.quantity,
                avg_cost=p.avg_cost,
                last_close=p.last_close,
                market_value=p.market_value,
                unrealized_pl=p.unrealized_pl,
            )
            for p in snap.positions
        ],
    )


@router.post("/trades", response_model=TradeOut, status_code=status.HTTP_201_CREATED)
def post_trade(body: TradeIn, session: SessionDep, user_id: UserIdDep) -> Trade:
    try:
        side = TradeSide(body.side)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid side: {body.side!r}") from exc

    try:
        return execute_trade(
            session,
            user_id=user_id,
            ticker=body.ticker,
            side=side,
            quantity=body.quantity,
        )
    except SymbolNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (InsufficientCash, InsufficientPosition, NoMarketDataError) as exc:
        # 422: request was well-formed but couldn't be honored against the
        # current portfolio / market state.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except TradeExecutionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/portfolio/history", response_model=list[PortfolioHistoryPointOut])
def get_portfolio_history(
    session: SessionDep,
    user_id: UserIdDep,
    days: Annotated[int | None, Query(ge=1, le=3650)] = 90,
) -> list[PortfolioSnapshot]:
    """Return the user's daily NAV history, oldest first.

    ``days=None`` (omit query param) returns the full history; otherwise the
    last N days. Empty list when the scheduler hasn't written any snapshots
    yet for this user — the UI hides the chart in that case.
    """
    stmt = select(PortfolioSnapshot).where(PortfolioSnapshot.user_id == user_id)
    if days is not None:
        cutoff = utcnow().date() - timedelta(days=days)
        stmt = stmt.where(PortfolioSnapshot.date >= cutoff)
    stmt = stmt.order_by(PortfolioSnapshot.date.asc())  # type: ignore[attr-defined]
    return list(session.exec(stmt).all())


@router.get("/trades", response_model=list[TradeOut])
def list_trades(
    session: SessionDep,
    user_id: UserIdDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[Trade]:
    portfolio = ensure_default_portfolio(session, user_id)
    stmt = (
        select(Trade)
        .where(Trade.portfolio_id == portfolio.id)
        .order_by(Trade.ts.desc())  # type: ignore[attr-defined]
        .limit(limit)
    )
    return list(session.exec(stmt).all())


@router.get("/portfolio/dividends", response_model=DividendSummaryOut)
def get_portfolio_dividends(session: SessionDep, user_id: UserIdDep) -> DividendSummaryOut:
    """Return dividend income history and projected next payouts for the user's portfolio."""
    from datetime import date as date_type

    portfolio = ensure_default_portfolio(session, user_id)

    # Credit history, newest first.
    credits = list(
        session.exec(
            select(PortfolioDividend)
            .where(PortfolioDividend.portfolio_id == portfolio.id)
            .order_by(PortfolioDividend.ex_date.desc())  # type: ignore[attr-defined]
        )
    )

    # YTD income (Jan 1 of current year).
    today = date_type.today()
    ytd_cutoff = date_type(today.year, 1, 1)
    ytd_income = sum(
        (c.amount_credited for c in credits if c.ex_date >= ytd_cutoff),
        start=__import__("decimal").Decimal(0),
    )

    # Projected payouts: for each current position find the most recent
    # dividend in the master calendar and estimate the next payment date
    # by adding the observed payment frequency.
    from stockviz.models import Position

    positions = list(
        session.exec(
            select(Position).where(
                Position.portfolio_id == portfolio.id,
                Position.quantity > 0,
            )
        )
    )

    projected: list[ProjectedDividendOut] = []
    for pos in positions:
        recent_divs = list(
            session.exec(
                select(Dividend)
                .where(Dividend.ticker == pos.ticker)
                .order_by(Dividend.ex_date.desc())  # type: ignore[attr-defined]
                .limit(5)
            )
        )
        if not recent_divs:
            continue

        last_div = recent_divs[0]
        projected_amount = (pos.quantity * last_div.amount).quantize(last_div.amount)

        # Estimate frequency from the gap between the last two payments.
        projected_ex_date: date_type | None = None
        if len(recent_divs) >= 2:
            gap = (recent_divs[0].ex_date - recent_divs[1].ex_date).days
            if gap > 0:
                from datetime import timedelta

                projected_ex_date = last_div.ex_date + timedelta(days=gap)

        projected.append(
            ProjectedDividendOut(
                ticker=pos.ticker,
                projected_ex_date=projected_ex_date,
                projected_amount=projected_amount,
            )
        )

    projected.sort(key=lambda p: p.projected_ex_date or date_type.max)

    return DividendSummaryOut(
        ytd_income=ytd_income,
        history=[DividendCreditOut.model_validate(c) for c in credits],
        projected=projected,
    )
