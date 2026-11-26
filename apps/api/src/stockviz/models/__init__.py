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
from stockviz.models.alert import Alert, AlertDirection, AlertEvent, AlertKind, AlertRepeat
from stockviz.models.auth_rate_limit import AuthRateLimit
from stockviz.models.broker_import import BrokerFill, ImportBatch
from stockviz.models.checklist import ChecklistEvidence, ChecklistScore
from stockviz.models.corporate_action import CorporateAction, CorporateActionApplication
from stockviz.models.data_file import DataFile
from stockviz.models.delivery import (
    ChannelKind,
    DeliveryAttempt,
    DeliveryStatus,
    NotificationChannel,
)
from stockviz.models.dividend import Dividend, PortfolioDividend
from stockviz.models.drawing import Drawing
from stockviz.models.drill import Drill, DrillDeck
from stockviz.models.earnings import EarningsEvent
from stockviz.models.eod import EodExtras, EodRaw
from stockviz.models.events import ConsumerInbox, OutboxEvent, PortfolioTradeActivity
from stockviz.models.execution import SimulatedExecution
from stockviz.models.experiment import Experiment, ExperimentRun
from stockviz.models.feed_stream import FeedStream
from stockviz.models.fundamentals import FundamentalFact
from stockviz.models.import_column_map import ImportColumnMap
from stockviz.models.indicator_evidence import IndicatorEvidence
from stockviz.models.instrument import Instrument, InstrumentIdentifier
from stockviz.models.intraday import IntradayBar, IntradayFile
from stockviz.models.job_run import JobRun
from stockviz.models.journal_entry import JournalEntry, JournalEntryFill
from stockviz.models.market import (
    FxRate,
    PriceBar,
    QuarantinedPriceBar,
    Symbol,
)
from stockviz.models.metrics import SymbolMetrics
from stockviz.models.notification import Notification, NotificationCategory
from stockviz.models.option import (
    OptionCover,
    OptionSide,
    OptionsPosition,
    OptionStatus,
    OptionType,
)
from stockviz.models.option_quote import OptionChainQuote
from stockviz.models.option_strategy import OptionStrategy, StrategyKind, StrategyStatus
from stockviz.models.order import OrderStatus, OrderType, PendingOrder
from stockviz.models.portfolio import (
    MAX_BOOKS_PER_USER,
    BookKind,
    CashBalance,
    FxConversion,
    HolderKind,
    Portfolio,
    PortfolioSnapshot,
    Position,
    Trade,
    TradeSide,
)
from stockviz.models.replay import (
    ReplayDrawing,
    ReplayFill,
    ReplayOrder,
    ReplayOrderStatus,
    ReplayPosition,
    ReplaySession,
    ReplaySessionStatus,
)
from stockviz.models.risk_limit import RiskLimit
from stockviz.models.screen import SavedScreen, ScreenRun
from stockviz.models.setup import Setup, SetupVersion, Thesis
from stockviz.models.trade_plan import TradePlan
from stockviz.models.trial import BacktestTrial, HoldoutUnlock
from stockviz.models.user import User
from stockviz.models.watchlist import ColumnSet, Watchlist, WatchlistItem

__all__ = [
    "MAX_BOOKS_PER_USER",
    "AegisAnalysis",
    "AegisDocument",
    "AegisDocumentEntity",
    "AegisEvent",
    "AegisMapping",
    "AegisSyncRun",
    "AegisSyncState",
    "Alert",
    "AlertDirection",
    "AlertEvent",
    "AlertKind",
    "AlertRepeat",
    "AuthRateLimit",
    "BacktestTrial",
    "BookKind",
    "BrokerFill",
    "CashBalance",
    "ChannelKind",
    "ChecklistEvidence",
    "ChecklistScore",
    "ColumnSet",
    "ConsumerInbox",
    "CorporateAction",
    "CorporateActionApplication",
    "DataFile",
    "DeliveryAttempt",
    "DeliveryStatus",
    "Dividend",
    "Drawing",
    "Drill",
    "DrillDeck",
    "EarningsEvent",
    "EodExtras",
    "EodRaw",
    "Experiment",
    "ExperimentRun",
    "FeedStream",
    "FundamentalFact",
    "FxConversion",
    "FxRate",
    "HolderKind",
    "HoldoutUnlock",
    "ImportBatch",
    "ImportColumnMap",
    "IndicatorEvidence",
    "Instrument",
    "InstrumentIdentifier",
    "IntradayBar",
    "IntradayFile",
    "JobRun",
    "JournalEntry",
    "JournalEntryFill",
    "Notification",
    "NotificationCategory",
    "NotificationChannel",
    "OptionChainQuote",
    "OptionCover",
    "OptionSide",
    "OptionStatus",
    "OptionStrategy",
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
    "ReplayDrawing",
    "ReplayFill",
    "ReplayOrder",
    "ReplayOrderStatus",
    "ReplayPosition",
    "ReplaySession",
    "ReplaySessionStatus",
    "RiskLimit",
    "SavedScreen",
    "ScreenRun",
    "Setup",
    "SetupVersion",
    "SimulatedExecution",
    "StrategyKind",
    "StrategyStatus",
    "Symbol",
    "SymbolMetrics",
    "Thesis",
    "Trade",
    "TradePlan",
    "TradeSide",
    "User",
    "Watchlist",
    "WatchlistItem",
]

# Identity triggers for schemas built by create_all (Phase 4.4a).
import stockviz.db_identity  # noqa: F401
