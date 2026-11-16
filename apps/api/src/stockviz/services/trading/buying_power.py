"""Derived buying-power and share reservations from pending orders.

A pending BUY reserves ``quantity * limit_price`` converted to the portfolio's base currency at the
latest FX rate. A pending SELL reserves its quantity of the ticker. Only
``PENDING`` rows contribute, so cancel/fill/expiry releases the reservation
without a second stored balance.

Open short option legs reserve their cover the same way (Phase 9.2): a
covered call holds back its shares (contracts x shares per contract), a
cash-secured put its full strike value, in USD converted to the base. Closing, assignment or expiry releases it.
``exclude_option_id`` lets that leg's own settlement use its cover.

Callers that create reservations or spend cash/shares must lock the portfolio
row first (:func:`lock_portfolio`) so two concurrent transactions cannot both
observe the same available buying power.

FX for an existing reservation is re-read at the latest known rate. That is an
admission-control estimate, not a frozen fill price — settlement still
revalidates actual base-currency cost against ``cash_balance`` minus *other* orders'
reservations.
"""

from __future__ import annotations

from decimal import Decimal

from sqlmodel import Session, select

from stockviz.models import PendingOrder, Portfolio, Position, Symbol, TradeSide, User
from stockviz.models.option import (
    OptionCover,
    OptionSide,
    OptionsPosition,
    OptionStatus,
    OptionType,
)
from stockviz.models.option_strategy import OptionStrategy, StrategyStatus
from stockviz.models.order import OrderStatus
from stockviz.services.instruments import instrument_of
from stockviz.services.trading.fx import base_rate

MICROS = Decimal("0.000001")


def lock_portfolio(session: Session, portfolio_id: int) -> Portfolio:
    """``SELECT ... FOR UPDATE`` the portfolio row and return a *fresh* copy.

    PostgreSQL holds the row lock until this transaction commits or rolls
    back, serializing competing reservation and cash-spend paths.

    ``Session.refresh(..., with_for_update=True)`` is required: a prior
    ``ensure_default_portfolio`` (or any other load) may already have the
    row in the identity map. A bare ``SELECT ... FOR UPDATE`` would then
    reuse the stale ``cash_balance`` and overwrite a concurrent debit.

    SQLite accepts ``FOR UPDATE`` but does not enforce it. Concurrent
    exclusion is proven by the PostgreSQL test in ``test_pg_concurrency.py``.
    """
    portfolio = session.get(Portfolio, portfolio_id)
    if portfolio is None:
        raise LookupError(f"Portfolio {portfolio_id} not found")
    session.refresh(portfolio, with_for_update=True)
    return portfolio


def lock_user(session: Session, user_id: int) -> User:
    """``SELECT ... FOR UPDATE`` the user row so first-portfolio creation serializes."""
    user = session.get(User, user_id)
    if user is None:
        raise LookupError(f"User {user_id} not found")
    session.refresh(user, with_for_update=True)
    return user


def buy_reservation(
    session: Session,
    *,
    ticker: str,
    quantity: Decimal,
    limit_price: Decimal,
    base: str = "USD",
) -> Decimal:
    """Base-currency amount reserved by a pending BUY of ``quantity`` at ``limit_price``.

    ``base`` is the portfolio's base currency (Phase 4.8). Raises
    ``LookupError`` when a rate is missing — callers wrap that as
    ``NoFxRateError``.
    """
    symbol = session.get(Symbol, ticker)
    currency = (symbol.currency if symbol is not None else None) or "USD"
    native = (quantity * limit_price).quantize(MICROS)
    try:
        rate = base_rate(session, currency, base)
    except LookupError as exc:
        raise LookupError(
            f"No FX rate for {currency!r}; cannot price {ticker!r} reservation in {base}"
        ) from exc
    return (native * rate).quantize(MICROS)


def _open_short_legs(
    session: Session,
    portfolio_id: int,
    *,
    option_type: OptionType,
    cover: OptionCover,
    exclude_option_id: int | None,
    exclude_strategy_id: int | None = None,
) -> list[OptionsPosition]:
    stmt = select(OptionsPosition).where(
        OptionsPosition.portfolio_id == portfolio_id,
        OptionsPosition.status == OptionStatus.OPEN,
        OptionsPosition.side == OptionSide.SHORT,
        OptionsPosition.option_type == option_type,
        OptionsPosition.cover == cover,
    )
    if exclude_option_id is not None:
        stmt = stmt.where(OptionsPosition.id != exclude_option_id)
    legs = list(session.exec(stmt).all())
    if exclude_strategy_id is not None:
        legs = [leg for leg in legs if leg.strategy_id != exclude_strategy_id]
    return legs


def strategy_collateral_usd(
    session: Session, portfolio_id: int, *, exclude_strategy_id: int | None = None
) -> Decimal:
    """USD held back by open strategies while a short leg in them is covered by a
    long leg (Phase 9.3): spreads and calendars. Covered calls and cash-secured
    puts reserve through their own legs instead."""
    open_shorts = select(OptionsPosition.strategy_id).where(
        OptionsPosition.portfolio_id == portfolio_id,
        OptionsPosition.status == OptionStatus.OPEN,
        OptionsPosition.side == OptionSide.SHORT,
        OptionsPosition.cover == OptionCover.LEG,
    )
    stmt = select(OptionStrategy).where(
        OptionStrategy.portfolio_id == portfolio_id,
        OptionStrategy.status == StrategyStatus.OPEN,
        OptionStrategy.id.in_(open_shorts),  # type: ignore[union-attr]
    )
    if exclude_strategy_id is not None:
        stmt = stmt.where(OptionStrategy.id != exclude_strategy_id)
    return sum((row.collateral for row in session.exec(stmt).all()), Decimal(0))


def put_collateral_usd(position: OptionsPosition) -> Decimal:
    """USD a cash-secured put holds back: the full strike value.

    Not the strike value less the premium: the premium already sits in cash
    and is spendable, so holding back only the difference would let it be
    spent twice and leave assignment one premium short.
    """
    shares = position.shares_per_contract * position.quantity
    return (position.strike * shares).quantize(MICROS)


def option_cash_reservation(
    session: Session,
    portfolio_id: int,
    *,
    base: str = "USD",
    exclude_option_id: int | None = None,
    exclude_strategy_id: int | None = None,
) -> Decimal:
    """Base currency held back by cash-secured puts and covered strategies."""
    legs = _open_short_legs(
        session,
        portfolio_id,
        option_type=OptionType.PUT,
        cover=OptionCover.CASH,
        exclude_option_id=exclude_option_id,
        exclude_strategy_id=exclude_strategy_id,
    )
    usd = sum((put_collateral_usd(leg) for leg in legs), Decimal(0))
    usd += strategy_collateral_usd(session, portfolio_id, exclude_strategy_id=exclude_strategy_id)
    if not usd:
        return Decimal(0)
    return (usd * base_rate(session, "USD", base)).quantize(MICROS)


def option_share_reservation(
    session: Session,
    portfolio_id: int,
    ticker: str,
    *,
    exclude_option_id: int | None = None,
) -> Decimal:
    """Shares of ``ticker`` held back by open covered calls."""
    legs = _open_short_legs(
        session,
        portfolio_id,
        option_type=OptionType.CALL,
        cover=OptionCover.SHARES,
        exclude_option_id=exclude_option_id,
    )
    return sum(
        (leg.quantity * leg.shares_per_contract for leg in legs if leg.ticker == ticker),
        Decimal(0),
    )


def reserved_cash(
    session: Session,
    portfolio_id: int,
    *,
    exclude_order_id: int | None = None,
    exclude_option_id: int | None = None,
    exclude_strategy_id: int | None = None,
) -> Decimal:
    """Base currency reserved by pending BUY orders and short option covers."""
    portfolio = session.get(Portfolio, portfolio_id)
    base = (portfolio.base_currency if portfolio is not None else None) or "USD"
    stmt = select(PendingOrder).where(
        PendingOrder.portfolio_id == portfolio_id,
        PendingOrder.status == OrderStatus.PENDING,
        PendingOrder.side == TradeSide.BUY,
    )
    if exclude_order_id is not None:
        stmt = stmt.where(PendingOrder.id != exclude_order_id)
    total = Decimal(0)
    for order in session.exec(stmt).all():
        total += buy_reservation(
            session,
            ticker=order.ticker,
            quantity=order.quantity,
            limit_price=order.limit_price,
            base=base,
        )
    total += option_cash_reservation(
        session,
        portfolio_id,
        base=base,
        exclude_option_id=exclude_option_id,
        exclude_strategy_id=exclude_strategy_id,
    )
    return total.quantize(MICROS)


def available_cash(
    session: Session,
    portfolio: Portfolio,
    *,
    exclude_order_id: int | None = None,
    exclude_option_id: int | None = None,
    exclude_strategy_id: int | None = None,
) -> Decimal:
    """``cash_balance`` minus reservations (optionally excluding one order, option
    or strategy, so a fill or close can use its own reservation)."""
    assert portfolio.id is not None
    reserved = reserved_cash(
        session,
        portfolio.id,
        exclude_order_id=exclude_order_id,
        exclude_option_id=exclude_option_id,
        exclude_strategy_id=exclude_strategy_id,
    )
    return (portfolio.cash_balance - reserved).quantize(MICROS)


def reserved_shares(
    session: Session,
    portfolio_id: int,
    ticker: str,
    *,
    exclude_order_id: int | None = None,
    exclude_option_id: int | None = None,
) -> Decimal:
    """Shares reserved by pending SELL orders and covered calls for ``ticker``."""
    stmt = select(PendingOrder).where(
        PendingOrder.portfolio_id == portfolio_id,
        PendingOrder.instrument_id == instrument_of(ticker),
        PendingOrder.status == OrderStatus.PENDING,
        PendingOrder.side == TradeSide.SELL,
    )
    if exclude_order_id is not None:
        stmt = stmt.where(PendingOrder.id != exclude_order_id)
    total = Decimal(0)
    for order in session.exec(stmt).all():
        total += order.quantity
    return total + option_share_reservation(
        session, portfolio_id, ticker, exclude_option_id=exclude_option_id
    )


def available_shares(
    session: Session,
    portfolio_id: int,
    ticker: str,
    *,
    exclude_order_id: int | None = None,
    exclude_option_id: int | None = None,
) -> Decimal:
    """Held quantity minus reserved shares (optionally excluding one order or option)."""
    position = session.exec(
        select(Position)
        .where(
            Position.portfolio_id == portfolio_id, Position.instrument_id == instrument_of(ticker)
        )
        .limit(1)
    ).first()
    held = position.quantity if position is not None else Decimal(0)
    return held - reserved_shares(
        session,
        portfolio_id,
        ticker,
        exclude_order_id=exclude_order_id,
        exclude_option_id=exclude_option_id,
    )
