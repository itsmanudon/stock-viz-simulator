"""Persist kernel FillDecision provenance next to a live equity Trade.

The simulation package stays free of Session. This module is the trading-layer
writer: same transaction as ``apply_fill`` and the outbox row, no extra commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session

from stockviz.models import SimulatedExecution, Trade
from stockviz.services.simulation import FillDecision, FillStatus
from stockviz.services.trading.simulation_adapter import as_aware_utc


@dataclass(frozen=True, slots=True)
class FillProvenance:
    """The kernel decision plus trading-layer observation metadata.

    ``evaluated_at`` is when the adapter asked the kernel, not ``PriceBar.ts``
    and not the provenance row's ``created_at``.
    """

    decision: FillDecision
    market_interval: str
    evaluated_at: datetime
    order_type: str


def record_execution_provenance(
    session: Session,
    *,
    trade: Trade,
    provenance: FillProvenance,
) -> SimulatedExecution:
    """Stage a ``SimulatedExecution`` row for ``trade``. Does not commit."""

    if trade.id is None:
        raise ValueError("trade must be flushed before provenance is recorded")

    decision = provenance.decision
    if decision.status is not FillStatus.FILLED or decision.fill_price is None:
        raise ValueError("execution provenance is only recorded for filled decisions")

    trace = decision.trace
    evaluated_at = as_aware_utc(provenance.evaluated_at).replace(tzinfo=None)
    row = SimulatedExecution(
        trade_id=trade.id,
        profile_name=trace.profile,
        model_version=trace.model_version,
        reference_price=trace.reference_price,
        fill_price=decision.fill_price,
        reason=trace.reason,
        assumptions=list(trace.assumptions),
        market_interval=provenance.market_interval,
        order_type=provenance.order_type,
        evaluated_at=evaluated_at,
    )
    session.add(row)
    return row
