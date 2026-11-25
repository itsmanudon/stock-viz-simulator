"""The Checklist (A2.4, M4.4): nightly scores and the evidence grades.

``checklist_scores`` holds one row per (instrument, session): the six
dimension results the nightly ``checklist`` job judged on that session, each
with its reason and the setup version that judged it. A rerun of the night
replaces the row. Keyed by ``instrument_id`` (no ticker column, so no
identity trigger), like theses.

``checklist_evidence`` holds the weekly ``checklist-evidence`` study: per
dimension setup version, universe and window, the forward 20-session return
after the rule turned true, net of fees, against the base rate, and the A-D
grade (``services/checklist/evidence.py``).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Column, Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow

_JSON = JSON().with_variant(JSONB(), "postgresql")

GRADES = ("A", "B", "C", "D", "insufficient")


class ChecklistScore(SQLModel, table=True):
    __tablename__ = "checklist_scores"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "instrument_id", "session_date", name="uq_checklist_scores_instrument_session"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    instrument_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    session_date: date = Field(index=True)
    # [{key, scope, setup_version_id, status, reason, conditions: [{label,
    # rule, status, reason}]}], in DIMENSIONS order.
    dimensions: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(_JSON, nullable=False)
    )
    met_count: int = Field(default=0)
    evaluated_count: int = Field(default=0)
    computed_at: datetime = Field(default_factory=utcnow, nullable=False)


class ChecklistEvidence(SQLModel, table=True):
    __tablename__ = "checklist_evidence"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "setup_version_id",
            "universe",
            "window_start",
            "window_end",
            "horizon",
            name="uq_checklist_evidence_version_window",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    setup_version_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("setup_versions.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    dimension: str = Field(max_length=32)
    scope: str = Field(max_length=16)
    universe: str = Field(max_length=64)
    point_in_time: bool = Field(sa_column=Column(Boolean, nullable=False))
    survivorship_biased: bool = Field(sa_column=Column(Boolean, nullable=False))
    window_start: date
    window_end: date
    horizon: int = Field(default=20)
    symbols: int = Field(default=0)
    n_events: int = Field(default=0)
    overlapping_skipped: int = Field(default=0)
    mean_net_return: float | None = Field(default=None, sa_column=Column(Float, nullable=True))
    base_rate: float | None = Field(default=None, sa_column=Column(Float, nullable=True))
    mean_excess: float | None = Field(default=None, sa_column=Column(Float, nullable=True))
    t_stat: float | None = Field(default=None, sa_column=Column(Float, nullable=True))
    hit_rate: float | None = Field(default=None, sa_column=Column(Float, nullable=True))
    grade: str = Field(max_length=16)
    # Fee schedule name -> events charged under it.
    fee_schedules: dict[str, Any] | None = Field(
        default=None, sa_column=Column(_JSON, nullable=True)
    )
    computed_at: datetime = Field(default_factory=utcnow, nullable=False)


__all__ = ["GRADES", "ChecklistEvidence", "ChecklistScore"]
