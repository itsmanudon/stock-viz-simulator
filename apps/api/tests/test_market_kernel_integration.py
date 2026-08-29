"""SIM-02: live MARKET fills go through evaluate_order(..., LEGACY_CLOSE).

These tests pin parity with pre-kernel market economics and prove the kernel
fill price is what ``apply_fill`` records. Pending settlement is covered by
``test_pending_kernel_integration.py`` (SIM-03).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlmodel import Session, select

from stockviz.events.contracts import TradeExecutedEvent
from stockviz.events.outbox import parse_trade_executed
from stockviz.models import (
    FxRate,
    OutboxEvent,
    Portfolio,
    Position,
    PriceBar,
    Symbol,
    Trade,
    TradeSide,
    User,
)
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
    InsufficientCash,
    InsufficientPosition,
    execute_trade,
)
from stockviz.services.trading.execute import (
    TradeExecutionError,
    ensure_default_portfolio,
    get_position,
)
from stockviz.services.trading.portfolio import compute_portfolio


def _seed_usd(session: Session, *, ticker: str = "AAPL", close: Decimal = Decimal("150")) -> None:
    session.add(Symbol(ticker=ticker, name=f"{ticker} Inc.", currency="USD"))
    session.commit()
    session.add(
        PriceBar(
            ticker=ticker,
            ts=datetime(2025, 4, 10),
            interval="1d",
            open=close,
            high=close,
            low=close,
            close=close,
            volume=1_000_000,
            source="test",
        )
    )
    session.commit()


def _user(session: Session, email: str = "sim02@stockviz.dev") -> int:
    user = User(email=email, name="SIM-02")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def test_sim02_market_buy_matches_pre_kernel_fill_economics(session: Session) -> None:
    _seed_usd(session, close=Decimal("150"))
    user_id = _user(session, "buy-parity@stockviz.dev")

    result = execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(10)
    )
    assert result.trade.price == Decimal("150")
    assert result.trade.quantity == Decimal(10)
    assert result.currency == "USD"
    assert result.native_cost == Decimal("1500")
    assert result.usd_cost == Decimal("1500")

    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.cash_balance == DEFAULT_STARTING_CASH - Decimal("1500")
    pos = get_position(session, portfolio_id=portfolio.id, ticker="AAPL")  # type: ignore[arg-type]
    assert pos is not None
    assert pos.quantity == Decimal(10)
    assert pos.avg_cost == Decimal("150")


def test_sim02_market_sell_matches_pre_kernel_position_and_pnl(session: Session) -> None:
    _seed_usd(session, close=Decimal("150"))
    user_id = _user(session, "sell-parity@stockviz.dev")
    execute_trade(session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(10))

    session.add(
        PriceBar(
            ticker="AAPL",
            ts=datetime(2025, 4, 11),
            interval="1d",
            open=Decimal("170"),
            high=Decimal("170"),
            low=Decimal("170"),
            close=Decimal("170"),
            volume=1_000,
            source="test",
        )
    )
    session.commit()

    result = execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.SELL, quantity=Decimal(5)
    )
    assert result.trade.price == Decimal("170")
    assert result.realized_pnl == Decimal("100.000000")

    portfolio = ensure_default_portfolio(session, user_id)
    # Bought 10 @ 150 = 1500; sold 5 @ 170 = 850; cash = 100000 - 1500 + 850
    assert portfolio.cash_balance == DEFAULT_STARTING_CASH - Decimal("1500") + Decimal("850")
    pos = get_position(session, portfolio_id=portfolio.id, ticker="AAPL")  # type: ignore[arg-type]
    assert pos is not None
    assert pos.quantity == Decimal(5)
    assert pos.avg_cost == Decimal("150")

    execute_trade(session, user_id=user_id, ticker="AAPL", side=TradeSide.SELL, quantity=Decimal(5))
    snap = compute_portfolio(session, portfolio)
    assert snap.positions == []


def test_sim02_insufficient_cash_is_still_a_trading_layer_error(session: Session) -> None:
    _seed_usd(session, close=Decimal("150"))
    user_id = _user(session, "cash-fail@stockviz.dev")
    with pytest.raises(InsufficientCash):
        execute_trade(
            session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(1000)
        )


def test_sim02_insufficient_shares_is_still_a_trading_layer_error(session: Session) -> None:
    _seed_usd(session, close=Decimal("150"))
    user_id = _user(session, "shares-fail@stockviz.dev")
    with pytest.raises(InsufficientPosition):
        execute_trade(
            session, user_id=user_id, ticker="AAPL", side=TradeSide.SELL, quantity=Decimal(1)
        )


def test_sim02_fx_path_still_converts_native_fill_to_usd(session: Session) -> None:
    session.add(Symbol(ticker="SAP.DE", name="SAP SE", currency="EUR"))
    session.commit()
    session.add(
        PriceBar(
            ticker="SAP.DE",
            ts=datetime(2026, 5, 16),
            interval="1d",
            open=Decimal("120"),
            high=Decimal("120"),
            low=Decimal("120"),
            close=Decimal("120"),
            volume=1_000,
            source="test",
        )
    )
    from stockviz._time import utcnow

    session.add(FxRate(currency="EUR", date=utcnow().date(), usd_rate=Decimal("1.10")))
    session.commit()
    user_id = _user(session, "fx-parity@stockviz.dev")

    result = execute_trade(
        session, user_id=user_id, ticker="SAP.DE", side=TradeSide.BUY, quantity=Decimal(10)
    )
    assert result.trade.price == Decimal("120")
    assert result.currency == "EUR"
    assert result.fx_rate == Decimal("1.10")
    assert result.native_cost == Decimal("1200.000000")
    assert result.usd_cost == Decimal("1320.000000")
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.cash_balance == DEFAULT_STARTING_CASH - Decimal("1320.000000")


def test_sim02_outbox_schema_unchanged(session: Session) -> None:
    _seed_usd(session, close=Decimal("10"))
    user_id = _user(session, "outbox-parity@stockviz.dev")
    execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal("10")
    )

    events = session.exec(select(OutboxEvent)).all()
    assert len(events) == 1
    envelope = parse_trade_executed(events[0].payload)
    assert isinstance(envelope, TradeExecutedEvent)
    payload = envelope.payload.model_dump()
    assert "profile" not in payload
    assert "trace" not in payload
    assert "model_version" not in payload
    assert Decimal(envelope.payload.price) == Decimal("10")


def test_sim02_kernel_fill_price_is_authoritative(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_usd(session, close=Decimal("150"))
    user_id = _user(session, "kernel-price@stockviz.dev")
    kernel_price = Decimal("321.09")
    seen: dict[str, Any] = {}

    def fake_evaluate(order: Any, market: Any, profile: Any) -> FillDecision:
        seen["profile"] = profile
        seen["close"] = market.close
        remaining = (
            order.remaining_quantity if order.remaining_quantity is not None else order.quantity
        )
        return FillDecision(
            status=FillStatus.FILLED,
            fill_quantity=remaining,
            fill_price=kernel_price,
            remaining_quantity=Decimal(0),
            trace=ExecutionTrace(
                profile=LEGACY_CLOSE.name,
                model_version=LEGACY_CLOSE.model_version,
                reference_price=kernel_price,
                fill_price=kernel_price,
                reason="test double",
                assumptions=LEGACY_CLOSE.assumptions,
            ),
        )

    monkeypatch.setattr("stockviz.services.trading.execute.evaluate_order", fake_evaluate)
    result = execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(2)
    )
    assert seen["profile"] == LEGACY_CLOSE
    assert seen["close"] == Decimal("150")
    assert result.trade.price == kernel_price
    assert result.native_cost == Decimal("642.180000")
    portfolio = ensure_default_portfolio(session, user_id)
    assert portfolio.cash_balance == DEFAULT_STARTING_CASH - Decimal("642.180000")


def test_sim02_unexpected_kernel_outcome_does_not_apply_fill(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_usd(session, close=Decimal("150"))
    user_id = _user(session, "kernel-miss@stockviz.dev")

    def fake_evaluate(order: Any, market: Any, profile: Any) -> FillDecision:
        return FillDecision(
            status=FillStatus.NOT_TRIGGERED,
            fill_quantity=Decimal(0),
            fill_price=None,
            remaining_quantity=order.quantity,
            trace=ExecutionTrace(
                profile=LEGACY_CLOSE.name,
                model_version=LEGACY_CLOSE.model_version,
                reference_price=market.close,
                fill_price=None,
                reason="test: market did not trigger",
                assumptions=LEGACY_CLOSE.assumptions,
            ),
        )

    monkeypatch.setattr("stockviz.services.trading.execute.evaluate_order", fake_evaluate)
    with pytest.raises(TradeExecutionError, match="Unable to fill market order"):
        execute_trade(
            session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(1)
        )

    assert session.exec(select(Trade)).all() == []
    portfolio = session.exec(select(Portfolio)).first()
    if portfolio is not None:
        assert portfolio.cash_balance == DEFAULT_STARTING_CASH
    assert session.exec(select(Position)).all() == []


def test_sim02_adapter_does_not_use_bar_ts_as_observed_at(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_usd(session, close=Decimal("150"))
    user_id = _user(session, "observed-at@stockviz.dev")
    seen: dict[str, Any] = {}

    def wrapping_evaluate(order: Any, market: Any, profile: Any) -> FillDecision:
        seen["submitted_at"] = order.submitted_at
        seen["observed_at"] = market.observed_at
        seen["close"] = market.close
        seen["interval"] = market.interval
        return real_evaluate_order(order, market, profile)

    monkeypatch.setattr("stockviz.services.trading.execute.evaluate_order", wrapping_evaluate)
    result = execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(1)
    )
    assert result.trade.price == Decimal("150")
    assert seen["interval"] == "1d"
    assert seen["close"] == Decimal("150")
    assert seen["observed_at"] == seen["submitted_at"]
    assert seen["observed_at"].tzinfo is not None
    assert seen["observed_at"].replace(tzinfo=None) != datetime(2025, 4, 10)
