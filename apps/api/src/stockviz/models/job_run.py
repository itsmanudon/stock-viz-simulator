"""One row per run of a nightly CLI job (audit OP-5).

Before this, a failed night left no trace: nothing recorded that a step ran,
`/health` only checked the database, and the cron's exit code was the only
signal. ``stockviz.cli`` writes a row when a recorded command starts and
updates it when the command ends. ``/health`` reads the newest rows.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow


class JobRun(SQLModel, table=True):
    __tablename__ = "job_runs"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    job: str = Field(max_length=64, index=True)
    started_at: datetime = Field(default_factory=utcnow, index=True)
    finished_at: datetime | None = Field(default=None)
    # running, succeeded, failed or skipped (exit code 2: not configured)
    status: str = Field(default="running", max_length=16)
    exit_code: int | None = Field(default=None)
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
