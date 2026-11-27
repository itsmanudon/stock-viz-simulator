"""Classroom cohorts and auto-graded drill assignments (A10.2, M12.1, M12.2).

Owner, 27 Nov 2026: invite codes, members opt in, and the instructor sees only
process scores (each drill's plan checks), never P&L, R, fills or books.

- ``Cohort``: an instructor's class, joined by its ``invite_code``.
- ``CohortMember``: a student who joined and consented (``consented_at``).
- ``CohortAssignment``: a drill-deck recipe (A4.7's ``DrillDeckIn``, seed
  fixed and anonymised, so every student drills the same triggers) and its
  rubric (the share of traded drills that followed the plan).
- ``AssignmentDeck``: the deck one student made from an assignment.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, ForeignKey, Integer, UniqueConstraint
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow


class Cohort(SQLModel, table=True):
    __tablename__ = "cohorts"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="users.id", index=True, ondelete="CASCADE")
    name: str = Field(max_length=120)
    invite_code: str = Field(max_length=16, unique=True)
    created_at: datetime = Field(default_factory=utcnow)
    archived_at: datetime | None = None


class CohortMember(SQLModel, table=True):
    __tablename__ = "cohort_members"  # pyright: ignore[reportAssignmentType]

    cohort_id: int = Field(
        sa_column=Column(Integer, ForeignKey("cohorts.id", ondelete="CASCADE"), primary_key=True)
    )
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    )
    joined_at: datetime = Field(default_factory=utcnow)
    consented_at: datetime = Field(default_factory=utcnow)


class CohortAssignment(SQLModel, table=True):
    __tablename__ = "cohort_assignments"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    cohort_id: int = Field(foreign_key="cohorts.id", index=True, ondelete="CASCADE")
    title: str = Field(max_length=120)
    recipe: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    min_followed_pct: int = Field(default=70)
    due_on: date_type | None = None
    created_at: datetime = Field(default_factory=utcnow)


class AssignmentDeck(SQLModel, table=True):
    __tablename__ = "assignment_decks"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("deck_id", name="uq_assignment_decks_deck"),)

    assignment_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("cohort_assignments.id", ondelete="CASCADE"), primary_key=True
        )
    )
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    )
    deck_id: int = Field(
        sa_column=Column(Integer, ForeignKey("drill_decks.id", ondelete="CASCADE"), nullable=False)
    )
    started_at: datetime = Field(default_factory=utcnow)
