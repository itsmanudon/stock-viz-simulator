"""Trade execution + portfolio computation tests against the SQLite fixture."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from sqlmodel import Session

from stockviz.models import PriceBar, Symbol, TradeSide, User
from stockviz.services.trading import (
    DEFAULT_STARTING_CASH,
    InsufficientCash,
    InsufficientPosition,
    NoMarketDataError,
    SymbolNotFound,
    TradeExecutionError,
    compute_portfolio,
    ensure_default_portfolio,
    execute_trade,
)


def _seed_market(session: Session) -> None:
    session.add_all(
        [
            Symbol(ticker="AAPL", name="Apple Inc."),
            Symbol(ticker="MSFT", name="Microsoft"),
        ]
    )
    session.commit()
    # Latest close = $150 for AAPL, $300 for MSFT
    session.add_all(
        [
            PriceBar(
                ticker="AAPL",
                ts=datetime(2025, 4, 10),
                interval="1d",
                open=Decimal("145"),
                high=Decimal("151"),
                low=Decimal("144"),
                close=Decimal("150"),
                volume=1_000_000,
                source="test",
            ),
            PriceBar(
                ticker="MSFT",
                ts=datetime(2025, 4, 10),
                interval="1d",
                open=Decimal("298"),
                high=Decimal("305"),
                low=Decimal("295"),
                close=Decimal("300"),
                volume=1_000_000,
                source="test",
            ),
        ]
    )
    session.commit()


def _make_user(session: Session) -> int:
    user = User(email="trader@stockviz.dev", name="Trader")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def test_ensure_default_portfolio_is_idempotent(session: Session) -> None:
    user_id = _make_user(session)
    p1 = ensure_default_portfolio(session, user_id)
    p2 = ensure_default_portfolio(session, user_id)
    assert p1.id == p2.id
    assert p1.cash_balance == DEFAULT_STARTING_CASH


def test_buy_then_sell_round_trip(session: Session) -> None:
    _seed_market(session)
    user_id = _make_user(session)

    # Buy 10 AAPL @ 150 = $1,500
    result = execute_trade(
        session,
        user_id=user_id,
        ticker="AAPL",
        side=TradeSide.BUY,
        quantity=Decimal(10),
    )
    assert result.trade.price == Decimal("150")
    # USD symbol: native and USD cost match.
    assert result.currency == "USD"
    assert result.fx_rate == Decimal(1)
    assert result.native_cost == Decimal("1500")
    assert result.usd_cost == Decimal("1500")

    portfolio = ensure_default_portfolio(session, user_id)
    snap = compute_portfolio(session, portfolio)
    assert snap.cash_balance == DEFAULT_STARTING_CASH - Decimal("1500")
    assert len(snap.positions) == 1
    assert snap.positions[0].quantity == Decimal(10)
    assert snap.positions[0].avg_cost == Decimal("150")
    # Unrealized P&L is zero right after the buy (last close == avg cost).
    assert snap.unrealized_pl == Decimal(0)

    # Sell 4 AAPL @ 150 = $600 back into cash
    execute_trade(
        session,
        user_id=user_id,
        ticker="AAPL",
        side=TradeSide.SELL,
        quantity=Decimal(4),
    )
    snap = compute_portfolio(session, portfolio)
    assert snap.cash_balance == DEFAULT_STARTING_CASH - Decimal("900")
    assert snap.positions[0].quantity == Decimal(6)

    # Sell the remaining 6 — the position row should be removed.
    execute_trade(
        session,
        user_id=user_id,
        ticker="AAPL",
        side=TradeSide.SELL,
        quantity=Decimal(6),
    )
    snap = compute_portfolio(session, portfolio)
    assert snap.cash_balance == DEFAULT_STARTING_CASH
    assert snap.positions == []


def test_buy_recomputes_weighted_avg_cost(session: Session) -> None:
    _seed_market(session)
    user_id = _make_user(session)

    # First buy 10 AAPL at $150.
    execute_trade(session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(10))
    # Move the market to $160 then buy 10 more — should average to $155.
    session.add(
        PriceBar(
            ticker="AAPL",
            ts=datetime(2025, 4, 11),
            interval="1d",
            open=Decimal("155"),
            high=Decimal("162"),
            low=Decimal("154"),
            close=Decimal("160"),
            volume=1_000_000,
            source="test",
        )
    )
    session.commit()
    execute_trade(session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(10))
    snap = compute_portfolio(session, ensure_default_portfolio(session, user_id))
    pos = snap.positions[0]
    assert pos.quantity == Decimal(20)
    assert pos.avg_cost == Decimal("155")


def test_buy_rejects_insufficient_cash(session: Session) -> None:
    _seed_market(session)
    user_id = _make_user(session)
    with pytest.raises(InsufficientCash):
        # AAPL is $150; 1000 shares = $150k, but we only have $100k.
        execute_trade(
            session,
            user_id=user_id,
            ticker="AAPL",
            side=TradeSide.BUY,
            quantity=Decimal(1000),
        )


def test_sell_rejects_no_position(session: Session) -> None:
    _seed_market(session)
    user_id = _make_user(session)
    with pytest.raises(InsufficientPosition):
        execute_trade(
            session, user_id=user_id, ticker="AAPL", side=TradeSide.SELL, quantity=Decimal(1)
        )


def test_unknown_symbol_rejected(session: Session) -> None:
    user_id = _make_user(session)
    with pytest.raises(SymbolNotFound):
        execute_trade(
            session, user_id=user_id, ticker="NOPE", side=TradeSide.BUY, quantity=Decimal(1)
        )


def test_symbol_without_bars_rejected(session: Session) -> None:
    user_id = _make_user(session)
    session.add(Symbol(ticker="NEWCO", name="New"))
    session.commit()
    with pytest.raises(NoMarketDataError):
        execute_trade(
            session, user_id=user_id, ticker="NEWCO", side=TradeSide.BUY, quantity=Decimal(1)
        )


def test_zero_quantity_rejected(session: Session) -> None:
    _seed_market(session)
    user_id = _make_user(session)
    with pytest.raises(TradeExecutionError):
        execute_trade(
            session, user_id=user_id, ticker="AAPL", side=TradeSide.BUY, quantity=Decimal(0)
        )
