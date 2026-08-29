"""Trading-layer adapters onto the pure execution kernel (SIM-02 / SIM-03)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from stockviz.models import PriceBar, TradeSide
from stockviz.models.order import OrderType, PendingOrder
from stockviz.services.simulation import OrderSide, SimulationOrderType
from stockviz.services.trading.simulation_adapter import (
    as_aware_utc,
    market_snapshot_from_bar,
    order_intent_from_pending,
    order_side,
    simulation_order_type,
)


def test_as_aware_utc_labels_naive_values_as_utc() -> None:
    naive = datetime(2026, 8, 27, 12, 0, 0)
    aware = as_aware_utc(naive)
    assert aware.tzinfo is not None
    assert aware == datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)


def test_as_aware_utc_converts_aware_values_to_utc() -> None:
    offset = timezone(timedelta(hours=-4))
    local = datetime(2026, 8, 27, 8, 0, 0, tzinfo=offset)
    assert as_aware_utc(local) == datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)


def test_order_side_and_type_use_domain_enums() -> None:
    assert order_side(TradeSide.BUY) is OrderSide.BUY
    assert order_side(TradeSide.SELL) is OrderSide.SELL
    assert simulation_order_type(OrderType.LIMIT) is SimulationOrderType.LIMIT
    assert simulation_order_type(OrderType.STOP_LOSS) is SimulationOrderType.STOP_LOSS
    assert simulation_order_type(OrderType.TAKE_PROFIT) is SimulationOrderType.TAKE_PROFIT


def test_market_order_type_is_not_a_pending_adapter_mapping() -> None:
    with pytest.raises(ValueError, match="unsupported pending order type"):
        simulation_order_type("market")  # type: ignore[arg-type]


def test_market_snapshot_observed_at_is_caller_supplied_not_bar_ts() -> None:
    bar_ts = datetime(2025, 4, 10)
    observed = datetime(2026, 8, 27, 20, 45, tzinfo=UTC)
    bar = PriceBar(
        ticker="AAPL",
        ts=bar_ts,
        interval="1d",
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10.5"),
        volume=100,
        source="test",
    )
    snapshot = market_snapshot_from_bar(bar, observed_at=observed)
    assert snapshot.observed_at == observed
    assert snapshot.observed_at.replace(tzinfo=None) != bar_ts
    assert snapshot.close == Decimal("10.5")
    assert snapshot.ticker == "AAPL"


def test_order_intent_submitted_at_is_persisted_created_at() -> None:
    created = datetime(2026, 4, 1, 14, 30, 0)
    order = PendingOrder(
        portfolio_id=1,
        ticker="AAPL",
        side=TradeSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("7"),
        limit_price=Decimal("123.45"),
        created_at=created,
    )
    intent = order_intent_from_pending(order)
    assert intent.submitted_at == datetime(2026, 4, 1, 14, 30, 0, tzinfo=UTC)
    assert intent.submitted_at != datetime.now(UTC)
    assert intent.side is OrderSide.BUY
    assert intent.order_type is SimulationOrderType.LIMIT
    assert intent.quantity == Decimal("7")
    assert intent.remaining_quantity == Decimal("7")
    assert intent.limit_price == Decimal("123.45")
