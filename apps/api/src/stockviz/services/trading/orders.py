"""Pending order creation and EOD settlement.

Limit, stop-loss, and take-profit orders are stored in ``pending_orders`` and
checked against each EOD close by ``settle_pending_orders``. Trigger and fill
price come from ``evaluate_order(..., LIVE_PAPER_EXECUTION_PROFILE)``. Orders that
can't fill (e.g. insufficient cash) are cancelled with a ``cancel_reason``
rather than left in an inconsistent state. Successful fills persist kernel
provenance in the same transaction as the Trade.

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
from datetime import UTC, datetime
from datetime import date as date_type
from decimal import Decimal

from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import PendingOrder, Portfolio, Symbol, TradeSide
from stockviz.models.order import OrderStatus, OrderType
from stockviz.services.ingest.bar_semantics import latest_completed_session
from stockviz.services.simulation import (
    LIVE_PAPER_EXECUTION_PROFILE,
    FillDecision,
    FillStatus,
    evaluate_order,
)
from stockviz.services.trading.buying_power import (
    available_cash,
    available_shares,
    buy_reservation_usd,
    lock_portfolio,
    reserved_shares,
)
from stockviz.services.trading.execute import (
    ClientOrderIdConflict,
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
from stockviz.services.trading.execution_provenance import (
    FillProvenance,
    record_execution_provenance,
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
    client_order_id: str | None = None,
) -> PendingOrder:
    """Validate and persist a new pending order.

    With a ``client_order_id`` a repeat of the same order returns the first
    one, and a repeat naming a different order raises
    :class:`ClientOrderIdConflict` (#67, audit LG-10). The lookup runs under
    the portfolio lock.
    """
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

    if client_order_id is not None:
        earlier = session.exec(
            select(PendingOrder).where(
                PendingOrder.portfolio_id == portfolio_id,
                PendingOrder.client_order_id == client_order_id,
            )
        ).first()
        if earlier is not None:
            same = (
                earlier.ticker == ticker
                and earlier.side == side
                and earlier.order_type == order_type
                and earlier.quantity == quantity
                and earlier.limit_price == limit_price
            )
            if not same:
                raise ClientOrderIdConflict(
                    "This client_order_id was already used for a different order "
                    f"({earlier.side.value} {earlier.quantity} {earlier.ticker} "
                    f"{earlier.order_type.value} at {earlier.limit_price})."
                )
            session.rollback()  # release the lock; nothing was written
            session.refresh(earlier)
            return earlier

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
        client_order_id=client_order_id,
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


ORDER_MAX_AGE_DAYS = 30
"""A pending order expires this many days after it was placed (audit LG-6).

Orders never expired, so a reservation lasted until the user cancelled it.
"""


def _expire(session: Session, order: PendingOrder) -> None:
    order.status = OrderStatus.EXPIRED
    order.cancel_reason = f"Expired after {ORDER_MAX_AGE_DAYS} days without filling"
    session.add(order)
    logger.info("order %s expired", order.id)


def _known_at_placement(order: PendingOrder) -> date_type:
    """The newest session whose close the user could see when placing the order."""
    return latest_completed_session(order.created_at.replace(tzinfo=UTC))


def settle_pending_orders(session: Session, *, session_date: date_type | None = None) -> int:
    """Check all pending orders against the latest close; fill, cancel or expire them.

    ``session_date`` guards against filling at a stale price: an order is only
    considered when the symbol's latest ``1d`` bar is dated on or after it, so
    a failed price refresh leaves orders **pending** for the next run. Pass
    ``None`` to skip that check.

    An order also fills only on a session that closed after it was placed
    (audit LG-5): a close the user could already see when placing it is not a
    trigger. Orders older than :data:`ORDER_MAX_AGE_DAYS` expire (LG-6).

    Each order commits on its own (audit LG-4): one unexpected error rolls
    back that order only, and no portfolio stays locked for the whole run.

    Trigger and fill price come from ``evaluate_order(..., LIVE_PAPER_EXECUTION_PROFILE)``.
    Account failures still cancel the order. Kernel ``INELIGIBLE`` (adapter
    inconsistency) is logged and the order is left pending.

    Returns the number of orders filled.
    """
    pending = list(
        session.exec(select(PendingOrder).where(PendingOrder.status == OrderStatus.PENDING)).all()
    )
    now = utcnow()
    filled = 0
    for order in pending:
        try:
            if _settle_one(session, order, session_date=session_date, now=now):
                filled += 1
            session.commit()
        except Exception:
            session.rollback()
            logger.exception("order %s: settlement failed; left pending", order.id)
    return filled


def _settle_one(
    session: Session, order: PendingOrder, *, session_date: date_type | None, now: datetime
) -> bool:
    """Settle one pending order. Returns True when it filled. Does not commit."""
    if (now - order.created_at).days >= ORDER_MAX_AGE_DAYS:
        _expire(session, order)
        return False
    # The FX rate's age is judged against the session being settled (MD-7).
    try:
        priced = resolve_priced_symbol(session, order.ticker, settled_session=session_date)
    except NoMarketDataError:
        return False
    except (SymbolNotFound, NoFxRateError) as exc:
        _cancel(session, order, str(exc))
        return False

    if session_date is not None and priced.bar.ts.date() < session_date:
        logger.info(
            "order %s: latest %s bar is %s, older than session %s — leaving pending",
            order.id,
            order.ticker,
            priced.bar.ts.date(),
            session_date,
        )
        return False

    if priced.bar.ts.date() <= _known_at_placement(order):
        # LG-5: this close was already known when the order was placed.
        return False

    provenance = _evaluate_pending(order, priced)
    if provenance is None or provenance.decision.status is FillStatus.NOT_TRIGGERED:
        return False
    if provenance.decision.status is FillStatus.INELIGIBLE:
        logger.error(
            "pending order %s ineligible for kernel evaluation: ticker=%s type=%s side=%s reason=%s",
            order.id,
            order.ticker,
            order.order_type,
            order.side,
            provenance.decision.trace.reason,
        )
        return False
    fill_price = _require_full_pending_fill(order, provenance.decision)
    if fill_price is None:
        return False

    return _fill(session, order, priced, fill_price=fill_price, provenance=provenance)


def _evaluate_pending(order: PendingOrder, priced: PricedSymbol) -> FillProvenance | None:
    """Ask the kernel whether this pending order triggers. Does not mutate state."""

    try:
        intent = order_intent_from_pending(order)
        evaluated_at = evaluation_clock()
        market = market_snapshot_from_bar(priced.bar, observed_at=evaluated_at)
        decision = evaluate_order(intent, market, LIVE_PAPER_EXECUTION_PROFILE)
        return FillProvenance(
            decision=decision,
            market_interval=priced.bar.interval,
            evaluated_at=evaluated_at,
            order_type=order.order_type.value,
        )
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
    provenance: FillProvenance,
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
        result = apply_fill(
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

    record_execution_provenance(session, trade=result.trade, provenance=provenance)

    order.status = OrderStatus.FILLED
    order.filled_at = utcnow()
    order.fill_price = fill_price
    session.add(order)
    return True
