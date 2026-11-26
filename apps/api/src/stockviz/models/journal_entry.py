"""Journal entries (A5.5, M10.3): one row per round trip.

A round trip is a position from flat to flat in one book (paper or imported)
or one replay session: it opens when the quantity leaves zero and closes when
it returns, so partial sells stay in the same entry (the replay episode rule,
``services/replay/forensics.py::reconstruct_episodes``). A position still held
is an open entry.

**Only the grouping and the user's text are stored.** ``journal_entry_fills``
links each fill (a ``trades`` row for paper and imported books, a
``replay_fills`` row for replay) to its entry. Net P&L, MAE, MFE, R and plan
adherence are computed on every read from the fills, the stored daily bars and
the plan, so a corrected bar, a split restatement or an import rebuild
corrects the journal (``services/journal/entries.py``).

**Following the fills.** ``sync_user`` regroups a user's fills on each read and
matches each round trip to its row by ``entry_key``, a stable name for the
entry's first fill (an imported fill by its broker trade id, so deleting an
import and importing the same file again finds the same row, notes intact).
A row whose fills are gone is deleted when it has no text, or kept as
``detached`` (hidden from the journal) when it does.

``plan_id``, ``status``, ``opened_at`` and ``closed_at`` are copies of what
the fills say, kept for filtering; the sync rewrites them.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow
from stockviz.models.instrument import ID_TYPE

ENTRY_SOURCES = ("paper", "imported", "replay")
ENTRY_STATUSES = ("open", "closed", "detached")
MAX_TEXT_LENGTH = 4000
MAX_ENTRY_TAGS = 12
MAX_ENTRY_TAG_LENGTH = 32


class JournalEntry(SQLModel, table=True):
    __tablename__ = "journal_entries"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("user_id", "entry_key", name="uq_journal_entries_user_key"),
        CheckConstraint(
            "source IN ('paper', 'imported', 'replay')", name="ck_journal_entries_source"
        ),
        CheckConstraint(
            "status IN ('open', 'closed', 'detached')", name="ck_journal_entries_status"
        ),
        CheckConstraint(
            "(source = 'replay' AND replay_session_id IS NOT NULL AND portfolio_id IS NULL) "
            "OR (source IN ('paper', 'imported') AND portfolio_id IS NOT NULL "
            "AND replay_session_id IS NULL)",
            name="ck_journal_entries_home",
        ),
        Index("ix_journal_entries_user_opened", "user_id", "opened_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    source: str = Field(sa_column=Column(String(16), nullable=False))
    portfolio_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=True, index=True
        ),
    )
    replay_session_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("replay_sessions.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    instrument_id: int = Field(
        sa_column=Column(ID_TYPE, ForeignKey("instruments.id"), nullable=False, index=True)
    )
    entry_key: str = Field(sa_column=Column(String(160), nullable=False))
    """Stable name of the entry's first fill (see the module docstring)."""
    plan_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("trade_plans.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    status: str = Field(sa_column=Column(String(12), nullable=False))
    opened_at: datetime = Field(nullable=False)
    closed_at: datetime | None = Field(default=None, nullable=True)

    # The user's text: always editable.
    review_notes: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    mistakes: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    lessons: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    setup_tags: list[str] = Field(
        default_factory=list,
        sa_column=Column(
            JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
            server_default=text("'[]'"),
        ),
    )
    mistake_tags: list[str] = Field(
        default_factory=list,
        sa_column=Column(
            JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
            server_default=text("'[]'"),
        ),
    )

    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)

    @property
    def has_text(self) -> bool:
        return bool(
            (self.review_notes or "").strip()
            or (self.mistakes or "").strip()
            or (self.lessons or "").strip()
            or self.setup_tags
            or self.mistake_tags
        )


class JournalEntryFill(SQLModel, table=True):
    """One fill of an entry: a ``trades`` row or a ``replay_fills`` row."""

    __tablename__ = "journal_entry_fills"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint(
            "(trade_id IS NULL) <> (replay_fill_id IS NULL)", name="ck_journal_entry_fills_one"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    entry_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("journal_entries.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    trade_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("trades.id", ondelete="CASCADE"), nullable=True, unique=True
        ),
    )
    replay_fill_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("replay_fills.id", ondelete="CASCADE"),
            nullable=True,
            unique=True,
        ),
    )


__all__ = [
    "ENTRY_SOURCES",
    "ENTRY_STATUSES",
    "MAX_ENTRY_TAGS",
    "MAX_ENTRY_TAG_LENGTH",
    "MAX_TEXT_LENGTH",
    "JournalEntry",
    "JournalEntryFill",
]
