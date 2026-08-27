"""Pure deterministic execution kernel (SIM-01).

Not on the live trade-commit path. See ``docs/SIMULATION.md``.
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
)

__all__ = [
    "LEGACY_CLOSE",
    "LEGACY_CLOSE_ASSUMPTIONS",
    "LEGACY_CLOSE_MODEL_VERSION",
    "LEGACY_CLOSE_NAME",
    "ExecutionProfile",
    "ExecutionTrace",
    "FillDecision",
    "FillStatus",
    "MarketSnapshot",
    "OrderIntent",
    "OrderSide",
    "SimulationOrderType",
    "evaluate_order",
]
