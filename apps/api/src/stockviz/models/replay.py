"""Isolated replay-session state (SIM-05).

Replay fills are not live paper trades. They do not FK to ``trades`` and they
do not share cash or positions with the user's ``Portfolio``. Provenance lives
on ``ReplayFill`` itself rather than ``simulated_executions.trade_id``.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Column, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow


class ReplaySessionStatus(enum.StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class ReplaySession(SQLModel, table=True):
    """One isolated paper book driven by a simulation clock."""

    __tablename__ = "replay_sessions"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)

    profile_name: str = Field(max_length=64)
    model_version: str = Field(max_length=32)
    # Naive UTC. The replay adapter labels this UTC before constructing
    # SimulationClock. It is not datetime.now and not PriceBar.ts.
    clock_now: datetime = Field(nullable=False, index=True)
    starting_cash: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    cash_balance: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    status: str = Field(default=ReplaySessionStatus.OPEN.value, max_length=16)

    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class ReplayPosition(SQLModel, table=True):
    """Isolated holding for one (session, ticker). No FK onto live symbols."""

    __tablename__ = "replay_positions"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("session_id", "ticker", name="uq_replay_positions_session_ticker"),
    )

    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="replay_sessions.id", index=True)
    ticker: str = Field(max_length=16)
    quantity: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    avg_cost: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))


class ReplayFill(SQLModel, table=True):
    """One successful replay fill plus snapshotted kernel provenance.

    There is no ``trade_id``. Live ``simulated_executions`` stay 1:1 with
    ``trades``; replay must not share that FK.
    """

    __tablename__ = "replay_fills"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="replay_sessions.id", index=True)
    ticker: str = Field(max_length=16)
    side: str = Field(max_length=8)
    quantity: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    fill_price: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    realized_pnl: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(20, 6), nullable=True)
    )

    profile_name: str = Field(max_length=64)
    model_version: str = Field(max_length=32)
    reference_price: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(18, 6), nullable=True)
    )
    reason: str = Field(sa_column=Column(Text, nullable=False))
    assumptions: list[str] = Field(
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
    )
    market_interval: str = Field(max_length=16)
    order_type: str = Field(max_length=16)
    evaluated_at: datetime = Field(nullable=False)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
