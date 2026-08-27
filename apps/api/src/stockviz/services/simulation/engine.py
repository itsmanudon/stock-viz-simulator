"""Deterministic order-execution decisions.

Pure functions: no Session, settings, clock, or I/O. Fill economics for
``LEGACY_CLOSE`` match ``services/trading/execute.py`` (market at latest 1d
close) and ``services/trading/orders.py::_should_fill`` (pending EOD close).
"""

from __future__ import annotations

from decimal import Decimal

from stockviz.services.simulation.contracts import (
    ExecutionProfile,
    ExecutionTrace,
    FillDecision,
    FillStatus,
    MarketSnapshot,
    OrderIntent,
    OrderSide,
    SimulationOrderType,
)
from stockviz.services.simulation.profiles import is_legacy_close


def evaluate_order(
    order: OrderIntent,
    market: MarketSnapshot,
    profile: ExecutionProfile,
) -> FillDecision:
    """Decide whether ``order`` fills against ``market`` under ``profile``."""

    if not is_legacy_close(profile):
        return _ineligible(
            order,
            profile,
            reason=f"Execution profile {profile.name!r} {profile.model_version!r} is not implemented",
        )

    if _norm_ticker(order.ticker) != _norm_ticker(market.ticker):
        return _ineligible(
            order,
            profile,
            reason="Order ticker does not match market snapshot ticker",
        )

    if market.observed_at < order.submitted_at:
        return _ineligible(
            order,
            profile,
            reason="Market snapshot observed_at precedes order submitted_at",
        )

    if (
        order.order_type
        in (
            SimulationOrderType.STOP_LOSS,
            SimulationOrderType.TAKE_PROFIT,
        )
        and order.side is not OrderSide.SELL
    ):
        label = "Stop-loss" if order.order_type is SimulationOrderType.STOP_LOSS else "Take-profit"
        return _ineligible(
            order,
            profile,
            reason=f"{label} orders are sell-only",
        )

    if order.order_type is SimulationOrderType.MARKET:
        return _filled(
            order,
            market,
            profile,
            reason="Market order fills at observable daily close",
        )

    assert order.limit_price is not None
    if not _legacy_should_fill(order, market.close):
        return _not_triggered(order, market, profile, reason=_not_triggered_reason(order))
    return _filled(order, market, profile, reason=_filled_reason(order))


def _legacy_should_fill(order: OrderIntent, close: Decimal) -> bool:
    """Parity with ``services/trading/orders.py::_should_fill``."""

    assert order.limit_price is not None
    if order.order_type is SimulationOrderType.LIMIT:
        return (
            close <= order.limit_price
            if order.side is OrderSide.BUY
            else close >= order.limit_price
        )
    if order.order_type is SimulationOrderType.STOP_LOSS:
        return close <= order.limit_price
    if order.order_type is SimulationOrderType.TAKE_PROFIT:
        return close >= order.limit_price
    return False


def _norm_ticker(ticker: str) -> str:
    return ticker.strip().upper()


def _filled(
    order: OrderIntent,
    market: MarketSnapshot,
    profile: ExecutionProfile,
    *,
    reason: str,
) -> FillDecision:
    remaining = _remaining(order)
    return FillDecision(
        status=FillStatus.FILLED,
        fill_quantity=remaining,
        fill_price=market.close,
        remaining_quantity=Decimal(0),
        trace=_trace(profile, reference_price=market.close, fill_price=market.close, reason=reason),
    )


def _not_triggered(
    order: OrderIntent,
    market: MarketSnapshot,
    profile: ExecutionProfile,
    *,
    reason: str,
) -> FillDecision:
    return FillDecision(
        status=FillStatus.NOT_TRIGGERED,
        fill_quantity=Decimal(0),
        fill_price=None,
        remaining_quantity=_remaining(order),
        trace=_trace(profile, reference_price=market.close, fill_price=None, reason=reason),
    )


def _ineligible(
    order: OrderIntent,
    profile: ExecutionProfile,
    *,
    reason: str,
    reference_price: Decimal | None = None,
) -> FillDecision:
    return FillDecision(
        status=FillStatus.INELIGIBLE,
        fill_quantity=Decimal(0),
        fill_price=None,
        remaining_quantity=_remaining(order),
        trace=_trace(profile, reference_price=reference_price, fill_price=None, reason=reason),
    )


def _remaining(order: OrderIntent) -> Decimal:
    remaining = order.remaining_quantity
    assert remaining is not None
    return remaining


def _trace(
    profile: ExecutionProfile,
    *,
    reference_price: Decimal | None,
    fill_price: Decimal | None,
    reason: str,
) -> ExecutionTrace:
    return ExecutionTrace(
        profile=profile.name,
        model_version=profile.model_version,
        reference_price=reference_price,
        fill_price=fill_price,
        reason=reason,
        assumptions=profile.assumptions,
    )


def _filled_reason(order: OrderIntent) -> str:
    if order.order_type is SimulationOrderType.LIMIT:
        if order.side is OrderSide.BUY:
            return "Limit buy triggers when close <= limit; fills at close"
        return "Limit sell triggers when close >= limit; fills at close"
    if order.order_type is SimulationOrderType.STOP_LOSS:
        return "Stop-loss triggers when close <= trigger; fills at close"
    if order.order_type is SimulationOrderType.TAKE_PROFIT:
        return "Take-profit triggers when close >= target; fills at close"
    return "Order fills at observable daily close"


def _not_triggered_reason(order: OrderIntent) -> str:
    if order.order_type is SimulationOrderType.LIMIT:
        if order.side is OrderSide.BUY:
            return "Limit buy does not trigger when close > limit"
        return "Limit sell does not trigger when close < limit"
    if order.order_type is SimulationOrderType.STOP_LOSS:
        return "Stop-loss does not trigger when close > trigger"
    if order.order_type is SimulationOrderType.TAKE_PROFIT:
        return "Take-profit does not trigger when close < target"
    return "Order did not trigger against observable daily close"
