"""Pure deterministic execution kernel (SIM-01).

Live MARKET and pending equity paper fills call ``evaluate_order``.
Accounting stays in ``services.trading.apply_fill``. Replay sessions own a
``SimulationClock`` and never read the wall clock for evaluation.
See ``docs/SIMULATION.md``.
"""

from stockviz.services.simulation.clock import SimulationClock, SimulationClockError
from stockviz.services.simulation.contracts import (
    NO_COSTS,
    CostModel,
    ExecutionProfile,
    ExecutionTrace,
    FillDecision,
    FillStatus,
    MarketSnapshot,
    OrderIntent,
    OrderSide,
    SimulationOrderType,
)
from stockviz.services.simulation.engine import (
    OcoDecision,
    cost_adjusted,
    evaluate_oco_exit,
    evaluate_order,
    evaluate_range_stop,
)
from stockviz.services.simulation.fees import (
    FEE_SCHEDULES,
    FeeBreakdown,
    FeeSchedule,
    UnknownFeeScheduleError,
    get_fee_schedule,
)
from stockviz.services.simulation.ledger import (
    SimFill,
    SimInsufficientCash,
    SimInsufficientPosition,
    SimLedger,
    SimPosition,
)
from stockviz.services.simulation.profiles import (
    INTRABAR_OHLC,
    INTRABAR_UNKNOWN_LABEL,
    LEGACY_CLOSE,
    LEGACY_CLOSE_ASSUMPTIONS,
    LEGACY_CLOSE_MODEL_VERSION,
    LEGACY_CLOSE_NAME,
    NEXT_OPEN,
    is_intrabar_ohlc,
    is_legacy_close,
)
from stockviz.services.simulation.registry import (
    BACKTEST_PROFILES,
    LIVE_PAPER_EXECUTION_PROFILE,
    REPLAY_PROFILES,
    UnknownExecutionProfileError,
    get_execution_profile,
    replay_profile,
)

__all__ = [
    "BACKTEST_PROFILES",
    "FEE_SCHEDULES",
    "INTRABAR_OHLC",
    "INTRABAR_UNKNOWN_LABEL",
    "LEGACY_CLOSE",
    "LEGACY_CLOSE_ASSUMPTIONS",
    "LEGACY_CLOSE_MODEL_VERSION",
    "LEGACY_CLOSE_NAME",
    "LIVE_PAPER_EXECUTION_PROFILE",
    "NEXT_OPEN",
    "NO_COSTS",
    "REPLAY_PROFILES",
    "CostModel",
    "ExecutionProfile",
    "ExecutionTrace",
    "FeeBreakdown",
    "FeeSchedule",
    "FillDecision",
    "FillStatus",
    "MarketSnapshot",
    "OcoDecision",
    "OrderIntent",
    "OrderSide",
    "SimFill",
    "SimInsufficientCash",
    "SimInsufficientPosition",
    "SimLedger",
    "SimPosition",
    "SimulationClock",
    "SimulationClockError",
    "SimulationOrderType",
    "UnknownExecutionProfileError",
    "UnknownFeeScheduleError",
    "cost_adjusted",
    "evaluate_oco_exit",
    "evaluate_order",
    "evaluate_range_stop",
    "get_execution_profile",
    "get_fee_schedule",
    "is_intrabar_ohlc",
    "is_legacy_close",
    "replay_profile",
]
