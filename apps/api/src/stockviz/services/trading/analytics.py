"""Portfolio analytics: returns, Sharpe, drawdown, sector mix, top movers.

All computations are pure functions over the snapshot series + current
position list. The router glues these together, but they're individually
testable here without touching the DB.

When history is insufficient (under two snapshots) every time-series metric
returns ``None`` so the UI can render a "not enough data yet" state.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise

from stockviz.services.trading.portfolio import PortfolioPosition

TRADING_DAYS_PER_YEAR = 252
"""Sessions per year: annualises Sharpe, whose returns are one session each."""

CALENDAR_DAYS_PER_YEAR = 365
"""Annualises the return, whose period is measured in calendar days (SR-4)."""

MAX_SESSION_GAP_DAYS = 4
"""Widest calendar gap between two snapshots that is still one session apart:
Friday to Tuesday over a holiday weekend. Wider gaps are missed nights (SR-5)."""

MIN_SHARPE_RETURNS = 20
"""About a month of session returns before a Sharpe ratio means anything (SR-5)."""


@dataclass(frozen=True, slots=True)
class SectorAllocation:
    sector: str
    market_value: Decimal
    pct: float


@dataclass(frozen=True, slots=True)
class TopMover:
    ticker: str
    name: str
    sector: str | None
    unrealized_pl: Decimal
    return_pct: float


@dataclass(frozen=True, slots=True)
class AnalyticsResult:
    display_currency: str
    history_days: int
    total_return_pct: float | None
    annualised_return_pct: float | None
    sharpe_ratio: float | None
    max_drawdown_pct: float | None
    risk_free_rate: float
    sector_allocation: list[SectorAllocation]
    top_gainers: list[TopMover]
    top_losers: list[TopMover]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _stdev(values: list[float], mean: float) -> float:
    if len(values) < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def compute_total_return_pct(navs: list[Decimal]) -> float | None:
    """``(last/first - 1) * 100``. ``None`` when fewer than two points or first == 0."""
    if len(navs) < 2:
        return None
    first = float(navs[0])
    last = float(navs[-1])
    if first == 0:
        return None
    return (last / first - 1) * 100


def compute_annualised_return_pct(navs: list[Decimal], *, days: int) -> float | None:
    """Annualise the period return over ``days`` calendar days.

    ``(1 + total_return) ** (365 / days) - 1``. ``days`` is calendar time, so
    the exponent uses calendar days too: it used 252, raising growth to a
    trading-day power over calendar days and overstating the rate (SR-4).
    """
    if days <= 0:
        return None
    total = compute_total_return_pct(navs)
    if total is None:
        return None
    growth = 1 + total / 100
    if growth <= 0:
        return None
    return (growth ** (CALENDAR_DAYS_PER_YEAR / days) - 1) * 100


def session_returns(points: list[tuple[date, Decimal]]) -> list[float]:
    """Returns between snapshots one session apart, from a date-ordered series.

    A pair further apart than :data:`MAX_SESSION_GAP_DAYS` spans missed nights,
    so it is not one session's return and is left out (SR-5).
    """
    out: list[float] = []
    for (prev_day, prev), (day, curr) in pairwise(points):
        if prev == 0 or (day - prev_day).days > MAX_SESSION_GAP_DAYS:
            continue
        out.append(float((curr - prev) / prev))
    return out


def compute_sharpe(points: list[tuple[date, Decimal]], *, risk_free_rate: float) -> float | None:
    """Annualised Sharpe from dated end-of-day snapshots.

    Uses only returns between adjacent sessions and needs
    :data:`MIN_SHARPE_RETURNS` of them; three snapshots used to be enough
    (SR-5). ``risk_free_rate`` is annual, converted to per-session.
    """
    daily = session_returns(points)
    if len(daily) < MIN_SHARPE_RETURNS:
        return None
    daily_rf = risk_free_rate / TRADING_DAYS_PER_YEAR
    excess = [r - daily_rf for r in daily]
    mean = _mean(excess)
    sd = _stdev(daily, _mean(daily))
    if sd == 0:
        return None
    return (mean / sd) * math.sqrt(TRADING_DAYS_PER_YEAR)


def compute_max_drawdown_pct(navs: list[Decimal]) -> float | None:
    """Worst peak-to-trough decline expressed as a negative percent.

    Walks the series once tracking the running peak; for each NAV computes
    the drawdown from that peak and remembers the worst. Returns ``None``
    on insufficient history or when every peak so far was zero.
    """
    if len(navs) < 2:
        return None
    peak = float(navs[0])
    max_dd = 0.0
    for nav in navs[1:]:
        v = float(nav)
        if v > peak:
            peak = v
            continue
        if peak == 0:
            continue
        dd = (v - peak) / peak
        if dd < max_dd:
            max_dd = dd
    return max_dd * 100


def compute_sector_allocation(
    positions: list[PortfolioPosition],
    *,
    sectors_by_ticker: Mapping[str, str | None],
) -> list[SectorAllocation]:
    """Aggregate market value by symbol's sector and convert to a percentage.

    Positions whose ticker has no sector entry (or ``None``) are bucketed
    under ``"Unknown"``. Output is sorted by market value descending so the
    largest slice is first.
    """
    sums: dict[str, Decimal] = {}
    total = Decimal(0)
    for p in positions:
        sector = sectors_by_ticker.get(p.ticker) or "Unknown"
        sums[sector] = sums.get(sector, Decimal(0)) + p.market_value
        total += p.market_value
    if total == 0:
        return []
    out = [
        SectorAllocation(sector=s, market_value=v, pct=float(v / total * 100))
        for s, v in sums.items()
    ]
    out.sort(key=lambda a: a.market_value, reverse=True)
    return out


def compute_top_movers(
    positions: list[PortfolioPosition],
    *,
    sectors_by_ticker: Mapping[str, str | None],
    limit: int = 5,
) -> tuple[list[TopMover], list[TopMover]]:
    """Return ``(gainers, losers)`` ranked by return percent.

    Cost basis of zero or missing price data are skipped — a P&L percent is
    undefined in either case. Gainers are descending, losers ascending.
    """
    movers: list[TopMover] = []
    for p in positions:
        cost = p.avg_cost * p.quantity
        if cost == 0 or p.last_close is None:
            continue
        return_pct = float(p.unrealized_pl_native / cost * 100)
        movers.append(
            TopMover(
                ticker=p.ticker,
                name=p.name,
                sector=sectors_by_ticker.get(p.ticker),
                unrealized_pl=p.unrealized_pl,
                return_pct=return_pct,
            )
        )
    gainers = sorted(
        [m for m in movers if m.return_pct > 0],
        key=lambda m: m.return_pct,
        reverse=True,
    )
    losers = sorted([m for m in movers if m.return_pct < 0], key=lambda m: m.return_pct)
    return gainers[:limit], losers[:limit]
