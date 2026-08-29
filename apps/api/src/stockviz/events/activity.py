"""Apply ``trade.executed`` to derived portfolio activity, exactly once per event."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from stockviz._time import utcnow
from stockviz.events.contracts import TRADE_ACTIVITY_CONSUMER, TradeExecutedEvent
from stockviz.models.events import ConsumerInbox, PortfolioTradeActivity

logger = logging.getLogger(__name__)


def already_processed(session: Session, *, event_id: UUID, consumer_name: str) -> bool:
    row = session.exec(
        select(ConsumerInbox).where(
            ConsumerInbox.consumer_name == consumer_name,
            ConsumerInbox.event_id == event_id,
        )
    ).first()
    return row is not None


def apply_trade_executed(
    session: Session,
    event: TradeExecutedEvent,
    *,
    consumer_name: str = TRADE_ACTIVITY_CONSUMER,
) -> str:
    """Apply derived state + inbox in the caller's transaction.

    Returns ``"applied"`` or ``"duplicate"``. Does not commit — the worker
    commits the DB transaction, then the Kafka offset.
    """
    if already_processed(session, event_id=event.event_id, consumer_name=consumer_name):
        logger.info("consumer duplicate event_id=%s", event.event_id)
        return "duplicate"

    portfolio_id = event.payload.portfolio_id
    activity = session.get(PortfolioTradeActivity, portfolio_id)
    now = utcnow()
    if activity is None:
        activity = PortfolioTradeActivity(
            portfolio_id=portfolio_id,
            trade_count=0,
            updated_at=now,
        )
        session.add(activity)
        session.flush()

    activity.trade_count += 1
    activity.last_trade_id = event.payload.trade_id
    activity.last_event_id = event.event_id
    activity.last_trade_at = event.occurred_at
    activity.updated_at = now
    session.add(activity)
    session.add(
        ConsumerInbox(
            consumer_name=consumer_name,
            event_id=event.event_id,
        )
    )
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError:
        logger.info("consumer duplicate (unique) event_id=%s", event.event_id)
        return "duplicate"

    logger.info(
        "consumer applied event_id=%s portfolio_id=%s trade_count=%s",
        event.event_id,
        portfolio_id,
        activity.trade_count,
    )
    return "applied"
