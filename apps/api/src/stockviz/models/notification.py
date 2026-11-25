"""In-app notifications (Phase 7.2).

One row per thing the user should hear about: an alert firing, an order
filled, cancelled or expired, a dividend credited, a split applied, an
option settled. Each writer adds its row in the transaction of the change it
reports; ``source_key`` is unique, so a rerun of the night adds nothing.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow


class NotificationCategory(enum.StrEnum):
    ALERT = "alert"
    ORDER = "order"
    DIVIDEND = "dividend"
    CORPORATE_ACTION = "corporate_action"
    OPTION = "option"
    SCREEN = "screen"
    SYSTEM = "system"


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read_at", "id"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    category: str = Field(max_length=24)
    title: str = Field(max_length=200)
    body: str = Field(max_length=1000)
    # A path inside the app, e.g. "/orders?status=filled".
    link: str | None = Field(default=None, max_length=300)
    source_key: str = Field(max_length=160, unique=True)
    # A2.3: structured detail (a screen's entries and exits, an alert's ids),
    # shown by the page and sent as `data` by the delivery channels.
    data: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    )
    created_at: datetime = Field(default_factory=utcnow, nullable=False, index=True)
    read_at: datetime | None = Field(default=None, nullable=True)
