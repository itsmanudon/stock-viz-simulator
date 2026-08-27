"""Pure deterministic execution kernel (SIM-01).

Live MARKET and pending equity paper fills call ``evaluate_order``.
Accounting stays in ``services.trading.apply_fill``. See ``docs/SIMULATION.md``.
"""

from stockviz.services.simulation.contracts import (
    ExecutionProfile,
    ExecutionTrace,
    FillDecision,
    FillStatus,
    MarketSnapshot,
    OrderIntent,
    OrderSide,
    SimulationOrderType,
)
from stockviz.services.simulation.engine import evaluate_order
from stockviz.services.simulation.profiles import (
    LEGACY_CLOSE,
    LEGACY_CLOSE_ASSUMPTIONS,
    LEGACY_CLOSE_MODEL_VERSION,
    LEGACY_CLOSE_NAME,
    is_legacy_close,
)
from stockviz.services.simulation.registry import (
    LIVE_PAPER_EXECUTION_PROFILE,
    UnknownExecutionProfileError,
    get_execution_profile,
)

__all__ = [
    "LEGACY_CLOSE",
    "LEGACY_CLOSE_ASSUMPTIONS",
    "LEGACY_CLOSE_MODEL_VERSION",
    "LEGACY_CLOSE_NAME",
    "LIVE_PAPER_EXECUTION_PROFILE",
    "ExecutionProfile",
    "ExecutionTrace",
    "FillDecision",
    "FillStatus",
    "MarketSnapshot",
    "OrderIntent",
    "OrderSide",
    "SimulationOrderType",
    "UnknownExecutionProfileError",
    "evaluate_order",
    "get_execution_profile",
    "is_legacy_close",
]
