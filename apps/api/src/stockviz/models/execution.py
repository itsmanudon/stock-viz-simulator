"""Durable simulation provenance for live equity paper fills (SIM-04).

The financial ``Trade`` row stays a simple ledger entry. This table snapshots
the kernel ``FillDecision`` that priced that trade so historical fills remain
explainable after profile definitions change.

Pre-SIM-04 trades have no row here. That is expected, not an error in the
ledger.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Column, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow


class SimulatedExecution(SQLModel, table=True):
    """1:1 provenance for a live equity ``Trade`` produced by the simulator."""

    __tablename__ = "simulated_executions"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("trade_id", name="uq_simulated_executions_trade_id"),)

    id: int | None = Field(default=None, primary_key=True)
    trade_id: int = Field(foreign_key="trades.id")

    profile_name: str = Field(max_length=64)
    model_version: str = Field(max_length=32)
    reference_price: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(18, 6), nullable=True)
    )
    fill_price: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    reason: str = Field(sa_column=Column(Text, nullable=False))
    assumptions: list[str] = Field(
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
    )
    market_interval: str = Field(max_length=16)
    # Kernel order type that produced this fill (market / limit / …). Side and
    # ticker live on Trade; they are not duplicated here.
    order_type: str = Field(max_length=16)

    evaluated_at: datetime = Field(nullable=False)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
