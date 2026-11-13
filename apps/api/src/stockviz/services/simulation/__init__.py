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
from stockviz.services.simulation.engine import cost_adjusted, evaluate_order
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
    LEGACY_CLOSE,
    LEGACY_CLOSE_ASSUMPTIONS,
    LEGACY_CLOSE_MODEL_VERSION,
    LEGACY_CLOSE_NAME,
    NEXT_OPEN,
    is_legacy_close,
)
from stockviz.services.simulation.registry import (
    LIVE_PAPER_EXECUTION_PROFILE,
    UnknownExecutionProfileError,
    get_execution_profile,
)

__all__ = [
    "FEE_SCHEDULES",
    "LEGACY_CLOSE",
    "LEGACY_CLOSE_ASSUMPTIONS",
    "LEGACY_CLOSE_MODEL_VERSION",
    "LEGACY_CLOSE_NAME",
    "LIVE_PAPER_EXECUTION_PROFILE",
    "NEXT_OPEN",
    "NO_COSTS",
    "CostModel",
    "ExecutionProfile",
    "ExecutionTrace",
    "FeeBreakdown",
    "FeeSchedule",
    "FillDecision",
    "FillStatus",
    "MarketSnapshot",
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
    "evaluate_order",
    "get_execution_profile",
    "get_fee_schedule",
    "is_legacy_close",
]
