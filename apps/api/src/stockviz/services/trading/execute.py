"""Trade execution.

A market order fills at the most recent ``1d`` close in ``price_bars``. We
validate cash on buys and position size on sells, update the ``positions``
row, and write the ``trades`` row in a single transaction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlmodel import Session, select

from stockviz.models import Portfolio, Position, PriceBar, Symbol, Trade, TradeSide
from stockviz.services.trading.fx import latest_rate

logger = logging.getLogger(__name__)

DEFAULT_STARTING_CASH = Decimal("100000.00")
"""Matches the v1 simulator: every new portfolio starts with $100k."""


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


def _latest_close(session: Session, ticker: str) -> Decimal | None:
    bar = session.exec(
        select(PriceBar)
        .where(PriceBar.ticker == ticker, PriceBar.interval == "1d")
        .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()
    return bar.close if bar else None


def ensure_default_portfolio(session: Session, user_id: int) -> Portfolio:
    """Return the user's default portfolio, creating it if needed.

    The web app calls this on the first /v1/portfolio request so users see a
    funded starting balance instead of an empty page. Idempotent — re-running
    returns the existing portfolio.
    """

    existing = session.exec(
        select(Portfolio).where(Portfolio.user_id == user_id).order_by(Portfolio.id)  # type: ignore[arg-type]
    ).first()
    if existing is not None:
        return existing

    portfolio = Portfolio(user_id=user_id, name="Default", cash_balance=DEFAULT_STARTING_CASH)
    session.add(portfolio)
    session.commit()
    session.refresh(portfolio)
    return portfolio


def _get_or_create_position(session: Session, *, portfolio_id: int, ticker: str) -> Position | None:
    """Return the existing Position row for (portfolio, ticker), or None."""

    return session.exec(
        select(Position)
        .where(Position.portfolio_id == portfolio_id, Position.ticker == ticker)
        .limit(1)
    ).first()


@dataclass(frozen=True, slots=True)
class TradeExecution:
    """Result of execute_trade: the persisted Trade row plus FX metadata.

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
    symbol = session.get(Symbol, ticker)
    if symbol is None:
        raise SymbolNotFound(f"Symbol {ticker!r} not found")

    price = _latest_close(session, ticker)
    if price is None:
        raise NoMarketDataError(f"No market data for {ticker!r}; cannot fill order")

    currency = symbol.currency or "USD"
    try:
        fx_rate = latest_rate(session, currency)
    except LookupError as exc:
        raise NoFxRateError(
            f"No FX rate for {currency!r}; cannot price {ticker!r} trade in USD"
        ) from exc

    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None  # ensure_default_portfolio commits/refreshes

    native_cost = (price * quantity).quantize(Decimal("0.000001"))
    usd_cost = (native_cost * fx_rate).quantize(Decimal("0.000001"))
    position = _get_or_create_position(session, portfolio_id=portfolio.id, ticker=ticker)

    if side == TradeSide.BUY:
        if portfolio.cash_balance < usd_cost:
            raise InsufficientCash(
                f"Cash balance ${portfolio.cash_balance:.2f} < trade cost ${usd_cost:.2f}"
            )
        portfolio.cash_balance = (portfolio.cash_balance - usd_cost).quantize(Decimal("0.000001"))

        if position is None:
            position = Position(
                portfolio_id=portfolio.id,
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
            position.avg_cost = (total_cost / new_qty).quantize(Decimal("0.000001"))

    else:  # SELL
        if position is None or position.quantity < quantity:
            held = position.quantity if position else Decimal(0)
            raise InsufficientPosition(f"Held {held} {ticker}, cannot sell {quantity}")
        portfolio.cash_balance = (portfolio.cash_balance + usd_cost).quantize(Decimal("0.000001"))
        position.quantity = position.quantity - quantity
        # Don't recompute avg_cost on sells — keeps cost basis honest for
        # remaining shares. If the position is fully sold, delete the row so
        # the portfolio view stays clean.
        if position.quantity == 0:
            session.delete(position)

    trade = Trade(
        portfolio_id=portfolio.id,
        ticker=ticker,
        side=side,
        quantity=quantity,
        price=price,
    )
    session.add(trade)
    session.add(portfolio)
    session.commit()
    session.refresh(trade)
    return TradeExecution(
        trade=trade,
        currency=currency,
        fx_rate=fx_rate,
        native_cost=native_cost,
        usd_cost=usd_cost,
    )
