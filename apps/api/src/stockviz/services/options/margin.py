"""What an option position can lose and must hold back (Phase 9.2).

Pure functions over per-share figures, so the quote, the open and the hand
check all agree. Every figure is for the whole position: ``shares`` is
contracts x shares per contract. Amounts are in the premium's currency (USD).

``collateral`` is what the open reserves on top of what it pays:

- a long call or put reserves nothing (its premium is paid and is the most it
  can lose);
- a covered call reserves the shares (no cash): ``collateral`` is 0 and
  ``shares_reserved`` is the share count;
- a cash-secured put reserves its full strike value, what assignment costs.
  Its most it can lose is that less the premium; the premium itself is in
  cash and spendable, so it is not netted off the reservation (netting it
  would let the premium be spent twice).

``max_gain`` is ``None`` when it is unbounded (a long call). A covered call's
figures are measured from ``spot``, the price the shares are worth now.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_UP, Decimal
from itertools import pairwise

CENTS = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class PositionRisk:
    collateral: Decimal
    shares_reserved: Decimal
    max_loss: Decimal
    max_gain: Decimal | None
    breakeven: Decimal
    """Underlying price at expiry where the position neither gains nor loses."""
    basis: str
    """How the figures are measured, in words."""


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENTS)


def long_option(
    *, option_type: str, strike: Decimal, premium: Decimal, shares: Decimal
) -> PositionRisk:
    """A bought call or put: the premium is the most it can lose."""
    total = premium * shares
    if option_type == "call":
        return PositionRisk(
            collateral=Decimal(0),
            shares_reserved=Decimal(0),
            max_loss=_q(total),
            max_gain=None,
            breakeven=_q(strike + premium),
            basis="long call: loss limited to the premium, gain unlimited",
        )
    return PositionRisk(
        collateral=Decimal(0),
        shares_reserved=Decimal(0),
        max_loss=_q(total),
        max_gain=_q(max(strike - premium, Decimal(0)) * shares),
        breakeven=_q(strike - premium),
        basis="long put: loss limited to the premium, gain if the stock falls to 0",
    )


def covered_call(
    *, strike: Decimal, premium: Decimal, shares: Decimal, spot: Decimal
) -> PositionRisk:
    """Shares held plus a written call on them, measured from today's ``spot``."""
    return PositionRisk(
        collateral=Decimal(0),
        shares_reserved=shares,
        max_loss=_q(max(spot - premium, Decimal(0)) * shares),
        max_gain=_q((strike - spot + premium) * shares),
        breakeven=_q(spot - premium),
        basis=(
            "covered call from today's close: the shares are reserved; the most it "
            "can lose is the shares falling to 0, less the premium; gains stop at the strike"
        ),
    )


def protective_put(
    *, strike: Decimal, premium: Decimal, shares: Decimal, spot: Decimal
) -> PositionRisk:
    """Shares held plus a bought put on them, measured from today's ``spot``."""
    return PositionRisk(
        collateral=Decimal(0),
        shares_reserved=Decimal(0),
        max_loss=_q(max(spot - strike + premium, Decimal(0)) * shares),
        max_gain=None,
        breakeven=_q(spot + premium),
        basis=(
            "protective put from today's close: the shares can fall no lower than the "
            "strike before the put pays, so the most it can lose is the drop to the "
            "strike plus the premium; gains are the shares' less the premium"
        ),
    )


def cash_secured_put(*, strike: Decimal, premium: Decimal, shares: Decimal) -> PositionRisk:
    """A written put with its strike value held back in cash."""
    return PositionRisk(
        collateral=_q(strike * shares),
        shares_reserved=Decimal(0),
        max_loss=_q(max(strike - premium, Decimal(0)) * shares),
        max_gain=_q(premium * shares),
        breakeven=_q(strike - premium),
        basis=(
            "cash-secured put: the strike value is reserved; the most it can lose is that "
            "less the premium (assigned with the stock at 0); the premium is the most it can gain"
        ),
    )


def position_risk(
    *,
    side: str,
    option_type: str,
    strike: Decimal,
    premium: Decimal,
    shares: Decimal,
    spot: Decimal,
) -> PositionRisk:
    """The figures for one leg. A short call is covered by shares, a short put by cash."""
    if side == "long":
        return long_option(option_type=option_type, strike=strike, premium=premium, shares=shares)
    if option_type == "call":
        return covered_call(strike=strike, premium=premium, shares=shares, spot=spot)
    return cash_secured_put(strike=strike, premium=premium, shares=shares)


# ---------------------------------------------------------------------------
# Strategies (Phase 9.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LegSpec:
    """One leg for the payoff maths: ``shares`` is contracts x shares per contract."""

    side: str  # "long" | "short"
    option_type: str  # "call" | "put"
    strike: Decimal
    shares: Decimal
    premium: Decimal  # per share, as priced


@dataclass(frozen=True, slots=True)
class StrategyRisk:
    net_premium: Decimal
    """Whole strategy, positive when credited."""
    collateral: Decimal
    """Cash held back while open: the most the legs can cost at expiry, premiums aside."""
    max_loss: Decimal
    max_gain: Decimal | None
    breakevens: tuple[Decimal, ...]
    basis: str


def _intrinsic(leg: LegSpec, spot: Decimal) -> Decimal:
    if leg.option_type == "call":
        value = max(spot - leg.strike, Decimal(0))
    else:
        value = max(leg.strike - spot, Decimal(0))
    signed = value if leg.side == "long" else -value
    return signed * leg.shares


def expiry_payoff(legs: list[LegSpec], spot: Decimal, *, with_premium: bool = True) -> Decimal:
    """Value of the legs at a common expiry with the stock at ``spot``, in money."""
    total = sum((_intrinsic(leg, spot) for leg in legs), Decimal(0))
    if with_premium:
        total += net_premium(legs)
    return total


def net_premium(legs: list[LegSpec]) -> Decimal:
    """Premiums received less premiums paid, for the whole strategy."""
    return sum(
        ((leg.premium if leg.side == "short" else -leg.premium) * leg.shares for leg in legs),
        Decimal(0),
    )


def _upper_slope(legs: list[LegSpec]) -> Decimal:
    """Payoff change per $1 of stock beyond the highest strike (calls only move it)."""
    return sum(
        ((leg.shares if leg.side == "long" else -leg.shares) for leg in legs
         if leg.option_type == "call"),
        Decimal(0),
    )  # fmt: skip


def same_expiry_risk(legs: list[LegSpec], *, basis: str) -> StrategyRisk:
    """Exact figures for legs that share one expiry: the payoff is piecewise
    linear between strikes, so its extremes are at 0, at a strike, or at
    infinity, and its breakevens are where a segment crosses zero.

    Raises ``ValueError`` when the loss is unbounded as the stock rises: a
    short call no long call covers. That is a naked option.
    """
    slope = _upper_slope(legs)
    if slope < 0:
        raise ValueError("a short call is not covered: the loss would be unlimited")
    points = sorted({Decimal(0), *(leg.strike for leg in legs)})
    with_prem = [expiry_payoff(legs, p) for p in points]
    without = [expiry_payoff(legs, p, with_premium=False) for p in points]
    breakevens: list[Decimal] = []
    pairs = list(zip(points, with_prem, strict=True))
    for (a, va), (b, vb) in pairwise(pairs):
        if va == 0:
            breakevens.append(a)
        elif (va < 0 < vb) or (vb < 0 < va):
            breakevens.append(a + (b - a) * (-va) / (vb - va))
    last, v_last = points[-1], with_prem[-1]
    if v_last == 0 and last not in breakevens:
        breakevens.append(last)
    elif slope > 0 and v_last < 0:
        breakevens.append(last + (-v_last) / slope)
    max_gain = None if slope > 0 else max(with_prem)
    return StrategyRisk(
        net_premium=_q(net_premium(legs)),
        collateral=_q(max(Decimal(0), -min(without))),
        max_loss=_q(max(Decimal(0), -min(with_prem))),
        max_gain=None if max_gain is None else _q(max_gain),
        breakevens=tuple(_q(b) for b in breakevens),
        basis=basis,
    )


def calendar_risk(
    *,
    option_type: str,
    strike: Decimal,
    shares: Decimal,
    near_premium: Decimal,
    far_premium: Decimal,
    years_between: float,
    rate: float,
) -> StrategyRisk:
    """Short the near expiry, long the far one, same strike.

    At the near expiry the long leg is still worth at least the short leg's
    intrinsic value for a call (C >= S - K e^(-rT) >= S - K), so a call
    calendar needs no cash. A European put can be worth a little less than
    intrinsic (P >= K e^(-rT) - S), at most K (1 - e^(-rT)) a share short, so
    a put calendar holds that back. The most it can lose is the net debit plus
    that; what it can gain depends on volatility at the near expiry and is not
    stated.
    """
    import math

    debit = (far_premium - near_premium) * shares
    gap = Decimal(0)
    if option_type == "put":
        gap = strike * shares * Decimal(str(1 - math.exp(-rate * years_between)))
    return StrategyRisk(
        net_premium=_q(-debit),
        collateral=gap.quantize(CENTS, rounding=ROUND_UP),
        max_loss=_q(max(debit, Decimal(0)) + gap),
        max_gain=None,
        breakevens=(),
        basis=(
            "calendar: the most it can lose is the net debit"
            + (" plus the put's small gap below intrinsic, held back" if gap else "")
            + "; the gain depends on volatility when the near leg expires"
        ),
    )
