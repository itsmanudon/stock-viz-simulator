"""ReplaySession over stored 1d bars (SIM-05).

Server-owned market truth, frozen range, next-bar advance, live-ledger isolation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlmodel import Session, select

from stockviz.models import (
    OutboxEvent,
    PriceBar,
    ReplayFill,
    ReplaySession,
    SimulatedExecution,
    Symbol,
    Trade,
    User,
)
from stockviz.services.replay import (
    DEFAULT_REPLAY_CASH,
    ReplayClosed,
    ReplayCompleted,
    ReplayInsufficientCash,
    ReplayInsufficientPosition,
    ReplayRangeError,
    ReplaySymbolNotFound,
    ReplayUnsupportedCurrency,
    advance_replay_session,
    cancel_replay_session,
    create_replay_session,
    get_next_session_bar,
    get_visible_replay_history,
    submit_replay_order,
)
from stockviz.services.simulation import FillStatus, OrderSide, SimulationOrderType
from stockviz.services.trading import DEFAULT_STARTING_CASH, ensure_default_portfolio, execute_trade

DAY1 = datetime(2024, 6, 3)
DAY2 = datetime(2024, 6, 4)
DAY3 = datetime(2024, 6, 5)
DAY4 = datetime(2024, 6, 6)
DAY5 = datetime(2024, 6, 7)
FRIDAY = datetime(2024, 6, 7)
MONDAY = datetime(2024, 6, 10)
TUESDAY = datetime(2024, 6, 11)


def _user(session: Session, email: str = "replay@stockviz.dev") -> int:
    user = User(email=email, name="Replay")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def _bar(ticker: str, ts: datetime, close: Decimal) -> PriceBar:
    return PriceBar(
        ticker=ticker,
        ts=ts,
        interval="1d",
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1_000_000,
        source="test",
    )


def _seed_usd(
    session: Session,
    *,
    ticker: str = "AAPL",
    bars: list[tuple[datetime, Decimal]] | None = None,
) -> None:
    session.add(Symbol(ticker=ticker, name=f"{ticker} Inc.", currency="USD"))
    session.commit()
    if bars is None:
        bars = [
            (DAY1, Decimal("100")),
            (DAY2, Decimal("120")),
            (DAY3, Decimal("80")),
            (DAY4, Decimal("90")),
        ]
    session.add_all([_bar(ticker, ts, close) for ts, close in bars])
    session.commit()


def _session(session: Session, user_id: int, **kwargs) -> ReplaySession:
    return create_replay_session(
        session,
        user_id=user_id,
        ticker=kwargs.get("ticker", "AAPL"),
        start_at=kwargs.get("start_at", DAY1),
        end_at=kwargs.get("end_at", DAY4),
        starting_cash=kwargs.get("starting_cash", DEFAULT_REPLAY_CASH),
    )


def test_create_session_snaps_range_and_pins_profile(session: Session) -> None:
    _seed_usd(session)
    user_id = _user(session)
    replay = create_replay_session(
        session,
        user_id=user_id,
        ticker="aapl",
        start_at=datetime(2024, 6, 3, 12, 0, tzinfo=UTC),
        end_at=datetime(2024, 6, 5, 12, 0, tzinfo=UTC),
    )
    assert replay.ticker == "AAPL"
    assert replay.profile_name == "legacy_close"
    assert replay.model_version == "v1"
    assert replay.start_at == DAY2
    assert replay.current_at == DAY2
    assert replay.end_at == DAY3
    assert replay.status == "active"
    assert replay.cash_balance == DEFAULT_REPLAY_CASH


def test_end_snaps_at_or_before(session: Session) -> None:
    _seed_usd(session)
    user_id = _user(session)
    replay = create_replay_session(
        session,
        user_id=user_id,
        ticker="AAPL",
        start_at=DAY1,
        end_at=datetime(2024, 6, 5, 12, 0),
    )
    assert replay.end_at == DAY3


def test_missing_ticker_fails(session: Session) -> None:
    user_id = _user(session)
    with pytest.raises(ReplaySymbolNotFound):
        create_replay_session(session, user_id=user_id, ticker="NOPE", start_at=DAY1, end_at=DAY2)


def test_non_usd_symbol_rejected(session: Session) -> None:
    session.add(Symbol(ticker="BARC.L", name="Barclays", currency="GBP"))
    session.commit()
    session.add_all(
        [
            _bar("BARC.L", DAY1, Decimal("10")),
            _bar("BARC.L", DAY2, Decimal("11")),
        ]
    )
    session.commit()
    user_id = _user(session)
    with pytest.raises(ReplayUnsupportedCurrency):
        create_replay_session(session, user_id=user_id, ticker="BARC.L", start_at=DAY1, end_at=DAY2)


def test_single_bar_range_rejected(session: Session) -> None:
    _seed_usd(session, bars=[(DAY1, Decimal("100"))])
    user_id = _user(session)
    with pytest.raises(ReplayRangeError, match="at least 2"):
        create_replay_session(session, user_id=user_id, ticker="AAPL", start_at=DAY1, end_at=DAY1)


def test_no_future_history_or_market(session: Session) -> None:
    _seed_usd(session)
    user_id = _user(session)
    replay = _session(session, user_id, start_at=DAY1, end_at=DAY3)
    history = get_visible_replay_history(session, replay)
    assert [bar.ts for bar in history] == [DAY1]
    assert [bar.close for bar in history] == [Decimal("100")]
    nxt = get_next_session_bar(session, replay)
    assert nxt is not None
    assert nxt.ts == DAY2
    replay = advance_replay_session(session, replay=replay)
    history = get_visible_replay_history(session, replay)
    assert [bar.ts for bar in history] == [DAY1, DAY2]
    assert all(bar.ts <= replay.current_at for bar in history)


def test_end_bound_never_crosses_and_new_data_does_not_extend(session: Session) -> None:
    _seed_usd(session)
    user_id = _user(session)
    replay = _session(session, user_id, start_at=DAY1, end_at=DAY3)
    session.add(_bar("AAPL", DAY5, Decimal("200")))
    session.commit()
    assert replay.end_at == DAY3
    replay = advance_replay_session(session, replay=replay)
    replay = advance_replay_session(session, replay=replay)
    assert replay.current_at == DAY3
    assert replay.status == "completed"
    assert get_next_session_bar(session, replay) is None
    history = get_visible_replay_history(session, replay)
    assert [bar.ts for bar in history] == [DAY1, DAY2, DAY3]


def test_weekend_skip_on_advance(session: Session) -> None:
    _seed_usd(
        session,
        bars=[
            (FRIDAY, Decimal("10")),
            (MONDAY, Decimal("11")),
            (TUESDAY, Decimal("12")),
        ],
    )
    user_id = _user(session)
    replay = create_replay_session(
        session, user_id=user_id, ticker="AAPL", start_at=FRIDAY, end_at=TUESDAY
    )
    replay = advance_replay_session(session, replay=replay)
    assert replay.current_at == MONDAY
    assert replay.status == "active"


def test_complete_then_advance_conflicts(session: Session) -> None:
    _seed_usd(session, bars=[(DAY1, Decimal("1")), (DAY2, Decimal("2"))])
    user_id = _user(session)
    replay = create_replay_session(
        session, user_id=user_id, ticker="AAPL", start_at=DAY1, end_at=DAY2
    )
    replay = advance_replay_session(session, replay=replay)
    assert replay.current_at == DAY2
    assert replay.status == "completed"
    assert replay.completed_at is not None
    with pytest.raises(ReplayCompleted):
        advance_replay_session(session, replay=replay)


def test_market_buy_uses_server_bar_close(session: Session) -> None:
    _seed_usd(session)
    user_id = _user(session)
    replay = _session(session, user_id)
    result = submit_replay_order(
        session,
        replay=replay,
        side=OrderSide.BUY,
        order_type=SimulationOrderType.MARKET,
        quantity=Decimal("10"),
    )
    assert result.decision.status is FillStatus.FILLED
    assert result.decision.fill_price == Decimal("100")
    assert result.fill is not None
    assert result.fill.fill_price == Decimal("100")
    assert result.fill.evaluated_at == DAY1
    assert result.fill.profile_name == "legacy_close"
    assert result.replay.cash_balance == DEFAULT_REPLAY_CASH - Decimal("1000.000000")


def test_limit_not_triggered_writes_no_fill(session: Session) -> None:
    _seed_usd(session)
    user_id = _user(session)
    replay = _session(session, user_id)
    result = submit_replay_order(
        session,
        replay=replay,
        side=OrderSide.BUY,
        order_type=SimulationOrderType.LIMIT,
        quantity=Decimal("10"),
        limit_price=Decimal("50"),
    )
    assert result.decision.status is FillStatus.NOT_TRIGGERED
    assert result.fill is None
    assert session.exec(select(ReplayFill)).first() is None


def test_insufficient_cash_does_not_fill(session: Session) -> None:
    _seed_usd(session)
    user_id = _user(session)
    replay = _session(session, user_id, starting_cash=Decimal("10"))
    with pytest.raises(ReplayInsufficientCash):
        submit_replay_order(
            session,
            replay=replay,
            side=OrderSide.BUY,
            order_type=SimulationOrderType.MARKET,
            quantity=Decimal("10"),
        )
    session.refresh(replay)
    assert replay.cash_balance == Decimal("10")
    assert session.exec(select(ReplayFill)).first() is None


def test_sell_without_position_does_not_fill(session: Session) -> None:
    _seed_usd(session)
    user_id = _user(session)
    replay = _session(session, user_id)
    with pytest.raises(ReplayInsufficientPosition):
        submit_replay_order(
            session,
            replay=replay,
            side=OrderSide.SELL,
            order_type=SimulationOrderType.MARKET,
            quantity=Decimal("1"),
        )


def test_cancelled_session_rejects_advance_and_orders(session: Session) -> None:
    _seed_usd(session)
    user_id = _user(session)
    replay = _session(session, user_id)
    cancel_replay_session(session, replay=replay)
    with pytest.raises(ReplayClosed):
        advance_replay_session(session, replay=replay)
    with pytest.raises(ReplayClosed):
        submit_replay_order(
            session,
            replay=replay,
            side=OrderSide.BUY,
            order_type=SimulationOrderType.MARKET,
            quantity=Decimal("1"),
        )


def test_replay_does_not_write_live_trade_provenance_or_outbox(session: Session) -> None:
    _seed_usd(session)
    user_id = _user(session)
    portfolio = ensure_default_portfolio(session, user_id)
    live_cash = portfolio.cash_balance
    replay = _session(session, user_id)
    submit_replay_order(
        session,
        replay=replay,
        side=OrderSide.BUY,
        order_type=SimulationOrderType.MARKET,
        quantity=Decimal("10"),
    )
    advance_replay_session(session, replay=replay)
    session.refresh(portfolio)
    assert portfolio.cash_balance == live_cash == DEFAULT_STARTING_CASH
    assert session.exec(select(Trade)).first() is None
    assert session.exec(select(SimulatedExecution)).first() is None
    assert session.exec(select(OutboxEvent)).first() is None
    assert session.exec(select(ReplayFill)).first() is not None


def test_live_fill_does_not_write_replay_rows(session: Session) -> None:
    from stockviz.models import TradeSide

    _seed_usd(session)
    user_id = _user(session)
    execute_trade(
        session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal("1")
    )
    assert session.exec(select(Trade)).first() is not None
    assert session.exec(select(ReplaySession)).first() is None
    assert session.exec(select(ReplayFill)).first() is None


def test_lock_replay_session_emits_for_update() -> None:
    from sqlalchemy.dialects import postgresql
    from sqlmodel import select

    from stockviz.models import ReplaySession

    stmt = select(ReplaySession).where(ReplaySession.id == 1).with_for_update()
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in compiled.upper()


def test_replay_source_does_not_use_live_ledger_or_unconstrained_bars() -> None:
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "stockviz" / "services" / "replay"
    forbidden_names = {
        "apply_fill",
        "enqueue_trade_executed",
        "evaluation_clock",
        "latest_bar",
    }
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
