"""Pending order creation and EOD settlement.

Limit, stop-loss, and take-profit orders are stored in ``pending_orders`` and
checked against each EOD close by ``settle_pending_orders``. Trigger and fill
price come from ``evaluate_order(..., LEGACY_CLOSE)``. Orders that can't fill
(e.g. insufficient cash) are cancelled with a ``cancel_reason`` rather than
left in an inconsistent state.

At creation, pending BUYs reserve USD buying power (``quantity * limit_price``
at the latest FX rate) and pending SELLs reserve shares. Reservations are
derived from ``PENDING`` rows — cancel and fill release them automatically.
A fill may consume its own reservation but not another order's.

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
from stockviz.services.simulation import LEGACY_CLOSE, FillDecision, FillStatus, evaluate_order
from stockviz.services.trading.buying_power import (
    available_cash,
    available_shares,
    buy_reservation_usd,
    lock_portfolio,
    reserved_shares,
)
from stockviz.services.trading.execute import (
    InsufficientCash,
    InsufficientPosition,
    NoFxRateError,
    NoMarketDataError,
    PricedSymbol,
    SymbolNotFound,
    TradeExecutionError,
    apply_fill,
    ensure_default_portfolio,
    resolve_priced_symbol,
)
from stockviz.services.trading.simulation_adapter import (
    evaluation_clock,
    market_snapshot_from_bar,
    order_intent_from_pending,
)

logger = logging.getLogger(__name__)


class OrderError(TradeExecutionError):
    """Raised when an order cannot be created or settled."""


class OrderNotFound(OrderError):
    """Raised when a cancel/lookup targets a missing or foreign order."""


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
    portfolio_id = portfolio.id
    portfolio = lock_portfolio(session, portfolio_id)

    if side == TradeSide.BUY:
        try:
            required = buy_reservation_usd(
                session, ticker=ticker, quantity=quantity, limit_price=limit_price
            )
            spendable = available_cash(session, portfolio)
        except LookupError as exc:
            raise NoFxRateError(str(exc)) from exc
        if required > spendable:
            raise InsufficientCash(
                f"Available buying power ${spendable:.2f}; order requires ${required:.2f}."
            )
    else:
        reserved = reserved_shares(session, portfolio_id, ticker)
        spendable = available_shares(session, portfolio_id, ticker)
        if quantity > spendable:
            raise InsufficientPosition(
                f"Only {spendable} {ticker} shares are available; "
                f"{reserved} are reserved by pending orders."
            )

    order = PendingOrder(
        portfolio_id=portfolio_id,
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


def cancel_pending_order(session: Session, *, user_id: int, order_id: int) -> None:
    """Cancel a pending order, serialized on the portfolio row.

    Holds the same ``FOR UPDATE`` lock settlement uses, then re-reads
    ``order.status`` so a fill that committed while we waited cannot be
    overwritten back to ``CANCELLED``.
    """
    portfolio = session.exec(
        select(Portfolio).where(Portfolio.user_id == user_id).order_by(Portfolio.id)  # type: ignore[arg-type]
    ).first()
    if portfolio is None or portfolio.id is None:
        raise OrderNotFound("Order not found")
    lock_portfolio(session, portfolio.id)

    order = session.get(PendingOrder, order_id)
    if order is None or order.portfolio_id != portfolio.id:
        raise OrderNotFound("Order not found")
    session.refresh(order)
    if order.status != OrderStatus.PENDING:
        raise OrderError("Only pending orders can be cancelled")

    order.status = OrderStatus.CANCELLED
    session.add(order)
    session.commit()


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

    Trigger and fill price come from ``evaluate_order(..., LEGACY_CLOSE)``.
    Account failures still cancel the order. Kernel ``INELIGIBLE`` (adapter
    inconsistency) is logged and the order is left pending so one bad row
    cannot abort the batch.

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

        decision = _evaluate_pending(order, priced)
        if decision is None or decision.status is FillStatus.NOT_TRIGGERED:
            continue
        if decision.status is FillStatus.INELIGIBLE:
            logger.error(
                "pending order %s ineligible for kernel evaluation: ticker=%s type=%s side=%s reason=%s",
                order.id,
                order.ticker,
                order.order_type,
                order.side,
                decision.trace.reason,
            )
            continue
        fill_price = _require_full_pending_fill(order, decision)
        if fill_price is None:
            continue

        if _fill(session, order, priced, fill_price=fill_price):
            filled += 1

    session.commit()
    return filled


def _evaluate_pending(order: PendingOrder, priced: PricedSymbol) -> FillDecision | None:
    """Ask the kernel whether this pending order triggers. Does not mutate state."""

    try:
        intent = order_intent_from_pending(order)
        market = market_snapshot_from_bar(priced.bar, observed_at=evaluation_clock())
        return evaluate_order(intent, market, LEGACY_CLOSE)
    except (TypeError, ValueError) as exc:
        logger.error("pending order %s adapter failed: %s", order.id, exc)
        return None


def _require_full_pending_fill(order: PendingOrder, decision: FillDecision) -> Decimal | None:
    if (
        decision.status is FillStatus.FILLED
        and decision.fill_price is not None
        and decision.fill_quantity == order.quantity
        and decision.remaining_quantity == Decimal(0)
    ):
        return decision.fill_price
    logger.error(
        "pending order %s kernel did not fully fill: status=%s fill_qty=%s remaining=%s reason=%s",
        order.id,
        decision.status,
        decision.fill_quantity,
        decision.remaining_quantity,
        decision.trace.reason,
    )
    return None


def _fill(
    session: Session,
    order: PendingOrder,
    priced: PricedSymbol,
    *,
    fill_price: Decimal,
) -> bool:
    """Fill one triggered order. Returns True when it actually filled."""
    if order.portfolio_id is None or order.id is None:
        _cancel(session, order, "Portfolio no longer exists")
        return False

    try:
        lock_portfolio(session, order.portfolio_id)
    except LookupError:
        _cancel(session, order, "Portfolio no longer exists")
        return False

    session.refresh(order)
    if order.status != OrderStatus.PENDING:
        return False

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
            price=fill_price,
            currency=priced.currency,
            fx_rate=priced.fx_rate,
            exclude_order_id=order.id,
        )
    except TradeExecutionError as exc:
        _cancel(session, order, str(exc))
        return False

    order.status = OrderStatus.FILLED
    order.filled_at = utcnow()
    order.fill_price = fill_price
    session.add(order)
    return True
