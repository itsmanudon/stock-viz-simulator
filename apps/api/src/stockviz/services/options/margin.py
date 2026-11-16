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
from decimal import Decimal

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
