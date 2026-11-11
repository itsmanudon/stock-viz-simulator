"""Retention for the event tables (audit OP-11).

Nothing else deletes from ``outbox_events`` or ``consumer_inbox``. Where a
publisher runs, published outbox rows and old inbox receipts are history that
no code reads again. Where none runs (the Railway cron), unpublished rows are
never sent either, and a publisher attached later would replay all of them.

- Published outbox rows go once ``published_at`` is older than the cutoff.
- Inbox receipts go once ``processed_at`` is older than the cutoff. A receipt
  only guards against Kafka redelivering the same event, and redelivery after
  the cutoff would need a retention far longer than the topics keep.
- Unpublished outbox rows are kept unless the caller asks, because where a
  publisher runs they are events still waiting to be sent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlmodel import Session

from stockviz.models.auth_rate_limit import AuthRateLimit
from stockviz.models.events import ConsumerInbox, OutboxEvent

DEFAULT_RETENTION_DAYS = 30
"""Well past Kafka's default seven-day topic retention."""


@dataclass(frozen=True, slots=True)
class PruneResult:
    published: int
    unpublished: int
    inbox: int
    auth_counters: int = 0


def prune_events(
    session: Session,
    *,
    now: datetime,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    include_unpublished: bool = False,
) -> PruneResult:
    """Delete event rows older than ``retention_days``. Does not commit."""
    if retention_days < 1:
        raise ValueError("retention_days must be at least 1")
    cutoff = now - timedelta(days=retention_days)

    published = session.exec(  # type: ignore[call-overload]
        delete(OutboxEvent).where(
            OutboxEvent.published_at.is_not(None),  # type: ignore[union-attr]
            OutboxEvent.published_at < cutoff,  # type: ignore[operator]
        )
    ).rowcount
    unpublished = 0
    if include_unpublished:
        unpublished = session.exec(  # type: ignore[call-overload]
            delete(OutboxEvent).where(
                OutboxEvent.published_at.is_(None),  # type: ignore[union-attr]
                OutboxEvent.created_at < cutoff,  # type: ignore[arg-type]
            )
        ).rowcount
    inbox = session.exec(  # type: ignore[call-overload]
        delete(ConsumerInbox).where(ConsumerInbox.processed_at < cutoff)  # type: ignore[arg-type]
    ).rowcount
    # Sign-in counters whose window ended a day ago (audit OP-8); nothing reads them.
    expired = now.replace(tzinfo=UTC) if now.tzinfo is None else now
    auth_counters = session.exec(  # type: ignore[call-overload]
        delete(AuthRateLimit).where(
            AuthRateLimit.reset_at < expired - timedelta(days=1)  # type: ignore[arg-type]
        )
    ).rowcount
    return PruneResult(
        published=published or 0,
        unpublished=unpublished or 0,
        inbox=inbox or 0,
        auth_counters=auth_counters or 0,
    )
