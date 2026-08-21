"""Backtest realism: no look-ahead, real costs, and a benchmark to beat.

The pre-existing suite uses price plateaus around every signal, so a one-bar
shift in fill timing is invisible to it. These fixtures deliberately move the
price on the bar after the signal, which is the only way to tell the two
behaviours apart.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from stockviz.services.backtest import BacktestError, run_backtest
from stockviz.services.backtest.engine import DEFAULT_RISK_FREE_RATE, _sharpe

_EPOCH = datetime(2024, 1, 1)


def _bars(prices: Sequence[float]) -> list[tuple[datetime, Decimal]]:
    return [(_EPOCH + timedelta(days=i), Decimal(str(p))) for i, p in enumerate(prices)]


def test_fill_happens_on_the_bar_after_the_signal() -> None:
    """The SMA2/SMA3 cross prints at index 3; the fill belongs at index 4.

    Prices jump from 25 to 40 right after the cross. Filling at the signal bar
    would buy at 25 — a price the strategy could not have known to act on until
    that bar had already closed.
    """
    prices = [10, 10, 10, 25, 40, 40, 40, 40, 40]
    result = run_backtest(
        _bars(prices),
        initial_cash=Decimal(1000),
        strategy_type="sma_crossover",
        params={"short_window": 2, "long_window": 3},
    )

    assert len(result.trades) == 1
    buy = result.trades[0]
    assert buy.side == "buy"
    # The realistic fill: bar index 4, price 40. Look-ahead would give 25.
    assert buy.price == Decimal(40)
    assert buy.date == (_EPOCH + timedelta(days=4)).date()
    assert buy.shares == Decimal(25)  # 1000 / 40


def test_final_bar_signal_is_never_filled() -> None:
    """There is no next bar to trade into, so a last-bar signal does nothing."""
    # Cross prints on the very last bar.
    prices = [10, 10, 10, 10, 10, 10, 10, 10, 30]
    result = run_backtest(
        _bars(prices),
        initial_cash=Decimal(1000),
        strategy_type="sma_crossover",
        params={"short_window": 2, "long_window": 3},
    )
    assert result.trades == []
    assert result.summary.final_nav == Decimal(1000)


def test_costs_reduce_returns_on_a_round_trip() -> None:
    """Commission and slippage are charged on both legs."""
    prices = [10, 10, 10, 25, 25, 25, 5, 5, 5]
    free = run_backtest(
        _bars(prices),
        initial_cash=Decimal(1000),
        strategy_type="sma_crossover",
        params={"short_window": 2, "long_window": 3},
    )
    costly = run_backtest(
        _bars(prices),
        initial_cash=Decimal(1000),
        strategy_type="sma_crossover",
        params={"short_window": 2, "long_window": 3},
        commission_bps=50,  # 0.5% a side
        slippage_bps=50,  # another 0.5% a side
    )

    assert [t.side for t in costly.trades] == ["buy", "sell"]
    assert costly.summary.final_nav < free.summary.final_nav
    assert costly.summary.total_costs > Decimal(0)
    assert free.summary.total_costs == Decimal(0)


def test_costs_must_be_non_negative() -> None:
    with pytest.raises(BacktestError):
        run_backtest(
            _bars([10, 11, 12, 13]),
            initial_cash=Decimal(1000),
            strategy_type="sma_crossover",
            params={"short_window": 2, "long_window": 3},
            commission_bps=-1,
        )


def test_benchmark_is_buy_and_hold_over_the_same_window() -> None:
    """A strategy that never trades should match buy-and-hold at zero excess."""
    prices = [10, 20, 30, 40, 50]
    result = run_backtest(
        _bars(prices),
        initial_cash=Decimal(1000),
        strategy_type="rsi_threshold",
        # Thresholds that never fire on a 5-bar series (RSI needs 14 periods).
        params={"buy_below": 1, "sell_above": 99},
    )
    assert result.trades == []
    # Buy-and-hold: 100 shares at 10 -> 5000 at 50, a 4x.
    assert result.summary.benchmark_final_nav == Decimal(5000)
    assert result.summary.benchmark_return == pytest.approx(4.0)
    # The strategy stayed in cash, so it underperformed by 400 points.
    assert result.summary.excess_return == pytest.approx(-400.0)


def test_sharpe_subtracts_the_risk_free_rate() -> None:
    """A higher risk-free rate must lower Sharpe for the same NAV series.

    Previously the engine hardcoded a zero rate while the live portfolio
    analytics used 0.05, so the same NAV series scored differently depending
    on which surface rendered it.
    """
    navs = [Decimal(n) for n in (1000, 1010, 1005, 1030, 1025, 1060)]
    assert _sharpe(navs, risk_free_rate=0.5) < _sharpe(navs, risk_free_rate=0.0)


def test_sharpe_defaults_to_the_analytics_risk_free_rate() -> None:
    from stockviz.routers.trading import DEFAULT_RISK_FREE_RATE as ANALYTICS_RATE

    assert DEFAULT_RISK_FREE_RATE == ANALYTICS_RATE

    navs = [Decimal(n) for n in (1000, 1010, 1005, 1030, 1025, 1060)]
    assert _sharpe(navs) == _sharpe(navs, risk_free_rate=ANALYTICS_RATE)
