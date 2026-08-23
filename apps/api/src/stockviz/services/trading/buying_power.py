"""Derived buying-power and share reservations from pending orders.

A pending BUY reserves ``quantity * limit_price`` converted to USD at the
latest FX rate. A pending SELL reserves its quantity of the ticker. Only
``PENDING`` rows contribute, so cancel/fill/expiry releases the reservation
without a second stored balance.

Callers that create reservations or spend cash/shares must lock the portfolio
row first (:func:`lock_portfolio`) so two concurrent transactions cannot both
observe the same available buying power.

FX for an existing reservation is re-read at the latest known rate. That is an
admission-control estimate, not a frozen fill price — settlement still
revalidates actual USD cost against ``cash_balance`` minus *other* orders'
reservations.
"""

from __future__ import annotations

from decimal import Decimal

from sqlmodel import Session, select

from stockviz.models import PendingOrder, Portfolio, Position, Symbol, TradeSide
from stockviz.models.order import OrderStatus
from stockviz.services.trading.fx import latest_rate

MICROS = Decimal("0.000001")


def lock_portfolio(session: Session, portfolio_id: int) -> Portfolio:
    """``SELECT ... FOR UPDATE`` the portfolio row and return it.

    PostgreSQL holds the row lock until this transaction commits or rolls
    back, serializing competing reservation and cash-spend paths. SQLite
    accepts the clause but does not enforce it — tests in this repo use
    SQLite and therefore do not prove concurrent exclusion.
    """
    return session.exec(
        select(Portfolio).where(Portfolio.id == portfolio_id).with_for_update()
    ).one()


def buy_reservation_usd(
    session: Session,
    *,
    ticker: str,
    quantity: Decimal,
    limit_price: Decimal,
) -> Decimal:
    """USD notional reserved by a pending BUY of ``quantity`` at ``limit_price``.

    Raises ``LookupError`` (from :func:`latest_rate`) when a non-USD symbol
    has no FX rate — callers wrap that as ``NoFxRateError``.
    """
    symbol = session.get(Symbol, ticker)
    currency = (symbol.currency if symbol is not None else None) or "USD"
    native = (quantity * limit_price).quantize(MICROS)
    try:
        rate = latest_rate(session, currency)
    except LookupError as exc:
        raise LookupError(
            f"No FX rate for {currency!r}; cannot price {ticker!r} reservation in USD"
        ) from exc
    return (native * rate).quantize(MICROS)


def reserved_cash(
    session: Session,
    portfolio_id: int,
    *,
    exclude_order_id: int | None = None,
) -> Decimal:
    """USD reserved by currently pending BUY orders on ``portfolio_id``."""
    stmt = select(PendingOrder).where(
        PendingOrder.portfolio_id == portfolio_id,
        PendingOrder.status == OrderStatus.PENDING,
        PendingOrder.side == TradeSide.BUY,
    )
    if exclude_order_id is not None:
        stmt = stmt.where(PendingOrder.id != exclude_order_id)
    total = Decimal(0)
    for order in session.exec(stmt).all():
        total += buy_reservation_usd(
            session,
            ticker=order.ticker,
            quantity=order.quantity,
            limit_price=order.limit_price,
        )
    return total.quantize(MICROS)


def available_cash(
    session: Session,
    portfolio: Portfolio,
    *,
    exclude_order_id: int | None = None,
) -> Decimal:
    """``cash_balance`` minus pending-BUY reservations (optionally excluding one order)."""
    assert portfolio.id is not None
    reserved = reserved_cash(session, portfolio.id, exclude_order_id=exclude_order_id)
    return (portfolio.cash_balance - reserved).quantize(MICROS)


def reserved_shares(
    session: Session,
    portfolio_id: int,
    ticker: str,
    *,
    exclude_order_id: int | None = None,
) -> Decimal:
    """Shares reserved by currently pending SELL orders for ``ticker``."""
    stmt = select(PendingOrder).where(
        PendingOrder.portfolio_id == portfolio_id,
        PendingOrder.ticker == ticker,
        PendingOrder.status == OrderStatus.PENDING,
        PendingOrder.side == TradeSide.SELL,
    )
    if exclude_order_id is not None:
        stmt = stmt.where(PendingOrder.id != exclude_order_id)
    total = Decimal(0)
    for order in session.exec(stmt).all():
        total += order.quantity
    return total


def available_shares(
    session: Session,
    portfolio_id: int,
    ticker: str,
    *,
    exclude_order_id: int | None = None,
) -> Decimal:
    """Held quantity minus pending-SELL reservations (optionally excluding one order)."""
    position = session.exec(
        select(Position)
        .where(Position.portfolio_id == portfolio_id, Position.ticker == ticker)
        .limit(1)
    ).first()
    held = position.quantity if position is not None else Decimal(0)
    return held - reserved_shares(session, portfolio_id, ticker, exclude_order_id=exclude_order_id)
