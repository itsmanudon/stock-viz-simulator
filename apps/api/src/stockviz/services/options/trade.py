"""Options paper-trading: open, close, value, and settle long option positions.

The book is long-only. ``open_option`` buys a contract (premium debited from
cash), ``close_option`` sells it back at the current theoretical price
(proceeds credited), and ``settle_expired_options`` runs at/after expiry:

- ITM call  -> exercised into the equity book: buy ``qty * 100`` shares at the
  strike. If cash can't cover the strike cost, the intrinsic value is
  cash-settled instead.
- ITM put   -> if the portfolio holds enough shares they're sold at the strike
  (protective-put semantics); otherwise the intrinsic value is cash-settled.
- OTM       -> expires worthless; the premium is already lost.

Implied volatility is the 30-day historical volatility of the underlying — a
documented v1 proxy for a real IV surface.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date as date_type
from decimal import Decimal

from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import (
    OptionsPosition,
    OptionStatus,
    OptionType,
    Portfolio,
    Position,
    PriceBar,
    Symbol,
)
from stockviz.models.option import CONTRACT_MULTIPLIER
from stockviz.services.options.pricing import OptionPrice, black_scholes, historical_volatility
from stockviz.services.trading.execute import ensure_default_portfolio

logger = logging.getLogger(__name__)

RISK_FREE_RATE = 0.05
"""Annual risk-free rate fed to Black-Scholes (matches the analytics default)."""

_CENTS = Decimal("0.01")
_MICROS = Decimal("0.000001")


class OptionTradeError(Exception):
    """Base class for option-trade failures the caller turns into 4xx."""


class OptionSymbolNotFound(OptionTradeError):
    pass


class NoOptionMarketData(OptionTradeError):
    pass


class InvalidExpiry(OptionTradeError):
    pass


class InsufficientCashForOption(OptionTradeError):
    pass


class OptionNotFound(OptionTradeError):
    pass


def _bar_closes(session: Session, ticker: str, *, limit: int = 60) -> list[Decimal]:
    """Most-recent ``limit`` daily closes for ``ticker``, oldest first."""
    rows = list(
        session.exec(
            select(PriceBar)
            .where(PriceBar.ticker == ticker, PriceBar.interval == "1d")
            .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
            .limit(limit)
        )
    )
    rows.reverse()
    return [r.close for r in rows]


def _spot(session: Session, ticker: str) -> Decimal | None:
    closes = _bar_closes(session, ticker, limit=1)
    return closes[-1] if closes else None


def _years_to_expiry(expiry: date_type, *, asof: date_type) -> float:
    return (expiry - asof).days / 365.0


def value_option(
    session: Session, position: OptionsPosition, *, asof: date_type | None = None
) -> OptionPrice:
    """Current Black-Scholes valuation (per share) for an open position."""
    asof = asof or date_type.today()
    spot = _spot(session, position.ticker)
    if spot is None:
        raise NoOptionMarketData(f"No market data for {position.ticker!r}")
    vol = historical_volatility(_bar_closes(session, position.ticker))
    return black_scholes(
        spot=float(spot),
        strike=float(position.strike),
        time_to_expiry_years=max(_years_to_expiry(position.expiry, asof=asof), 0.0),
        volatility=vol,
        risk_free_rate=RISK_FREE_RATE,
        option_type=position.option_type.value,
    )


@dataclass(frozen=True, slots=True)
class OptionTradeResult:
    position: OptionsPosition
    cash_delta: Decimal  # negative when premium paid, positive when proceeds received


def open_option(
    session: Session,
    *,
    user_id: int,
    ticker: str,
    option_type: OptionType,
    strike: Decimal,
    expiry: date_type,
    quantity: int,
) -> OptionTradeResult:
    """Buy ``quantity`` contracts to open. Premium is debited from portfolio cash."""

    if quantity <= 0:
        raise OptionTradeError("quantity must be a positive number of contracts")
    if strike <= 0:
        raise OptionTradeError("strike must be positive")

    ticker = ticker.upper()
    if session.get(Symbol, ticker) is None:
        raise OptionSymbolNotFound(f"Symbol {ticker!r} not found")

    today = date_type.today()
    if expiry <= today:
        raise InvalidExpiry("expiry must be a future date")

    spot = _spot(session, ticker)
    if spot is None:
        raise NoOptionMarketData(f"No market data for {ticker!r}; cannot price option")

    vol = historical_volatility(_bar_closes(session, ticker))
    price = black_scholes(
        spot=float(spot),
        strike=float(strike),
        time_to_expiry_years=_years_to_expiry(expiry, asof=today),
        volatility=vol,
        risk_free_rate=RISK_FREE_RATE,
        option_type=option_type.value,
    )
    premium = (Decimal(str(price.value)) * CONTRACT_MULTIPLIER * quantity).quantize(_CENTS)
    if premium < 0:
        premium = Decimal("0.00")

    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    if portfolio.cash_balance < premium:
        raise InsufficientCashForOption(
            f"Cash balance ${portfolio.cash_balance:.2f} < option premium ${premium:.2f}"
        )

    portfolio.cash_balance = (portfolio.cash_balance - premium).quantize(_MICROS)
    position = OptionsPosition(
        user_id=user_id,
        portfolio_id=portfolio.id,
        ticker=ticker,
        option_type=option_type,
        strike=strike,
        expiry=expiry,
        quantity=quantity,
        premium_paid=premium,
        status=OptionStatus.OPEN,
    )
    session.add(portfolio)
    session.add(position)
    session.commit()
    session.refresh(position)
    return OptionTradeResult(position=position, cash_delta=-premium)


def close_option(session: Session, *, user_id: int, option_id: int) -> OptionTradeResult:
    """Sell an open position back at its current theoretical value."""

    position = session.get(OptionsPosition, option_id)
    if position is None or position.user_id != user_id:
        raise OptionNotFound("Option position not found")
    if position.status != OptionStatus.OPEN:
        raise OptionTradeError(f"Option position is already {position.status.value}")

    price = value_option(session, position)
    proceeds = (Decimal(str(price.value)) * CONTRACT_MULTIPLIER * position.quantity).quantize(
        _CENTS
    )
    if proceeds < 0:
        proceeds = Decimal("0.00")

    portfolio = session.get(Portfolio, position.portfolio_id)
    assert portfolio is not None
    portfolio.cash_balance = (portfolio.cash_balance + proceeds).quantize(_MICROS)
    position.status = OptionStatus.CLOSED
    position.settled_at = utcnow()
    session.add(portfolio)
    session.add(position)
    session.commit()
    session.refresh(position)
    return OptionTradeResult(position=position, cash_delta=proceeds)


def _exercise_call_into_equity(
    session: Session, portfolio: Portfolio, position: OptionsPosition, *, spot: Decimal
) -> None:
    """ITM call: buy qty*100 shares at the strike, adding to the equity book.

    Falls back to cash-settling the intrinsic value if the portfolio can't
    afford the strike cost.
    """
    shares = Decimal(position.quantity * CONTRACT_MULTIPLIER)
    strike_cost = (position.strike * shares).quantize(_MICROS)

    if portfolio.cash_balance < strike_cost:
        intrinsic = ((spot - position.strike) * shares).quantize(_CENTS)
        portfolio.cash_balance = (portfolio.cash_balance + intrinsic).quantize(_MICROS)
        logger.info(
            "options_settle: call %s cash-settled (insufficient cash to exercise) +%s",
            position.id,
            intrinsic,
        )
        return

    portfolio.cash_balance = (portfolio.cash_balance - strike_cost).quantize(_MICROS)
    equity = session.exec(
        select(Position).where(
            Position.portfolio_id == portfolio.id, Position.ticker == position.ticker
        )
    ).first()
    if equity is None:
        session.add(
            Position(
                portfolio_id=portfolio.id,  # type: ignore[arg-type]
                ticker=position.ticker,
                quantity=shares,
                avg_cost=position.strike,
            )
        )
    else:
        total_cost = equity.avg_cost * equity.quantity + strike_cost
        equity.quantity = equity.quantity + shares
        equity.avg_cost = (total_cost / equity.quantity).quantize(_MICROS)
        session.add(equity)


def _exercise_put(
    session: Session, portfolio: Portfolio, position: OptionsPosition, *, spot: Decimal
) -> None:
    """ITM put: sell qty*100 held shares at the strike if the portfolio owns
    enough; otherwise cash-settle the intrinsic value."""
    shares = Decimal(position.quantity * CONTRACT_MULTIPLIER)
    equity = session.exec(
        select(Position).where(
            Position.portfolio_id == portfolio.id, Position.ticker == position.ticker
        )
    ).first()

    if equity is not None and equity.quantity >= shares:
        proceeds = (position.strike * shares).quantize(_MICROS)
        portfolio.cash_balance = (portfolio.cash_balance + proceeds).quantize(_MICROS)
        equity.quantity = equity.quantity - shares
        if equity.quantity == 0:
            session.delete(equity)
        else:
            session.add(equity)
    else:
        intrinsic = ((position.strike - spot) * shares).quantize(_CENTS)
        portfolio.cash_balance = (portfolio.cash_balance + intrinsic).quantize(_MICROS)


def settle_expired_options(session: Session, *, settle_date: date_type) -> int:
    """Settle every open option whose expiry is on or before ``settle_date``.

    Returns the number of positions settled. Idempotent: only ``OPEN``
    positions are touched, and each is flipped to a terminal status.
    """

    expired = list(
        session.exec(
            select(OptionsPosition).where(
                OptionsPosition.status == OptionStatus.OPEN,
                OptionsPosition.expiry <= settle_date,
            )
        )
    )
    settled = 0
    for position in expired:
        spot = _spot(session, position.ticker)
        portfolio = session.get(Portfolio, position.portfolio_id)
        if spot is None or portfolio is None:
            # No closing price to settle against — leave it for a later run.
            logger.warning("options_settle: skipping option %s (no spot/portfolio)", position.id)
            continue

        if position.option_type == OptionType.CALL:
            in_the_money = spot > position.strike
        else:
            in_the_money = spot < position.strike

        if in_the_money:
            if position.option_type == OptionType.CALL:
                _exercise_call_into_equity(session, portfolio, position, spot=spot)
            else:
                _exercise_put(session, portfolio, position, spot=spot)
            position.status = OptionStatus.EXERCISED
        else:
            position.status = OptionStatus.EXPIRED

        position.settled_at = utcnow()
        session.add(portfolio)
        session.add(position)
        session.commit()
        settled += 1
        logger.info("options_settle: option %s -> %s", position.id, position.status.value)

    return settled
