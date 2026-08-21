"""SQLModel ORM models for StockViz.

All models are imported here so that ``SQLModel.metadata`` is populated when
Alembic runs autogenerate. Keep this module side-effect-free apart from the
imports themselves.
"""

from stockviz.models.alert import Alert, AlertDirection
from stockviz.models.comment import Comment
from stockviz.models.dividend import Dividend, PortfolioDividend
from stockviz.models.market import FxRate, NewsArticle, PriceBar, Symbol
from stockviz.models.metrics import SymbolMetrics
from stockviz.models.option import OptionsPosition, OptionStatus, OptionType
from stockviz.models.order import OrderStatus, OrderType, PendingOrder
from stockviz.models.portfolio import Portfolio, PortfolioSnapshot, Position, Trade, TradeSide
from stockviz.models.recommendation import Recommendation
from stockviz.models.sentiment import NewsSentiment
from stockviz.models.user import User
from stockviz.models.watchlist import Watchlist, WatchlistItem

__all__ = [
    "Alert",
    "AlertDirection",
    "Comment",
    "Dividend",
    "FxRate",
    "NewsArticle",
    "NewsSentiment",
    "OptionStatus",
    "OptionType",
    "OptionsPosition",
    "OrderStatus",
    "OrderType",
    "PendingOrder",
    "Portfolio",
    "PortfolioDividend",
    "PortfolioSnapshot",
    "Position",
    "PriceBar",
    "Recommendation",
    "Symbol",
    "SymbolMetrics",
    "Trade",
    "TradeSide",
    "User",
    "Watchlist",
    "WatchlistItem",
]
