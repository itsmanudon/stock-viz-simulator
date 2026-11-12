"""Experiment registry (Phase 5.4).

An ``Experiment`` names a question (a hypothesis); each ``ExperimentRun`` is
one stored backtest: the exact request, the kernel profile and fee schedule,
the code version, the dataset fingerprint, and the result. A rerun replays
the stored request and must match the stored result to the micro-unit, or
reports that the data changed (a different fingerprint). Walk-forward and
sweep windows (5.5) are runs with a ``parent_run_id``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


class Experiment(SQLModel, table=True):
    __tablename__ = "experiments"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    name: str = Field(max_length=120)
    hypothesis: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=utcnow, nullable=False)


class ExperimentRun(SQLModel, table=True):
    __tablename__ = "experiment_runs"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    experiment_id: int | None = Field(default=None, foreign_key="experiments.id", index=True)
    parent_run_id: int | None = Field(default=None, foreign_key="experiment_runs.id", index=True)
    kind: str = Field(default="single", max_length=16)  # single | walk_forward | window
    ticker: str = Field(max_length=16, index=True)
    request: dict[str, Any] = Field(sa_column=Column(JSON_TYPE, nullable=False))
    execution_profile: str = Field(max_length=40)
    fee_schedule: str = Field(max_length=40)
    code_version: str = Field(max_length=64)
    dataset_fingerprint: str = Field(max_length=64)
    bar_count: int
    first_bar_at: datetime | None = None
    last_bar_at: datetime | None = None
    result: dict[str, Any] = Field(sa_column=Column(JSON_TYPE, nullable=False))
    created_at: datetime = Field(default_factory=utcnow, nullable=False, index=True)
