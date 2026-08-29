"""`/v1/orders` — pending (advanced) order management.

POST   /v1/orders          Create a new limit / stop-loss / take-profit order.
GET    /v1/orders          List all orders for the caller (filterable by status).
DELETE /v1/orders/{id}    Cancel a pending order.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from stockviz.auth import UserIdDep
from stockviz.db import get_session
from stockviz.models import TradeSide
from stockviz.models.order import OrderStatus, OrderType, PendingOrder
from stockviz.schemas import PendingOrderIn, PendingOrderOut
from stockviz.services.trading import (
    OrderError,
    OrderNotFound,
    SymbolNotFound,
    TradeExecutionError,
    cancel_pending_order,
    create_pending_order,
    ensure_default_portfolio,
)

router = APIRouter(prefix="/v1", tags=["orders"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/orders", response_model=PendingOrderOut, status_code=status.HTTP_201_CREATED)
def create_order(body: PendingOrderIn, session: SessionDep, user_id: UserIdDep) -> PendingOrder:
    try:
        side = TradeSide(body.side)
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"Invalid side: {body.side!r}"
        ) from None
    try:
        order_type = OrderType(body.order_type)
    except ValueError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail=f"Invalid order_type: {body.order_type!r}"
        ) from None
    try:
        quantity = Decimal(body.quantity)
        limit_price = Decimal(body.limit_price)
    except InvalidOperation:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="quantity and limit_price must be valid numbers",
        ) from None

    try:
        return create_pending_order(
            session,
            user_id=user_id,
            ticker=body.ticker,
            side=side,
            order_type=order_type,
            quantity=quantity,
            limit_price=limit_price,
        )
    except SymbolNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (OrderError, TradeExecutionError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/orders", response_model=list[PendingOrderOut])
def list_orders(
    session: SessionDep,
    user_id: UserIdDep,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> list[PendingOrder]:
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None

    stmt = select(PendingOrder).where(
        PendingOrder.portfolio_id == portfolio.id  # pyright: ignore[reportArgumentType]
    )
    if status_filter:
        try:
            s = OrderStatus(status_filter)
        except ValueError:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail=f"Invalid status: {status_filter!r}"
            ) from None
        stmt = stmt.where(PendingOrder.status == s)  # pyright: ignore[reportArgumentType]

    stmt = stmt.order_by(PendingOrder.created_at.desc())  # type: ignore[attr-defined]
    return list(session.exec(stmt).all())


@router.delete("/orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_order(order_id: int, session: SessionDep, user_id: UserIdDep) -> None:
    try:
        cancel_pending_order(session, user_id=user_id, order_id=order_id)
    except OrderNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except OrderError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
