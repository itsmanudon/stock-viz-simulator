"""Pending order creation and EOD settlement.

Limit, stop-loss, and take-profit orders are stored in ``pending_orders`` and
checked against each EOD close by ``settle_pending_orders``. Orders that
trigger at a close are filled at that price; orders that can't fill (e.g.
insufficient cash) are cancelled rather than left in an inconsistent state.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import Portfolio, Position, PriceBar, Symbol, Trade, TradeSide
from stockviz.models.order import OrderStatus, OrderType, PendingOrder
from stockviz.services.trading.execute import (
    InsufficientCash,
    InsufficientPosition,
    SymbolNotFound,
    TradeExecutionError,
    ensure_default_portfolio,
)

logger = logging.getLogger(__name__)


def _latest_close(session: Session, ticker: str) -> Decimal | None:
    bar = session.exec(
        select(PriceBar)
        .where(PriceBar.ticker == ticker, PriceBar.interval == "1d")
        .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()
    return bar.close if bar else None


def _get_or_create_position(session: Session, *, portfolio_id: int, ticker: str) -> Position | None:
    return session.exec(
        select(Position)
        .where(Position.portfolio_id == portfolio_id, Position.ticker == ticker)
        .limit(1)
    ).first()


class OrderError(TradeExecutionError):
    """Raised when an order cannot be created or settled."""


def create_pending_order(
    session: Session,
    *,
    user_id: int,
    ticker: str,
    side: TradeSide,
    order_type: OrderType,
    quantity: Decimal,
    limit_price: Decimal,
) -> PendingOrder:
    """Validate and persist a new pending order."""
    if quantity <= 0:
        raise OrderError("quantity must be positive")
    if limit_price <= 0:
        raise OrderError("limit_price must be positive")

    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise SymbolNotFound(f"Symbol {ticker!r} not found")

    if order_type in (OrderType.STOP_LOSS, OrderType.TAKE_PROFIT) and side != TradeSide.SELL:
        raise OrderError(f"{order_type} orders must be sell orders")

    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None

    order = PendingOrder(
        portfolio_id=portfolio.id,
        ticker=ticker,
        side=side,
        order_type=order_type,
        quantity=quantity,
        limit_price=limit_price,
    )
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


def _should_fill(order: PendingOrder, close: Decimal) -> bool:
    """Return True if the EOD close should trigger this order."""
    if order.order_type == OrderType.LIMIT:
        return (
            close <= order.limit_price
            if order.side == TradeSide.BUY
            else close >= order.limit_price
        )
    if order.order_type == OrderType.STOP_LOSS:
        return close <= order.limit_price
    if order.order_type == OrderType.TAKE_PROFIT:
        return close >= order.limit_price
    return False


def _fill_order(session: Session, order: PendingOrder, close: Decimal) -> None:
    """Execute the trade for a triggered order; cancel on any validation error."""
    portfolio = session.get(Portfolio, order.portfolio_id)
    if portfolio is None:
        order.status = OrderStatus.CANCELLED
        session.add(order)
        return

    cost = (close * order.quantity).quantize(Decimal("0.000001"))
    position = _get_or_create_position(
        session, portfolio_id=order.portfolio_id, ticker=order.ticker
    )

    try:
        if order.side == TradeSide.BUY:
            if portfolio.cash_balance < cost:
                raise InsufficientCash(f"Insufficient cash to fill order #{order.id}")
            portfolio.cash_balance = (portfolio.cash_balance - cost).quantize(Decimal("0.000001"))
            if position is None:
                position = Position(
                    portfolio_id=order.portfolio_id,
                    ticker=order.ticker,
                    quantity=order.quantity,
                    avg_cost=close,
                )
                session.add(position)
            else:
                total_cost = position.avg_cost * position.quantity + cost
                new_qty = position.quantity + order.quantity
                position.quantity = new_qty
                position.avg_cost = (total_cost / new_qty).quantize(Decimal("0.000001"))
        else:
            if position is None or position.quantity < order.quantity:
                held = position.quantity if position else Decimal(0)
                raise InsufficientPosition(
                    f"Held {held} {order.ticker}, cannot sell {order.quantity}"
                )
            portfolio.cash_balance = (portfolio.cash_balance + cost).quantize(Decimal("0.000001"))
            position.quantity -= order.quantity
            if position.quantity == 0:
                session.delete(position)

        trade = Trade(
            portfolio_id=order.portfolio_id,
            ticker=order.ticker,
            side=order.side,
            quantity=order.quantity,
            price=close,
        )
        session.add(trade)
        session.add(portfolio)
        order.status = OrderStatus.FILLED
        order.filled_at = utcnow()
        order.fill_price = close
        session.add(order)
    except TradeExecutionError as exc:
        logger.warning("order %s cancelled: %s", order.id, exc)
        order.status = OrderStatus.CANCELLED
        session.add(order)


def settle_pending_orders(session: Session) -> int:
    """Check all pending orders against the latest close; fill or cancel as triggered.

    Returns the number of orders filled.
    """
    pending = list(
        session.exec(select(PendingOrder).where(PendingOrder.status == OrderStatus.PENDING)).all()
    )
    filled = 0
    for order in pending:
        close = _latest_close(session, order.ticker)
        if close is None:
            continue
        if _should_fill(order, close):
            _fill_order(session, order, close)
            if order.status == OrderStatus.FILLED:
                filled += 1
    session.commit()
    return filled
