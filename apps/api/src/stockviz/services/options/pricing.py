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

RISK_FREE_RATES: dict[str, float] = {"USD": 0.05}
"""Annual risk-free rate by premium currency (Phase 9.1). One place for the
rate every option price uses; INR joins when Indian options do."""

MIN_VOL_CLOSES = 20
"""Fewer usable closes than this in the volatility window and an option is not
priced at all (audit LG-14): a near-zero volatility would price an
out-of-the-money contract at nothing."""

MIN_PREMIUM_PER_SHARE = Decimal("0.01")
"""No contract opens for less than a cent a share (audit LG-14)."""

IV_MIN = 0.01
IV_MAX = 5.0
"""Bounds of the implied-volatility search: 1% to 500% a year."""


def risk_free_rate(currency: str) -> float:
    """The rate options in ``currency`` are priced at. KeyError if unsupported."""
    return RISK_FREE_RATES[currency.upper()]


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
    per calendar day, ``rho`` the price change per 1.00 (100%) change in the
    risk-free rate.
    """

    value: float
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float = 0.0


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
        return OptionPrice(value=intrinsic, delta=0.0, gamma=0.0, theta=0.0, vega=0.0, rho=0.0)

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
        rho = strike * time_to_expiry_years * discount * _norm_cdf(d2)
        theta_year = -(spot * pdf_d1 * volatility) / (2.0 * sqrt_t) - (
            risk_free_rate * strike * discount * _norm_cdf(d2)
        )
    else:
        value = strike * discount * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0
        rho = -strike * time_to_expiry_years * discount * _norm_cdf(-d2)
        theta_year = -(spot * pdf_d1 * volatility) / (2.0 * sqrt_t) + (
            risk_free_rate * strike * discount * _norm_cdf(-d2)
        )

    return OptionPrice(
        value=value,
        delta=delta,
        gamma=gamma,
        theta=theta_year / 365.0,  # per calendar day
        vega=vega,
        rho=rho,
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


def usable_closes(closes: list[Decimal], *, window: int = 30) -> int:
    """How many positive closes :func:`historical_volatility` would use."""
    return sum(1 for c in closes[-(window + 1) :] if c > 0)


@dataclass(frozen=True, slots=True)
class ImpliedVolatility:
    """The volatility that prices a contract at ``price``, or why there is none."""

    volatility: float | None
    reason: str | None = None


def implied_volatility(
    *,
    price: float,
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    option_type: str,
    tolerance: float = 1e-8,
    max_iterations: int = 100,
) -> ImpliedVolatility:
    """Solve Black-Scholes for volatility: Newton's method on vega, bisection fallback.

    Returns ``volatility=None`` with a reason when no volatility in
    [:data:`IV_MIN`, :data:`IV_MAX`] gives ``price``: at or below the
    discounted intrinsic value, at or above the no-arbitrage bound (spot for a
    call, discounted strike for a put), or past expiry.
    """
    if time_to_expiry_years <= 0:
        return ImpliedVolatility(None, "the contract has expired")
    if price <= 0:
        return ImpliedVolatility(None, "the price must be positive")

    def value(vol: float) -> OptionPrice:
        return black_scholes(
            spot=spot,
            strike=strike,
            time_to_expiry_years=time_to_expiry_years,
            volatility=vol,
            risk_free_rate=risk_free_rate,
            option_type=option_type,
        )

    discount = math.exp(-risk_free_rate * time_to_expiry_years)
    if option_type == "call":
        intrinsic = max(spot - strike * discount, 0.0)
        upper = spot
    else:
        intrinsic = max(strike * discount - spot, 0.0)
        upper = strike * discount
    if price <= intrinsic:
        return ImpliedVolatility(None, "the price is at or below intrinsic value")
    if price >= upper:
        return ImpliedVolatility(None, "the price is above the no-arbitrage bound")

    low, high = IV_MIN, IV_MAX
    if not value(low).value <= price <= value(high).value:
        return ImpliedVolatility(None, "no volatility between 1% and 500% gives this price")

    vol = 0.3
    for _ in range(max_iterations):
        priced = value(vol)
        diff = priced.value - price
        if abs(diff) < tolerance:
            return ImpliedVolatility(vol)
        if diff > 0:
            high = vol
        else:
            low = vol
        step = vol - diff / priced.vega if priced.vega > 1e-12 else -1.0
        # Newton while it stays inside the bracket, bisection otherwise.
        vol = step if low < step < high else (low + high) / 2.0
    return ImpliedVolatility(vol)
