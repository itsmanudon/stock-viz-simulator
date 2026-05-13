"""Paper-trading: trade execution and portfolio computation.

The model is intentionally simple: one default portfolio per user, market
orders only, fills at the most recent ``1d`` close. The Position row is a
materialized roll-up of all Trade rows — we recompute avg cost on every
buy and zero out the row when the last share is sold.
"""

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
    "PortfolioPosition",
    "PortfolioValuation",
    "SymbolNotFound",
    "TradeExecutionError",
    "compute_portfolio",
    "credit_due_dividends",
    "ensure_default_portfolio",
    "execute_trade",
    "snapshot_user_navs",
    "upsert_user_snapshot",
]
