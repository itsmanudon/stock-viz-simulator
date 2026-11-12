"""SQLModel ORM models for StockViz.

All models are imported here so that ``SQLModel.metadata`` is populated when
Alembic runs autogenerate. Keep this module side-effect-free apart from the
imports themselves.
"""

from stockviz.models.aegis import (
    AegisAnalysis,
    AegisDocument,
    AegisDocumentEntity,
    AegisEvent,
    AegisMapping,
    AegisSyncRun,
    AegisSyncState,
)
from stockviz.models.alert import Alert, AlertDirection
from stockviz.models.auth_rate_limit import AuthRateLimit
from stockviz.models.comment import Comment
from stockviz.models.corporate_action import CorporateAction, CorporateActionApplication
from stockviz.models.dividend import Dividend, PortfolioDividend
from stockviz.models.earnings import EarningsEvent
from stockviz.models.events import ConsumerInbox, OutboxEvent, PortfolioTradeActivity
from stockviz.models.execution import SimulatedExecution
from stockviz.models.experiment import Experiment, ExperimentRun
from stockviz.models.fundamentals import FundamentalFact
from stockviz.models.instrument import Instrument, InstrumentIdentifier
from stockviz.models.job_run import JobRun
from stockviz.models.market import (
    FxRate,
    NewsArticle,
    PriceBar,
    QuarantinedPriceBar,
    Symbol,
)
from stockviz.models.metrics import SymbolMetrics
from stockviz.models.option import OptionsPosition, OptionStatus, OptionType
from stockviz.models.order import OrderStatus, OrderType, PendingOrder
from stockviz.models.portfolio import (
    CashBalance,
    FxConversion,
    Portfolio,
    PortfolioSnapshot,
    Position,
    Trade,
    TradeSide,
)
from stockviz.models.recommendation import Recommendation
from stockviz.models.replay import (
    ReplayFill,
    ReplayJournal,
    ReplayPosition,
    ReplaySession,
    ReplaySessionStatus,
)
from stockviz.models.screen import SavedScreen
from stockviz.models.sentiment import NewsSentiment
from stockviz.models.user import User
from stockviz.models.watchlist import Watchlist, WatchlistItem

__all__ = [
    "AegisAnalysis",
    "AegisDocument",
    "AegisDocumentEntity",
    "AegisEvent",
    "AegisMapping",
    "AegisSyncRun",
    "AegisSyncState",
    "Alert",
    "AlertDirection",
    "AuthRateLimit",
    "CashBalance",
    "Comment",
    "ConsumerInbox",
    "CorporateAction",
    "CorporateActionApplication",
    "Dividend",
    "EarningsEvent",
    "Experiment",
    "ExperimentRun",
    "FundamentalFact",
    "FxConversion",
    "FxRate",
    "Instrument",
    "InstrumentIdentifier",
    "JobRun",
    "NewsArticle",
    "NewsSentiment",
    "OptionStatus",
    "OptionType",
    "OptionsPosition",
    "OrderStatus",
    "OrderType",
    "OutboxEvent",
    "PendingOrder",
    "Portfolio",
    "PortfolioDividend",
    "PortfolioSnapshot",
    "PortfolioTradeActivity",
    "Position",
    "PriceBar",
    "QuarantinedPriceBar",
    "Recommendation",
    "ReplayFill",
    "ReplayJournal",
    "ReplayPosition",
    "ReplaySession",
    "ReplaySessionStatus",
    "SavedScreen",
    "SimulatedExecution",
    "Symbol",
    "SymbolMetrics",
    "Trade",
    "TradeSide",
    "User",
    "Watchlist",
    "WatchlistItem",
]

# Identity triggers for schemas built by create_all (Phase 4.4a).
import stockviz.db_identity  # noqa: F401
