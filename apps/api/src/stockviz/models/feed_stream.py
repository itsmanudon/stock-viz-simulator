"""A stream the worker has run (A6.5): ``feed_streams``.

One row per stream name (``simulated`` for ``SimulatedFeed`` replays,
``alpaca`` from A6.6). The worker upserts it as it starts, after each bar it
writes, and when it stops; ``/v1/broker/feeds`` reads it. ``state`` is
``streaming`` while it runs, ``closed`` after a clean stop and ``error`` when
the stream ended on an error (``error`` is a fixed summary, never a key or a
provider's text). A ``streaming`` row whose ``updated_at`` is old means the
worker died without saying so: broker status reports it as ``closed``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, Column
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow


class FeedStream(SQLModel, table=True):
    __tablename__ = "feed_streams"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint("state IN ('streaming', 'closed', 'error')", name="ck_feed_streams_state"),
    )

    name: str = Field(primary_key=True, max_length=24)
    label: str = Field(max_length=40)
    state: str = Field(max_length=16)
    symbols: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    started_at: datetime = Field(default_factory=utcnow, nullable=False)
    stopped_at: datetime | None = None
    last_tick_at: datetime | None = None
    last_bar_at: datetime | None = None
    bars_written: int = Field(default=0, nullable=False)
    alerts_fired: int = Field(default=0, nullable=False)
    error: str | None = Field(default=None, max_length=200)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)
