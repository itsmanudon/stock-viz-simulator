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
from stockviz.schemas import (
    PortfolioHistoryPointOut,
    PortfolioOut,
    PositionOut,
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
