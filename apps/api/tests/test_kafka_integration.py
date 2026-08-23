"""End-to-end outbox → Kafka → idempotent consumer (requires a broker)."""

from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlmodel import Session, select

from stockviz.events.activity import apply_trade_executed
from stockviz.events.contracts import TRADES_TOPIC, TRADES_TOPIC_PARTITIONS
from stockviz.events.outbox import parse_trade_executed, publish_batch
from stockviz.events.producer import (
    ConfluentBrokerConsumer,
    ConfluentBrokerPublisher,
    ensure_trades_topic,
)
from stockviz.models import OutboxEvent, PortfolioTradeActivity, PriceBar, Symbol, TradeSide, User
from stockviz.models.events import ConsumerInbox
from stockviz.services.trading import ensure_default_portfolio, execute_trade
from tests.pg_scratch import postgres_admin_url, scratch_postgres_engine

_KAFKA = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
_REQUIRED = os.environ.get("STOCKVIZ_KAFKA_REQUIRED") == "1"


def _broker_up() -> bool:
    try:
        from confluent_kafka.admin import AdminClient

        admin = AdminClient({"bootstrap.servers": _KAFKA})
        admin.list_topics(timeout=8)
        return True
    except Exception:
        return False


def _require_kafka() -> None:
    if _broker_up():
        return
    if _REQUIRED:
        pytest.fail(f"Kafka is required but unreachable at {_KAFKA}")
    pytest.skip("Kafka broker not reachable")


@pytest.mark.skipif(postgres_admin_url() is None, reason="DATABASE_URL is not PostgreSQL")
def test_trade_outbox_publisher_consumer_roundtrip() -> None:
    _require_kafka()
    group = f"stockviz.trade-activity.test.{uuid4().hex[:8]}"
    ensure_trades_topic(
        bootstrap_servers=_KAFKA, topic=TRADES_TOPIC, partitions=TRADES_TOPIC_PARTITIONS
    )

    with scratch_postgres_engine() as engine:
        with Session(engine) as session:
            user = User(email=f"kafka-{uuid4().hex}@stockviz.dev", name="Kafka")
            session.add(user)
            session.commit()
            session.refresh(user)
            assert user.id is not None
            session.add(Symbol(ticker="MSFT", name="Microsoft", currency="USD"))
            session.commit()
            session.add(
                PriceBar(
                    ticker="MSFT",
                    ts=datetime(2025, 4, 10),
                    interval="1d",
                    open=Decimal("100"),
                    high=Decimal("100"),
                    low=Decimal("100"),
                    close=Decimal("100"),
                    volume=1_000,
                    source="test",
                )
            )
            session.commit()
            portfolio = ensure_default_portfolio(session, user.id)
            assert portfolio.id is not None
            portfolio_id = portfolio.id
            execute_trade(
                session,
                user_id=user.id,
                ticker="MSFT",
                side=TradeSide.BUY,
                quantity=Decimal("2"),
            )
            pending = session.exec(select(OutboxEvent)).all()
            assert len(pending) == 1
            assert pending[0].published_at is None

        publisher = ConfluentBrokerPublisher(bootstrap_servers=_KAFKA)
        try:
            with Session(engine) as session:
                n = publish_batch(session, publisher, limit=50)
            assert n == 1
        finally:
            publisher.close()

        with Session(engine) as session:
            row = session.exec(select(OutboxEvent)).one()
            assert row.published_at is not None

        consumer = ConfluentBrokerConsumer(
            bootstrap_servers=_KAFKA,
            group_id=group,
            topic=TRADES_TOPIC,
        )
        try:
            polled = consumer.poll_json(20.0)
            assert polled is not None, "consumer did not receive the published trade.executed"
            msg, payload = polled
            with Session(engine) as session:
                event = parse_trade_executed(payload)
                apply_trade_executed(session, event)
                session.commit()
            consumer.commit(msg)
            # Redeliver-style second apply of the same payload.
            with Session(engine) as session:
                apply_trade_executed(session, parse_trade_executed(payload))
                session.commit()
                activity = session.get(PortfolioTradeActivity, portfolio_id)
                assert activity is not None
                assert activity.trade_count == 1
                receipts = session.exec(select(ConsumerInbox)).all()
                assert len(receipts) == 1
        finally:
            consumer.close()
