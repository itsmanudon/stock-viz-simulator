"""Paper-trading: trade execution, portfolio computation, and pending orders."""

from stockviz.services.trading.dividends import credit_due_dividends
from stockviz.services.trading.execute import (
    DEFAULT_STARTING_CASH,
    InsufficientCash,
    InsufficientPosition,
    NoMarketDataError,
    SymbolNotFound,
    TradeExecutionError,
    ensure_default_portfolio,
    execute_trade,
)
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
    "InsufficientCash",
    "InsufficientPosition",
    "NoMarketDataError",
    "OrderError",
    "PortfolioPosition",
    "PortfolioValuation",
    "SymbolNotFound",
    "TradeExecutionError",
    "compute_portfolio",
    "create_pending_order",
    "credit_due_dividends",
    "ensure_default_portfolio",
    "execute_trade",
    "settle_pending_orders",
    "snapshot_user_navs",
    "upsert_user_snapshot",
]
