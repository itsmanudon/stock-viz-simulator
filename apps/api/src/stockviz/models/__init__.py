"""SQLModel ORM models for StockViz.

All models are imported here so that ``SQLModel.metadata`` is populated when
Alembic runs autogenerate. Keep this module side-effect-free apart from the
imports themselves.
"""

from stockviz.models.alert import Alert, AlertDirection
from stockviz.models.comment import Comment
from stockviz.models.dividend import Dividend, PortfolioDividend
from stockviz.models.market import FxRate, NewsArticle, PriceBar, Symbol
from stockviz.models.option import OptionsPosition, OptionStatus, OptionType
from stockviz.models.portfolio import Portfolio, PortfolioSnapshot, Position, Trade, TradeSide
from stockviz.models.recommendation import Recommendation
from stockviz.models.user import User
from stockviz.models.watchlist import Watchlist, WatchlistItem

__all__ = [
    "Alert",
    "AlertDirection",
    "Comment",
    "Dividend",
    "FxRate",
    "NewsArticle",
    "OptionStatus",
    "OptionType",
    "OptionsPosition",
    "Portfolio",
    "PortfolioDividend",
    "PortfolioSnapshot",
    "Position",
    "PriceBar",
    "Recommendation",
    "Symbol",
    "Trade",
    "TradeSide",
    "User",
    "Watchlist",
    "WatchlistItem",
]
