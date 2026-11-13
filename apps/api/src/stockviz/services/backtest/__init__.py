"""Strategy backtesting — replay stored bars through a strategy spec.

Pure computation: no DB, no network. The router loads ``PriceBar`` rows (with
warm-up bars before the window) and hands ``(timestamp, close)`` pairs to
:func:`run_backtest`, which fills through the shared kernel and SimLedger.
"""

from stockviz.services.backtest.engine import (
    BacktestError,
    BacktestResult,
    BacktestSummary,
    BacktestTrade,
    EquityPoint,
    run_backtest,
    warmup_bars_for,
)

__all__ = [
    "BacktestError",
    "BacktestResult",
    "BacktestSummary",
    "BacktestTrade",
    "EquityPoint",
    "run_backtest",
    "warmup_bars_for",
]
