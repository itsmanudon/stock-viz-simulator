"""Time-weighted and money-weighted returns (Phase 8.1).

Paper accounts have no outside cash flows yet: they start with fixed cash and
the only restart is allowed while the account is fresh. So the account's
time-weighted return equals its NAV return. The functions still take outside
flows, so deposits later need no rewrite. The figure that adds something now
is each holding's own money-weighted return (XIRR), from its buys, sells and
dividends with today's value as the last flow.

The math is pure (no session) and every result states its method, so the API
and the page can show it beside the number (UX-9).
"""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise

TWR_METHOD = "time_weighted"
TWR_BASIS = "opening value, nightly NAV snapshots and the live valuation, chained"
XIRR_METHOD = "money_weighted_xirr"
XIRR_BASIS = "dated cash flows in the base currency, today's value as the last flow"

ANNUALISE_AFTER_DAYS = 365
"""A period's return is annualised only when it spans more than a year."""

MIN_XIRR_DAYS = 30
"""An annual rate from under a month of history is noise: XIRR stays null."""

PERIODS: tuple[str, ...] = ("1M", "3M", "YTD", "1Y", "ALL")


@dataclass(frozen=True, slots=True)
class PeriodReturn:
    period: str
    start_date: date | None
    end_date: date
    return_pct: float | None
    annualised_pct: float | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class Xirr:
    rate_pct: float | None
    first_flow: date | None
    flows: int
    reason: str | None = None


def _minus_months(day: date, months: int) -> date:
    month = day.month - months
    year = day.year
    while month <= 0:
        month += 12
        year -= 1
    # Clamp to the month's length (31 Mar minus one month is 28/29 Feb).
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def period_start(period: str, as_of: date, opened: date) -> date:
    if period == "1M":
        return _minus_months(as_of, 1)
    if period == "3M":
        return _minus_months(as_of, 3)
    if period == "1Y":
        return _minus_months(as_of, 12)
    if period == "YTD":
        return date(as_of.year - 1, 12, 31)
    if period == "ALL":
        return opened
    raise ValueError(f"unknown period {period}")


def time_weighted_return(
    points: Sequence[tuple[date, Decimal]],
    flows: Sequence[tuple[date, Decimal]] = (),
) -> float | None:
    """Chain sub-period returns between valuation points, as a fraction.

    An outside flow dated ``d`` (deposit positive) is taken to arrive just
    before the valuation on ``d``, so that sub-period's return is
    ``(V_d - F_d) / V_prev - 1``. Over a missed night the gap is simply one
    longer sub-period: the return stays right.
    """
    if len(points) < 2:
        return None
    by_day: dict[date, Decimal] = {}
    for day, amount in flows:
        by_day[day] = by_day.get(day, Decimal(0)) + amount
    growth = 1.0
    for (_, prev), (day, curr) in pairwise(points):
        if prev <= 0:
            return None
        growth *= float((curr - by_day.get(day, Decimal(0))) / prev)
    return growth - 1


def annualise(fraction: float, days: int) -> float | None:
    if days <= 0 or fraction <= -1:
        return None
    return (1 + fraction) ** (365 / days) - 1


def period_returns(
    points: Sequence[tuple[date, Decimal]],
    *,
    as_of: date,
    opened: date,
    flows: Sequence[tuple[date, Decimal]] = (),
) -> list[PeriodReturn]:
    """TWR for each of :data:`PERIODS`, from date-ordered valuation points.

    A period starts at the last point on or before its start date. When the
    account opened after that date the period has no return ("the account is
    younger than the period"), except ``ALL``, which starts at the opening.
    """
    out: list[PeriodReturn] = []
    for period in PERIODS:
        start = period_start(period, as_of, opened)
        if start < opened:
            out.append(
                PeriodReturn(period, None, as_of, None, None, "account is younger than the period")
            )
            continue
        before = [i for i, (day, _) in enumerate(points) if day <= start]
        if not before:
            out.append(PeriodReturn(period, None, as_of, None, None, "no valuation at the start"))
            continue
        # ALL starts at the opening value itself, before that day's trading;
        # other periods at the close on or before their start date.
        window = list(points if period == "ALL" else points[before[-1] :])
        start_day = window[0][0]
        fraction = time_weighted_return(window, [f for f in flows if f[0] > start_day])
        if fraction is None:
            out.append(PeriodReturn(period, start_day, as_of, None, None, "not enough history"))
            continue
        days = (as_of - start_day).days
        yearly = annualise(fraction, days) if days > ANNUALISE_AFTER_DAYS else None
        out.append(
            PeriodReturn(
                period,
                start_day,
                as_of,
                fraction * 100,
                yearly * 100 if yearly is not None else None,
            )
        )
    return out


def _npv(rate: float, flows: Sequence[tuple[float, float]]) -> float:
    return sum(amount / (1 + rate) ** years for years, amount in flows)


def _dnpv(rate: float, flows: Sequence[tuple[float, float]]) -> float:
    return sum(-years * amount / (1 + rate) ** (years + 1) for years, amount in flows)


def xirr(flows: Sequence[tuple[date, Decimal]], *, as_of: date) -> Xirr:
    """Annual money-weighted return of dated flows (money out negative).

    Newton's method from 10%, falling back to bisection on [-99.99%, 10,000%]
    when Newton leaves the bracket or stalls. Null with a reason when the
    flows never change sign or span under :data:`MIN_XIRR_DAYS`.
    """
    dated = sorted((d, a) for d, a in flows if a != 0)
    if not dated:
        return Xirr(None, None, 0, "no cash flows")
    first = dated[0][0]
    count = len(dated)
    if not any(a < 0 for _, a in dated) or not any(a > 0 for _, a in dated):
        return Xirr(None, first, count, "cash flows do not change sign")
    if (as_of - first).days < MIN_XIRR_DAYS:
        return Xirr(None, first, count, f"held under {MIN_XIRR_DAYS} days")
    years = [((d - first).days / 365, float(a)) for d, a in dated]

    low, high = -0.9999, 100.0
    rate = 0.1
    for _ in range(50):
        value = _npv(rate, years)
        slope = _dnpv(rate, years)
        if slope == 0:
            break
        step = rate - value / slope
        if not (low < step < high):
            break
        if abs(step - rate) < 1e-12:
            return Xirr(step * 100, first, count)
        rate = step
    else:
        if abs(_npv(rate, years)) < 1e-6:
            return Xirr(rate * 100, first, count)

    f_low, f_high = _npv(low, years), _npv(high, years)
    if f_low * f_high > 0:
        return Xirr(None, first, count, "no rate solves the cash flows")
    for _ in range(200):
        mid = (low + high) / 2
        f_mid = _npv(mid, years)
        if abs(f_mid) < 1e-9 or high - low < 1e-12:
            break
        if f_low * f_mid < 0:
            high, f_high = mid, f_mid
        else:
            low, f_low = mid, f_mid
    return Xirr((low + high) / 2 * 100, first, count)
