"""Infrastructure adapters from SQLModel trading rows onto the pure kernel.

The simulation package stays free of Session, FX, and clocks. This module is
the trading-layer boundary: naive-UTC DB timestamps, PriceBar OHLC, and
SQLModel enums become OrderIntent / MarketSnapshot values.

``PriceBar.ts`` is a market/session timestamp. It is never copied into
``MarketSnapshot.observed_at``. Callers pass an explicit availability instant.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from stockviz.models import PriceBar, TradeSide
from stockviz.models.order import OrderType, PendingOrder
from stockviz.services.simulation import (
    MarketSnapshot,
    OrderIntent,
    OrderSide,
    SimulationOrderType,
)


def evaluation_clock() -> datetime:
    """Aware UTC instant for live paper evaluation (not stored on PriceBar)."""

    return datetime.now(UTC)


def as_aware_utc(value: datetime) -> datetime:
    """Normalize a DB timestamp to aware UTC.

    StockViz persists naive UTC (``stockviz._time.utcnow``). Naive values are
    labeled UTC; aware values are converted to UTC. Local-timezone invention
    is not performed.
    """

    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def order_side(side: TradeSide) -> OrderSide:
    if side is TradeSide.BUY:
        return OrderSide.BUY
    if side is TradeSide.SELL:
        return OrderSide.SELL
    raise ValueError(f"unsupported trade side {side!r}")


def simulation_order_type(order_type: OrderType) -> SimulationOrderType:
    if order_type is OrderType.LIMIT:
        return SimulationOrderType.LIMIT
    if order_type is OrderType.STOP_LOSS:
        return SimulationOrderType.STOP_LOSS
    if order_type is OrderType.TAKE_PROFIT:
        return SimulationOrderType.TAKE_PROFIT
    raise ValueError(f"unsupported pending order type {order_type!r}")


def market_snapshot_from_bar(bar: PriceBar, *, observed_at: datetime) -> MarketSnapshot:
    """Adapt a stored 1d bar. ``observed_at`` is caller-supplied availability time."""

    return MarketSnapshot(
        ticker=bar.ticker,
        observed_at=observed_at,
        interval=bar.interval,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=Decimal(bar.volume),
    )


def order_intent_from_pending(order: PendingOrder) -> OrderIntent:
    """Map a persisted pending order. ``submitted_at`` is the order's created_at."""

    return OrderIntent(
        ticker=order.ticker,
        side=order_side(order.side),
        order_type=simulation_order_type(order.order_type),
        quantity=order.quantity,
        remaining_quantity=order.quantity,
        submitted_at=as_aware_utc(order.created_at),
        limit_price=order.limit_price,
    )
