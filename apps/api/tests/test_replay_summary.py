"""Replay summary, availability, and list payload (SIM-06)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlmodel import Session

from stockviz.models import Symbol
from stockviz.services.replay import (
    DEFAULT_REPLAY_CASH,
    ReplaySymbolNotFound,
    ReplayUnsupportedCurrency,
    advance_replay_session,
    cancel_replay_session,
    compute_replay_summary,
    create_replay_session,
    get_replay_availability,
    get_visible_replay_history,
    submit_replay_order,
)
from stockviz.services.simulation import OrderSide, SimulationOrderType
from tests.test_replay_session import DAY1, DAY2, DAY3, DAY4, _bar, _seed_usd, _session, _user


def test_availability_returns_stored_range(session: Session) -> None:
    _seed_usd(session)
    symbol, first, last, count = get_replay_availability(session, ticker="aapl")
    assert symbol.ticker == "AAPL"
    assert first.ts == DAY1
    assert last.ts == DAY4
    assert count == 4


def test_availability_rejects_missing_and_non_usd(session: Session) -> None:
    session.add(Symbol(ticker="BARC.L", name="Barclays", currency="GBP"))
    session.commit()
    session.add_all([_bar("BARC.L", DAY1, Decimal("10")), _bar("BARC.L", DAY2, Decimal("11"))])
    session.commit()
    with pytest.raises(ReplayUnsupportedCurrency):
        get_replay_availability(session, ticker="BARC.L")
    with pytest.raises(ReplaySymbolNotFound):
        get_replay_availability(session, ticker="MSFT")


def test_summary_no_position_uses_current_bar_only(session: Session) -> None:
    _seed_usd(
        session,
        bars=[
            (DAY1, Decimal("100")),
            (DAY2, Decimal("105")),
            (DAY3, Decimal("1000")),
        ],
    )
    replay = _session(session, _user(session), end_at=DAY3)
    summary = compute_replay_summary(session, replay)
    assert summary.current_close == Decimal("100")
    assert summary.cash == DEFAULT_REPLAY_CASH
    assert summary.positions_market_value == Decimal("0")
    assert summary.equity == DEFAULT_REPLAY_CASH
    assert summary.realized_pnl == Decimal("0")
    assert summary.unrealized_pnl == Decimal("0")
    assert summary.total_pnl == Decimal("0")
    assert summary.return_pct == Decimal("0")
    assert summary.fills_count == 0
    assert summary.visible_high == Decimal("100")
    assert summary.visible_low == Decimal("100")
    history = get_visible_replay_history(session, replay)
    assert [row.close for row in history] == [Decimal("100")]


def test_summary_long_position_marks_current_close(session: Session) -> None:
    _seed_usd(
        session,
        bars=[
            (DAY1, Decimal("100")),
            (DAY2, Decimal("105")),
            (DAY3, Decimal("1000")),
        ],
    )
    replay = _session(session, _user(session), end_at=DAY3)
    submit_replay_order(
        session,
        replay=replay,
        side=OrderSide.BUY,
        order_type=SimulationOrderType.MARKET,
        quantity=Decimal("2"),
    )
    replay = advance_replay_session(session, replay=replay)
    summary = compute_replay_summary(session, replay)
    assert summary.current_close == Decimal("105")
    assert summary.cash == DEFAULT_REPLAY_CASH - Decimal("200")
    assert summary.positions_market_value == Decimal("210")
    assert summary.unrealized_pnl == Decimal("10")
    assert summary.realized_pnl == Decimal("0")
    assert summary.equity == DEFAULT_REPLAY_CASH + Decimal("10")
    assert summary.total_pnl == Decimal("10")
    assert summary.fills_count == 1
    assert summary.visible_high == Decimal("105")
    history = get_visible_replay_history(session, replay)
    assert max(row.close for row in history) == Decimal("105")


def test_summary_partial_then_full_exit(session: Session) -> None:
    _seed_usd(session)
    replay = _session(session, _user(session))
    submit_replay_order(
        session,
        replay=replay,
        side=OrderSide.BUY,
        order_type=SimulationOrderType.MARKET,
        quantity=Decimal("2"),
    )
    replay = advance_replay_session(session, replay=replay)
    submit_replay_order(
        session,
        replay=replay,
        side=OrderSide.SELL,
        order_type=SimulationOrderType.MARKET,
        quantity=Decimal("1"),
    )
    summary = compute_replay_summary(session, replay)
    assert summary.fills_count == 2
    assert summary.realized_pnl == Decimal("20")
    assert summary.unrealized_pnl == Decimal("20")
    assert summary.positions_market_value == Decimal("120")

    replay = advance_replay_session(session, replay=replay)
    submit_replay_order(
        session,
        replay=replay,
        side=OrderSide.SELL,
        order_type=SimulationOrderType.MARKET,
        quantity=Decimal("1"),
    )
    summary = compute_replay_summary(session, replay)
    assert summary.positions_market_value == Decimal("0")
    assert summary.unrealized_pnl == Decimal("0")
    assert summary.realized_pnl == Decimal("0")
    assert summary.cash == DEFAULT_REPLAY_CASH
    assert summary.equity == DEFAULT_REPLAY_CASH
    assert summary.fills_count == 3


def test_summary_completed_and_cancelled_still_mark_current_bar(session: Session) -> None:
    _seed_usd(session, bars=[(DAY1, Decimal("100")), (DAY2, Decimal("110"))])
    user_id = _user(session)
    completed = create_replay_session(
        session, user_id=user_id, ticker="AAPL", start_at=DAY1, end_at=DAY2
    )
    completed = advance_replay_session(session, replay=completed)
    assert completed.status == "completed"
    summary = compute_replay_summary(session, completed)
    assert summary.current_close == Decimal("110")
    assert summary.has_next is False

    cancelled = create_replay_session(
        session, user_id=user_id, ticker="AAPL", start_at=DAY1, end_at=DAY2
    )
    cancelled = cancel_replay_session(session, replay=cancelled)
    summary = compute_replay_summary(session, cancelled)
    assert cancelled.status == "cancelled"
    assert summary.current_close == Decimal("100")
