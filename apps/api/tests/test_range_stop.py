"""A4.1: the kernel's range stop and SimLedger's shorts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from stockviz.services.simulation import (
    LEGACY_CLOSE,
    NEXT_OPEN,
    CostModel,
    ExecutionProfile,
    FillStatus,
    MarketSnapshot,
    OrderIntent,
    OrderSide,
    SimInsufficientPosition,
    SimLedger,
    SimulationOrderType,
    evaluate_range_stop,
)

AT = datetime(2025, 1, 2, 21, tzinfo=UTC)


def bar(o: str, h: str, lo: str, c: str) -> MarketSnapshot:
    return MarketSnapshot(ticker="AAPL", observed_at=AT, interval="1d", open=Decimal(o),
                          high=Decimal(h), low=Decimal(lo), close=Decimal(c), volume=Decimal(1))  # fmt: skip


def stop(side: OrderSide, level: str, kind=SimulationOrderType.STOP_LOSS) -> OrderIntent:
    return OrderIntent(ticker="AAPL", side=side, order_type=kind, quantity=Decimal(3),
                       submitted_at=AT, limit_price=Decimal(level))  # fmt: skip


@pytest.mark.parametrize(
    ("side", "level", "b", "status", "price"),
    [
        (OrderSide.SELL, "95", ("100", "101", "94", "96"), FillStatus.FILLED, "95"),
        (OrderSide.SELL, "95", ("93", "96", "92", "95"), FillStatus.FILLED, "93"),  # gap
        (OrderSide.SELL, "95", ("95", "96", "95", "95"), FillStatus.FILLED, "95"),  # open at stop
        (OrderSide.SELL, "95", ("100", "101", "95.01", "96"), FillStatus.NOT_TRIGGERED, None),
        (OrderSide.BUY, "105", ("100", "106", "99", "104"), FillStatus.FILLED, "105"),
        (OrderSide.BUY, "105", ("107", "108", "106", "107"), FillStatus.FILLED, "107"),  # gap
        (OrderSide.BUY, "105", ("100", "104.99", "99", "104"), FillStatus.NOT_TRIGGERED, None),
    ],
)
def test_range_stop_rule(side, level, b, status, price) -> None:
    for profile in (NEXT_OPEN, LEGACY_CLOSE):
        decision = evaluate_range_stop(stop(side, level), bar(*b), profile)
        assert decision.status is status
        assert decision.fill_price == (Decimal(price) if price else None)
        assert decision.trace.profile == profile.name


def test_range_stop_costs_move_against_the_trader() -> None:
    d = evaluate_range_stop(
        stop(OrderSide.SELL, "95"), bar("100", "101", "94", "96"), NEXT_OPEN,
        CostModel(slippage_bps=Decimal(10)),
    )  # fmt: skip
    assert d.fill_price == Decimal("94.905000") and d.trace.reference_price == Decimal(95)


def test_range_stop_refuses_other_orders_and_profiles() -> None:
    limit = stop(OrderSide.SELL, "95", SimulationOrderType.LIMIT)
    assert evaluate_range_stop(limit, bar("100", "101", "94", "96"), NEXT_OPEN).status is (
        FillStatus.INELIGIBLE
    )
    fake = ExecutionProfile(name="ideal", model_version="v1", assumptions=())
    assert evaluate_range_stop(
        stop(OrderSide.SELL, "95"), bar("100", "101", "94", "96"), fake
    ).status is (FillStatus.INELIGIBLE)


def test_ledger_short_round_trip() -> None:
    ledger = SimLedger(cash=Decimal(1000))
    ledger.apply_short(OrderSide.SELL, "AAPL", Decimal(5), Decimal(100), fees=Decimal(1))
    assert ledger.cash == Decimal(1499) and ledger.shorts["AAPL"].quantity == 5
    assert ledger.equity({"AAPL": Decimal(90)}) == Decimal(1049)
    with pytest.raises(SimInsufficientPosition):
        ledger.apply_short(OrderSide.BUY, "AAPL", Decimal(6), Decimal(90))
    fill = ledger.apply_short(OrderSide.BUY, "AAPL", Decimal(5), Decimal(90), fees=Decimal(1))
    assert fill.realized_pnl == Decimal(50) and ledger.cash == Decimal(1048)
    assert ledger.shorts == {} and ledger.fees_paid == Decimal(2)
