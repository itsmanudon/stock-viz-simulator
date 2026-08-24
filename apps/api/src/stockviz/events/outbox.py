"""Enqueue and claim transactional outbox rows.

Domain services call :func:`enqueue_event` (or a typed helper) in the same
Session that wrote the source row. A separate publisher process claims
unpublished rows with ``FOR UPDATE SKIP LOCKED`` and marks ``published_at``
only after the broker acknowledges the produce.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.events.contracts import (
    EVENT_TYPE_MARKET_BARS_REFRESHED,
    EVENT_TYPE_MARKET_REFRESH_REQUESTED,
    EVENT_TYPE_NEWS_ARTICLE_INGESTED,
    EVENT_TYPE_NEWS_REFRESH_REQUESTED,
    EVENT_TYPE_NEWS_SENTIMENT_SCORED,
    EVENT_TYPE_TRADE_EXECUTED,
    MARKET_TOPIC,
    NEWS_TOPIC,
    SCHEMA_VERSION_V1,
    TRADES_TOPIC,
    MarketBarsRefreshedEvent,
    MarketBarsRefreshedPayload,
    MarketRefreshRequestedEvent,
    MarketRefreshRequestedPayload,
    NewsArticleIngestedEvent,
    NewsArticleIngestedPayload,
    NewsRefreshRequestedEvent,
    NewsRefreshRequestedPayload,
    NewsSentimentScoredEvent,
    NewsSentimentScoredPayload,
    TradeExecutedEvent,
    TradeExecutedPayload,
    decimal_str,
)
from stockviz.events.producer import BrokerPublisher
from stockviz.models import Trade
from stockviz.models.events import OutboxEvent

logger = logging.getLogger(__name__)


class SchemaIncompatibleError(ValueError):
    """Payload does not match a supported v1 event contract."""


def enqueue_event(
    session: Session,
    *,
    event_id: UUID,
    event_type: str,
    schema_version: int,
    aggregate_type: str,
    aggregate_id: str,
    topic: str,
    partition_key: str,
    envelope: dict[str, Any],
    occurred_at: datetime,
) -> OutboxEvent:
    """Stage one outbox row. Does not commit."""
    row = OutboxEvent(
        id=event_id,
        event_type=event_type,
        schema_version=schema_version,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        topic=topic,
        partition_key=partition_key,
        payload=envelope,
        occurred_at=occurred_at,
    )
    session.add(row)
    logger.info(
        "outbox enqueued event_id=%s event_type=%s topic=%s key=%s",
        event_id,
        event_type,
        topic,
        partition_key,
    )
    return row


def enqueue_envelope(
    session: Session,
    envelope: BaseModel,
    *,
    topic: str,
    partition_key: str,
) -> OutboxEvent:
    """Persist a pydantic envelope as an outbox row. Does not commit."""
    dumped = envelope.model_dump(mode="json")
    return enqueue_event(
        session,
        event_id=envelope.event_id,  # type: ignore[attr-defined]
        event_type=str(dumped["event_type"]),
        schema_version=int(dumped["schema_version"]),
        aggregate_type=str(dumped["aggregate_type"]),
        aggregate_id=str(dumped["aggregate_id"]),
        topic=topic,
        partition_key=partition_key,
        envelope=dumped,
        occurred_at=envelope.occurred_at,  # type: ignore[attr-defined]
    )


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
    row = enqueue_envelope(
        session,
        envelope,
        topic=TRADES_TOPIC,
        partition_key=str(trade.portfolio_id),
    )
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


def _require_v1(payload: dict, event_type: str) -> None:
    got_type = payload.get("event_type")
    version = payload.get("schema_version")
    if got_type != event_type:
        raise SchemaIncompatibleError(f"unsupported event_type {got_type!r}")
    if version != SCHEMA_VERSION_V1:
        raise SchemaIncompatibleError(f"unsupported schema_version {version!r}")


def parse_trade_executed(payload: dict) -> TradeExecutedEvent:
    """Validate a dict (outbox JSON or Kafka value) as trade.executed v1."""
    _require_v1(payload, EVENT_TYPE_TRADE_EXECUTED)
    return TradeExecutedEvent.model_validate(payload)


def parse_market_refresh_requested(payload: dict) -> MarketRefreshRequestedEvent:
    _require_v1(payload, EVENT_TYPE_MARKET_REFRESH_REQUESTED)
    return MarketRefreshRequestedEvent.model_validate(payload)


def parse_market_bars_refreshed(payload: dict) -> MarketBarsRefreshedEvent:
    _require_v1(payload, EVENT_TYPE_MARKET_BARS_REFRESHED)
    return MarketBarsRefreshedEvent.model_validate(payload)


def parse_news_refresh_requested(payload: dict) -> NewsRefreshRequestedEvent:
    _require_v1(payload, EVENT_TYPE_NEWS_REFRESH_REQUESTED)
    return NewsRefreshRequestedEvent.model_validate(payload)


def parse_news_article_ingested(payload: dict) -> NewsArticleIngestedEvent:
    _require_v1(payload, EVENT_TYPE_NEWS_ARTICLE_INGESTED)
    return NewsArticleIngestedEvent.model_validate(payload)


def parse_news_sentiment_scored(payload: dict) -> NewsSentimentScoredEvent:
    _require_v1(payload, EVENT_TYPE_NEWS_SENTIMENT_SCORED)
    return NewsSentimentScoredEvent.model_validate(payload)


def enqueue_market_refresh_requested(
    session: Session,
    *,
    ticker: str,
    reason: str,
    since: datetime | None = None,
    requested_at: datetime | None = None,
) -> OutboxEvent:
    """Durable work request. Does not fetch prices and does not commit."""
    occurred_at = requested_at or utcnow()
    event_id = uuid4()
    ticker = ticker.strip().upper()
    envelope = MarketRefreshRequestedEvent(
        event_id=event_id,
        occurred_at=occurred_at,
        aggregate_id=ticker,
        payload=MarketRefreshRequestedPayload(
            ticker=ticker,
            reason=reason,  # type: ignore[arg-type]
            requested_at=occurred_at,
            since=since,
        ),
    )
    return enqueue_envelope(session, envelope, topic=MARKET_TOPIC, partition_key=ticker)


def enqueue_market_bars_refreshed(
    session: Session,
    *,
    ticker: str,
    interval: str,
    source: str,
    bar_count: int,
    latest_bar_at: datetime | None,
    latest_close: Decimal | None,
    request_event_id: UUID,
    occurred_at: datetime | None = None,
) -> OutboxEvent:
    occurred_at = occurred_at or utcnow()
    event_id = uuid4()
    ticker = ticker.strip().upper()
    envelope = MarketBarsRefreshedEvent(
        event_id=event_id,
        occurred_at=occurred_at,
        aggregate_id=ticker,
        payload=MarketBarsRefreshedPayload(
            ticker=ticker,
            interval=interval,
            source=source,
            bar_count=bar_count,
            latest_bar_at=latest_bar_at,
            latest_close=None if latest_close is None else decimal_str(latest_close),
            request_event_id=str(request_event_id),
        ),
    )
    return enqueue_envelope(session, envelope, topic=MARKET_TOPIC, partition_key=ticker)


def enqueue_news_refresh_requested(
    session: Session,
    *,
    ticker: str,
    company_name: str,
    reason: str = "scheduled",
    requested_at: datetime | None = None,
) -> OutboxEvent:
    occurred_at = requested_at or utcnow()
    event_id = uuid4()
    ticker = ticker.strip().upper()
    envelope = NewsRefreshRequestedEvent(
        event_id=event_id,
        occurred_at=occurred_at,
        aggregate_id=ticker,
        payload=NewsRefreshRequestedPayload(
            ticker=ticker,
            company_name=company_name,
            reason=reason,  # type: ignore[arg-type]
            requested_at=occurred_at,
        ),
    )
    return enqueue_envelope(session, envelope, topic=NEWS_TOPIC, partition_key=ticker)


def enqueue_news_article_ingested(
    session: Session,
    *,
    article_id: int,
    ticker: str,
    url: str,
    published_at: datetime,
    source: str | None,
    occurred_at: datetime | None = None,
) -> OutboxEvent:
    occurred_at = occurred_at or utcnow()
    event_id = uuid4()
    ticker = ticker.strip().upper()
    envelope = NewsArticleIngestedEvent(
        event_id=event_id,
        occurred_at=occurred_at,
        aggregate_id=ticker,
        payload=NewsArticleIngestedPayload(
            article_id=article_id,
            ticker=ticker,
            url=url,
            published_at=published_at,
            source=source,
        ),
    )
    return enqueue_envelope(session, envelope, topic=NEWS_TOPIC, partition_key=ticker)


def enqueue_news_sentiment_scored(
    session: Session,
    *,
    article_id: int,
    ticker: str,
    model: str,
    label: str,
    score: Decimal,
    confidence: Decimal | None,
    occurred_at: datetime | None = None,
) -> OutboxEvent:
    occurred_at = occurred_at or utcnow()
    event_id = uuid4()
    ticker = ticker.strip().upper()
    envelope = NewsSentimentScoredEvent(
        event_id=event_id,
        occurred_at=occurred_at,
        aggregate_id=ticker,
        payload=NewsSentimentScoredPayload(
            article_id=article_id,
            ticker=ticker,
            model=model,
            label=label,
            score=decimal_str(score),
            confidence=None if confidence is None else decimal_str(confidence),
        ),
    )
    return enqueue_envelope(session, envelope, topic=NEWS_TOPIC, partition_key=ticker)


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
