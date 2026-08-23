"""Enqueue and claim transactional outbox rows.

The trading service calls :func:`enqueue_trade_executed` in the same Session
that wrote the ``Trade``. A separate publisher process claims unpublished
rows with ``FOR UPDATE SKIP LOCKED`` and marks ``published_at`` only after
the broker acknowledges the produce.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID, uuid4

from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.events.contracts import (
    EVENT_TYPE_TRADE_EXECUTED,
    SCHEMA_VERSION_V1,
    TRADES_TOPIC,
    TradeExecutedEvent,
    TradeExecutedPayload,
    decimal_str,
)
from stockviz.events.producer import BrokerPublisher
from stockviz.models import Trade
from stockviz.models.events import OutboxEvent

logger = logging.getLogger(__name__)


class SchemaIncompatibleError(ValueError):
    """Payload does not match the ``trade.executed`` v1 contract."""


def enqueue_trade_executed(
    session: Session,
    *,
    trade: Trade,
    currency: str,
    fx_rate: Decimal,
    usd_notional: Decimal,
) -> OutboxEvent:
    """Stage a ``trade.executed`` outbox row. Does not commit.

    ``trade`` must already have a primary key (flush first). The outbox insert
    uses the caller's open transaction.
    """
    if trade.id is None:
        raise RuntimeError("flush the Trade before enqueueing trade.executed")
    if trade.portfolio_id is None:
        raise RuntimeError("trade.portfolio_id is required")

    event_id = uuid4()
    envelope = TradeExecutedEvent(
        event_id=event_id,
        occurred_at=trade.ts,
        aggregate_id=str(trade.portfolio_id),
        payload=TradeExecutedPayload(
            trade_id=trade.id,
            portfolio_id=trade.portfolio_id,
            ticker=trade.ticker,
            side=trade.side.value,
            quantity=decimal_str(trade.quantity),
            price=decimal_str(trade.price),
            currency=currency,
            fx_rate=decimal_str(fx_rate),
            usd_notional=decimal_str(usd_notional),
        ),
    )
    row = OutboxEvent(
        id=event_id,
        event_type=EVENT_TYPE_TRADE_EXECUTED,
        schema_version=SCHEMA_VERSION_V1,
        aggregate_type="portfolio",
        aggregate_id=str(trade.portfolio_id),
        topic=TRADES_TOPIC,
        partition_key=str(trade.portfolio_id),
        payload=envelope.model_dump(mode="json"),
        occurred_at=trade.ts,
    )
    session.add(row)
    logger.info(
        "outbox enqueued event_id=%s trade_id=%s portfolio_id=%s",
        event_id,
        trade.id,
        trade.portfolio_id,
    )
    return row


def unpublished_events(session: Session, *, limit: int) -> Sequence[OutboxEvent]:
    """Pending outbox rows, oldest first. No lock — used by tests and inspection."""
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None))  # type: ignore[union-attr]
        .order_by(OutboxEvent.created_at)  # type: ignore[arg-type]
        .limit(limit)
    )
    return list(session.exec(stmt).all())


def claim_unpublished(session: Session, *, limit: int) -> list[OutboxEvent]:
    """Lock a batch of unpublished rows (Postgres ``SKIP LOCKED``).

    Two publisher processes cannot hold the same pending row at once. After
    Kafka acks, ``published_at`` is set and the lock is released on commit.
    If the process dies after the broker ack but before this commit, the row
    stays unpublished and will be produced again (at-least-once).

    SQLite (unit tests) has no ``SKIP LOCKED``; the same SELECT is used
    without a row lock.
    """
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None))  # type: ignore[union-attr]
        .order_by(OutboxEvent.created_at)  # type: ignore[arg-type]
        .limit(limit)
    )
    bind = session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    return list(session.exec(stmt).all())


def mark_published(event: OutboxEvent) -> None:
    event.published_at = utcnow()
    event.last_error = None


def mark_publish_failure(event: OutboxEvent, error: str) -> None:
    event.publish_attempts += 1
    event.last_error = error[:2000]


def parse_trade_executed(payload: dict) -> TradeExecutedEvent:
    """Validate a dict (outbox JSON or Kafka value) as trade.executed v1."""
    event_type = payload.get("event_type")
    version = payload.get("schema_version")
    if event_type != EVENT_TYPE_TRADE_EXECUTED:
        raise SchemaIncompatibleError(f"unsupported event_type {event_type!r}")
    if version != SCHEMA_VERSION_V1:
        raise SchemaIncompatibleError(f"unsupported schema_version {version!r}")
    return TradeExecutedEvent.model_validate(payload)


def publish_batch(
    session: Session,
    publisher: BrokerPublisher,
    *,
    limit: int,
) -> int:
    """Claim, produce, and mark one batch. Commits the session."""
    claimed = claim_unpublished(session, limit=limit)
    logger.info("outbox publisher claimed batch_size=%s", len(claimed))
    published = 0
    for event in claimed:
        try:
            publisher.publish(
                topic=event.topic,
                key=event.partition_key,
                value=event.payload,
            )
            mark_published(event)
            published += 1
            logger.info(
                "outbox published event_id=%s topic=%s key=%s attempts=%s",
                event.id,
                event.topic,
                event.partition_key,
                event.publish_attempts,
            )
        except Exception as exc:
            mark_publish_failure(event, f"{type(exc).__name__}: {exc}")
            logger.exception(
                "outbox publish failed event_id=%s attempts=%s",
                event.id,
                event.publish_attempts,
            )
        session.add(event)
    session.commit()
    return published


def get_outbox(session: Session, event_id: UUID) -> OutboxEvent | None:
    return session.get(OutboxEvent, event_id)
