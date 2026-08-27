"""SIM-03: pending LIMIT/STOP/TAKE_PROFIT settlement uses evaluate_order.

Trigger and fill price come from LEGACY_CLOSE. Account failures, reservations,
FX, stale-bar guards, and outbox stay in the trading layer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import Session, select

from stockviz.events.contracts import TradeExecutedEvent
from stockviz.events.outbox import parse_trade_executed
from stockviz.models import (
    FxRate,
    OutboxEvent,
    PendingOrder,
    PriceBar,
    Symbol,
    Trade,
    TradeSide,
    User,
)
from stockviz.models.order import OrderStatus, OrderType
from stockviz.services.simulation import (
    LEGACY_CLOSE,
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
from stockviz.services.trading.buying_power import reserved_cash, reserved_shares
from stockviz.services.trading.simulation_adapter import as_aware_utc

BAR_TS = datetime(2025, 4, 10)
BAR_DAY = BAR_TS.date()


def _user(session: Session, email: str) -> int:
    user = User(email=email, name="SIM-03")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _symbol(
    session: Session,
    ticker: str = "AAPL",
    *,
    close: Decimal = Decimal("100"),
    currency: str = "USD",
    ts: datetime = BAR_TS,
) -> None:
    session.add(Symbol(ticker=ticker, name=f"{ticker} Inc.", currency=currency))
    session.commit()
    session.add(
        PriceBar(
            ticker=ticker,
            ts=ts,
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


def _fx(session: Session, currency: str, usd_rate: str) -> None:
    session.add(FxRate(currency=currency, date=BAR_DAY, usd_rate=Decimal(usd_rate)))
    session.commit()


def _pid(session: Session, user_id: int) -> int:
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    return portfolio.id


def _limit_buy(
    session: Session,
    user_id: int,
    *,
    limit: Decimal,
    quantity: Decimal = Decimal(10),
    ticker: str = "AAPL",
) -> PendingOrder:
    return create_pending_order(
        session,
        user_id=user_id,
        ticker=ticker,
        side=TradeSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=quantity,
        limit_price=limit,
    )


def _filled_decision(*, quantity: Decimal, price: Decimal, close: Decimal) -> FillDecision:
    return FillDecision(
        status=FillStatus.FILLED,
        fill_quantity=quantity,
        fill_price=price,
        remaining_quantity=Decimal(0),
        trace=ExecutionTrace(
            profile=LEGACY_CLOSE.name,
            model_version=LEGACY_CLOSE.model_version,
            reference_price=close,
            fill_price=price,
            reason="test double",
            assumptions=LEGACY_CLOSE.assumptions,
        ),
    )


def _not_triggered_decision(*, quantity: Decimal, close: Decimal) -> FillDecision:
    return FillDecision(
        status=FillStatus.NOT_TRIGGERED,
        fill_quantity=Decimal(0),
        fill_price=None,
        remaining_quantity=quantity,
        trace=ExecutionTrace(
            profile=LEGACY_CLOSE.name,
            model_version=LEGACY_CLOSE.model_version,
            reference_price=close,
            fill_price=None,
            reason="test: not triggered",
            assumptions=LEGACY_CLOSE.assumptions,
        ),
    )


@pytest.mark.parametrize(
    ("close", "limit", "expect_fill"),
    [
        (Decimal("99"), Decimal("100"), True),
        (Decimal("100"), Decimal("100"), True),
        (Decimal("101"), Decimal("100"), False),
    ],
)
def test_sim03_limit_buy_trigger_parity(
    session: Session, close: Decimal, limit: Decimal, expect_fill: bool
) -> None:
    _symbol(session, close=close)
    user_id = _user(session, f"lb-{close}@stockviz.dev")
    order = _limit_buy(session, user_id, limit=limit, quantity=Decimal(2))
    filled = settle_pending_orders(session, session_date=BAR_DAY)
    session.refresh(order)
    if expect_fill:
        assert filled == 1
        assert order.status == OrderStatus.FILLED
        assert order.fill_price == close
        trade = session.exec(select(Trade)).one()
        assert trade.price == close
    else:
        assert filled == 0
        assert order.status == OrderStatus.PENDING
        assert session.exec(select(Trade)).all() == []


@pytest.mark.parametrize(
    ("close", "limit", "expect_fill"),
    [
        (Decimal("101"), Decimal("100"), True),
        (Decimal("100"), Decimal("100"), True),
        (Decimal("99"), Decimal("100"), False),
    ],
)
def test_sim03_limit_sell_trigger_parity(
    session: Session, close: Decimal, limit: Decimal, expect_fill: bool
) -> None:
    _symbol(session, close=Decimal("90"))
    user_id = _user(session, f"ls-{close}@stockviz.dev")
    execute_trade(session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(5))
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
    order = create_pending_order(
        session,
        user_id=user_id,
        ticker="AAPL",
        side=TradeSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Decimal(5),
        limit_price=limit,
    )
    filled = settle_pending_orders(session, session_date=BAR_TS.date() + timedelta(days=1))
    session.refresh(order)
    if expect_fill:
        assert filled == 1
        assert order.status == OrderStatus.FILLED
        assert order.fill_price == close
    else:
        assert filled == 0
        assert order.status == OrderStatus.PENDING


@pytest.mark.parametrize(
    ("close", "trigger", "expect_fill"),
    [
        (Decimal("99"), Decimal("100"), True),
        (Decimal("100"), Decimal("100"), True),
        (Decimal("101"), Decimal("100"), False),
    ],
)
def test_sim03_stop_loss_trigger_parity(
    session: Session, close: Decimal, trigger: Decimal, expect_fill: bool
) -> None:
    _symbol(session, close=Decimal("120"))
    user_id = _user(session, f"sl-{close}@stockviz.dev")
    execute_trade(session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(4))
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
    order = create_pending_order(
        session,
        user_id=user_id,
        ticker="AAPL",
        side=TradeSide.SELL,
        order_type=OrderType.STOP_LOSS,
        quantity=Decimal(4),
        limit_price=trigger,
    )
    filled = settle_pending_orders(session, session_date=BAR_TS.date() + timedelta(days=1))
    session.refresh(order)
    if expect_fill:
        assert filled == 1
        assert order.fill_price == close
        assert order.status == OrderStatus.FILLED
    else:
        assert filled == 0
        assert order.status == OrderStatus.PENDING


@pytest.mark.parametrize(
    ("close", "target", "expect_fill"),
    [
        (Decimal("101"), Decimal("100"), True),
        (Decimal("100"), Decimal("100"), True),
        (Decimal("99"), Decimal("100"), False),
    ],
)
def test_sim03_take_profit_trigger_parity(
    session: Session, close: Decimal, target: Decimal, expect_fill: bool
) -> None:
    _symbol(session, close=Decimal("80"))
    user_id = _user(session, f"tp-{close}@stockviz.dev")
    execute_trade(session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(3))
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
    order = create_pending_order(
        session,
        user_id=user_id,
        ticker="AAPL",
        side=TradeSide.SELL,
        order_type=OrderType.TAKE_PROFIT,
        quantity=Decimal(3),
        limit_price=target,
    )
    filled = settle_pending_orders(session, session_date=BAR_TS.date() + timedelta(days=1))
    session.refresh(order)
    if expect_fill:
        assert filled == 1
        assert order.fill_price == close
    else:
        assert filled == 0
        assert order.status == OrderStatus.PENDING


def test_sim03_kernel_fill_price_is_authoritative(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _symbol(session, close=Decimal("100"))
    user_id = _user(session, "kernel-price@stockviz.dev")
    kernel_price = Decimal("321.09")
    order = _limit_buy(session, user_id, limit=Decimal("150"), quantity=Decimal(2))
    seen: dict[str, Any] = {}

    def fake_evaluate(intent: Any, market: Any, profile: Any) -> FillDecision:
        seen["profile"] = profile
        seen["close"] = market.close
        return _filled_decision(quantity=intent.quantity, price=kernel_price, close=market.close)

    monkeypatch.setattr("stockviz.services.trading.orders.evaluate_order", fake_evaluate)
    assert settle_pending_orders(session, session_date=BAR_DAY) == 1
    session.refresh(order)
    assert seen["profile"] == LEGACY_CLOSE
    assert seen["close"] == Decimal("100")
    assert order.fill_price == kernel_price
    trade = session.exec(select(Trade)).one()
    assert trade.price == kernel_price
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.cash_balance == DEFAULT_STARTING_CASH - Decimal("642.180000")


def test_sim03_not_triggered_kernel_overrides_numeric_close(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _symbol(session, close=Decimal("100"))
    user_id = _user(session, "kernel-nt@stockviz.dev")
    order = _limit_buy(session, user_id, limit=Decimal("150"), quantity=Decimal(10))
    pid = _pid(session, user_id)
    reserved_before = reserved_cash(session, pid)

    def fake_evaluate(intent: Any, market: Any, profile: Any) -> FillDecision:
        return _not_triggered_decision(quantity=intent.quantity, close=market.close)

    monkeypatch.setattr("stockviz.services.trading.orders.evaluate_order", fake_evaluate)
    assert settle_pending_orders(session, session_date=BAR_DAY) == 0
    session.refresh(order)
    assert order.status == OrderStatus.PENDING
    assert order.fill_price is None
    assert session.exec(select(Trade)).all() == []
    assert reserved_cash(session, pid) == reserved_before


def test_sim03_triggered_buy_insufficient_cash_cancels_without_trade(session: Session) -> None:
    _symbol(session, close=Decimal("150"))
    user_id = _user(session, "buy-broke@stockviz.dev")
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
    assert order.cancel_reason is not None
    assert (
        "buying power" in order.cancel_reason.lower() or "requires" in order.cancel_reason.lower()
    )
    assert session.exec(select(Trade)).all() == []
    session.refresh(portfolio)
    assert portfolio.cash_balance == DEFAULT_STARTING_CASH
    assert reserved_cash(session, portfolio.id) == Decimal(0)


def test_sim03_triggered_sell_insufficient_shares_cancels_without_trade(session: Session) -> None:
    _symbol(session, close=Decimal("100"))
    user_id = _user(session, "sell-broke@stockviz.dev")
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    session.add(
        PendingOrder(
            portfolio_id=portfolio.id,
            ticker="AAPL",
            side=TradeSide.SELL,
            order_type=OrderType.TAKE_PROFIT,
            quantity=Decimal(5),
            limit_price=Decimal("50"),
        )
    )
    session.commit()
    assert settle_pending_orders(session, session_date=BAR_DAY) == 0
    order = session.exec(select(PendingOrder)).one()
    assert order.status == OrderStatus.CANCELLED
    assert order.cancel_reason is not None
    assert "cannot sell" in order.cancel_reason or "available" in order.cancel_reason
    assert session.exec(select(Trade)).all() == []
    assert reserved_shares(session, portfolio.id, "AAPL") == Decimal(0)


def test_sim03_not_triggered_buy_keeps_cash_reservation(session: Session) -> None:
    _symbol(session, close=Decimal("150"))
    user_id = _user(session, "res-buy@stockviz.dev")
    order = _limit_buy(session, user_id, limit=Decimal("100"), quantity=Decimal(10))
    pid = _pid(session, user_id)
    before = reserved_cash(session, pid)
    assert before > 0
    assert settle_pending_orders(session, session_date=BAR_DAY) == 0
    session.refresh(order)
    assert order.status == OrderStatus.PENDING
    assert reserved_cash(session, pid) == before


def test_sim03_not_triggered_sell_keeps_share_reservation(session: Session) -> None:
    _symbol(session, close=Decimal("90"))
    user_id = _user(session, "res-sell@stockviz.dev")
    execute_trade(session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(10))
    order = create_pending_order(
        session,
        user_id=user_id,
        ticker="AAPL",
        side=TradeSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Decimal(6),
        limit_price=Decimal("120"),
    )
    pid = _pid(session, user_id)
    before = reserved_shares(session, pid, "AAPL")
    assert before == Decimal(6)
    assert settle_pending_orders(session, session_date=BAR_DAY) == 0
    session.refresh(order)
    assert order.status == OrderStatus.PENDING
    assert reserved_shares(session, pid, "AAPL") == before


def test_sim03_fill_releases_buy_reservation(session: Session) -> None:
    _symbol(session, close=Decimal("100"))
    user_id = _user(session, "res-fill@stockviz.dev")
    order = _limit_buy(session, user_id, limit=Decimal("100"), quantity=Decimal(10))
    pid = _pid(session, user_id)
    assert reserved_cash(session, pid) > 0
    assert settle_pending_orders(session, session_date=BAR_DAY) == 1
    session.refresh(order)
    assert order.status == OrderStatus.FILLED
    assert reserved_cash(session, pid) == Decimal(0)


def test_sim03_ineligible_leaves_order_pending(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _symbol(session, close=Decimal("100"))
    user_id = _user(session, "ineligible@stockviz.dev")
    order = _limit_buy(session, user_id, limit=Decimal("150"), quantity=Decimal(1))
    pid = _pid(session, user_id)
    reserved_before = reserved_cash(session, pid)

    def past_clock() -> datetime:
        return datetime(2020, 1, 1, tzinfo=UTC)

    monkeypatch.setattr("stockviz.services.trading.orders.evaluation_clock", past_clock)
    assert settle_pending_orders(session, session_date=BAR_DAY) == 0
    session.refresh(order)
    assert order.status == OrderStatus.PENDING
    assert order.cancel_reason is None
    assert session.exec(select(Trade)).all() == []
    assert reserved_cash(session, pid) == reserved_before


def test_sim03_normal_settlement_observed_at_after_created_at(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _symbol(session, close=Decimal("100"))
    user_id = _user(session, "temporal-ok@stockviz.dev")
    order = _limit_buy(session, user_id, limit=Decimal("150"), quantity=Decimal(1))
    seen: dict[str, Any] = {}

    def wrapping_evaluate(intent: Any, market: Any, profile: Any) -> FillDecision:
        seen["submitted_at"] = intent.submitted_at
        seen["observed_at"] = market.observed_at
        return real_evaluate_order(intent, market, profile)

    monkeypatch.setattr("stockviz.services.trading.orders.evaluate_order", wrapping_evaluate)
    assert settle_pending_orders(session, session_date=BAR_DAY) == 1
    session.refresh(order)
    assert order.status == OrderStatus.FILLED
    assert seen["submitted_at"].tzinfo is not None
    assert seen["observed_at"].tzinfo is not None
    assert seen["submitted_at"] == as_aware_utc(order.created_at)
    assert seen["observed_at"] >= seen["submitted_at"]
    assert seen["observed_at"].replace(tzinfo=None) != BAR_TS


def test_sim03_stale_bar_guard_leaves_pending(session: Session) -> None:
    _symbol(session, close=Decimal("100"))
    user_id = _user(session, "stale@stockviz.dev")
    order = _limit_buy(session, user_id, limit=Decimal("150"), quantity=Decimal(1))
    filled = settle_pending_orders(session, session_date=BAR_DAY + timedelta(days=1))
    session.refresh(order)
    assert filled == 0
    assert order.status == OrderStatus.PENDING
    assert session.exec(select(Trade)).all() == []


def test_sim03_non_usd_fill_stays_native_and_converts_cash(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _symbol(session, "SAP.DE", close=Decimal("80"), currency="EUR")
    _fx(session, "EUR", "1.10")
    user_id = _user(session, "fx@stockviz.dev")
    order = _limit_buy(session, user_id, ticker="SAP.DE", limit=Decimal("90"), quantity=Decimal(5))
    seen: dict[str, Any] = {}

    def wrapping_evaluate(intent: Any, market: Any, profile: Any) -> Any:
        seen["close"] = market.close
        seen["limit"] = intent.limit_price
        seen["ticker"] = intent.ticker
        return real_evaluate_order(intent, market, profile)

    monkeypatch.setattr("stockviz.services.trading.orders.evaluate_order", wrapping_evaluate)
    assert settle_pending_orders(session, session_date=BAR_DAY) == 1
    session.refresh(order)
    assert seen["ticker"] == "SAP.DE"
    assert seen["close"] == Decimal("80")
    assert seen["limit"] == Decimal("90")
    assert order.fill_price == Decimal("80")
    trade = session.exec(select(Trade)).one()
    assert trade.price == Decimal("80")
    assert trade.fx_rate == Decimal("1.10000000")
    portfolio = ensure_default_portfolio(session, user_id)
    assert DEFAULT_STARTING_CASH - portfolio.cash_balance == Decimal("440.000000")


def test_sim03_filled_pending_order_outbox_schema_unchanged(session: Session) -> None:
    _symbol(session, close=Decimal("10"))
    user_id = _user(session, "outbox@stockviz.dev")
    _limit_buy(session, user_id, limit=Decimal("12"), quantity=Decimal(5))
    assert settle_pending_orders(session, session_date=BAR_DAY) == 1
    events = session.exec(select(OutboxEvent)).all()
    assert len(events) == 1
    envelope = parse_trade_executed(events[0].payload)
    assert isinstance(envelope, TradeExecutedEvent)
    payload = envelope.payload.model_dump()
    assert "profile" not in payload
    assert "trace" not in payload
    assert Decimal(envelope.payload.price) == Decimal("10")


def test_sim03_batch_handles_mixed_outcomes(session: Session) -> None:
    _symbol(session, close=Decimal("100"))
    user_id = _user(session, "batch@stockviz.dev")
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    execute_trade(session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(5))

    stay = _limit_buy(session, user_id, limit=Decimal("50"), quantity=Decimal(1))
    fill = create_pending_order(
        session,
        user_id=user_id,
        ticker="AAPL",
        side=TradeSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Decimal(5),
        limit_price=Decimal("100"),
    )
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
    assert settle_pending_orders(session, session_date=BAR_DAY) == 1
    session.refresh(stay)
    session.refresh(fill)
    ghost = session.exec(select(PendingOrder).where(PendingOrder.quantity == Decimal(1000))).one()
    assert stay.status == OrderStatus.PENDING
    assert fill.status == OrderStatus.FILLED
    assert ghost.status == OrderStatus.CANCELLED
    assert ghost.cancel_reason is not None


def test_sim03_invalid_buy_stop_left_pending(session: Session) -> None:
    _symbol(session, close=Decimal("50"))
    user_id = _user(session, "buystop@stockviz.dev")
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    session.add(
        PendingOrder(
            portfolio_id=portfolio.id,
            ticker="AAPL",
            side=TradeSide.BUY,
            order_type=OrderType.STOP_LOSS,
            quantity=Decimal(1),
            limit_price=Decimal("100"),
        )
    )
    session.commit()
    assert settle_pending_orders(session, session_date=BAR_DAY) == 0
    order = session.exec(select(PendingOrder)).one()
    assert order.status == OrderStatus.PENDING
    assert session.exec(select(Trade)).all() == []


def test_sim03_fx_missing_cancels_like_today(session: Session) -> None:
    session.add(Symbol(ticker="SAP.DE", name="SAP SE", currency="EUR"))
    session.commit()
    session.add(
        PriceBar(
            ticker="SAP.DE",
            ts=BAR_TS,
            interval="1d",
            open=Decimal("80"),
            high=Decimal("80"),
            low=Decimal("80"),
            close=Decimal("80"),
            volume=1,
            source="test",
        )
    )
    session.commit()
    user_id = _user(session, "nofx@stockviz.dev")
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.id is not None
    session.add(
        PendingOrder(
            portfolio_id=portfolio.id,
            ticker="SAP.DE",
            side=TradeSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal(1),
            limit_price=Decimal("90"),
        )
    )
    session.commit()
    assert settle_pending_orders(session, session_date=BAR_DAY) == 0
    order = session.exec(select(PendingOrder)).one()
    assert order.status == OrderStatus.CANCELLED
    assert order.cancel_reason is not None
    assert "FX" in order.cancel_reason or "fx" in order.cancel_reason.lower()
    assert session.exec(select(Trade)).all() == []


def test_sim03_production_orders_module_has_no_should_fill() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "stockviz"
        / "services"
        / "trading"
        / "orders.py"
    ).read_text(encoding="utf-8")
    assert "_should_fill" not in source
    assert "evaluate_order" in source
    assert "LEGACY_CLOSE" in source
