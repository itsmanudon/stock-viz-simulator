"""SIM-04: successful live fills persist kernel provenance with the Trade.

Provenance is fill-only: NOT_TRIGGERED, INELIGIBLE, and account failures
must not write SimulatedExecution rows. Kafka trade.executed.v1 is unchanged.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from stockviz.events.contracts import TradeExecutedEvent
from stockviz.events.outbox import parse_trade_executed
from stockviz.models import (
    OutboxEvent,
    PendingOrder,
    PriceBar,
    SimulatedExecution,
    Symbol,
    Trade,
    TradeSide,
    User,
)
from stockviz.models.order import OrderStatus, OrderType
from stockviz.services.simulation import (
    LEGACY_CLOSE,
    LEGACY_CLOSE_ASSUMPTIONS,
    ExecutionTrace,
    FillDecision,
    FillStatus,
)
from stockviz.services.simulation import (
    evaluate_order as real_evaluate_order,
)
from stockviz.services.trading import (
    DEFAULT_STARTING_CASH,
    create_pending_order,
    ensure_default_portfolio,
    execute_trade,
    settle_pending_orders,
)
from stockviz.services.trading.execute import (
    _market_fill_provenance,
    apply_fill,
    resolve_priced_symbol,
)
from stockviz.services.trading.execution_provenance import record_execution_provenance

BAR_TS = datetime(2025, 4, 10)
BAR_DAY = BAR_TS.date()


def _user(session: Session, email: str) -> int:
    user = User(email=email, name="SIM-04")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _symbol(
    session: Session,
    ticker: str = "AAPL",
    *,
    close: Decimal = Decimal("150"),
    currency: str = "USD",
) -> None:
    session.add(Symbol(ticker=ticker, name=f"{ticker} Inc.", currency=currency))
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


def _provenance(session: Session, trade_id: int) -> SimulatedExecution:
    return session.exec(
        select(SimulatedExecution).where(SimulatedExecution.trade_id == trade_id)
    ).one()


def test_sim04_market_buy_persists_legacy_close_provenance(session: Session) -> None:
    close = Decimal("184.16")
    _symbol(session, close=close)
    user_id = _user(session, "mkt@stockviz.dev")
    result = execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(2)
    )
    trade = result.trade
    assert trade.id is not None
    row = _provenance(session, trade.id)
    assert row.profile_name == "legacy_close"
    assert row.model_version == "v1"
    assert row.reference_price == close
    assert row.fill_price == trade.price == close
    assert row.market_interval == "1d"
    assert row.order_type == "market"
    assert row.assumptions == list(LEGACY_CLOSE_ASSUMPTIONS)
    assert row.reason == "Market order fills at observable daily close"
    assert row.evaluated_at is not None
    assert row.created_at is not None


@pytest.mark.parametrize(
    ("order_type", "side", "limit", "close"),
    [
        (OrderType.LIMIT, TradeSide.BUY, Decimal("160"), Decimal("150")),
        (OrderType.LIMIT, TradeSide.SELL, Decimal("140"), Decimal("150")),
        (OrderType.STOP_LOSS, TradeSide.SELL, Decimal("160"), Decimal("150")),
        (OrderType.TAKE_PROFIT, TradeSide.SELL, Decimal("140"), Decimal("150")),
    ],
)
def test_sim04_conditional_fill_persists_provenance(
    session: Session,
    order_type: OrderType,
    side: TradeSide,
    limit: Decimal,
    close: Decimal,
) -> None:
    user_id = _user(session, f"cond-{order_type}-{side}@stockviz.dev")
    if side is TradeSide.SELL:
        _symbol(session, close=Decimal("100"))
        execute_trade(
            session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(3)
        )
        session.add(
            PriceBar(
                ticker="AAPL",
                ts=BAR_TS + timedelta(days=1),
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
        session_date = BAR_TS.date() + timedelta(days=1)
    else:
        _symbol(session, close=close)
        session_date = BAR_DAY

    create_pending_order(
        session,
        user_id=user_id,
        ticker="AAPL",
        side=side,
        order_type=order_type,
        quantity=Decimal(3) if side is TradeSide.SELL else Decimal(2),
        limit_price=limit,
    )
    assert settle_pending_orders(session, session_date=session_date) == 1
    trades = list(session.exec(select(Trade)).all())
    fill_trade = max(trades, key=lambda t: t.id or 0)
    assert fill_trade.id is not None
    row = _provenance(session, fill_trade.id)
    assert row.profile_name == "legacy_close"
    assert row.model_version == "v1"
    assert row.fill_price == fill_trade.price == close
    assert row.reference_price == close
    assert row.assumptions == list(LEGACY_CLOSE_ASSUMPTIONS)
    assert row.market_interval == "1d"
    assert row.order_type == order_type.value


def test_sim04_not_triggered_writes_no_trade_or_provenance(session: Session) -> None:
    _symbol(session, close=Decimal("200"))
    user_id = _user(session, "nt@stockviz.dev")
    order = create_pending_order(
        session,
        user_id=user_id,
        ticker="AAPL",
        side=TradeSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal(1),
        limit_price=Decimal("100"),
    )
    assert settle_pending_orders(session, session_date=BAR_DAY) == 0
    session.refresh(order)
    assert order.status == OrderStatus.PENDING
    assert session.exec(select(Trade)).all() == []
    assert session.exec(select(SimulatedExecution)).all() == []


def test_sim04_account_failure_writes_no_trade_or_provenance(session: Session) -> None:
    _symbol(session, close=Decimal("150"))
    user_id = _user(session, "broke@stockviz.dev")
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    session.add(
        PendingOrder(
            portfolio_id=portfolio.id,
            ticker="AAPL",
            side=TradeSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal(1000),
            limit_price=Decimal("200"),
        )
    )
    session.commit()
    assert settle_pending_orders(session, session_date=BAR_DAY) == 0
    order = session.exec(select(PendingOrder)).one()
    assert order.status == OrderStatus.CANCELLED
    assert session.exec(select(Trade)).all() == []
    assert session.exec(select(SimulatedExecution)).all() == []
    session.refresh(portfolio)
    assert portfolio.cash_balance == DEFAULT_STARTING_CASH


def test_sim04_provenance_uses_actual_kernel_decision(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _symbol(session, close=Decimal("100"))
    user_id = _user(session, "synth@stockviz.dev")

    def fake_evaluate(intent: Any, market: Any, profile: Any) -> FillDecision:
        return FillDecision(
            status=FillStatus.FILLED,
            fill_quantity=intent.quantity,
            fill_price=Decimal("321.09"),
            remaining_quantity=Decimal(0),
            trace=ExecutionTrace(
                profile=LEGACY_CLOSE.name,
                model_version=LEGACY_CLOSE.model_version,
                reference_price=Decimal("100"),
                fill_price=Decimal("321.09"),
                reason="synthetic test",
                assumptions=LEGACY_CLOSE.assumptions,
            ),
        )

    monkeypatch.setattr("stockviz.services.trading.execute.evaluate_order", fake_evaluate)
    result = execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(1)
    )
    assert result.trade.price == Decimal("321.09")
    assert result.trade.id is not None
    row = _provenance(session, result.trade.id)
    assert row.reference_price == Decimal("100")
    assert row.fill_price == Decimal("321.09")
    assert row.reason == "synthetic test"
    assert row.assumptions == list(LEGACY_CLOSE.assumptions)


def test_sim04_historical_trade_without_provenance_remains_valid(session: Session) -> None:
    _symbol(session, close=Decimal("10"))
    user_id = _user(session, "legacy-row@stockviz.dev")
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    trade = Trade(
        portfolio_id=portfolio.id,
        ticker="AAPL",
        side=TradeSide.BUY,
        quantity=Decimal(1),
        price=Decimal("10"),
        fx_rate=Decimal(1),
    )
    session.add(trade)
    session.commit()
    session.refresh(trade)
    assert trade.id is not None
    assert (
        session.exec(
            select(SimulatedExecution).where(SimulatedExecution.trade_id == trade.id)
        ).first()
        is None
    )
    loaded = session.get(Trade, trade.id)
    assert loaded is not None
    assert loaded.price == Decimal("10")


def test_sim04_trade_id_unique(session: Session) -> None:
    _symbol(session, close=Decimal("50"))
    user_id = _user(session, "uniq@stockviz.dev")
    result = execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(1)
    )
    assert result.trade.id is not None
    row = _provenance(session, result.trade.id)
    session.add(
        SimulatedExecution(
            trade_id=result.trade.id,
            profile_name=row.profile_name,
            model_version=row.model_version,
            reference_price=row.reference_price,
            fill_price=row.fill_price,
            reason="duplicate",
            assumptions=row.assumptions,
            market_interval=row.market_interval,
            order_type=row.order_type,
            evaluated_at=row.evaluated_at,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_sim04_rollback_drops_trade_provenance_and_outbox(session: Session) -> None:
    _symbol(session, close=Decimal("40"))
    user_id = _user(session, "tx@stockviz.dev")
    priced = resolve_priced_symbol(session, "AAPL")
    provenance = _market_fill_provenance(bar=priced.bar, side=TradeSide.BUY, quantity=Decimal(1))
    fill_price = provenance.decision.fill_price
    assert fill_price is not None
    portfolio = ensure_default_portfolio(session, user_id)
    result = apply_fill(
        session,
        portfolio=portfolio,
        ticker="AAPL",
        side=TradeSide.BUY,
        quantity=Decimal(1),
        price=fill_price,
        currency=priced.currency,
        fx_rate=priced.fx_rate,
    )
    record_execution_provenance(session, trade=result.trade, provenance=provenance)
    session.flush()
    assert session.exec(select(Trade)).all()
    assert session.exec(select(SimulatedExecution)).all()
    assert session.exec(select(OutboxEvent)).all()
    session.rollback()
    assert session.exec(select(Trade)).all() == []
    assert session.exec(select(SimulatedExecution)).all() == []
    assert session.exec(select(OutboxEvent)).all() == []


def test_sim04_outbox_v1_has_no_provenance_fields(session: Session) -> None:
    _symbol(session, close=Decimal("12"))
    user_id = _user(session, "outbox@stockviz.dev")
    execute_trade(session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(1))
    events = session.exec(select(OutboxEvent)).all()
    assert len(events) == 1
    envelope = parse_trade_executed(events[0].payload)
    assert isinstance(envelope, TradeExecutedEvent)
    payload = envelope.payload.model_dump()
    assert "profile" not in payload
    assert "profile_name" not in payload
    assert "trace" not in payload
    assert "assumptions" not in payload
    assert "model_version" not in payload
    assert Decimal(envelope.payload.price) == Decimal("12")


def test_sim04_live_profile_is_passed_to_kernel(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _symbol(session, close=Decimal("90"))
    user_id = _user(session, "profile@stockviz.dev")
    seen: dict[str, Any] = {}

    def wrapping(intent: Any, market: Any, profile: Any) -> Any:
        seen["profile"] = profile
        return real_evaluate_order(intent, market, profile)

    monkeypatch.setattr("stockviz.services.trading.execute.evaluate_order", wrapping)
    execute_trade(session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(1))
    assert seen["profile"] is LEGACY_CLOSE
