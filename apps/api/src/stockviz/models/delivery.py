"""Notification delivery beyond the in-app bell (A2.3, M4.5 end of day).

- ``notification_channels``: one row per user and channel (``webhook``,
  ``email``, ``telegram``) with its settings. The webhook secret is
  write-only: stored here so the payload can be signed, never returned by
  the API or written to a log.
- ``delivery_attempts``: the outbox of sends. ``services/delivery.deliver``
  stages one row per enabled channel in the transaction that writes the
  notification, so a send exists exactly when its notification does; the
  ``deliver-notifications`` job sends them after commit. Unique per
  (notification, channel), so nothing is sent twice by a rerun.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy import false as sa_false
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from stockviz._time import utcnow

_JSON = JSON().with_variant(JSONB(), "postgresql")


class ChannelKind(enum.StrEnum):
    WEBHOOK = "webhook"
    EMAIL = "email"
    TELEGRAM = "telegram"


class DeliveryStatus(enum.StrEnum):
    PENDING = "pending"  # waiting for its first or next attempt
    SENT = "sent"
    DEAD = "dead"  # gave up: attempts used, or an error no retry can fix
    SKIPPED = "skipped"  # the channel was off when its turn came


class NotificationChannel(SQLModel, table=True):
    __tablename__ = "notification_channels"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("user_id", "channel", name="uq_notification_channels_user_channel"),
        CheckConstraint(
            "channel IN ('webhook', 'email', 'telegram')", name="ck_notification_channels_channel"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    channel: str = Field(max_length=16)
    enabled: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default=sa_false())
    )
    # webhook: {"url"}; email: {"address"} (blank = the account email);
    # telegram: {"chat_id"}.
    config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(_JSON, nullable=False))
    # Webhook HMAC key. Write-only: never in a response or a log line.
    secret: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    # Notification categories this channel does not send (the bell still shows them).
    muted_categories: list[str] = Field(
        default_factory=list, sa_column=Column(_JSON, nullable=False)
    )
    # Only notifications created after this are sent, so turning a channel on
    # never floods it with old ones.
    enabled_at: datetime | None = Field(default=None, nullable=True)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class DeliveryAttempt(SQLModel, table=True):
    __tablename__ = "delivery_attempts"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "notification_id", "channel", name="uq_delivery_attempts_notification_channel"
        ),
        Index("ix_delivery_attempts_status_next", "status", "next_attempt_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    notification_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("notifications.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    user_id: int = Field(foreign_key="users.id", index=True)
    channel: str = Field(max_length=16)
    status: str = Field(default=DeliveryStatus.PENDING.value, max_length=16)
    attempts: int = Field(default=0)
    next_attempt_at: datetime = Field(default_factory=utcnow, nullable=False)
    # Never holds a secret, a token or a full URL with credentials.
    last_error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    sent_at: datetime | None = Field(default=None, nullable=True)
    dead_at: datetime | None = Field(default=None, nullable=True)


__all__ = [
    "ChannelKind",
    "DeliveryAttempt",
    "DeliveryStatus",
    "NotificationChannel",
]
