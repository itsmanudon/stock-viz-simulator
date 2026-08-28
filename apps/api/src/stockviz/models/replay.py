"""Isolated replay-session state (SIM-05).

Replay fills are not live paper trades. They do not FK to ``trades`` and they
do not share cash or positions with the user's ``Portfolio``. Provenance lives
on ``ReplayFill`` itself rather than ``simulated_executions.trade_id``.

Sessions are not deleted in product code; child rows cascade if a session
row is removed.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Column, ForeignKey, Integer, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow


class ReplaySessionStatus(enum.StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ReplaySession(SQLModel, table=True):
    """One isolated paper book over a frozen historical 1d range."""

    __tablename__ = "replay_sessions"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    ticker: str = Field(foreign_key="symbols.ticker", max_length=16, index=True)

    profile_name: str = Field(max_length=64)
    model_version: str = Field(max_length=32)
    # Naive UTC PriceBar.ts values. current_at is the currently observable bar.
    start_at: datetime = Field(nullable=False)
    current_at: datetime = Field(nullable=False, index=True)
    end_at: datetime = Field(nullable=False)
    starting_cash: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    cash_balance: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    status: str = Field(default=ReplaySessionStatus.ACTIVE.value, max_length=16, index=True)
    completed_at: datetime | None = Field(default=None)

    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class ReplayPosition(SQLModel, table=True):
    """Isolated holding for one (session, ticker)."""

    __tablename__ = "replay_positions"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("session_id", "ticker", name="uq_replay_positions_session_ticker"),
    )

    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("replay_sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
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
    session_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("replay_sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
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
