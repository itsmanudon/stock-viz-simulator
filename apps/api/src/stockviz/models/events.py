"""Transactional outbox, consumer inbox, and derived trade-activity state.

These tables are not the trading ledger. Cash and positions remain on
``portfolios`` / ``positions`` / ``trades``. Kafka consumers may only write
derived rows here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow


class OutboxEvent(SQLModel, table=True):
    """Row written in the same transaction as the ledger mutation.

    ``published_at`` stays NULL until a publisher process has a broker ack.
    """

    __tablename__ = "outbox_events"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        Index("ix_outbox_events_published_created", "published_at", "created_at"),
        Index("ix_outbox_events_aggregate", "aggregate_type", "aggregate_id"),
        Index(
            "ix_outbox_events_unpublished",
            "created_at",
            postgresql_where=text("published_at IS NULL"),
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    event_type: str = Field(max_length=64, index=True)
    schema_version: int = Field(default=1, nullable=False)
    aggregate_type: str = Field(max_length=64)
    aggregate_id: str = Field(max_length=64)
    topic: str = Field(max_length=128)
    partition_key: str = Field(max_length=64)
    payload: dict[str, Any] = Field(
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
    )
    occurred_at: datetime = Field(nullable=False)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    published_at: datetime | None = Field(default=None, index=True)
    publish_attempts: int = Field(default=0, nullable=False)
    last_error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))


class ConsumerInbox(SQLModel, table=True):
    """Durable receipt that ``consumer_name`` has applied ``event_id``."""

    __tablename__ = "consumer_inbox"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("consumer_name", "event_id", name="uq_consumer_inbox_name_event"),
    )

    id: int | None = Field(default=None, primary_key=True)
    consumer_name: str = Field(max_length=128, index=True)
    event_id: uuid.UUID = Field(index=True)
    processed_at: datetime = Field(default_factory=utcnow, nullable=False)


class PortfolioTradeActivity(SQLModel, table=True):
    """Derived per-portfolio counter. Not a source of cash or positions."""

    __tablename__ = "portfolio_trade_activity"  # pyright: ignore[reportAssignmentType]

    portfolio_id: int = Field(primary_key=True, foreign_key="portfolios.id")
    trade_count: int = Field(default=0, nullable=False)
    last_trade_id: int | None = Field(default=None)
    last_event_id: uuid.UUID | None = Field(default=None)
    last_trade_at: datetime | None = Field(default=None)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)
