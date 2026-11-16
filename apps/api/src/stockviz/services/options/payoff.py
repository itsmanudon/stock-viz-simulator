"""Payoff curves and the chance of profit for a strategy (Phase 9.5).

Computed on the server so the web and the tests agree. Two curves over a
range of underlying prices:

- **at the first expiry**: legs expiring then are worth their intrinsic
  value; a later leg (a calendar's far leg) its Black-Scholes value with the
  time it has left. For same-expiry strategies this is the exact expiry
  payoff.
- **today**: every leg at its Black-Scholes value now.

Both are profit or loss after the premiums. A covered call and a protective
put include their shares, measured from today's close.

The chance of profit assumes the stock's price at the first expiry is
lognormal with the volatility the legs were priced with and the risk-free
drift, and integrates where the expiry curve is above zero. It is a model
figure, labelled as such: it inherits every assumption Black-Scholes makes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date as date_type
from statistics import NormalDist

from stockviz.models.option_strategy import StrategyKind
from stockviz.services.options.pricing import black_scholes
from stockviz.services.options.strategies import StrategyQuote
from stockviz.services.options.trade import RISK_FREE_RATE, _today

POINTS = 81
_NORMAL = NormalDist()


@dataclass(frozen=True, slots=True)
class PayoffPoint:
    spot: float
    at_expiry: float
    today: float


@dataclass(frozen=True, slots=True)
class Payoff:
    horizon: date_type
    points: list[PayoffPoint]
    prob_profit: float | None
    volatility: float
    method: str


def _with_shares(kind: StrategyKind) -> bool:
    return kind in (StrategyKind.COVERED_CALL, StrategyKind.PROTECTIVE_PUT)


def strategy_payoff(quote: StrategyQuote, *, asof: date_type | None = None) -> Payoff:
    asof = asof or _today()
    first = quote.legs[0][1]
    spot0 = float(first.spot)
    # Each leg keeps the volatility it was priced with (a chain's IV differs
    # by strike, Phase 9.6); the chance of profit uses the leg nearest the money.
    atm = min(quote.legs, key=lambda leg: abs(float(leg[0].strike) - spot0))
    vol = atm[1].volatility
    horizon = min(plan.expiry for plan, _ in quote.legs)
    t_h = max((horizon - asof).days / 365.0, 0.0)
    shares = 100 * quote.quantity
    cost = sum(
        (1 if plan.side.value == "long" else -1) * float(q.per_share) * shares
        for plan, q in quote.legs
    )

    def value(spot: float, years_from_now: float) -> float:
        total = 0.0
        for plan, q in quote.legs:
            left = max((plan.expiry - asof).days / 365.0 - years_from_now, 0.0)
            price = black_scholes(
                spot=spot,
                strike=float(plan.strike),
                time_to_expiry_years=left,
                volatility=q.volatility,
                risk_free_rate=RISK_FREE_RATE,
                option_type=plan.option_type.value,
            ).value
            if left == 0.0:  # expired: intrinsic, undiscounted
                k = float(plan.strike)
                price = (
                    max(spot - k, 0.0) if plan.option_type.value == "call" else max(k - spot, 0.0)
                )
            total += (1 if plan.side.value == "long" else -1) * price * shares
        if _with_shares(quote.kind):
            total += (spot - spot0) * shares
        return total

    def at_expiry(spot: float) -> float:
        return value(spot, t_h) - cost

    strikes = [float(plan.strike) for plan, _ in quote.legs]
    lo = max(0.01, min(0.5 * spot0, 0.8 * min(strikes)))
    hi = max(1.5 * spot0, 1.2 * max(strikes))
    grid = sorted({*(lo + (hi - lo) * i / (POINTS - 1) for i in range(POINTS)), *strikes})
    points = [
        PayoffPoint(
            spot=round(s, 4), at_expiry=round(at_expiry(s), 2), today=round(value(s, 0.0) - cost, 2)
        )
        for s in grid
    ]

    prob: float | None = None
    if vol > 0 and t_h > 0:
        drift = (RISK_FREE_RATE - vol * vol / 2) * t_h
        scale = vol * math.sqrt(t_h)
        step = 0.01
        z = -6.0
        hit = 0.0
        while z <= 6.0:
            if at_expiry(spot0 * math.exp(drift + scale * z)) > 0:
                hit += _NORMAL.pdf(z) * step
            z += step
        prob = round(min(max(hit, 0.0), 1.0), 4)
    return Payoff(
        horizon=horizon,
        points=points,
        prob_profit=prob,
        volatility=vol,
        method=(
            "profit or loss after premiums; at the first expiry legs expiring then are worth "
            "intrinsic value and later legs their Black-Scholes value; chance of profit assumes "
            "a lognormal price at that expiry with the volatility of the leg nearest the money"
        ),
    )
