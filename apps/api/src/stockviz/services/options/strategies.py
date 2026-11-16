"""Multi-leg option strategies from templates (Phase 9.3).

A template turns an underlying, an expiry (two for a calendar), strikes and a
number of contracts into legs. Every leg is priced the way a single open is
(``quote_option``), then the whole strategy opens in one transaction under
the portfolio lock: every leg or none. Short legs are always covered:

- covered call: by shares held, reserved;
- cash-secured put: by its strike value in cash, reserved;
- spreads, iron condors and calendars: by the long leg of the same type in the
  strategy (``cover = 'leg'``, ``covering_leg_id``), with the most the legs
  can cost at expiry held back as the strategy's ``collateral``.

``same_expiry_risk`` refuses any set of legs whose loss is unlimited, so no
template can leave a naked option. Strategies are for USD accounts only, as
writing a single leg is.

At expiry (batch 9.4) a multi-leg strategy settles as a unit, in cash:
every leg expiring that day is worth its intrinsic value at the expiry
session's close; long legs receive it, short legs pay it, and the strategy
moves the net once. Nothing is exercised into shares, so a spread never needs
cash or shares it does not hold back: the net it can owe is at most its
collateral. For a calendar the near (short) leg settles first: out of the
money it expires and the far leg stays open as a plain long option; in the
money the far leg is sold at its model value at that close and the short
leg's intrinsic value paid from the proceeds, closing both.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from decimal import Decimal

from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.models import Portfolio, Position
from stockviz.models.option import (
    CONTRACT_MULTIPLIER,
    OptionCover,
    OptionSide,
    OptionsPosition,
    OptionStatus,
    OptionType,
)
from stockviz.models.option_strategy import OptionStrategy, StrategyKind, StrategyStatus
from stockviz.services.instruments import instrument_of
from stockviz.services.options import margin
from stockviz.services.options.pricing import black_scholes, historical_volatility
from stockviz.services.options.trade import (
    RISK_FREE_RATE,
    InsufficientCashForOption,
    InsufficientCoverForOption,
    OptionNotFound,
    OptionOrderConflict,
    OptionQuote,
    OptionTradeError,
    _bar_closes,
    _expiry_close,
    _last_weekday_on_or_before,
    _record_realization,
    _today,
    quote_option,
    value_option,
)
from stockviz.services.trading.buying_power import available_cash, available_shares, lock_portfolio
from stockviz.services.trading.cash import base_currency, credit, pay_for_buy, plan_buy
from stockviz.services.trading.execute import NoFxRateError, ensure_default_portfolio

_CENTS = Decimal("0.01")

LONG, SHORT = OptionSide.LONG, OptionSide.SHORT
CALL, PUT = OptionType.CALL, OptionType.PUT

STRIKES_NEEDED: dict[StrategyKind, int] = {
    StrategyKind.COVERED_CALL: 1,
    StrategyKind.CASH_SECURED_PUT: 1,
    StrategyKind.PROTECTIVE_PUT: 1,
    StrategyKind.BULL_CALL: 2,
    StrategyKind.BEAR_PUT: 2,
    StrategyKind.BULL_PUT: 2,
    StrategyKind.BEAR_CALL: 2,
    StrategyKind.IRON_CONDOR: 4,
    StrategyKind.STRADDLE: 1,
    StrategyKind.STRANGLE: 2,
    StrategyKind.CALENDAR: 1,
}

LABELS: dict[StrategyKind, str] = {
    StrategyKind.COVERED_CALL: "Covered call",
    StrategyKind.CASH_SECURED_PUT: "Cash-secured put",
    StrategyKind.PROTECTIVE_PUT: "Protective put",
    StrategyKind.BULL_CALL: "Bull call spread",
    StrategyKind.BEAR_PUT: "Bear put spread",
    StrategyKind.BULL_PUT: "Bull put spread",
    StrategyKind.BEAR_CALL: "Bear call spread",
    StrategyKind.IRON_CONDOR: "Iron condor",
    StrategyKind.STRADDLE: "Straddle",
    StrategyKind.STRANGLE: "Strangle",
    StrategyKind.CALENDAR: "Calendar spread",
}


@dataclass(frozen=True, slots=True)
class LegPlan:
    side: OptionSide
    option_type: OptionType
    strike: Decimal
    expiry: date_type
    covered_by: int | None = None
    """Index of the long leg that covers this short one (spreads, calendars).
    It is always an earlier leg, so the long leg exists when the short is written."""


@dataclass(frozen=True, slots=True)
class StrategyQuote:
    kind: StrategyKind
    ticker: str
    quantity: int
    legs: list[tuple[LegPlan, OptionQuote]]
    risk: margin.StrategyRisk
    shares_reserved: Decimal
    """Shares a covered call holds back; shares a protective put needs held."""


@dataclass(frozen=True, slots=True)
class StrategyResult:
    strategy: OptionStrategy
    legs: list[OptionsPosition]
    cash_delta: Decimal


def plan_legs(
    kind: StrategyKind,
    *,
    strikes: list[Decimal],
    expiry: date_type,
    far_expiry: date_type | None = None,
    option_type: OptionType | None = None,
) -> list[LegPlan]:
    """The legs a template makes. Strikes are given low to high."""
    needed = STRIKES_NEEDED[kind]
    if len(strikes) != needed:
        raise OptionTradeError(f"{LABELS[kind]} takes {needed} strike(s), got {len(strikes)}")
    if any(k <= 0 for k in strikes):
        raise OptionTradeError("strikes must be positive")
    if list(strikes) != sorted(strikes) or len(set(strikes)) != len(strikes):
        raise OptionTradeError("strikes must be different and given from low to high")
    k = strikes
    e = expiry
    match kind:
        case StrategyKind.COVERED_CALL:
            return [LegPlan(SHORT, CALL, k[0], e)]
        case StrategyKind.CASH_SECURED_PUT:
            return [LegPlan(SHORT, PUT, k[0], e)]
        case StrategyKind.PROTECTIVE_PUT:
            return [LegPlan(LONG, PUT, k[0], e)]
        case StrategyKind.BULL_CALL:
            return [LegPlan(LONG, CALL, k[0], e), LegPlan(SHORT, CALL, k[1], e, covered_by=0)]
        case StrategyKind.BEAR_PUT:
            return [LegPlan(LONG, PUT, k[1], e), LegPlan(SHORT, PUT, k[0], e, covered_by=0)]
        case StrategyKind.BULL_PUT:
            return [LegPlan(LONG, PUT, k[0], e), LegPlan(SHORT, PUT, k[1], e, covered_by=0)]
        case StrategyKind.BEAR_CALL:
            return [LegPlan(LONG, CALL, k[1], e), LegPlan(SHORT, CALL, k[0], e, covered_by=0)]
        case StrategyKind.IRON_CONDOR:
            # Each long leg is listed before the short leg it covers.
            return [
                LegPlan(LONG, PUT, k[0], e),
                LegPlan(SHORT, PUT, k[1], e, covered_by=0),
                LegPlan(LONG, CALL, k[3], e),
                LegPlan(SHORT, CALL, k[2], e, covered_by=2),
            ]
        case StrategyKind.STRADDLE:
            return [LegPlan(LONG, CALL, k[0], e), LegPlan(LONG, PUT, k[0], e)]
        case StrategyKind.STRANGLE:
            return [LegPlan(LONG, PUT, k[0], e), LegPlan(LONG, CALL, k[1], e)]
        case StrategyKind.CALENDAR:
            if far_expiry is None or far_expiry <= expiry:
                raise OptionTradeError("a calendar needs a far expiry after the near one")
            if option_type is None:
                raise OptionTradeError("a calendar needs option_type (call or put)")
            return [
                LegPlan(LONG, option_type, k[0], far_expiry),
                LegPlan(SHORT, option_type, k[0], expiry, covered_by=0),
            ]
    raise OptionTradeError(f"unknown strategy {kind}")


def quote_strategy(
    session: Session,
    *,
    kind: StrategyKind,
    ticker: str,
    strikes: list[Decimal],
    expiry: date_type,
    quantity: int,
    far_expiry: date_type | None = None,
    option_type: OptionType | None = None,
) -> StrategyQuote:
    """Price every leg as an open would and work out the strategy's figures."""
    if quantity <= 0:
        raise OptionTradeError("quantity must be a positive number of contracts")
    plans = plan_legs(
        kind, strikes=strikes, expiry=expiry, far_expiry=far_expiry, option_type=option_type
    )
    quoted = [
        (
            plan,
            quote_option(
                session,
                ticker=ticker,
                option_type=plan.option_type,
                strike=plan.strike,
                expiry=plan.expiry,
                quantity=quantity,
                side=plan.side,
            ),
        )
        for plan in plans
    ]
    shares = Decimal(CONTRACT_MULTIPLIER * quantity)
    spot = quoted[0][1].spot
    shares_reserved = Decimal(0)
    if kind in (
        StrategyKind.COVERED_CALL,
        StrategyKind.CASH_SECURED_PUT,
        StrategyKind.PROTECTIVE_PUT,
    ):
        plan, q = quoted[0]
        leg_fn = {
            StrategyKind.COVERED_CALL: margin.covered_call,
            StrategyKind.PROTECTIVE_PUT: margin.protective_put,
        }
        if kind == StrategyKind.CASH_SECURED_PUT:
            one = margin.cash_secured_put(strike=plan.strike, premium=q.per_share, shares=shares)
        else:
            one = leg_fn[kind](strike=plan.strike, premium=q.per_share, shares=shares, spot=spot)
        shares_reserved = shares if kind != StrategyKind.CASH_SECURED_PUT else Decimal(0)
        sign = 1 if plan.side == SHORT else -1
        risk = margin.StrategyRisk(
            net_premium=(q.premium * sign).quantize(_CENTS),
            collateral=one.collateral,
            max_loss=one.max_loss,
            max_gain=one.max_gain,
            breakevens=(one.breakeven,),
            basis=one.basis,
        )
    elif kind == StrategyKind.CALENDAR:
        (far_plan, far_q), (near_plan, near_q) = quoted
        years = (far_plan.expiry - near_plan.expiry).days / 365.0
        risk = margin.calendar_risk(
            option_type=near_plan.option_type.value,
            strike=near_plan.strike,
            shares=shares,
            near_premium=near_q.per_share,
            far_premium=far_q.per_share,
            years_between=years,
            rate=RISK_FREE_RATE,
        )
    else:
        legs = [
            margin.LegSpec(
                side=plan.side.value,
                option_type=plan.option_type.value,
                strike=plan.strike,
                shares=shares,
                premium=q.per_share,
            )
            for plan, q in quoted
        ]
        try:
            risk = margin.same_expiry_risk(legs, basis=f"{LABELS[kind].lower()} at expiry")
        except ValueError as exc:
            raise OptionTradeError(str(exc)) from exc
    return StrategyQuote(
        kind=kind,
        ticker=quoted[0][1].ticker,
        quantity=quantity,
        legs=quoted,
        risk=risk,
        shares_reserved=shares_reserved,
    )


def open_strategy(
    session: Session,
    *,
    user_id: int,
    kind: StrategyKind,
    ticker: str,
    strikes: list[Decimal],
    expiry: date_type,
    quantity: int,
    far_expiry: date_type | None = None,
    option_type: OptionType | None = None,
    client_order_id: str | None = None,
) -> StrategyResult:
    """Open every leg of a template in one transaction, or none.

    The account must be able to pay the net debit and still hold back the
    collateral (for a credit, the credit counts toward it: it is cash in the
    account). The most the strategy can lose is checked against the
    single-order limit (Phase 8.5).
    """
    ticker = ticker.upper()
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    portfolio_id = portfolio.id
    if client_order_id is not None:
        lock_portfolio(session, portfolio_id)
        earlier = session.exec(
            select(OptionStrategy).where(
                OptionStrategy.portfolio_id == portfolio_id,
                OptionStrategy.client_order_id == client_order_id,
            )
        ).first()
        if earlier is not None:
            legs = _legs(session, earlier)
            same = earlier.kind == kind and sorted({leg.strike for leg in legs}) == sorted(
                set(strikes)
            )
            if not same:
                raise OptionOrderConflict(
                    "This client_order_id was already used for a different strategy."
                )
            session.rollback()
            return StrategyResult(strategy=earlier, legs=legs, cash_delta=earlier.net_premium)

    quote = quote_strategy(
        session,
        kind=kind,
        ticker=ticker,
        strikes=strikes,
        expiry=expiry,
        quantity=quantity,
        far_expiry=far_expiry,
        option_type=option_type,
    )
    risk = quote.risk
    portfolio = lock_portfolio(session, portfolio_id)
    if base_currency(portfolio) != "USD":
        raise OptionTradeError(
            "Option strategies are available on USD accounts only for now; this account's "
            "base currency is " + base_currency(portfolio)
        )
    shares = Decimal(CONTRACT_MULTIPLIER * quantity)
    if kind == StrategyKind.COVERED_CALL:
        free = available_shares(session, portfolio_id, ticker)
        if free < shares:
            raise InsufficientCoverForOption(
                f"A covered call on {quantity} contract(s) needs {shares:,.0f} {ticker} shares "
                f"that are not reserved; {free:,.0f} are available."
            )
    if kind == StrategyKind.PROTECTIVE_PUT:
        held = session.exec(
            select(Position).where(
                Position.portfolio_id == portfolio_id,
                Position.instrument_id == instrument_of(ticker),
            )
        ).first()
        if held is None or held.quantity < shares:
            raise InsufficientCoverForOption(
                f"A protective put on {quantity} contract(s) protects {shares:,.0f} {ticker} "
                "shares; hold them first, or buy the put on its own."
            )
    held_back = risk.collateral  # the CSP's strike value or a spread's collateral
    try:
        spendable = available_cash(session, portfolio)
    except LookupError as exc:
        raise NoFxRateError(str(exc)) from exc
    if spendable + risk.net_premium < held_back:
        raise InsufficientCashForOption(
            f"This {LABELS[kind].lower()} needs USD {held_back - risk.net_premium:,.2f} of "
            f"buying power (net premium {risk.net_premium:+,.2f}, held back "
            f"{held_back:,.2f}); available is USD {spendable:,.2f}."
        )
    from stockviz.services.risk.limits import enforce_option_open

    enforce_option_open(session, portfolio, base_debit=risk.max_loss, what="strategy's most loss")

    if risk.net_premium >= 0:
        credit(session, portfolio, "USD", risk.net_premium)
    else:
        funding = plan_buy(session, portfolio, "USD", -risk.net_premium, Decimal(1))
        pay_for_buy(session, portfolio, "USD", funding, Decimal(1))

    strategy = OptionStrategy(
        user_id=user_id,
        portfolio_id=portfolio_id,
        kind=kind.value,
        status=StrategyStatus.OPEN.value,
        net_premium=risk.net_premium,
        # A cash-secured put reserves through its leg; spreads through this.
        collateral=held_back if kind != StrategyKind.CASH_SECURED_PUT else Decimal(0),
        max_loss=risk.max_loss,
        max_gain=risk.max_gain,
        client_order_id=client_order_id,
    )
    session.add(strategy)
    session.flush()
    rows: list[OptionsPosition] = []
    for plan, q in quote.legs:  # long legs come before the short legs they cover
        cover: OptionCover | None = None
        covering: int | None = None
        if plan.side == SHORT:
            if plan.covered_by is not None:
                cover, covering = OptionCover.LEG, rows[plan.covered_by].id
            elif plan.option_type == CALL:
                cover = OptionCover.SHARES
            else:
                cover = OptionCover.CASH
        row = OptionsPosition(
            user_id=user_id,
            portfolio_id=portfolio_id,
            ticker=quote.ticker,
            option_type=plan.option_type,
            strike=plan.strike,
            expiry=plan.expiry,
            quantity=quantity,
            premium_paid=q.premium,
            status=OptionStatus.OPEN,
            side=plan.side,
            cover=cover,
            covering_leg_id=covering,
            strategy_id=strategy.id,
        )
        session.add(row)
        session.flush()
        rows.append(row)
    session.add(portfolio)
    session.commit()
    for row in rows:
        session.refresh(row)
    session.refresh(strategy)
    return StrategyResult(strategy=strategy, legs=rows, cash_delta=risk.net_premium)


def _legs(session: Session, strategy: OptionStrategy) -> list[OptionsPosition]:
    return list(
        session.exec(
            select(OptionsPosition)
            .where(OptionsPosition.strategy_id == strategy.id)
            .order_by(OptionsPosition.id)  # type: ignore[arg-type]
        ).all()
    )


def strategy_legs(session: Session, strategy: OptionStrategy) -> list[OptionsPosition]:
    """Every leg of ``strategy``, in the order they were opened."""
    return _legs(session, strategy)


def close_strategy(session: Session, *, user_id: int, strategy_id: int) -> StrategyResult:
    """Close every open leg at its model value as one unit.

    Long legs are sold, short legs bought back; the net is paid or credited
    once. A net cost may use the cash the strategy itself held back.
    """
    strategy = session.get(OptionStrategy, strategy_id)
    if strategy is None or strategy.user_id != user_id:
        raise OptionNotFound("Strategy not found")
    if strategy.status != StrategyStatus.OPEN:
        raise OptionTradeError(f"This strategy is already {strategy.status}")
    legs = [leg for leg in _legs(session, strategy) if leg.status == OptionStatus.OPEN]
    if any(leg.expiry < _today() for leg in legs):
        raise OptionTradeError("A leg has expired and is awaiting expiry settlement")
    values: list[tuple[OptionsPosition, Decimal]] = []
    for leg in legs:
        price = value_option(session, leg)
        amount = (Decimal(str(price.value)) * leg.shares_per_contract * leg.quantity).quantize(
            _CENTS
        )
        values.append((leg, max(amount, Decimal(0))))
    net = sum(((amount if leg.side == LONG else -amount) for leg, amount in values), Decimal(0))
    portfolio = lock_portfolio(session, strategy.portfolio_id)
    session.refresh(strategy)
    if strategy.status != StrategyStatus.OPEN:
        raise OptionTradeError(f"This strategy is already {strategy.status}")
    if net < 0:
        spendable = available_cash(session, portfolio, exclude_strategy_id=strategy.id)
        if spendable < -net:
            raise InsufficientCashForOption(
                f"Closing this strategy costs USD {-net:,.2f}; available buying power is "
                f"USD {spendable:,.2f}."
            )
        funding = plan_buy(session, portfolio, "USD", -net, Decimal(1))
        pay_for_buy(session, portfolio, "USD", funding, Decimal(1))
    else:
        credit(session, portfolio, "USD", net)
    now = utcnow()
    for leg, amount in values:
        leg.status = OptionStatus.CLOSED
        leg.settled_at = now
        if leg.side == LONG:
            _record_realization(leg, proceeds=amount)
        else:
            _record_realization(leg, proceeds=-amount, realized_pnl=leg.premium_paid - amount)
        session.add(leg)
    strategy.status = StrategyStatus.CLOSED.value
    strategy.settled_at = now
    session.add(strategy)
    session.add(portfolio)
    session.commit()
    session.refresh(strategy)
    return StrategyResult(strategy=strategy, legs=_legs(session, strategy), cash_delta=net)


def refresh_strategy_status(session: Session, strategy_id: int | None) -> None:
    """Mark a strategy closed or settled once none of its legs is open (staged, no commit)."""
    if strategy_id is None:
        return
    strategy = session.get(OptionStrategy, strategy_id)
    if strategy is None or strategy.status != StrategyStatus.OPEN:
        return
    legs = _legs(session, strategy)
    if any(leg.status == OptionStatus.OPEN for leg in legs):
        return
    settled = any(leg.status in (OptionStatus.EXERCISED, OptionStatus.EXPIRED) for leg in legs)
    strategy.status = (StrategyStatus.SETTLED if settled else StrategyStatus.CLOSED).value
    strategy.settled_at = utcnow()
    session.add(strategy)


def has_other_open_leg(session: Session, position: OptionsPosition) -> bool:
    """True while another leg of ``position``'s strategy is open: the strategy
    settles it, not the single-leg path."""
    if position.strategy_id is None:
        return False
    other = session.exec(
        select(OptionsPosition.id).where(
            OptionsPosition.strategy_id == position.strategy_id,
            OptionsPosition.status == OptionStatus.OPEN,
            OptionsPosition.id != position.id,
        )
    ).first()
    return other is not None


def _intrinsic(leg: OptionsPosition, spot: Decimal) -> Decimal:
    per_share = spot - leg.strike if leg.option_type == CALL else leg.strike - spot
    return (max(per_share, Decimal(0)) * leg.shares_per_contract * leg.quantity).quantize(_CENTS)


def settle_expired_strategies(
    session: Session, *, settle_date: date_type, newest_complete: date_type
) -> int:
    """Settle multi-leg strategies whose nearest open leg has expired. Returns legs settled.

    Waits, like a single leg (LG-3), until the expiry session's close is stored.
    Each strategy commits on its own.
    """
    candidates = session.exec(
        select(OptionStrategy).where(OptionStrategy.status == StrategyStatus.OPEN)
    ).all()
    settled = 0
    for strategy in candidates:
        legs = [leg for leg in _legs(session, strategy) if leg.status == OptionStatus.OPEN]
        if len(legs) < 2:
            continue  # a one-leg strategy (or what is left of a calendar) settles as a leg
        near = min(leg.expiry for leg in legs)
        if near > settle_date or _last_weekday_on_or_before(near) > newest_complete:
            continue
        expiring = [leg for leg in legs if leg.expiry == near]
        bar = _expiry_close(session, expiring[0])
        if bar is None:
            continue  # the expiry close is not stored yet
        portfolio = lock_portfolio(session, strategy.portfolio_id)
        session.refresh(strategy)
        if strategy.status != StrategyStatus.OPEN:
            continue
        later = [leg for leg in legs if leg.expiry != near]
        if later:
            settled += _settle_calendar(session, portfolio, strategy, expiring, later, bar.close)
        else:
            settled += _settle_in_cash(session, portfolio, strategy, expiring, bar.close)
        refresh_strategy_status(session, strategy.id)
        session.commit()
    return settled


def _settle_in_cash(
    session: Session,
    portfolio: Portfolio,
    strategy: OptionStrategy,
    legs: list[OptionsPosition],
    spot: Decimal,
) -> int:
    """Every leg at intrinsic value; the net moves once."""
    now = utcnow()
    net = Decimal(0)
    for leg in legs:
        value = _intrinsic(leg, spot)
        leg.status = OptionStatus.EXERCISED if value > 0 else OptionStatus.EXPIRED
        leg.settled_at = now
        if leg.side == LONG:
            net += value
            _record_realization(leg, proceeds=value)
        else:
            net -= value
            _record_realization(leg, proceeds=-value, realized_pnl=leg.premium_paid - value)
        session.add(leg)
    _move(session, portfolio, net)
    _notify(session, portfolio, strategy, spot, net, legs[0].expiry)
    return len(legs)


def _settle_calendar(
    session: Session,
    portfolio: Portfolio,
    strategy: OptionStrategy,
    near: list[OptionsPosition],
    far: list[OptionsPosition],
    spot: Decimal,
) -> int:
    """The near short leg expires; in the money, the far leg is sold to pay it."""
    now = utcnow()
    (short,) = near
    owed = _intrinsic(short, spot)
    short.settled_at = now
    if owed == 0:
        short.status = OptionStatus.EXPIRED
        _record_realization(short, proceeds=Decimal(0), realized_pnl=short.premium_paid)
        session.add(short)
        _notify(session, portfolio, strategy, spot, Decimal(0), short.expiry)
        return 1
    short.status = OptionStatus.EXERCISED
    _record_realization(short, proceeds=-owed, realized_pnl=short.premium_paid - owed)
    session.add(short)
    net = -owed
    closes = _bar_closes(session, short.ticker)
    vol = historical_volatility(closes)
    for leg in far:
        years = max((leg.expiry - short.expiry).days / 365.0, 0.0)
        per_share = black_scholes(
            spot=float(spot),
            strike=float(leg.strike),
            time_to_expiry_years=years,
            volatility=vol,
            risk_free_rate=RISK_FREE_RATE,
            option_type=leg.option_type.value,
        ).value
        value = (Decimal(str(per_share)) * leg.shares_per_contract * leg.quantity).quantize(_CENTS)
        leg.status = OptionStatus.CLOSED
        leg.settled_at = now
        _record_realization(leg, proceeds=value)
        session.add(leg)
        net += value
    _move(session, portfolio, net)
    _notify(session, portfolio, strategy, spot, net, short.expiry)
    return 1 + len(far)


def _move(session: Session, portfolio: Portfolio, net: Decimal) -> None:
    if net > 0:
        credit(session, portfolio, "USD", net)
    elif net < 0:
        funding = plan_buy(session, portfolio, "USD", -net, Decimal(1))
        pay_for_buy(session, portfolio, "USD", funding, Decimal(1))
    session.add(portfolio)


def _notify(
    session: Session,
    portfolio: Portfolio,
    strategy: OptionStrategy,
    spot: Decimal,
    net: Decimal,
    expiry: date_type,
) -> None:
    from stockviz.models import NotificationCategory
    from stockviz.services.notifications import notify

    label = LABELS[StrategyKind(strategy.kind)]
    notify(
        session,
        user_id=portfolio.user_id,
        category=NotificationCategory.OPTION,
        title=f"{label} settled",
        body=(
            f"Settled on the {expiry.isoformat()} expiry at a {spot:,.2f} close; "
            f"net {net:+,.2f} USD."
        ),
        link="/portfolio?tab=options",
        source_key=f"strategy:{strategy.id}:settled:{expiry.isoformat()}",
    )


__all__ = [
    "LABELS",
    "STRIKES_NEEDED",
    "LegPlan",
    "StrategyQuote",
    "StrategyResult",
    "close_strategy",
    "has_other_open_leg",
    "open_strategy",
    "plan_legs",
    "quote_strategy",
    "refresh_strategy_status",
    "settle_expired_strategies",
    "strategy_legs",
]
