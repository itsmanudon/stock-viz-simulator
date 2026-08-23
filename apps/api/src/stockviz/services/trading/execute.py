"""Trade execution.

A market order fills at the most recent ``1d`` close in ``price_bars``. We
validate cash on buys and position size on sells, update the ``positions``
row, and write the ``trades`` row in a single transaction.

The cash/position mutation lives in :func:`apply_fill`, which is shared with
the pending-order settlement job in ``services/trading/orders.py``. Both paths
must debit the *USD* cash bucket at the symbol's FX rate — keeping that in one
place is what stops the two from drifting apart.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from stockviz.models import Portfolio, Position, PriceBar, Symbol, Trade, TradeSide
from stockviz.services.trading.buying_power import (
    available_cash,
    available_shares,
    lock_portfolio,
    lock_user,
    reserved_shares,
)
from stockviz.services.trading.fx import latest_rate

logger = logging.getLogger(__name__)

DEFAULT_STARTING_CASH = Decimal("100000.00")
"""Matches the v1 simulator: every new portfolio starts with $100k."""

MICROS = Decimal("0.000001")
"""Quantization step for stored monetary values (matches Numeric(_, 6))."""


class TradeExecutionError(Exception):
    """Base class for things the caller should turn into a 400-shaped response."""


class SymbolNotFound(TradeExecutionError):
    pass


class NoMarketDataError(TradeExecutionError):
    pass


class NoFxRateError(TradeExecutionError):
    """Raised when a non-USD trade has no FX rate available to convert cost to USD."""


class InsufficientCash(TradeExecutionError):
    pass


class InsufficientPosition(TradeExecutionError):
    pass


def latest_bar(session: Session, ticker: str) -> PriceBar | None:
    """Most recent ``1d`` bar for ``ticker``, or None when there is no history."""
    return session.exec(
        select(PriceBar)
        .where(PriceBar.ticker == ticker, PriceBar.interval == "1d")
        .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()


def _latest_close(session: Session, ticker: str) -> Decimal | None:
    bar = latest_bar(session, ticker)
    return bar.close if bar else None


def ensure_default_portfolio(session: Session, user_id: int) -> Portfolio:
    """Return the user's default portfolio, creating it if needed.

    The web app calls this on the first /v1/portfolio request so users see a
    funded starting balance instead of an empty page. Idempotent — re-running
    returns the existing portfolio.

    A brand-new portfolio also gets a same-day NAV snapshot seeded at the
    starting cash, so return-since-inception is measured from the moment the
    account was funded rather than from whenever the nightly snapshot job
    first happened to run.
    """

    existing = session.exec(
        select(Portfolio).where(Portfolio.user_id == user_id).order_by(Portfolio.id)  # type: ignore[arg-type]
    ).first()
    if existing is not None:
        return existing

    # Serialize first-account creation on the user row. Without this, two
    # concurrent first /portfolio hits can INSERT two portfolios (user_id
    # uniqueness is enforced in the DB, but the race still needs a lock so
    # the loser re-reads instead of erroring out to the client).
    lock_user(session, user_id)
    existing = session.exec(
        select(Portfolio).where(Portfolio.user_id == user_id).order_by(Portfolio.id)  # type: ignore[arg-type]
    ).first()
    if existing is not None:
        return existing

    portfolio = Portfolio(user_id=user_id, name="Default", cash_balance=DEFAULT_STARTING_CASH)
    session.add(portfolio)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.exec(
            select(Portfolio).where(Portfolio.user_id == user_id).order_by(Portfolio.id)  # type: ignore[arg-type]
        ).first()
        if existing is None:
            raise
        return existing
    session.refresh(portfolio)
    _seed_opening_snapshot(session, user_id=user_id, nav=DEFAULT_STARTING_CASH)
    return portfolio


def _seed_opening_snapshot(session: Session, *, user_id: int, nav: Decimal) -> None:
    """Write the day-zero NAV snapshot for a freshly created portfolio.

    Imported lazily: ``services.trading.snapshots`` imports ``portfolio``,
    which imports this module, so a module-level import would cycle.
    """
    from stockviz._time import utcnow
    from stockviz.models import PortfolioSnapshot

    today = utcnow().date()
    existing = session.exec(
        select(PortfolioSnapshot).where(
            PortfolioSnapshot.user_id == user_id,
            PortfolioSnapshot.date == today,
        )
    ).first()
    if existing is not None:
        return
    session.add(PortfolioSnapshot(user_id=user_id, date=today, nav=nav))
    try:
        session.commit()
    except IntegrityError:
        # The portfolio page fans out several /v1 calls in Promise.all; two of
        # them can pass the SELECT above and one INSERT then hits
        # uq_portfolio_snapshots_user_date. The other request already wrote
        # the row — treat that as success.
        session.rollback()


def get_position(session: Session, *, portfolio_id: int, ticker: str) -> Position | None:
    """Return the existing Position row for (portfolio, ticker), or None."""

    return session.exec(
        select(Position)
        .where(Position.portfolio_id == portfolio_id, Position.ticker == ticker)
        .limit(1)
    ).first()


@dataclass(frozen=True, slots=True)
class PricedSymbol:
    """A symbol resolved to a fillable price plus the FX rate for its currency."""

    symbol: Symbol
    price: Decimal
    currency: str
    fx_rate: Decimal
    bar: PriceBar


def resolve_priced_symbol(session: Session, ticker: str) -> PricedSymbol:
    """Look up the symbol, its latest close, and the FX rate to convert to USD.

    Raises the matching ``TradeExecutionError`` subclass when any leg is
    missing, so callers get one consistent failure vocabulary.
    """

    symbol = session.get(Symbol, ticker)
    if symbol is None:
        raise SymbolNotFound(f"Symbol {ticker!r} not found")

    bar = latest_bar(session, ticker)
    if bar is None:
        raise NoMarketDataError(f"No market data for {ticker!r}; cannot fill order")

    currency = symbol.currency or "USD"
    try:
        fx_rate = latest_rate(session, currency)
    except LookupError as exc:
        raise NoFxRateError(
            f"No FX rate for {currency!r}; cannot price {ticker!r} trade in USD"
        ) from exc

    return PricedSymbol(symbol=symbol, price=bar.close, currency=currency, fx_rate=fx_rate, bar=bar)


@dataclass(frozen=True, slots=True)
class TradeExecution:
    """Result of a fill: the persisted Trade row plus FX metadata.

    The Trade row stores price + quantity in the symbol's native currency
    (e.g. EUR for SAP.DE). ``usd_cost`` is what was actually debited from /
    credited to the USD cash bucket; ``fx_rate`` is the USD-per-native-unit
    rate used for that conversion (1 for USD symbols).
    """

    trade: Trade
    currency: str
    fx_rate: Decimal
    native_cost: Decimal
    usd_cost: Decimal
    realized_pnl: Decimal | None


def apply_fill(
    session: Session,
    *,
    portfolio: Portfolio,
    ticker: str,
    side: TradeSide,
    quantity: Decimal,
    price: Decimal,
    currency: str,
    fx_rate: Decimal,
    exclude_order_id: int | None = None,
) -> TradeExecution:
    """Mutate cash + position and stage the Trade row for ``portfolio``.

    Shared by market orders (:func:`execute_trade`) and by the EOD
    pending-order settlement job. Adds rows to the session but does **not**
    commit — the caller owns the transaction boundary, which lets the
    settlement job batch many fills together.

    ``price`` is in the symbol's native currency; ``fx_rate`` is USD per one
    unit of that currency. Cash is always USD.

    Spendability is checked against *available* cash/shares (ledger balance
    minus reservations from *other* pending orders). ``exclude_order_id``
    lets a filling order consume its own reservation.

    Locks the portfolio row for the rest of the caller's transaction.

    Raises ``InsufficientCash`` / ``InsufficientPosition`` without having
    mutated anything, so a caller that catches the error can carry on with the
    same session.
    """

    assert portfolio.id is not None
    portfolio_id = portfolio.id
    portfolio = lock_portfolio(session, portfolio_id)

    native_cost = (price * quantity).quantize(MICROS)
    usd_cost = (native_cost * fx_rate).quantize(MICROS)
    position = get_position(session, portfolio_id=portfolio_id, ticker=ticker)
    realized_pnl: Decimal | None = None

    if side == TradeSide.BUY:
        try:
            spendable = available_cash(session, portfolio, exclude_order_id=exclude_order_id)
        except LookupError as exc:
            raise NoFxRateError(str(exc)) from exc
        if spendable < usd_cost:
            raise InsufficientCash(
                f"Available buying power ${spendable:.2f}; order requires ${usd_cost:.2f}."
            )
        portfolio.cash_balance = (portfolio.cash_balance - usd_cost).quantize(MICROS)

        if position is None:
            position = Position(
                portfolio_id=portfolio_id,
                ticker=ticker,
                quantity=quantity,
                avg_cost=price,
            )
            session.add(position)
        else:
            # Weighted-average cost recompute, in native currency (the
            # symbol's currency doesn't change between trades).
            total_cost = position.avg_cost * position.quantity + native_cost
            new_qty = position.quantity + quantity
            position.quantity = new_qty
            position.avg_cost = (total_cost / new_qty).quantize(MICROS)

    else:  # SELL
        held = position.quantity if position else Decimal(0)
        reserved = reserved_shares(session, portfolio_id, ticker, exclude_order_id=exclude_order_id)
        spendable = available_shares(
            session, portfolio_id, ticker, exclude_order_id=exclude_order_id
        )
        if spendable < quantity:
            if reserved > 0:
                raise InsufficientPosition(
                    f"Only {spendable} {ticker} shares are available; "
                    f"{reserved} are reserved by pending orders."
                )
            raise InsufficientPosition(f"Held {held} {ticker}, cannot sell {quantity}")
        assert position is not None
        portfolio.cash_balance = (portfolio.cash_balance + usd_cost).quantize(MICROS)
        # Realized P&L against the weighted-average cost basis, in USD.
        realized_pnl = ((price - position.avg_cost) * quantity * fx_rate).quantize(MICROS)
        position.quantity = position.quantity - quantity
        # Don't recompute avg_cost on sells — keeps cost basis honest for
        # remaining shares. If the position is fully sold, delete the row so
        # the portfolio view stays clean.
        if position.quantity == 0:
            session.delete(position)

    trade = Trade(
        portfolio_id=portfolio_id,
        ticker=ticker,
        side=side,
        quantity=quantity,
        price=price,
        fx_rate=fx_rate,
        realized_pnl=realized_pnl,
    )
    session.add(trade)
    session.add(portfolio)
    return TradeExecution(
        trade=trade,
        currency=currency,
        fx_rate=fx_rate,
        native_cost=native_cost,
        usd_cost=usd_cost,
        realized_pnl=realized_pnl,
    )


def execute_trade(
    session: Session,
    *,
    user_id: int,
    ticker: str,
    side: TradeSide,
    quantity: Decimal,
) -> TradeExecution:
    """Execute a market order. Raises a ``TradeExecutionError`` subclass on validation failure.

    The price stored on the Trade row is in the symbol's native currency.
    Cash (always USD) is debited/credited at today's FX rate for non-USD
    symbols. USD symbols pass through unchanged.
    """

    if quantity <= 0:
        raise TradeExecutionError("quantity must be positive")

    ticker = ticker.upper()
    priced = resolve_priced_symbol(session, ticker)

    portfolio = ensure_default_portfolio(session, user_id)
    result = apply_fill(
        session,
        portfolio=portfolio,
        ticker=ticker,
        side=side,
        quantity=quantity,
        price=priced.price,
        currency=priced.currency,
        fx_rate=priced.fx_rate,
    )
    session.commit()
    session.refresh(result.trade)
    return result
