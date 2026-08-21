"""Pending order creation and EOD settlement.

Limit, stop-loss, and take-profit orders are stored in ``pending_orders`` and
checked against each EOD close by ``settle_pending_orders``. Orders that
trigger at a close are filled at that price; orders that can't fill (e.g.
insufficient cash) are cancelled with a ``cancel_reason`` rather than left in
an inconsistent state.

The fill itself goes through ``execute.apply_fill``, the same code path market
orders use — so pending orders honour FX conversion, weighted-average cost,
and realized-P&L capture identically.
"""

from __future__ import annotations

import logging
from datetime import date as date_type
from decimal import Decimal

from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import PendingOrder, Portfolio, Symbol, TradeSide
from stockviz.models.order import OrderStatus, OrderType
from stockviz.services.trading.execute import (
    NoFxRateError,
    NoMarketDataError,
    PricedSymbol,
    SymbolNotFound,
    TradeExecutionError,
    apply_fill,
    ensure_default_portfolio,
    resolve_priced_symbol,
)

logger = logging.getLogger(__name__)


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


def _cancel(session: Session, order: PendingOrder, reason: str) -> None:
    order.status = OrderStatus.CANCELLED
    order.cancel_reason = reason[:200]
    session.add(order)
    logger.warning("order %s cancelled: %s", order.id, reason)


def settle_pending_orders(session: Session, *, session_date: date_type | None = None) -> int:
    """Check all pending orders against the latest close; fill or cancel as triggered.

    ``session_date`` guards against filling at a stale price: an order is only
    considered when the symbol's latest ``1d`` bar is dated on or after it.
    The scheduler passes today's date, so a failed or slow price refresh
    leaves orders **pending** for the next run rather than filling them
    against yesterday's close. Pass ``None`` to skip the freshness check.

    Returns the number of orders filled.
    """
    pending = list(
        session.exec(select(PendingOrder).where(PendingOrder.status == OrderStatus.PENDING)).all()
    )
    filled = 0
    for order in pending:
        try:
            priced = resolve_priced_symbol(session, order.ticker)
        except NoMarketDataError:
            continue
        except (SymbolNotFound, NoFxRateError) as exc:
            _cancel(session, order, str(exc))
            continue

        if session_date is not None and priced.bar.ts.date() < session_date:
            logger.info(
                "order %s: latest %s bar is %s, older than session %s — leaving pending",
                order.id,
                order.ticker,
                priced.bar.ts.date(),
                session_date,
            )
            continue

        if not _should_fill(order, priced.price):
            continue

        if _fill(session, order, priced):
            filled += 1

    session.commit()
    return filled


def _fill(session: Session, order: PendingOrder, priced: PricedSymbol) -> bool:
    """Fill one triggered order. Returns True when it actually filled."""
    portfolio = session.get(Portfolio, order.portfolio_id)
    if portfolio is None:
        _cancel(session, order, "Portfolio no longer exists")
        return False

    try:
        apply_fill(
            session,
            portfolio=portfolio,
            ticker=order.ticker,
            side=order.side,
            quantity=order.quantity,
            price=priced.price,
            currency=priced.currency,
            fx_rate=priced.fx_rate,
        )
    except TradeExecutionError as exc:
        _cancel(session, order, str(exc))
        return False

    order.status = OrderStatus.FILLED
    order.filled_at = utcnow()
    order.fill_price = priced.price
    session.add(order)
    return True
