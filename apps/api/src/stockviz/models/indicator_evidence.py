"""Indicator evidence badges (A3.4, M2.6).

``indicator_evidence`` holds the ``indicator-evidence`` study: per study's
canonical signal (``services/indicators/signals.py``, a Rule DSL rule keyed by
its canonical hash), universe and window, the A2.4 evidence study's figures
and grade. The same study as ``checklist_evidence``; a separate table
because a signal is not a setup version.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Column, Float, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow

_JSON = JSON().with_variant(JSONB(), "postgresql")


class IndicatorEvidence(SQLModel, table=True):
    __tablename__ = "indicator_evidence"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "rule_hash",
            "universe",
            "window_start",
            "window_end",
            "horizon",
            name="uq_indicator_evidence_rule_window",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    indicator: str = Field(max_length=32, index=True)
    rule: str = Field(sa_column=Column(Text, nullable=False))
    rule_hash: str = Field(max_length=64)
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
    fee_schedules: dict[str, Any] | None = Field(
        default=None, sa_column=Column(_JSON, nullable=True)
    )
    computed_at: datetime = Field(default_factory=utcnow, nullable=False)


__all__ = ["IndicatorEvidence"]
