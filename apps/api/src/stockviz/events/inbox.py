"""Durable consumer inbox helpers.

Identity is ``(consumer_name, event_id)``. Domain mutation and the inbox row
must be written in the same PostgreSQL transaction; the Kafka offset is
committed only after that transaction succeeds.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from stockviz.models.events import ConsumerInbox


def already_processed(session: Session, *, event_id: UUID, consumer_name: str) -> bool:
    row = session.exec(
        select(ConsumerInbox).where(
            ConsumerInbox.consumer_name == consumer_name,
            ConsumerInbox.event_id == event_id,
        )
    ).first()
    return row is not None


def record_processed(session: Session, *, event_id: UUID, consumer_name: str) -> None:
    """Insert an inbox receipt. Raises IntegrityError on a duplicate."""
    session.add(ConsumerInbox(consumer_name=consumer_name, event_id=event_id))


def try_record_processed(session: Session, *, event_id: UUID, consumer_name: str) -> bool:
    """Insert an inbox receipt. Returns False if the unique constraint fires."""
    try:
        with session.begin_nested():
            session.add(ConsumerInbox(consumer_name=consumer_name, event_id=event_id))
            session.flush()
    except IntegrityError:
        return False
    return True
