"""Paper-trading: trade execution and portfolio computation.

The model is intentionally simple: one default portfolio per user, market
orders only, fills at the most recent ``1d`` close. The Position row is a
materialized roll-up of all Trade rows — we recompute avg cost on every
buy and zero out the row when the last share is sold.
"""

from stockviz.services.trading.analytics import (
    AnalyticsResult,
    SectorAllocation,
    TopMover,
    compute_annualised_return_pct,
    compute_max_drawdown_pct,
    compute_sector_allocation,
    compute_sharpe,
    compute_top_movers,
    compute_total_return_pct,
)
from stockviz.services.trading.dividends import credit_due_dividends
from stockviz.services.trading.execute import (
    DEFAULT_STARTING_CASH,
    InsufficientCash,
    InsufficientPosition,
    NoFxRateError,
    NoMarketDataError,
    SymbolNotFound,
    TradeExecution,
    TradeExecutionError,
    ensure_default_portfolio,
    execute_trade,
)
from stockviz.services.trading.fx import convert as fx_convert
from stockviz.services.trading.fx import latest_rate as fx_latest_rate
from stockviz.services.trading.portfolio import (
    PortfolioPosition,
    PortfolioValuation,
    compute_portfolio,
)
from stockviz.services.trading.snapshots import (
    snapshot_user_navs,
    upsert_user_snapshot,
)

__all__ = [
    "DEFAULT_STARTING_CASH",
    "AnalyticsResult",
    "InsufficientCash",
    "InsufficientPosition",
    "NoFxRateError",
    "NoMarketDataError",
    "PortfolioPosition",
    "PortfolioValuation",
    "SectorAllocation",
    "SymbolNotFound",
    "TopMover",
    "TradeExecution",
    "TradeExecutionError",
    "compute_annualised_return_pct",
    "compute_max_drawdown_pct",
    "compute_portfolio",
    "compute_sector_allocation",
    "compute_sharpe",
    "compute_top_movers",
    "compute_total_return_pct",
    "credit_due_dividends",
    "ensure_default_portfolio",
    "execute_trade",
    "fx_convert",
    "fx_latest_rate",
    "snapshot_user_navs",
    "upsert_user_snapshot",
]
