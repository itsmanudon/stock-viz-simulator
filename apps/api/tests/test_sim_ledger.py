"""Phase 5.1: SimLedger matches live trading's apply_fill to the micro-unit."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlmodel import Session, col, select

from stockviz.models import Position, Trade, TradeSide, User
from stockviz.services.simulation import (
    OrderSide,
    SimInsufficientCash,
    SimInsufficientPosition,
    SimLedger,
)
from stockviz.services.trading import ensure_default_portfolio
from stockviz.services.trading.execute import apply_fill
from tests.symbols import seed_symbols

SEQUENCE = [
    (OrderSide.BUY, "10", "100.123456"),
    (OrderSide.BUY, "7", "101.5"),
    (OrderSide.SELL, "5", "103.25"),
    (OrderSide.BUY, "3", "99.999999"),
    (OrderSide.SELL, "15", "102"),
    (OrderSide.BUY, "1", "250.333333"),
]


def test_sim_ledger_matches_apply_fill(session: Session) -> None:
    seed_symbols(session, "AAPL")
    user = User(email="parity@stockviz.dev", name="P")
    session.add(user)
    session.commit()
    assert user.id is not None
    portfolio = ensure_default_portfolio(session, user.id)
    ledger = SimLedger(cash=portfolio.cash_balance)

    for side, qty, price in SEQUENCE:
        apply_fill(
            session,
            portfolio=portfolio,
            ticker="AAPL",
            side=TradeSide.BUY if side is OrderSide.BUY else TradeSide.SELL,
            quantity=Decimal(qty),
            price=Decimal(price),
            currency="USD",
            fx_rate=Decimal(1),
        )
        session.commit()
        ledger.apply(side, "AAPL", Decimal(qty), Decimal(price))

        session.refresh(portfolio)
        live = session.exec(select(Position).where(col(Position.ticker) == "AAPL")).first()
        sim = ledger.positions.get("AAPL")
        assert portfolio.cash_balance == ledger.cash
        assert (live is None) == (sim is None)
        if live is not None and sim is not None:
            assert (live.quantity, live.avg_cost) == (sim.quantity, sim.avg_cost)

    realized = sum(
        (t.realized_pnl for t in session.exec(select(Trade)).all() if t.realized_pnl is not None),
        Decimal(0),
    )
    assert realized == ledger.realized_pnl


def test_refusals_change_nothing() -> None:
    ledger = SimLedger(cash=Decimal(100))
    with pytest.raises(SimInsufficientCash):
        ledger.apply(OrderSide.BUY, "AAPL", Decimal(2), Decimal(60))
    with pytest.raises(SimInsufficientPosition):
        ledger.apply(OrderSide.SELL, "AAPL", Decimal(1), Decimal(60))
    assert ledger.cash == Decimal(100) and ledger.positions == {}


def test_fees_are_charged_on_both_sides() -> None:
    ledger = SimLedger(cash=Decimal(1000))
    ledger.apply(OrderSide.BUY, "AAPL", Decimal(5), Decimal(100), fees=Decimal("1.5"))
    ledger.apply(OrderSide.SELL, "AAPL", Decimal(5), Decimal(110), fees=Decimal("1.5"))
    assert ledger.cash == Decimal("1047.000000")
    assert ledger.realized_pnl == Decimal(50) and ledger.fees_paid == Decimal(3)
