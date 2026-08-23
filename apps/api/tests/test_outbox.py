"""Transactional outbox + trade.executed contract tests (SQLite)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlmodel import Session, select

from stockviz.events.activity import apply_trade_executed
from stockviz.events.contracts import (
    EVENT_TYPE_TRADE_EXECUTED,
    TRADES_TOPIC,
    TradeExecutedEvent,
    TradeExecutedPayload,
)
from stockviz.events.outbox import (
    parse_trade_executed,
    publish_batch,
)
from stockviz.models import (
    OutboxEvent,
    PortfolioTradeActivity,
    PriceBar,
    Symbol,
    Trade,
    TradeSide,
    User,
)
from stockviz.models.events import ConsumerInbox
from stockviz.models.order import OrderType
from stockviz.services.trading.execute import (
    InsufficientCash,
    apply_fill,
    ensure_default_portfolio,
    execute_trade,
    resolve_priced_symbol,
)
from stockviz.services.trading.orders import create_pending_order, settle_pending_orders

BAR_TS = datetime(2025, 4, 10)


class FakePublisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.published: list[tuple[str, str, dict]] = []
        self.fail = fail

    def publish(self, *, topic: str, key: str, value: dict) -> None:
        if self.fail:
            raise RuntimeError("broker down")
        self.published.append((topic, key, value))


def _user(session: Session, email: str) -> int:
    user = User(email=email, name="Outbox Trader")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _usd_symbol(session: Session, ticker: str, *, close: Decimal) -> None:
    session.add(Symbol(ticker=ticker, name=f"{ticker} Inc.", currency="USD"))
    session.commit()
    session.add(
        PriceBar(
            ticker=ticker,
            ts=BAR_TS,
            interval="1d",
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1_000,
            source="test",
        )
    )
    session.commit()


def test_market_buy_creates_exactly_one_outbox_event(session: Session) -> None:
    user_id = _user(session, "buy-outbox@stockviz.dev")
    _usd_symbol(session, "AAPL", close=Decimal("10"))
    execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal("10")
    )

    trades = session.exec(select(Trade)).all()
    events = session.exec(select(OutboxEvent)).all()
    assert len(trades) == 1
    assert len(events) == 1
    event = events[0]
    assert event.event_type == EVENT_TYPE_TRADE_EXECUTED
    assert event.schema_version == 1
    assert event.topic == TRADES_TOPIC
    assert event.partition_key == str(trades[0].portfolio_id)
    assert event.published_at is None
    envelope = parse_trade_executed(event.payload)
    assert envelope.payload.trade_id == trades[0].id
    assert envelope.payload.ticker == "AAPL"
    assert envelope.payload.side == "buy"
    assert Decimal(envelope.payload.quantity) == Decimal("10")
    assert Decimal(envelope.payload.price) == Decimal("10")
    assert Decimal(envelope.payload.fx_rate) == Decimal("1")
    assert Decimal(envelope.payload.usd_notional) == Decimal("100")
    assert envelope.event_id
    assert envelope.occurred_at is not None


def test_pending_fill_creates_exactly_one_outbox_event(session: Session) -> None:
    user_id = _user(session, "fill-outbox@stockviz.dev")
    _usd_symbol(session, "AAPL", close=Decimal("10"))
    create_pending_order(
        session,
        user_id=user_id,
        ticker="AAPL",
        side=TradeSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("5"),
        limit_price=Decimal("12"),
    )
    assert session.exec(select(OutboxEvent)).all() == []
    assert session.exec(select(Trade)).all() == []

    filled = settle_pending_orders(session, session_date=None)
    assert filled == 1
    trades = session.exec(select(Trade)).all()
    events = session.exec(select(OutboxEvent)).all()
    assert len(trades) == 1
    assert len(events) == 1
    assert events[0].payload["payload"]["trade_id"] == trades[0].id


def test_rejected_trade_creates_no_outbox_event(session: Session) -> None:
    user_id = _user(session, "reject-outbox@stockviz.dev")
    _usd_symbol(session, "AAPL", close=Decimal("100000"))
    with pytest.raises(InsufficientCash):
        execute_trade(
            session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal("2")
        )
    session.rollback()
    assert session.exec(select(Trade)).all() == []
    assert session.exec(select(OutboxEvent)).all() == []


def test_rollback_removes_trade_and_outbox(session: Session) -> None:
    user_id = _user(session, "rollback-outbox@stockviz.dev")
    _usd_symbol(session, "AAPL", close=Decimal("10"))
    portfolio = ensure_default_portfolio(session, user_id)
    priced = resolve_priced_symbol(session, "AAPL")
    apply_fill(
        session,
        portfolio=portfolio,
        ticker="AAPL",
        side=TradeSide.BUY,
        quantity=Decimal("1"),
        price=priced.price,
        currency=priced.currency,
        fx_rate=priced.fx_rate,
    )
    session.flush()
    assert session.exec(select(Trade)).all()
    assert session.exec(select(OutboxEvent)).all()
    session.rollback()
    assert session.exec(select(Trade)).all() == []
    assert session.exec(select(OutboxEvent)).all() == []


def test_publish_batch_marks_published_after_ack(session: Session) -> None:
    user_id = _user(session, "pub-ok@stockviz.dev")
    _usd_symbol(session, "AAPL", close=Decimal("10"))
    execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal("1")
    )
    publisher = FakePublisher()
    n = publish_batch(session, publisher, limit=50)
    assert n == 1
    event = session.exec(select(OutboxEvent)).one()
    assert event.published_at is not None
    assert event.publish_attempts == 0
    assert event.last_error is None
    assert publisher.published[0][0] == TRADES_TOPIC
    assert publisher.published[0][1] == str(event.aggregate_id)


def test_publish_batch_keeps_pending_on_broker_error(session: Session) -> None:
    user_id = _user(session, "pub-fail@stockviz.dev")
    _usd_symbol(session, "AAPL", close=Decimal("10"))
    execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal("1")
    )
    n = publish_batch(session, FakePublisher(fail=True), limit=50)
    assert n == 0
    event = session.exec(select(OutboxEvent)).one()
    assert event.published_at is None
    assert event.publish_attempts == 1
    assert event.last_error is not None
    assert "broker down" in event.last_error


def test_crash_window_allows_duplicate_publish(session: Session) -> None:
    """Kafka ack + process crash before published_at is the at-least-once window."""
    user_id = _user(session, "crash-window@stockviz.dev")
    _usd_symbol(session, "AAPL", close=Decimal("10"))
    execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal("1")
    )
    event = session.exec(select(OutboxEvent)).one()
    publisher = FakePublisher()
    publisher.publish(topic=event.topic, key=event.partition_key, value=event.payload)
    session.rollback()
    still = session.exec(select(OutboxEvent)).one()
    assert still.published_at is None
    n = publish_batch(session, publisher, limit=50)
    assert n == 1
    assert len(publisher.published) == 2


def test_consumer_idempotent_on_duplicate_event(session: Session) -> None:
    user_id = _user(session, "dup-consumer@stockviz.dev")
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    event = TradeExecutedEvent(
        event_id=uuid4(),
        occurred_at=datetime.now(UTC).replace(tzinfo=None),
        aggregate_id=str(portfolio.id),
        payload=TradeExecutedPayload(
            trade_id=10,
            portfolio_id=portfolio.id,
            ticker="AAPL",
            side="buy",
            quantity="1",
            price="10",
            currency="USD",
            fx_rate="1",
            usd_notional="10",
        ),
    )
    apply_trade_executed(session, event)
    apply_trade_executed(session, event)
    session.commit()
    activity = session.get(PortfolioTradeActivity, portfolio.id)
    assert activity is not None
    assert activity.trade_count == 1
    assert activity.last_trade_id == 10
    receipts = session.exec(select(ConsumerInbox)).all()
    assert len(receipts) == 1


def test_consumer_counts_distinct_events(session: Session) -> None:
    user_id = _user(session, "two-events@stockviz.dev")
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    for trade_id in (11, 12):
        apply_trade_executed(
            session,
            TradeExecutedEvent(
                event_id=uuid4(),
                occurred_at=datetime.now(UTC).replace(tzinfo=None),
                aggregate_id=str(portfolio.id),
                payload=TradeExecutedPayload(
                    trade_id=trade_id,
                    portfolio_id=portfolio.id,
                    ticker="MSFT",
                    side="buy",
                    quantity="1",
                    price="10",
                    currency="USD",
                    fx_rate="1",
                    usd_notional="10",
                ),
            ),
        )
    session.commit()
    activity = session.get(PortfolioTradeActivity, portfolio.id)
    assert activity is not None
    assert activity.trade_count == 2
    assert activity.last_trade_id == 12


def test_consumer_rejects_unknown_schema_version() -> None:
    payload = {
        "event_id": str(uuid4()),
        "event_type": EVENT_TYPE_TRADE_EXECUTED,
        "schema_version": 99,
        "occurred_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
        "aggregate_type": "portfolio",
        "aggregate_id": "1",
        "payload": {
            "trade_id": 1,
            "portfolio_id": 1,
            "ticker": "AAPL",
            "side": "buy",
            "quantity": "1",
            "price": "1",
            "currency": "USD",
            "fx_rate": "1",
            "usd_notional": "1",
        },
    }
    with pytest.raises(Exception, match="schema_version"):
        parse_trade_executed(payload)


def test_market_sell_also_enqueues_event(session: Session) -> None:
    user_id = _user(session, "sell-outbox@stockviz.dev")
    _usd_symbol(session, "AAPL", close=Decimal("10"))
    execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal("4")
    )
    execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.SELL, quantity=Decimal("2")
    )
    events = session.exec(select(OutboxEvent)).all()
    assert len(events) == 2
    sides = {e.payload["payload"]["side"] for e in events}
    assert sides == {"buy", "sell"}
