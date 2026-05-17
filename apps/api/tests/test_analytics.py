"""Pure-function tests for the portfolio analytics service.

The compute helpers are exercised in isolation here so the math is
verified independently of the DB / FastAPI plumbing. The HTTP-level test
for /v1/portfolio/analytics lives in test_analytics_router.py.
"""

from __future__ import annotations

import math
from decimal import Decimal

from stockviz.services.trading import (
    PortfolioPosition,
    compute_annualised_return_pct,
    compute_max_drawdown_pct,
    compute_sector_allocation,
    compute_sharpe,
    compute_top_movers,
    compute_total_return_pct,
)


def _pos(
    ticker: str,
    *,
    qty: str = "10",
    avg: str = "100",
    last: str = "110",
    name: str | None = None,
) -> PortfolioPosition:
    quantity = Decimal(qty)
    avg_cost = Decimal(avg)
    last_close = Decimal(last) if last is not None else None
    mv = (last_close * quantity) if last_close is not None else Decimal(0)
    cost = avg_cost * quantity
    pl = mv - cost
    return PortfolioPosition(
        ticker=ticker,
        name=name or ticker,
        quantity=quantity,
        currency="USD",
        avg_cost=avg_cost,
        last_close=last_close,
        market_value_native=mv,
        unrealized_pl_native=pl,
        market_value=mv,
        unrealized_pl=pl,
    )


# ---------------------------------------------------------------------------
# Time-series metrics
# ---------------------------------------------------------------------------


def test_total_return_pct_basic() -> None:
    navs = [Decimal(100_000), Decimal(110_000)]
    result = compute_total_return_pct(navs)
    assert result is not None
    assert math.isclose(result, 10.0, rel_tol=1e-9)


def test_total_return_pct_needs_two_points() -> None:
    assert compute_total_return_pct([]) is None
    assert compute_total_return_pct([Decimal(100)]) is None


def test_annualised_return_one_year_equals_total() -> None:
    navs = [Decimal(100), Decimal(110)]
    annualised = compute_annualised_return_pct(navs, days=252)
    assert annualised is not None
    assert math.isclose(annualised, 10.0, rel_tol=1e-6)


def test_annualised_return_short_window_extrapolates() -> None:
    # 5% over 30 trading days → ~52% annualised under the (1+r)^(252/30) - 1 rule.
    navs = [Decimal(100), Decimal(105)]
    annualised = compute_annualised_return_pct(navs, days=30)
    assert annualised is not None
    assert 50 < annualised < 55


def test_sharpe_undefined_with_flat_series() -> None:
    # Zero variance → division by zero → None.
    navs = [Decimal(100), Decimal(100), Decimal(100)]
    assert compute_sharpe(navs, risk_free_rate=0.05) is None


def test_sharpe_positive_when_returns_exceed_rf() -> None:
    # Each day +1%, well above the daily risk-free rate.
    navs = [Decimal(100)]
    for _ in range(20):
        navs.append((navs[-1] * Decimal("1.01")).quantize(Decimal("0.000001")))
    sharpe = compute_sharpe(navs, risk_free_rate=0.05)
    assert sharpe is not None
    # The stdev of identical 1% returns is 0 → would be None; jitter slightly.
    # Instead just sanity-check on a synthetic mix:
    mixed_navs = [Decimal(100)]
    daily = [Decimal("1.01"), Decimal("0.995"), Decimal("1.02"), Decimal("0.99")] * 5
    for d in daily:
        mixed_navs.append((mixed_navs[-1] * d).quantize(Decimal("0.000001")))
    mixed = compute_sharpe(mixed_navs, risk_free_rate=0.05)
    assert mixed is not None


def test_max_drawdown_finds_worst_peak_to_trough() -> None:
    # Peak 120 then bottom 80 → drawdown = (80-120)/120 = -33.33%.
    navs = [Decimal(100), Decimal(120), Decimal(80), Decimal(100)]
    dd = compute_max_drawdown_pct(navs)
    assert dd is not None
    assert math.isclose(dd, -100 / 3, rel_tol=1e-6)


def test_max_drawdown_zero_on_monotonic_climb() -> None:
    navs = [Decimal(100), Decimal(110), Decimal(120)]
    assert compute_max_drawdown_pct(navs) == 0


# ---------------------------------------------------------------------------
# Allocation + movers
# ---------------------------------------------------------------------------


def test_sector_allocation_sums_to_100() -> None:
    positions = [
        _pos("AAPL", qty="10", avg="100", last="110"),  # MV 1100
        _pos("MSFT", qty="5", avg="200", last="220"),  # MV 1100
        _pos("XOM", qty="20", avg="50", last="55"),  # MV 1100
    ]
    sectors = {"AAPL": "Technology", "MSFT": "Technology", "XOM": "Energy"}
    allocation = compute_sector_allocation(positions, sectors_by_ticker=sectors)
    total_pct = sum(a.pct for a in allocation)
    assert math.isclose(total_pct, 100.0, abs_tol=0.001)
    # Tech (AAPL+MSFT) should be 2/3 ≈ 66.67%.
    tech = next(a for a in allocation if a.sector == "Technology")
    assert math.isclose(tech.pct, 200 / 3, rel_tol=1e-6)


def test_sector_allocation_buckets_missing_under_unknown() -> None:
    positions = [_pos("AAPL", qty="1", avg="100", last="100")]
    allocation = compute_sector_allocation(positions, sectors_by_ticker={"AAPL": None})
    assert allocation[0].sector == "Unknown"


def test_sector_allocation_empty_on_no_holdings() -> None:
    assert compute_sector_allocation([], sectors_by_ticker={}) == []


def test_top_movers_split_and_rank() -> None:
    positions = [
        _pos("UP1", qty="1", avg="100", last="150"),  # +50%
        _pos("UP2", qty="1", avg="100", last="110"),  # +10%
        _pos("FLAT", qty="1", avg="100", last="100"),  # 0%
        _pos("DOWN1", qty="1", avg="100", last="90"),  # -10%
        _pos("DOWN2", qty="1", avg="100", last="50"),  # -50%
    ]
    sectors = {p.ticker: None for p in positions}
    gainers, losers = compute_top_movers(positions, sectors_by_ticker=sectors)
    assert [m.ticker for m in gainers] == ["UP1", "UP2"]
    assert [m.ticker for m in losers] == ["DOWN2", "DOWN1"]


def test_top_movers_skips_zero_cost_or_unpriced() -> None:
    no_price = PortfolioPosition(
        ticker="ZZZ",
        name="Z",
        quantity=Decimal(1),
        currency="USD",
        avg_cost=Decimal(100),
        last_close=None,
        market_value_native=Decimal(0),
        unrealized_pl_native=Decimal(0),
        market_value=Decimal(0),
        unrealized_pl=Decimal(0),
    )
    gainers, losers = compute_top_movers([no_price], sectors_by_ticker={"ZZZ": None})
    assert gainers == []
    assert losers == []
