"""ReplaySession + simulation clock (SIM-05).

Proves isolation from live paper (no Trade / SimulatedExecution / outbox),
clock-gated evaluation, and kernel reuse. Does not walk stored bars (SIM-06).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlmodel import Session, select

from stockviz.models import (
    OutboxEvent,
    ReplayFill,
    ReplaySession,
    SimulatedExecution,
    Trade,
    User,
)
from stockviz.services.replay import (
    DEFAULT_REPLAY_CASH,
    ReplayClosed,
    ReplayInsufficientCash,
    ReplayInsufficientPosition,
    ReplayLookaheadError,
    advance_replay_clock,
    close_replay_session,
    create_replay_session,
    market_snapshot_for_session,
    submit_replay_order,
)
from stockviz.services.simulation import (
    FillStatus,
    OrderSide,
    SimulationClockError,
    SimulationOrderType,
    UnknownExecutionProfileError,
)
from stockviz.services.trading import DEFAULT_STARTING_CASH, ensure_default_portfolio, execute_trade

CLOCK = datetime(2024, 6, 3, 21, 0, tzinfo=UTC)


def _user(session: Session) -> int:
    user = User(email="replay@stockviz.dev", name="Replay")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _snapshot(replay: ReplaySession, *, close: Decimal, observed_at: datetime | None = None):
    return market_snapshot_for_session(
        replay,
        ticker="AAPL",
        interval="1d",
        open=close,
        high=close,
        low=close,
        close=close,
        volume=Decimal("1000000"),
        observed_at=observed_at,
    )


def test_create_session_pins_legacy_close_and_isolated_cash(session: Session) -> None:
    user_id = _user(session)
    replay = create_replay_session(session, user_id=user_id, clock_now=CLOCK)
    assert replay.profile_name == "legacy_close"
    assert replay.model_version == "v1"
    assert replay.cash_balance == DEFAULT_REPLAY_CASH
    assert replay.status == "open"
    assert replay.clock_now.replace(tzinfo=UTC) == CLOCK


def test_unknown_profile_does_not_create_session(session: Session) -> None:
    user_id = _user(session)
    with pytest.raises(UnknownExecutionProfileError):
        create_replay_session(
            session,
            user_id=user_id,
            clock_now=CLOCK,
            profile_name="retail_realistic",
            model_version="v1",
        )
    assert session.exec(select(ReplaySession)).first() is None


def test_market_buy_uses_kernel_close_and_session_clock(session: Session) -> None:
    user_id = _user(session)
    replay = create_replay_session(session, user_id=user_id, clock_now=CLOCK)
    result = submit_replay_order(
        session,
        replay=replay,
        ticker="AAPL",
        side=OrderSide.BUY,
        order_type=SimulationOrderType.MARKET,
        quantity=Decimal("10"),
        snapshot=_snapshot(replay, close=Decimal("150")),
    )
    assert result.decision.status is FillStatus.FILLED
    assert result.decision.fill_price == Decimal("150")
    assert result.fill is not None
    assert result.fill.evaluated_at.replace(tzinfo=UTC) == CLOCK
    assert result.fill.profile_name == "legacy_close"
    assert result.fill.market_interval == "1d"
    assert result.fill.order_type == "market"
    assert "No spread model" in result.fill.assumptions
    assert result.replay.cash_balance == DEFAULT_REPLAY_CASH - Decimal("1500.000000")


def test_limit_not_triggered_writes_no_fill(session: Session) -> None:
    user_id = _user(session)
    replay = create_replay_session(session, user_id=user_id, clock_now=CLOCK)
    result = submit_replay_order(
        session,
        replay=replay,
        ticker="AAPL",
        side=OrderSide.BUY,
        order_type=SimulationOrderType.LIMIT,
        quantity=Decimal("10"),
        limit_price=Decimal("100"),
        snapshot=_snapshot(replay, close=Decimal("150")),
    )
    assert result.decision.status is FillStatus.NOT_TRIGGERED
    assert result.fill is None
    assert result.replay.cash_balance == DEFAULT_REPLAY_CASH
    assert session.exec(select(ReplayFill)).first() is None


def test_lookahead_snapshot_is_rejected(session: Session) -> None:
    user_id = _user(session)
    replay = create_replay_session(session, user_id=user_id, clock_now=CLOCK)
    future = datetime(2024, 6, 4, 21, 0, tzinfo=UTC)
    with pytest.raises(ReplayLookaheadError, match="observed_at"):
        submit_replay_order(
            session,
            replay=replay,
            ticker="AAPL",
            side=OrderSide.BUY,
            order_type=SimulationOrderType.MARKET,
            quantity=Decimal("1"),
            snapshot=_snapshot(replay, close=Decimal("150"), observed_at=future),
        )
    assert session.exec(select(ReplayFill)).first() is None
    session.refresh(replay)
    assert replay.cash_balance == DEFAULT_REPLAY_CASH


def test_advance_clock_then_that_snapshot_is_eligible(session: Session) -> None:
    user_id = _user(session)
    replay = create_replay_session(session, user_id=user_id, clock_now=CLOCK)
    later = datetime(2024, 6, 4, 21, 0, tzinfo=UTC)
    replay = advance_replay_clock(session, replay=replay, instant=later)
    result = submit_replay_order(
        session,
        replay=replay,
        ticker="AAPL",
        side=OrderSide.BUY,
        order_type=SimulationOrderType.MARKET,
        quantity=Decimal("1"),
        snapshot=_snapshot(replay, close=Decimal("10"), observed_at=later),
    )
    assert result.decision.status is FillStatus.FILLED
    assert result.fill is not None
    assert result.fill.evaluated_at.replace(tzinfo=UTC) == later


def test_clock_cannot_move_backwards(session: Session) -> None:
    user_id = _user(session)
    replay = create_replay_session(session, user_id=user_id, clock_now=CLOCK)
    with pytest.raises(SimulationClockError, match="backwards"):
        advance_replay_clock(session, replay=replay, instant=datetime(2024, 6, 1, tzinfo=UTC))


def test_insufficient_cash_does_not_fill(session: Session) -> None:
    user_id = _user(session)
    replay = create_replay_session(
        session, user_id=user_id, clock_now=CLOCK, starting_cash=Decimal("100")
    )
    with pytest.raises(ReplayInsufficientCash):
        submit_replay_order(
            session,
            replay=replay,
            ticker="AAPL",
            side=OrderSide.BUY,
            order_type=SimulationOrderType.MARKET,
            quantity=Decimal("10"),
            snapshot=_snapshot(replay, close=Decimal("150")),
        )
    session.refresh(replay)
    assert replay.cash_balance == Decimal("100")
    assert session.exec(select(ReplayFill)).first() is None


def test_sell_without_position_does_not_fill(session: Session) -> None:
    user_id = _user(session)
    replay = create_replay_session(session, user_id=user_id, clock_now=CLOCK)
    with pytest.raises(ReplayInsufficientPosition):
        submit_replay_order(
            session,
            replay=replay,
            ticker="AAPL",
            side=OrderSide.SELL,
            order_type=SimulationOrderType.MARKET,
            quantity=Decimal("1"),
            snapshot=_snapshot(replay, close=Decimal("150")),
        )


def test_closed_session_rejects_orders_and_clock(session: Session) -> None:
    user_id = _user(session)
    replay = create_replay_session(session, user_id=user_id, clock_now=CLOCK)
    close_replay_session(session, replay=replay)
    with pytest.raises(ReplayClosed):
        advance_replay_clock(session, replay=replay, instant=datetime(2024, 6, 5, tzinfo=UTC))
    with pytest.raises(ReplayClosed):
        submit_replay_order(
            session,
            replay=replay,
            ticker="AAPL",
            side=OrderSide.BUY,
            order_type=SimulationOrderType.MARKET,
            quantity=Decimal("1"),
            snapshot=_snapshot(replay, close=Decimal("10")),
        )


def test_replay_does_not_write_live_trade_provenance_or_outbox(
    session: Session,
) -> None:
    user_id = _user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    live_cash = portfolio.cash_balance
    replay = create_replay_session(session, user_id=user_id, clock_now=CLOCK)
    submit_replay_order(
        session,
        replay=replay,
        ticker="AAPL",
        side=OrderSide.BUY,
        order_type=SimulationOrderType.MARKET,
        quantity=Decimal("10"),
        snapshot=_snapshot(replay, close=Decimal("150")),
    )
    session.refresh(portfolio)
    assert portfolio.cash_balance == live_cash == DEFAULT_STARTING_CASH
    assert session.exec(select(Trade)).first() is None
    assert session.exec(select(SimulatedExecution)).first() is None
    assert session.exec(select(OutboxEvent)).first() is None
    assert session.exec(select(ReplayFill)).first() is not None


def test_live_fill_does_not_write_replay_rows(session: Session) -> None:
    from stockviz.models import PriceBar, Symbol, TradeSide

    user_id = _user(session)
    session.add(Symbol(ticker="AAPL", name="Apple", currency="USD"))
    session.commit()
    session.add(
        PriceBar(
            ticker="AAPL",
            ts=datetime(2024, 6, 3),
            interval="1d",
            open=Decimal("150"),
            high=Decimal("150"),
            low=Decimal("150"),
            close=Decimal("150"),
            volume=1_000_000,
            source="test",
        )
    )
    session.commit()
    execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal("1")
    )
    assert session.exec(select(Trade)).first() is not None
    assert session.exec(select(ReplaySession)).first() is None
    assert session.exec(select(ReplayFill)).first() is None


def test_replay_source_does_not_use_live_ledger() -> None:
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "stockviz" / "services" / "replay"
    forbidden_names = {"apply_fill", "enqueue_trade_executed", "evaluation_clock"}
    hits: list[str] = []
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in forbidden_names:
                        hits.append(f"{path.name}: import {alias.name}")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "now"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in {"datetime", "dt"}
            ):
                hits.append(f"{path.name}: datetime.now")
    assert hits == []
