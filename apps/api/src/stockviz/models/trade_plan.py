"""Trade plans (A5.4, M10.3): what the trader means to do, written down.

One table for every plan a user writes: a paper order's plan (``source =
'paper'``, in one book), a replay session's journal (``'replay'``) and a
drill's plan (``'drill'``), both keyed on the replay session, and, from A5.5,
a plan paired with an imported fill (``'imported'``). It absorbed A4.7's
``drill_plans`` and SIM-07's ``replay_journals`` (migration ``b5d4a7e1c902``;
both tables are archived in the ``archive`` schema).

**The lock rule is A4.7's:** a plan locks at the first fill it covers.
``locked_at`` is that fill's time (a paper trade's ``ts``; a replay fill's
simulated ``evaluated_at``). After the lock the plan's entry, stop, target,
size, setup, thesis, why, invalidation, horizon and confidence are frozen;
``notes`` and ``tags`` stay editable. Edits are refused with 409, not ignored.

**Written after entry.** A plan that first meets a fill already made before
the plan existed (a paper plan written for an open position, a replay journal
started after the first fill, an imported fill) is allowed and labelled
``written_after_entry``. It is never "locked" (``locked_at`` stays null), but
it is frozen the same way, since the entry it describes is already history.
``first_fill_at`` records the first fill either way.

Derived numbers (R:R, risk, R achieved) are never stored.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow

PLAN_SOURCES = ("paper", "replay", "drill", "imported")
PLAN_STATUSES = ("open", "active", "closed", "cancelled")
PLAN_SIDES = ("long", "short")
MAX_PLANS_PER_USER = 2000
MAX_TAGS = 12
MAX_TAG_LENGTH = 32

# bigint in Postgres (instruments.id); SQLite only autoincrements INTEGER.
_ID = BigInteger().with_variant(Integer(), "sqlite")


class TradePlan(SQLModel, table=True):
    __tablename__ = "trade_plans"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint(
            "source IN ('paper', 'replay', 'drill', 'imported')", name="ck_trade_plans_source"
        ),
        CheckConstraint("side IN ('long', 'short')", name="ck_trade_plans_side"),
        CheckConstraint(
            "status IN ('open', 'active', 'closed', 'cancelled')", name="ck_trade_plans_status"
        ),
        CheckConstraint(
            "(planned_entry IS NULL OR planned_entry > 0) "
            "AND (planned_stop IS NULL OR planned_stop > 0) "
            "AND (planned_target IS NULL OR planned_target > 0) "
            "AND (planned_size IS NULL OR planned_size > 0)",
            name="ck_trade_plans_positive",
        ),
        CheckConstraint(
            "(source IN ('replay', 'drill') AND replay_session_id IS NOT NULL) "
            "OR (source IN ('paper', 'imported') AND portfolio_id IS NOT NULL)",
            name="ck_trade_plans_home",
        ),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 1 AND 5", name="ck_trade_plans_confidence"
        ),
        CheckConstraint(
            "NOT (written_after_entry AND locked_at IS NOT NULL)",
            name="ck_trade_plans_lock_or_after",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    portfolio_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=True, index=True
        ),
    )
    """The book (paper, imported). Null for replay and drill plans."""
    replay_session_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("replay_sessions.id", ondelete="CASCADE"),
            nullable=True,
            unique=True,
        ),
    )
    """The replay session (replay, drill): one plan per session."""
    instrument_id: int = Field(
        sa_column=Column(_ID, ForeignKey("instruments.id"), nullable=False, index=True)
    )
    source: str = Field(sa_column=Column(String(16), nullable=False))
    side: str = Field(
        default="long", sa_column=Column(String(8), nullable=False, server_default="long")
    )

    planned_entry: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(18, 6), nullable=True)
    )
    planned_stop: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(18, 6), nullable=True)
    )
    planned_target: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(18, 6), nullable=True)
    )
    planned_size: Decimal | None = Field(
        default=None, sa_column=Column(Numeric(20, 6), nullable=True)
    )

    setup_version_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("setup_versions.id"), nullable=True, index=True),
    )
    thesis_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("theses.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    thesis_text: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    why: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    """The reason, in a line (the drill plan's "Why")."""
    invalidation: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    horizon_bars: int | None = Field(default=None, nullable=True)
    confidence: int | None = Field(default=None, nullable=True)

    notes: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    """Editable after the lock (the replay journal's reflection)."""
    tags: list[str] = Field(
        default_factory=list,
        sa_column=Column(
            JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
            server_default=text("'[]'"),
        ),
    )
    """Editable after the lock."""

    status: str = Field(
        default="open", sa_column=Column(String(16), nullable=False, server_default="open")
    )
    locked_at: datetime | None = Field(default=None, nullable=True)
    first_fill_at: datetime | None = Field(default=None, nullable=True)
    written_after_entry: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)

    @property
    def frozen(self) -> bool:
        """True once any fill is linked: the plan fields can no longer change."""
        return self.locked_at is not None or self.written_after_entry


__all__ = [
    "MAX_PLANS_PER_USER",
    "MAX_TAGS",
    "MAX_TAG_LENGTH",
    "PLAN_SIDES",
    "PLAN_SOURCES",
    "PLAN_STATUSES",
    "TradePlan",
]
