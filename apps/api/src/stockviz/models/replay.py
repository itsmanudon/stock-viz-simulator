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
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow
from stockviz.models.instrument import instrument_id_column


class ReplaySessionStatus(enum.StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ReplaySession(SQLModel, table=True):
    """One isolated paper book over a frozen historical 1d range.

    A4.6: the book is in the symbol's currency (``currency``, frozen at
    creation) and its fills pay ``fee_schedule`` (the A4.2 default for the
    symbol's venue, resolved once). ``lag_override`` records that the owner's
    override (``REPLAY_LAG_OVERRIDE_USER_IDS``) let an Indian session end
    inside the minimum lag.
    """

    __tablename__ = "replay_sessions"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    ticker: str = Field(foreign_key="symbols.ticker", max_length=16, index=True)
    instrument_id: int | None = Field(default=None, sa_column=instrument_id_column(required=True))

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
    currency: str = Field(
        default="USD",
        sa_column=Column(String(3), nullable=False, server_default=text("'USD'")),
    )
    fee_schedule: str = Field(
        default="none",
        sa_column=Column(String(40), nullable=False, server_default=text("'none'")),
    )
    lag_override: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )

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
    # A4.6: fees in the session currency (the session's schedule, the version
    # in force on the fill's venue date). Fills before A4.6 keep 0.
    fees: Decimal = Field(
        default=Decimal(0),
        sa_column=Column(Numeric(20, 6), nullable=False, server_default=text("0")),
    )
    fee_lines: list[dict[str, Any]] | None = Field(
        default=None, sa_column=Column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    )
    order_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("replay_orders.id", ondelete="SET NULL"), nullable=True
        ),
    )


class ReplayOrderStatus(enum.StrEnum):
    OPEN = "open"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


REPLAY_ORDER_TYPES = ("limit", "stop_loss", "take_profit")
MAX_OPEN_REPLAY_ORDERS = 20


class ReplayOrder(SQLModel, table=True):
    """A4.6: a resting limit / stop-loss / take-profit order in a session.

    Placed at the session clock (``placed_at`` = ``current_at`` then) and
    evaluated by the kernel on every later bar the session advances to, under
    the session's profile. Nothing is reserved: a fill the book cannot pay
    (cash) or deliver (shares) is ``rejected`` with the reason. Open orders
    expire when the session completes and are cancelled with it.
    """

    __tablename__ = "replay_orders"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint(
            "order_type IN ('limit', 'stop_loss', 'take_profit')",
            name="ck_replay_orders_type",
        ),
        CheckConstraint(
            "status IN ('open', 'filled', 'cancelled', 'rejected', 'expired')",
            name="ck_replay_orders_status",
        ),
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
    side: str = Field(max_length=8)
    order_type: str = Field(max_length=16)
    quantity: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    limit_price: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    status: str = Field(default=ReplayOrderStatus.OPEN.value, max_length=16)
    placed_at: datetime = Field(nullable=False)
    resolved_at: datetime | None = Field(default=None)
    reason: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class ReplayDrawing(SQLModel, table=True):
    """A4.6: a chart drawing made inside one replay session.

    Its own table, not ``drawings``: a live-chart drawing could sit on a later
    date and leak the future, so a session shows only its own, and nothing
    outside the session (the live chart, ``drawing()`` rules, other sessions)
    ever reads these. Same shape and rules as ``drawings`` (A3.2), anchored
    between the session's first bar and its clock.
    """

    __tablename__ = "replay_drawings"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("replay_sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    kind: str = Field(max_length=24)
    points: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False),
    )
    style: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False),
    )
    label: str | None = Field(default=None, max_length=80, nullable=True)
    locked: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)
