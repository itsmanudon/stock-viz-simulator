"""Twelve-month dividend projection per holding (A9.6, M10.8).

A projection, not a forecast of what a company will declare. From the stored
ex-dividend history (``dividends``) of one instrument, as of a date:

- **Trailing 12 months (TTM):** the sum of per-share amounts with an ex-date
  in the 365 days up to and including the date.
- **3-year growth:** ``(TTM / TTM three years earlier) ** (1/3) - 1`` when both
  are above 0; otherwise none, and the projection uses 0% growth. It is
  capped to [-50%, +25%] a year, so one special dividend does not compound
  into a fantasy.
- **Next 12 months per share** = TTM x (1 + growth).
- **Payout calendar:** each ex-date of the trailing year moved forward one
  year, each carrying TTM-weighted share of the projected amount (its own
  amount x (1 + growth)).
- **Forward yield** = next-12-month amount per share / the last close.
- **Growth streak:** consecutive completed calendar years, counting back from
  the last one, whose total beat the year before.

Holdings are valued at the current quantity; a dividend is projected only
while that quantity is held, which nobody knows. Pure functions; the route
loads the rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

GROWTH_CAP = (-0.5, 0.25)
TTM_DAYS = 365


@dataclass
class Projection:
    ticker: str
    currency: str
    quantity: Decimal
    ttm_per_share: Decimal = Decimal(0)
    growth_3y: float | None = None
    growth_used: float = 0.0
    next_12m_per_share: Decimal = Decimal(0)
    next_12m_total: Decimal = Decimal(0)
    forward_yield: float | None = None
    streak_years: int = 0
    payouts: list[dict[str, object]] = field(default_factory=list)
    reason: str | None = None


def ttm(history: list[tuple[date, Decimal]], on: date) -> Decimal:
    start = on - timedelta(days=TTM_DAYS - 1)
    return sum((a for d, a in history if start <= d <= on), start=Decimal(0))


def growth_3y(history: list[tuple[date, Decimal]], on: date) -> float | None:
    now, then = ttm(history, on), ttm(history, on - timedelta(days=3 * 365))
    if now <= 0 or then <= 0:
        return None
    return float((now / then) ** (Decimal(1) / Decimal(3))) - 1


def streak(history: list[tuple[date, Decimal]], on: date) -> int:
    totals: dict[int, Decimal] = {}
    for d, a in history:
        if d.year < on.year:
            totals[d.year] = totals.get(d.year, Decimal(0)) + a
    years, count = on.year - 1, 0
    while years in totals and years - 1 in totals and totals[years] > totals[years - 1]:
        count += 1
        years -= 1
    return count


def project(
    ticker: str,
    currency: str,
    quantity: Decimal,
    history: list[tuple[date, Decimal]],
    last_close: Decimal | None,
    on: date,
) -> Projection:
    out = Projection(ticker=ticker, currency=currency, quantity=quantity)
    history = sorted((d, a) for d, a in history if d <= on)
    out.ttm_per_share = ttm(history, on)
    out.streak_years = streak(history, on)
    if out.ttm_per_share <= 0:
        out.reason = "No dividend with an ex-date in the last 12 months."
        return out
    out.growth_3y = growth_3y(history, on)
    if out.growth_3y is not None:
        out.growth_used = min(max(out.growth_3y, GROWTH_CAP[0]), GROWTH_CAP[1])
    factor = Decimal(str(1 + out.growth_used))
    out.next_12m_per_share = (out.ttm_per_share * factor).quantize(Decimal("0.0001"))
    out.next_12m_total = (out.next_12m_per_share * quantity).quantize(Decimal("0.01"))
    if last_close and last_close > 0:
        out.forward_yield = round(float(out.next_12m_per_share / last_close), 6)
    start = on - timedelta(days=TTM_DAYS - 1)
    for d, a in history:
        if start <= d <= on:
            nxt = _plus_year(d)
            per_share = (a * factor).quantize(Decimal("0.0001"))
            out.payouts.append({
                "ex_date": nxt, "per_share": per_share,
                "amount": (per_share * quantity).quantize(Decimal("0.01")),
            })  # fmt: skip
    return out


def _plus_year(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year + 1, day=28)
