"""The options book: its Greeks and what each expiry brings (Phase 9.5).

**Greeks** are the position's, summed over open legs (a short leg's are the
contract's, negated), in money a user can read:

- ``delta_shares``: shares of the underlying the book moves like;
- ``dollar_delta``: that times the latest close (per underlying and in total);
- ``gamma_shares``: change in ``delta_shares`` for a $1 move;
- ``theta_per_day``: value lost (or gained) per calendar day, all else equal;
- ``vega_per_point``: change for 1 percentage point of volatility;
- ``rho_per_point``: change for 1 percentage point of the risk-free rate.

Totals across underlyings add money, not shares, so only the dollar figures
are summed for the whole book.

**Expirations** group open legs by expiry. A multi-leg strategy is one item;
any other leg is its own. Each item says what would happen if the stock
closed at today's price on that day, in the same terms as settlement, and
how much money is at risk (the most it can lose; for a covered call, the
shares, so no single figure).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date as date_type
from decimal import Decimal

from sqlmodel import Session, select

from stockviz.models import Portfolio
from stockviz.models.option import (
    OptionCover,
    OptionSide,
    OptionsPosition,
    OptionStatus,
    OptionType,
    position_sign,
)
from stockviz.models.option_strategy import OptionStrategy, StrategyKind
from stockviz.services.options.strategies import LABELS
from stockviz.services.options.trade import NoOptionMarketData, value_option
from stockviz.services.trading.portfolio import latest_close_map

_CENTS = Decimal("0.01")


@dataclass
class UnderlyingGreeks:
    ticker: str
    spot: Decimal
    delta_shares: float = 0.0
    gamma_shares: float = 0.0
    theta_per_day: float = 0.0
    vega_per_point: float = 0.0
    rho_per_point: float = 0.0

    @property
    def dollar_delta(self) -> float:
        return self.delta_shares * float(self.spot)


@dataclass(frozen=True, slots=True)
class ExpiryItem:
    label: str
    legs: list[str]
    at_risk: Decimal | None
    outcome: str
    """What happens at today's close, in words."""
    net_cash: Decimal | None
    """Cash the expiry would move at today's close (positive in), when it is cash."""
    strategy_id: int | None


@dataclass
class Book:
    underlyings: list[UnderlyingGreeks] = field(default_factory=list)
    expirations: list[tuple[date_type, list[ExpiryItem]]] = field(default_factory=list)
    unpriced: list[str] = field(default_factory=list)

    @property
    def dollar_delta(self) -> float:
        return sum(u.dollar_delta for u in self.underlyings)

    @property
    def theta_per_day(self) -> float:
        return sum(u.theta_per_day for u in self.underlyings)

    @property
    def vega_per_point(self) -> float:
        return sum(u.vega_per_point for u in self.underlyings)

    @property
    def rho_per_point(self) -> float:
        return sum(u.rho_per_point for u in self.underlyings)


def _shares(leg: OptionsPosition) -> Decimal:
    return leg.shares_per_contract * leg.quantity


def _intrinsic(leg: OptionsPosition, spot: Decimal) -> Decimal:
    per = spot - leg.strike if leg.option_type == OptionType.CALL else leg.strike - spot
    return (max(per, Decimal(0)) * _shares(leg)).quantize(_CENTS)


def _describe(leg: OptionsPosition) -> str:
    verb = "Long" if leg.side == OptionSide.LONG else "Short"
    return (
        f"{verb} {leg.quantity} {leg.ticker} {leg.strike:,.2f} {leg.option_type.value}"
        f" ({leg.expiry.isoformat()})"
    )


def _single_outcome(
    leg: OptionsPosition, spot: Decimal
) -> tuple[str, Decimal | None, Decimal | None]:
    """(outcome, net cash, money at risk) for a leg outside a multi-leg strategy."""
    shares = _shares(leg)
    itm = _intrinsic(leg, spot) > 0
    n = f"{shares:,.0f}"
    k = f"{leg.strike:,.2f}"
    if leg.side == OptionSide.LONG:
        at_risk = leg.premium_paid
        if not itm:
            return "Expires worthless; the premium is lost", Decimal(0), at_risk
        if leg.option_type == OptionType.CALL:
            return f"Exercised: {n} shares bought at {k}", -(leg.strike * shares), at_risk
        return (
            f"Exercised: {n} held shares sold at {k} (cash-settled if not held)",
            leg.strike * shares,
            at_risk,
        )
    if leg.cover == OptionCover.SHARES:
        if itm:
            return f"Assigned: the {n} reserved shares are sold at {k}", leg.strike * shares, None
        return "Expires; the premium is kept and the shares released", Decimal(0), None
    at_risk = max(leg.strike * shares - leg.premium_paid, Decimal(0))
    if itm:
        return (
            f"Assigned: {n} shares bought at {k} with the reserved cash",
            -(leg.strike * shares),
            at_risk,
        )
    return "Expires; the premium is kept and the cash released", Decimal(0), at_risk


def _strategy_outcome(
    legs: list[OptionsPosition], expiring: list[OptionsPosition], spot: Decimal
) -> tuple[str, Decimal]:
    later = [leg for leg in legs if leg not in expiring]
    if later:  # a calendar's near leg
        (short,) = expiring
        owed = _intrinsic(short, spot)
        if owed == 0:
            return "The near leg expires; the far leg stays open", Decimal(0)
        return f"The far leg is sold to pay {owed:,.2f} owed on the near leg", -owed
    net = sum((_intrinsic(leg, spot) * position_sign(leg) for leg in expiring), Decimal(0))
    return f"Settles in cash: net {net:+,.2f}", net


def options_book(session: Session, portfolio: Portfolio) -> Book:
    legs = list(
        session.exec(
            select(OptionsPosition)
            .where(
                OptionsPosition.portfolio_id == portfolio.id,
                OptionsPosition.status == OptionStatus.OPEN,
            )
            .order_by(OptionsPosition.expiry, OptionsPosition.id)  # type: ignore[arg-type]
        ).all()
    )
    book = Book()
    if not legs:
        return book
    spots = latest_close_map(session, sorted({leg.ticker for leg in legs}))
    by_ticker: dict[str, UnderlyingGreeks] = {}
    for leg in legs:
        spot = spots.get(leg.ticker)
        if spot is None:
            book.unpriced.append(_describe(leg))
            continue
        try:
            price = value_option(session, leg)
        except NoOptionMarketData:
            book.unpriced.append(_describe(leg))
            continue
        size = position_sign(leg) * float(_shares(leg))
        g = by_ticker.setdefault(leg.ticker, UnderlyingGreeks(leg.ticker, spot))
        g.delta_shares += price.delta * size
        g.gamma_shares += price.gamma * size
        g.theta_per_day += price.theta * size
        g.vega_per_point += price.vega * size / 100
        g.rho_per_point += price.rho * size / 100
    book.underlyings = sorted(by_ticker.values(), key=lambda u: u.ticker)

    strategies: dict[int, list[OptionsPosition]] = defaultdict(list)
    for leg in legs:
        if leg.strategy_id is not None:
            strategies[leg.strategy_id].append(leg)
    groups: dict[date_type, list[ExpiryItem]] = defaultdict(list)
    seen: set[int] = set()
    for leg in legs:
        spot = spots.get(leg.ticker)
        if spot is None:
            continue
        sid = leg.strategy_id
        if sid is not None and len(strategies[sid]) > 1:
            if sid in seen:
                continue
            seen.add(sid)
            group = strategies[sid]
            near = min(g.expiry for g in group)
            expiring = [g for g in group if g.expiry == near]
            strategy = session.get(OptionStrategy, sid)
            label = LABELS[StrategyKind(strategy.kind)] if strategy else "Strategy"
            outcome, net = _strategy_outcome(group, expiring, spot)
            groups[near].append(
                ExpiryItem(
                    label=label,
                    legs=[_describe(g) for g in group],
                    at_risk=strategy.max_loss if strategy else None,
                    outcome=outcome,
                    net_cash=net,
                    strategy_id=sid,
                )
            )
            continue
        outcome, net, at_risk = _single_outcome(leg, spot)
        groups[leg.expiry].append(
            ExpiryItem(
                label=_describe(leg),
                legs=[_describe(leg)],
                at_risk=at_risk,
                outcome=outcome,
                net_cash=net,
                strategy_id=sid,
            )
        )
    book.expirations = sorted(groups.items())
    return book
