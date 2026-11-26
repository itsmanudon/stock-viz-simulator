"""Options paper-trading: open, close, value, and settle long option positions.

``open_option`` buys a contract (premium debited from cash) or, since Phase
9.2, writes a covered one (premium credited, cover reserved: shares for a
call, the strike value for a put). ``close_option`` sells a
long contract back, or buys a short one back, at the current theoretical
price, and ``settle_expired_options`` runs at/after expiry. Long legs:

- ITM call  -> exercised into the equity book: buy ``qty * 100`` shares at the
  strike. If *available* cash (ledger minus pending-BUY reservations) can't
  cover the strike cost, the intrinsic value is cash-settled instead.
- ITM put   -> if the portfolio has enough *available* shares (held minus
  pending-SELL reservations) they're sold at the strike; otherwise the
  intrinsic value is cash-settled.
- OTM       -> expires worthless; the premium is already lost.

Short legs (always covered; settled after the long legs):

- ITM call  -> assigned: the reserved shares are sold at the strike.
- ITM put   -> assigned: shares are bought at the strike with the reserved cash.
- OTM       -> expires; the premium received is kept.

Implied volatility is the 30-day historical volatility of the underlying — a
documented v1 proxy for a real IV surface.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from datetime import date as date_type
from decimal import Decimal

from sqlmodel import Session, col, select

from stockviz._time import utcnow
from stockviz.models import (
    OptionsPosition,
    OptionStatus,
    OptionType,
    Portfolio,
    PriceBar,
    Symbol,
    TradeSide,
)
from stockviz.models.option import CONTRACT_MULTIPLIER, OptionCover, OptionSide, position_sign
from stockviz.services.ingest.bar_semantics import latest_completed_session
from stockviz.services.instruments import instrument_of
from stockviz.services.markets.calendar import (
    NEW_YORK_VENUE,
    session_on_or_before,
    trading_date,
)
from stockviz.services.options.chains import chain_volatility
from stockviz.services.options.margin import PositionRisk, position_risk
from stockviz.services.options.pricing import (
    MIN_PREMIUM_PER_SHARE,
    MIN_VOL_CLOSES,
    ImpliedVolatility,
    OptionPrice,
    black_scholes,
    historical_volatility,
    implied_volatility,
    risk_free_rate,
    usable_closes,
)
from stockviz.services.trading.books import require_writable, resolve_book
from stockviz.services.trading.buying_power import (
    available_cash,
    available_shares,
    lock_portfolio,
    put_collateral_usd,
)
from stockviz.services.trading.cash import base_currency, credit, pay_for_buy, plan_buy
from stockviz.services.trading.execute import (
    InsufficientCash,
    InsufficientPosition,
    NoFxRateError,
    apply_fill,
)
from stockviz.services.trading.fx import base_rate

logger = logging.getLogger(__name__)

RISK_FREE_RATE = risk_free_rate("USD")
HISTORICAL_VOL_METHOD = "historical volatility of daily closes, 30 sessions, annualised"
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


class OptionOrderConflict(OptionTradeError):
    """A client_order_id already names a different option open (audit LG-10)."""


class InsufficientCoverForOption(OptionTradeError):
    """A short leg needs shares (covered call) or cash (cash-secured put) it lacks."""


class OptionNotFound(OptionTradeError):
    pass


def _bar_closes(session: Session, ticker: str, *, limit: int = 60) -> list[Decimal]:
    """Most-recent ``limit`` daily closes for ``ticker``, oldest first."""
    rows = list(
        session.exec(
            select(PriceBar)
            .where(PriceBar.instrument_id == instrument_of(ticker), PriceBar.interval == "1d")
            .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
            .limit(limit)
        )
    )
    rows.reverse()
    return [r.close for r in rows]


def _spot(session: Session, ticker: str) -> Decimal | None:
    closes = _bar_closes(session, ticker, limit=1)
    return closes[-1] if closes else None


def _today() -> date_type:
    """The New York trading date (audit LG-15). ``utcnow`` stays patchable."""
    return trading_date(utcnow().replace(tzinfo=UTC))


def _years_to_expiry(expiry: date_type, *, asof: date_type) -> float:
    return (expiry - asof).days / 365.0


def value_option(
    session: Session, position: OptionsPosition, *, asof: date_type | None = None
) -> OptionPrice:
    """Current Black-Scholes valuation (per share) for an open position."""
    asof = asof or _today()
    spot = _spot(session, position.ticker)
    if spot is None:
        raise NoOptionMarketData(f"No market data for {position.ticker!r}")
    chain = chain_volatility(
        session,
        position.ticker,
        option_type=position.option_type.value,
        strike=position.strike,
        expiry=position.expiry,
        asof=asof,
    )
    vol = (
        chain.volatility
        if chain is not None
        else historical_volatility(_bar_closes(session, position.ticker))
    )
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


@dataclass(frozen=True, slots=True)
class OptionQuote:
    """What opening a contract costs now, priced as :func:`open_option` charges it.

    ``per_share`` is the Black-Scholes value; ``premium`` is the charge for
    ``quantity`` contracts (x ``CONTRACT_MULTIPLIER``), rounded to cents.
    ``spot`` is the latest stored close, dated ``spot_at``; ``volatility`` is
    the annualised 30-day historical volatility used as the IV proxy.
    ``strike`` is the one priced: the caller's, or the spot rounded to cents.
    """

    ticker: str
    strike: Decimal
    spot: Decimal
    spot_at: datetime
    volatility: float
    per_share: Decimal
    premium: Decimal
    price: OptionPrice
    floored: bool = False
    """True when the model price was under :data:`MIN_PREMIUM_PER_SHARE`."""
    closes_used: int = 0
    """Daily closes behind ``volatility``."""
    volatility_method: str = "historical volatility of daily closes, 30 sessions, annualised"
    """Where ``volatility`` came from, in words (Phase 9.6: a chain's IV or historical)."""
    side: OptionSide = OptionSide.LONG
    risk: PositionRisk | None = None
    """Collateral, most it can lose and gain, and breakeven (Phase 9.2)."""


def quote_option(
    session: Session,
    *,
    ticker: str,
    option_type: OptionType,
    strike: Decimal | None,
    expiry: date_type,
    quantity: int = 1,
    side: OptionSide = OptionSide.LONG,
) -> OptionQuote:
    """Price an open without placing it (audit LG-7). Raises the open's errors.

    Without a ``strike`` the contract is priced at the money: the latest close
    rounded to cents.
    """
    if quantity <= 0:
        raise OptionTradeError("quantity must be a positive number of contracts")
    if strike is not None and strike <= 0:
        raise OptionTradeError("strike must be positive")

    ticker = ticker.upper()
    symbol = session.get(Symbol, ticker)
    if symbol is None:
        raise OptionSymbolNotFound(f"Symbol {ticker!r} not found")
    if symbol.currency != "USD":
        raise OptionTradeError("Options paper trading currently supports USD underlyings only")
    if ticker.startswith("^"):
        raise OptionTradeError(f"{ticker} is an index: options are on stocks only")

    today = _today()
    if expiry <= today:
        raise InvalidExpiry("expiry must be a future date")

    newest = session.exec(
        select(PriceBar)
        .where(PriceBar.instrument_id == instrument_of(ticker), PriceBar.interval == "1d")
        .order_by(PriceBar.ts.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()
    if newest is None:
        raise NoOptionMarketData(f"No market data for {ticker!r}; cannot price option")
    if strike is None:
        strike = newest.close.quantize(_CENTS)

    closes = _bar_closes(session, ticker)
    usable = usable_closes(closes)
    # Phase 9.6: the nearest listed contract's implied volatility from the
    # latest option-chain snapshot, else the 30-session historical figure.
    chain = chain_volatility(
        session, ticker, option_type=option_type.value, strike=strike, expiry=expiry, asof=today
    )
    if chain is not None:
        vol, vol_method = chain.volatility, chain.method
    else:
        if usable < MIN_VOL_CLOSES:
            raise NoOptionMarketData(
                f"{ticker} has {usable} daily closes in the last 30 sessions; "
                f"at least {MIN_VOL_CLOSES} are needed to estimate its volatility"
            )
        vol, vol_method = historical_volatility(closes), HISTORICAL_VOL_METHOD
    price = black_scholes(
        spot=float(newest.close),
        strike=float(strike),
        time_to_expiry_years=_years_to_expiry(expiry, asof=today),
        volatility=vol,
        risk_free_rate=RISK_FREE_RATE,
        option_type=option_type.value,
    )
    per_share = Decimal(str(price.value))
    floored = per_share < MIN_PREMIUM_PER_SHARE
    if floored:
        per_share = MIN_PREMIUM_PER_SHARE
    premium = (per_share * CONTRACT_MULTIPLIER * quantity).quantize(_CENTS)
    return OptionQuote(
        ticker=ticker,
        strike=strike,
        spot=newest.close,
        spot_at=newest.ts,
        volatility=vol,
        per_share=per_share,
        premium=premium,
        price=price,
        floored=floored,
        closes_used=usable,
        volatility_method=vol_method,
        side=side,
        risk=position_risk(
            side=side.value,
            option_type=option_type.value,
            strike=strike,
            premium=per_share,
            shares=Decimal(CONTRACT_MULTIPLIER * quantity),
            spot=newest.close,
        ),
    )


def implied_volatility_for(
    quote: OptionQuote, *, expiry: date_type, price: Decimal, option_type: OptionType
) -> ImpliedVolatility:
    """Solve the volatility that gives ``price`` per share on ``quote``'s inputs."""
    return implied_volatility(
        price=float(price),
        spot=float(quote.spot),
        strike=float(quote.strike),
        time_to_expiry_years=_years_to_expiry(expiry, asof=_today()),
        risk_free_rate=RISK_FREE_RATE,
        option_type=option_type.value,
    )


def open_option(
    session: Session,
    *,
    user_id: int,
    ticker: str,
    option_type: OptionType,
    strike: Decimal,
    expiry: date_type,
    quantity: int,
    client_order_id: str | None = None,
    side: OptionSide = OptionSide.LONG,
    book_id: int | None = None,
) -> OptionTradeResult:
    """Open ``quantity`` contracts: buy them (``side`` long) or write covered ones.

    A long open debits the premium. A short open (Phase 9.2) credits it and
    reserves the cover under the portfolio lock: a call needs that many
    available shares, a put its strike value in available cash. Short legs are for USD accounts only for now.

    With a ``client_order_id`` a repeat of the same open returns the first
    contract without charging again, and a repeat naming a different contract
    raises :class:`OptionOrderConflict` (audit LG-10). The lookup runs under
    the portfolio lock.
    """

    if quantity <= 0:
        raise OptionTradeError("quantity must be a positive number of contracts")
    if strike <= 0:
        raise OptionTradeError("strike must be positive")

    ticker = ticker.upper()
    if client_order_id is not None:
        earlier = _earlier_open(
            session, user_id=user_id, client_order_id=client_order_id, book_id=book_id
        )
        if earlier is not None:
            same = (
                earlier.ticker == ticker
                and earlier.option_type == option_type
                and earlier.strike == strike
                and earlier.expiry == expiry
                and earlier.quantity == quantity
                and earlier.side == side
            )
            if not same:
                raise OptionOrderConflict(
                    "This client_order_id was already used for a different option "
                    f"({earlier.quantity} {earlier.ticker} {earlier.option_type.value} "
                    f"{earlier.strike} {earlier.expiry.isoformat()})."
                )
            session.rollback()  # release the lock; nothing was written
            session.refresh(earlier)
            return OptionTradeResult(
                position=earlier, cash_delta=earlier.premium_paid * -position_sign(earlier)
            )

    quote = quote_option(
        session,
        ticker=ticker,
        option_type=option_type,
        strike=strike,
        expiry=expiry,
        quantity=quantity,
        side=side,
    )
    premium = quote.premium
    if side == OptionSide.SHORT:
        return _write_covered(
            session,
            user_id=user_id,
            ticker=ticker,
            option_type=option_type,
            strike=strike,
            expiry=expiry,
            quantity=quantity,
            premium=premium,
            client_order_id=client_order_id,
            book_id=book_id,
        )

    portfolio = resolve_book(session, user_id, book_id, write=True)
    assert portfolio.id is not None
    portfolio_id = portfolio.id
    portfolio = lock_portfolio(session, portfolio_id)
    # Phase 4.8: the premium is in USD (options are USD underlyings only). A
    # USD book pays it from its base cash; an INR book spends any USD cash it
    # holds first and converts the shortfall from rupees, as a stock buy does.
    base = base_currency(portfolio)
    try:
        spendable = available_cash(session, portfolio)
        rate = base_rate(session, "USD", base)
    except LookupError as exc:
        raise NoFxRateError(str(exc)) from exc
    funding = plan_buy(session, portfolio, "USD", premium, rate)
    if spendable < funding.base_debit:
        raise InsufficientCashForOption(
            f"Available buying power {base} {spendable:,.2f}; option premium "
            f"{base} {funding.base_debit:,.2f}."
        )

    from stockviz.services.risk.limits import enforce_option_open

    enforce_option_open(session, portfolio, base_debit=funding.base_debit)
    pay_for_buy(session, portfolio, "USD", funding, rate)
    position = OptionsPosition(
        user_id=user_id,
        portfolio_id=portfolio_id,
        ticker=ticker,
        option_type=option_type,
        strike=strike,
        expiry=expiry,
        quantity=quantity,
        premium_paid=premium,
        status=OptionStatus.OPEN,
        client_order_id=client_order_id,
    )
    session.add(portfolio)
    session.add(position)
    session.commit()
    session.refresh(position)
    return OptionTradeResult(position=position, cash_delta=-premium)


def _write_covered(
    session: Session,
    *,
    user_id: int,
    ticker: str,
    option_type: OptionType,
    strike: Decimal,
    expiry: date_type,
    quantity: int,
    premium: Decimal,
    client_order_id: str | None,
    book_id: int | None = None,
) -> OptionTradeResult:
    """Write a covered call or a cash-secured put: credit the premium, reserve the cover."""
    portfolio = resolve_book(session, user_id, book_id, write=True)
    assert portfolio.id is not None
    portfolio_id = portfolio.id
    portfolio = lock_portfolio(session, portfolio_id)
    if base_currency(portfolio) != "USD":
        raise OptionTradeError(
            "Writing options is available on USD accounts only for now; "
            "this account's base currency is " + base_currency(portfolio)
        )
    shares = Decimal(CONTRACT_MULTIPLIER * quantity)
    position = OptionsPosition(
        user_id=user_id,
        portfolio_id=portfolio_id,
        ticker=ticker,
        option_type=option_type,
        strike=strike,
        expiry=expiry,
        quantity=quantity,
        premium_paid=premium,
        status=OptionStatus.OPEN,
        client_order_id=client_order_id,
        side=OptionSide.SHORT,
    )
    if option_type == OptionType.CALL:
        free = available_shares(session, portfolio_id, ticker)
        if free < shares:
            raise InsufficientCoverForOption(
                f"A covered call on {quantity} contract(s) needs {shares:,.0f} {ticker} "
                f"shares that are not reserved; {free:,.0f} are available. "
                "Writing an uncovered call is not allowed."
            )
        position.cover = OptionCover.SHARES
    else:
        collateral = put_collateral_usd(position)
        try:
            spendable = available_cash(session, portfolio)
        except LookupError as exc:
            raise NoFxRateError(str(exc)) from exc
        # The premium is credited into cash, so it counts toward the cover; it
        # is never also left spendable (the full strike value stays reserved).
        if spendable + premium < collateral:
            raise InsufficientCoverForOption(
                f"A cash-secured put reserves USD {collateral:,.2f} (its strike value); "
                f"available buying power is USD {spendable:,.2f}."
            )
        from stockviz.services.risk.limits import enforce_option_open

        enforce_option_open(session, portfolio, base_debit=collateral)
        position.cover = OptionCover.CASH

    credit(session, portfolio, "USD", premium)
    session.add(portfolio)
    session.add(position)
    session.commit()
    session.refresh(position)
    return OptionTradeResult(position=position, cash_delta=premium)


def _earlier_open(
    session: Session, *, user_id: int, client_order_id: str, book_id: int | None = None
) -> OptionsPosition | None:
    """The open this key already placed, read under the portfolio lock."""
    portfolio = resolve_book(session, user_id, book_id, write=True)
    assert portfolio.id is not None
    lock_portfolio(session, portfolio.id)
    return session.exec(
        select(OptionsPosition).where(
            OptionsPosition.portfolio_id == portfolio.id,
            OptionsPosition.client_order_id == client_order_id,
        )
    ).first()


def close_option(session: Session, *, user_id: int, option_id: int) -> OptionTradeResult:
    """Sell a long position back, or buy a short one back, at its theoretical value.

    Buying back a short leg pays from available cash, counting the cash its
    own cover held back (a cash-secured put's collateral is released by the
    same close); its realized P&L is the premium received less that cost.
    """

    position = session.get(OptionsPosition, option_id)
    if position is None or position.user_id != user_id:
        raise OptionNotFound("Option position not found")
    if position.status != OptionStatus.OPEN:
        raise OptionTradeError(f"Option position is already {position.status.value}")
    if position.expiry < _today():
        raise OptionTradeError("This expired option is awaiting expiry settlement")
    if position.side == OptionSide.LONG:
        covers = session.exec(
            select(OptionsPosition).where(
                OptionsPosition.covering_leg_id == position.id,
                OptionsPosition.status == OptionStatus.OPEN,
            )
        ).first()
        if covers is not None:
            raise OptionTradeError(
                "This long leg covers an open short leg of the same strategy; buy the "
                "short leg back first, or close the whole strategy."
            )

    price = value_option(session, position)
    proceeds = (
        Decimal(str(price.value)) * position.shares_per_contract * position.quantity
    ).quantize(_CENTS)
    if proceeds < 0:
        proceeds = Decimal("0.00")

    assert position.portfolio_id is not None
    # A5.1: closing trades in the leg's own book, so it must be writable.
    book = session.get(Portfolio, position.portfolio_id)
    if book is not None:
        require_writable(book)
    portfolio = lock_portfolio(session, position.portfolio_id)
    session.refresh(position)
    if position.status != OptionStatus.OPEN:
        raise OptionTradeError(f"Option position is already {position.status.value}")

    if position.side == OptionSide.SHORT:
        return _buy_back(session, portfolio, position, cost=proceeds)

    # Proceeds are USD: a USD book's base cash, an INR book's USD balance.
    credit(session, portfolio, "USD", proceeds)
    position.status = OptionStatus.CLOSED
    position.settled_at = utcnow()
    _record_realization(position, proceeds=proceeds)
    session.add(portfolio)
    session.add(position)
    _refresh_strategy(session, position)
    session.commit()
    session.refresh(position)
    return OptionTradeResult(position=position, cash_delta=proceeds)


def _buy_back(
    session: Session, portfolio: Portfolio, position: OptionsPosition, *, cost: Decimal
) -> OptionTradeResult:
    """Close a short leg: pay ``cost`` (USD; short legs are USD accounts only)."""
    try:
        spendable = available_cash(session, portfolio, exclude_option_id=position.id)
    except LookupError as exc:
        raise NoFxRateError(str(exc)) from exc
    if spendable < cost:
        raise InsufficientCashForOption(
            f"Buying back this contract costs USD {cost:,.2f}; available buying power "
            f"is USD {spendable:,.2f}."
        )
    funding = plan_buy(session, portfolio, "USD", cost, Decimal(1))
    pay_for_buy(session, portfolio, "USD", funding, Decimal(1))
    position.status = OptionStatus.CLOSED
    position.settled_at = utcnow()
    _record_realization(position, proceeds=-cost, realized_pnl=position.premium_paid - cost)
    session.add(portfolio)
    session.add(position)
    _refresh_strategy(session, position)
    session.commit()
    session.refresh(position)
    return OptionTradeResult(position=position, cash_delta=-cost)


def _refresh_strategy(session: Session, position: OptionsPosition) -> None:
    from stockviz.services.options.strategies import refresh_strategy_status

    session.flush()
    refresh_strategy_status(session, position.strategy_id)


def _record_realization(
    position: OptionsPosition, *, proceeds: Decimal, realized_pnl: Decimal | None = None
) -> None:
    """Stamp the terminal-event accounting on a position leaving ``OPEN``.

    ``realized_pnl`` defaults to ``proceeds - premium_paid``, which is right
    for every event that settles a long contract in cash. Short legs always
    pass it: the premium was received, so it is ``premium - cost``. Exercise into (or
    against) the equity book overrides it — see ``docs/TRADING_JOURNAL.md``
    for why those two cases differ.
    """

    position.proceeds = proceeds.quantize(_MICROS)
    if realized_pnl is None:
        realized_pnl = proceeds - position.premium_paid
    position.realized_pnl = realized_pnl.quantize(_MICROS)


def _cash_settle(
    session: Session,
    portfolio: Portfolio,
    position: OptionsPosition,
    *,
    intrinsic: Decimal,
    why: str,
) -> None:
    credit(session, portfolio, "USD", intrinsic)
    _record_realization(position, proceeds=intrinsic)
    logger.info(
        "options_settle: %s %s cash-settled (%s) +%s",
        position.option_type.value,
        position.id,
        why,
        intrinsic,
    )


def _exercise_call_into_equity(
    session: Session, portfolio: Portfolio, position: OptionsPosition, *, spot: Decimal
) -> None:
    """ITM call: buy qty*100 shares at the strike through the equity fill path.

    ``apply_fill`` moves cash and shares, sets the average cost and writes the
    ``Trade`` row, as a market buy at the strike would (issue #62: exercise
    used to change positions directly and leave no trade). If available cash
    cannot cover the strike, ``apply_fill`` raises before changing anything
    and the intrinsic value is cash-settled instead.
    """
    shares = position.quantity * position.shares_per_contract
    try:
        apply_fill(
            session,
            portfolio=portfolio,
            ticker=position.ticker,
            side=TradeSide.BUY,
            quantity=shares,
            price=position.strike,
            currency="USD",  # options are USD underlyings only (open_option)
            fx_rate=base_rate(session, "USD", base_currency(portfolio)),
            check_limits=False,  # settlement is never refused by a limit
        )
    except InsufficientCash:
        intrinsic = ((spot - position.strike) * shares).quantize(_CENTS)
        _cash_settle(
            session, portfolio, position, intrinsic=intrinsic, why="insufficient cash to exercise"
        )
        return
    # Exercised into the equity book: the upside carries forward as a
    # strike-priced cost basis and is realized by a later sell, so the option
    # leg realizes only the sunk premium.
    _record_realization(position, proceeds=Decimal("0"), realized_pnl=-position.premium_paid)


def _exercise_put(
    session: Session, portfolio: Portfolio, position: OptionsPosition, *, spot: Decimal
) -> None:
    """ITM put: sell qty*100 held shares at the strike through the equity fill path.

    The sale writes a ``Trade`` with its own realized P&L, as a market sell at
    the strike would (#62), so the option leg realizes only the premium. If
    the portfolio does not hold enough available shares, ``apply_fill``
    raises before changing anything and the intrinsic value is cash-settled.
    """
    shares = position.quantity * position.shares_per_contract
    try:
        apply_fill(
            session,
            portfolio=portfolio,
            ticker=position.ticker,
            side=TradeSide.SELL,
            quantity=shares,
            price=position.strike,
            currency="USD",
            fx_rate=base_rate(session, "USD", base_currency(portfolio)),
        )
    except InsufficientPosition:
        intrinsic = ((position.strike - spot) * shares).quantize(_CENTS)
        _cash_settle(
            session, portfolio, position, intrinsic=intrinsic, why="not enough shares to deliver"
        )
        return
    _record_realization(position, proceeds=Decimal("0"), realized_pnl=-position.premium_paid)


def _assign_short(
    session: Session, portfolio: Portfolio, position: OptionsPosition, *, spot: Decimal
) -> None:
    """ITM short leg: assigned against its own cover through the equity fill path.

    A covered call sells its reserved shares at the strike; a cash-secured put
    buys the shares at the strike with its reserved cash. Each writes a
    ``Trade`` (#62), so the option leg realizes the premium received. The
    cover was reserved for exactly this, so a failure here means the ledger
    moved in a way the reservation should have stopped; the intrinsic value
    is then paid in cash rather than leaving the contract open.
    """
    shares = position.quantity * position.shares_per_contract
    call = position.option_type == OptionType.CALL
    try:
        apply_fill(
            session,
            portfolio=portfolio,
            ticker=position.ticker,
            side=TradeSide.SELL if call else TradeSide.BUY,
            quantity=shares,
            price=position.strike,
            currency="USD",
            fx_rate=base_rate(session, "USD", base_currency(portfolio)),
            check_limits=False,  # settlement is never refused by a limit
            exclude_option_id=position.id,
        )
    except (InsufficientCash, InsufficientPosition):
        intrinsic = ((spot - position.strike) if call else (position.strike - spot)) * shares
        intrinsic = intrinsic.quantize(_CENTS)
        logger.error(
            "options_settle: short %s %s could not be assigned against its cover; "
            "paying intrinsic %s",
            position.option_type.value,
            position.id,
            intrinsic,
        )
        funding = plan_buy(session, portfolio, "USD", intrinsic, Decimal(1))
        pay_for_buy(session, portfolio, "USD", funding, Decimal(1))
        _record_realization(
            position, proceeds=-intrinsic, realized_pnl=position.premium_paid - intrinsic
        )
        return
    _record_realization(position, proceeds=Decimal("0"), realized_pnl=position.premium_paid)


def _last_weekday_on_or_before(day: date_type) -> date_type:
    """The expiry session: the last New York session on or before ``day``.

    Holidays come from the exchange calendar since Phase 4.1 (options are USD
    underlyings only); the name predates that, when only weekends counted.
    """
    return session_on_or_before(day, NEW_YORK_VENUE)


def _expiry_close(session: Session, position: OptionsPosition) -> PriceBar | None:
    """The expiry session's closing bar, or None while it is not known (LG-3).

    The newest bar on or before expiry counts only if it is the expiry
    session: dated the last weekday on or before expiry, or older when a bar
    after expiry proves the market had moved on (a holiday on expiry day).
    Otherwise ingest has not stored the expiry session yet, and settling now
    would use an older close and could not be undone.
    """
    bar = session.exec(
        select(PriceBar)
        .where(
            PriceBar.instrument_id == instrument_of(position.ticker),
            PriceBar.interval == "1d",
            PriceBar.ts < datetime.combine(position.expiry + timedelta(days=1), time.min),
        )
        .order_by(col(PriceBar.ts).desc())
        .limit(1)
    ).first()
    if bar is None:
        return None
    if bar.ts.date() == _last_weekday_on_or_before(position.expiry):
        return bar
    later = session.exec(
        select(PriceBar.ts)
        .where(
            PriceBar.instrument_id == instrument_of(position.ticker),
            PriceBar.interval == "1d",
            PriceBar.ts >= datetime.combine(position.expiry + timedelta(days=1), time.min),
        )
        .limit(1)
    ).first()
    return bar if later is not None else None


def settle_expired_options(session: Session, *, settle_date: date_type) -> int:
    """Settle every open option whose expiry is on or before ``settle_date``.

    Returns the number of positions settled. Idempotent: only ``OPEN``
    positions are touched, and each is flipped to a terminal status.
    """

    newest_complete = latest_completed_session(utcnow().replace(tzinfo=UTC))
    from stockviz.services.options.strategies import (
        has_other_open_leg,
        settle_expired_strategies,
    )

    # Multi-leg strategies first, each as a unit (Phase 9.4).
    strategy_legs_settled = settle_expired_strategies(
        session, settle_date=settle_date, newest_complete=newest_complete
    )
    # A weekend expiry's session is the Friday before, so compare sessions.
    expired = [
        position
        for position in session.exec(
            select(OptionsPosition).where(
                OptionsPosition.status == OptionStatus.OPEN,
                OptionsPosition.expiry <= settle_date,
            )
        )
        if _last_weekday_on_or_before(position.expiry) <= newest_complete
    ]
    # Long legs settle before short ones (design note, section 5): a long
    # leg's exercise may bring in what a short leg then needs.
    expired.sort(key=lambda p: (p.side == OptionSide.SHORT, p.id or 0))
    # A leg whose strategy still has another open leg was left by the
    # strategy pass (its expiry close is not stored yet): it waits with it.
    expired = [p for p in expired if not has_other_open_leg(session, p)]
    settled = 0
    for position in expired:
        # Only the expiry session's close may settle a contract (LG-3).
        bar = _expiry_close(session, position)
        spot = bar.close if bar else None
        portfolio = session.get(Portfolio, position.portfolio_id)
        if spot is None or portfolio is None:
            # The expiry session's close is not stored yet: leave it for a later run.
            logger.warning(
                "options_settle: option %s waits for the %s close", position.id, position.expiry
            )
            continue
        assert portfolio.id is not None
        portfolio = lock_portfolio(session, portfolio.id)
        session.refresh(position)
        if position.status != OptionStatus.OPEN:
            continue

        if position.option_type == OptionType.CALL:
            in_the_money = spot > position.strike
        else:
            in_the_money = spot < position.strike

        short = position.side == OptionSide.SHORT
        if in_the_money and short:
            _assign_short(session, portfolio, position, spot=spot)
            position.status = OptionStatus.EXERCISED
        elif in_the_money:
            if position.option_type == OptionType.CALL:
                _exercise_call_into_equity(session, portfolio, position, spot=spot)
            else:
                _exercise_put(session, portfolio, position, spot=spot)
            position.status = OptionStatus.EXERCISED
        elif short:
            # Expired unexercised: the writer keeps the premium; the cover is released.
            _record_realization(position, proceeds=Decimal("0"), realized_pnl=position.premium_paid)
            position.status = OptionStatus.EXPIRED
        else:
            # Worthless at expiry: the premium is the whole loss.
            _record_realization(position, proceeds=Decimal("0"))
            position.status = OptionStatus.EXPIRED

        position.settled_at = utcnow()
        session.add(portfolio)
        session.add(position)
        _refresh_strategy(session, position)
        from stockviz.models import NotificationCategory
        from stockviz.services.notifications import notify

        notify(
            session,
            user_id=portfolio.user_id,
            category=NotificationCategory.OPTION,
            title=(
                f"{position.ticker} {position.strike:,.2f} {position.option_type.value} "
                f"{position.status.value}"
            ),
            body=(
                f"Settled on the {position.expiry.isoformat()} expiry at a {spot:,.2f} close; "
                f"realized {position.realized_pnl or 0:,.2f} USD."
            ),
            link="/portfolio?tab=options",
            source_key=f"option:{position.id}:settled",
        )
        session.commit()
        settled += 1
        logger.info("options_settle: option %s -> %s", position.id, position.status.value)

    return settled + strategy_legs_settled
