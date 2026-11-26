"""Drills and decks (A4.7, M9.3).

A **deck** is a saved set of drills drawn from one rule's real historical
triggers: the rule (always a setup version; inline text is saved as one), a
universe, a date range, K, the lead-in N and follow-on M bars, and the seed
the K triggers were sampled with. A **drill** is one trigger: a replay
session (``replay_sessions``) that opens at the trigger bar with N bars of
lead-in visible and ends at least M bars later. Anonymised drills show the
symbol as "Stock A" (B, C... by position in the deck) and every date shifted
by ``date_offset_weeks`` whole weeks; ``revealed_at`` ends that.

A **plan** (``drill_plans``) is what the trader means to do before the first
order: planned entry, stop and size (the A5 journal's fields). It keys on the
replay session so A5's journal can absorb it; it locks at the session's
first fill. Drills are scored on process (did the trader follow the plan),
never on profit, and nothing ranks one user against another.

Deleting a deck deletes its drills, their plans and their replay sessions.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow

MAX_DRILLS_PER_DECK = 25
MAX_DECKS_PER_USER = 100


class DrillDeck(SQLModel, table=True):
    __tablename__ = "drill_decks"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint("k BETWEEN 1 AND 25", name="ck_drill_decks_k"),
        CheckConstraint("lead_bars >= 1 AND follow_bars >= 1", name="ck_drill_decks_bars"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    name: str = Field(max_length=120)
    setup_version_id: int = Field(
        sa_column=Column(Integer, ForeignKey("setup_versions.id"), nullable=False, index=True)
    )
    rule_text: str = Field(sa_column=Column(Text, nullable=False))
    rule_hash: str = Field(max_length=64)
    universe: dict[str, Any] = Field(
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
    )
    """The request's universe and what it resolved to: ``{kind, name,
    tickers | watchlist_id | market, symbols}``."""
    from_date: date = Field(nullable=False)
    to_date: date = Field(nullable=False)
    k: int
    lead_bars: int
    follow_bars: int
    seed: int = Field(sa_column=Column(BigInteger, nullable=False))
    anonymised: bool = Field(
        default=True, sa_column=Column(Boolean, nullable=False, server_default=text("true"))
    )
    triggers_found: int = 0
    """Every false-to-true edge of the rule in the range across the universe."""
    triggers_eligible: int = 0
    """Those left after the lag rule: the set the K were sampled from."""
    lag_skipped: int = 0
    """Edges on NSE/BSE symbols whose session would end inside the 30-day lag."""
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class Drill(SQLModel, table=True):
    __tablename__ = "drills"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("deck_id", "position", name="uq_drills_deck_position"),
        UniqueConstraint("session_id", name="uq_drills_session"),
    )

    id: int | None = Field(default=None, primary_key=True)
    deck_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("drill_decks.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    position: int
    """0-based; the label is "Stock " + the letter at this position."""
    session_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("replay_sessions.id", ondelete="CASCADE"), nullable=False
        )
    )
    ticker: str = Field(max_length=16)
    trigger_at: datetime = Field(nullable=False)
    """The trigger bar's ``PriceBar.ts`` (naive UTC)."""
    trigger_date: date = Field(nullable=False)
    """The trigger bar's venue date: a false-to-true edge of the rule."""
    date_offset_weeks: int
    """Shown dates = real dates - this many weeks (negative: later). Whole
    weeks, so every weekday is the real one."""
    revealed_at: datetime | None = Field(default=None, nullable=True)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class DrillPlan(SQLModel, table=True):
    """The trader's plan before the first order (A5 journal fields): entry,
    stop and size, long. Keyed on the replay session; locks at its first fill."""

    __tablename__ = "drill_plans"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint("side IN ('long')", name="ck_drill_plans_side"),
        CheckConstraint(
            "planned_entry > 0 AND planned_stop > 0 AND planned_size > 0",
            name="ck_drill_plans_positive",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("replay_sessions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        )
    )
    side: str = Field(
        default="long", sa_column=Column(String(8), nullable=False, server_default="long")
    )
    planned_entry: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    planned_stop: Decimal = Field(sa_column=Column(Numeric(18, 6), nullable=False))
    planned_size: Decimal = Field(sa_column=Column(Numeric(20, 6), nullable=False))
    note: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    locked_at: datetime | None = Field(default=None, nullable=True)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


__all__ = ["MAX_DECKS_PER_USER", "MAX_DRILLS_PER_DECK", "Drill", "DrillDeck", "DrillPlan"]
