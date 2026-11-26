"""Saved screens (Phase 6.2).

A screen is the screener's URL query string, stored under a name. The URL
stays the source of truth: opening a saved screen is opening its link, and a
screen can still be shared as a link without saving it.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Column, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy import false as sa_false
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow


class SavedScreen(SQLModel, table=True):
    __tablename__ = "saved_screens"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_saved_screens_user_name"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    name: str = Field(max_length=80)
    query: str = Field(sa_column=Column(Text, nullable=False))
    # A2.2: the setup version the screen runs, if any (the query still holds
    # the filters; a screen saved before A2.2 has none).
    setup_version_id: int | None = Field(
        default=None, foreign_key="setup_versions.id", index=True, nullable=True
    )
    # A2.3: a notification when the rule's members change (nightly
    # `screen-runs`). Needs a setup version.
    notify_on_change: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default=sa_false())
    )
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


_JSON = JSON().with_variant(JSONB(), "postgresql")


class ScreenRun(SQLModel, table=True):
    """A setup version's members on one session (A2.3, nightly ``screen-runs``).

    One row per (version, session date): a rerun of the night replaces it.
    ``members`` are the instrument ids whose rule was met; ``not_evaluated``
    counts the symbols whose result was unknown (never counted as members).
    """

    __tablename__ = "screen_runs"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("setup_version_id", "session_date", name="uq_screen_runs_version_session"),
    )

    id: int | None = Field(default=None, primary_key=True)
    setup_version_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("setup_versions.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    session_date: date
    # "all", or one MIC when the run covered one venue.
    venue: str = Field(default="all", max_length=16)
    universe: str = Field(max_length=64)
    members: list[int] = Field(default_factory=list, sa_column=Column(_JSON, nullable=False))
    member_count: int = Field(default=0)
    evaluated: int = Field(default=0)
    not_evaluated: int = Field(default=0)
    # Venue -> the session each venue was judged on.
    sessions: dict[str, Any] | None = Field(default=None, sa_column=Column(_JSON, nullable=True))
    computed_at: datetime = Field(default_factory=utcnow, nullable=False)
