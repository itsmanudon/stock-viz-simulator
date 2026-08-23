"""Paper-trading: trade execution, portfolio computation, and pending orders."""

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
from stockviz.services.trading.buying_power import (
    available_cash,
    available_shares,
    lock_portfolio,
    reserved_cash,
    reserved_shares,
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
from stockviz.services.trading.orders import OrderError, create_pending_order, settle_pending_orders
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
    "OrderError",
    "PortfolioPosition",
    "PortfolioValuation",
    "SectorAllocation",
    "SymbolNotFound",
    "TopMover",
    "TradeExecution",
    "TradeExecutionError",
    "available_cash",
    "available_shares",
    "compute_annualised_return_pct",
    "compute_max_drawdown_pct",
    "compute_portfolio",
    "compute_sector_allocation",
    "compute_sharpe",
    "compute_top_movers",
    "compute_total_return_pct",
    "create_pending_order",
    "credit_due_dividends",
    "ensure_default_portfolio",
    "execute_trade",
    "fx_convert",
    "fx_latest_rate",
    "lock_portfolio",
    "reserved_cash",
    "reserved_shares",
    "settle_pending_orders",
    "snapshot_user_navs",
    "upsert_user_snapshot",
]
