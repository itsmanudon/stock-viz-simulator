"""Strategy backtesting — replay stored bars through a strategy spec.

Pure computation: no DB, no network. The router loads ``PriceBar`` rows and
hands ``(timestamp, close)`` pairs to :func:`run_backtest`.
"""

from stockviz.services.backtest.engine import (
    BacktestError,
    BacktestResult,
    BacktestSummary,
    BacktestTrade,
    EquityPoint,
    run_backtest,
)

__all__ = [
    "BacktestError",
    "BacktestResult",
    "BacktestSummary",
    "BacktestTrade",
    "EquityPoint",
    "run_backtest",
]
