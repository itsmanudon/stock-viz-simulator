"""Black-Scholes option pricing and historical volatility.

No scipy dependency: the standard-normal CDF is built from ``math.erf`` and
the PDF from ``math.exp``. Everything here is pure float math — callers
quantize to ``Decimal`` at the persistence / wire boundary.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

TRADING_DAYS_PER_YEAR = 252


def _norm_cdf(x: float) -> float:
    """Standard-normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Standard-normal probability density function."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


@dataclass(frozen=True, slots=True)
class OptionPrice:
    """A Black-Scholes valuation. ``value`` is per share of the underlying.

    Greeks are per-share too: ``delta`` is unitless, ``vega`` is the price
    change per 1.00 (100%) change in volatility, ``theta`` is the price change
    per calendar day.
    """

    value: float
    delta: float
    gamma: float
    theta: float
    vega: float


def black_scholes(
    *,
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    volatility: float,
    risk_free_rate: float,
    option_type: str,
) -> OptionPrice:
    """Price a European call/put and its greeks.

    Degenerate inputs (``T <= 0`` or ``volatility <= 0``) collapse to the
    discounted intrinsic value with zero greeks — that keeps the function
    total so callers don't have to special-case an about-to-expire contract.
    """

    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be positive")
    if option_type not in ("call", "put"):
        raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")

    if time_to_expiry_years <= 0 or volatility <= 0:
        discounted_strike = strike * math.exp(-risk_free_rate * max(time_to_expiry_years, 0.0))
        if option_type == "call":
            intrinsic = max(spot - discounted_strike, 0.0)
        else:
            intrinsic = max(discounted_strike - spot, 0.0)
        return OptionPrice(value=intrinsic, delta=0.0, gamma=0.0, theta=0.0, vega=0.0)

    sqrt_t = math.sqrt(time_to_expiry_years)
    d1 = (
        math.log(spot / strike)
        + (risk_free_rate + 0.5 * volatility * volatility) * time_to_expiry_years
    ) / (volatility * sqrt_t)
    d2 = d1 - volatility * sqrt_t
    discount = math.exp(-risk_free_rate * time_to_expiry_years)
    pdf_d1 = _norm_pdf(d1)

    gamma = pdf_d1 / (spot * volatility * sqrt_t)
    vega = spot * pdf_d1 * sqrt_t

    if option_type == "call":
        value = spot * _norm_cdf(d1) - strike * discount * _norm_cdf(d2)
        delta = _norm_cdf(d1)
        theta_year = -(spot * pdf_d1 * volatility) / (2.0 * sqrt_t) - (
            risk_free_rate * strike * discount * _norm_cdf(d2)
        )
    else:
        value = strike * discount * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0
        theta_year = -(spot * pdf_d1 * volatility) / (2.0 * sqrt_t) + (
            risk_free_rate * strike * discount * _norm_cdf(-d2)
        )

    return OptionPrice(
        value=value,
        delta=delta,
        gamma=gamma,
        theta=theta_year / 365.0,  # per calendar day
        vega=vega,
    )


def historical_volatility(closes: list[Decimal], *, window: int = 30) -> float:
    """Annualised volatility from the last ``window`` daily closes.

    Uses the sample standard deviation of daily log returns scaled by
    ``sqrt(252)``. Returns ``0.0`` when there aren't enough closes to form at
    least two returns — callers treat 0 vol as "price at intrinsic".
    """

    prices = [float(c) for c in closes[-(window + 1) :] if c > 0]
    if len(prices) < 3:
        return 0.0

    log_returns = [
        math.log(prices[i] / prices[i - 1])
        for i in range(1, len(prices))
        if prices[i - 1] > 0 and prices[i] > 0
    ]
    if len(log_returns) < 2:
        return 0.0

    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)
    daily_vol = math.sqrt(variance)
    return daily_vol * math.sqrt(TRADING_DAYS_PER_YEAR)
