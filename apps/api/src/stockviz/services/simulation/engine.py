"""Deterministic order-execution decisions.

Pure functions: no Session, settings, clock, or I/O. Fill economics for
``LEGACY_CLOSE`` match live paper trading: MARKET fills at the latest 1d
close, and pending LIMIT / STOP_LOSS / TAKE_PROFIT trigger on that close.
``NEXT_OPEN`` (Phase 5.3, backtests) fills MARKET orders at the bar's open.
Either may take a ``CostModel`` (spread and slippage against the trader);
live trading passes none, so its fills are unchanged.
"""

from __future__ import annotations

from decimal import Decimal

from stockviz.services.simulation.contracts import (
    NO_COSTS,
    CostModel,
    ExecutionProfile,
    ExecutionTrace,
    FillDecision,
    FillStatus,
    MarketSnapshot,
    OrderIntent,
    OrderSide,
    SimulationOrderType,
)
from stockviz.services.simulation.profiles import (
    LEGACY_CLOSE,
    NEXT_OPEN,
    is_legacy_close,
    is_next_open,
)

MICROS = Decimal("0.000001")
BPS = Decimal(10_000)


def evaluate_order(
    order: OrderIntent,
    market: MarketSnapshot,
    profile: ExecutionProfile,
    costs: CostModel = NO_COSTS,
) -> FillDecision:
    """Decide whether ``order`` fills against ``market`` under ``profile``."""

    # Provenance is the canonical object, not a caller-built lookalike.
    if is_legacy_close(profile):
        profile = LEGACY_CLOSE
    elif is_next_open(profile):
        profile = NEXT_OPEN
    else:
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

    if profile is NEXT_OPEN:
        if order.order_type is not SimulationOrderType.MARKET:
            return _ineligible(order, profile, reason="next_open fills market orders only")
        return _filled(
            order,
            market,
            profile,
            reason="Market order fills at the bar's open",
            reference=market.open,
            costs=costs,
        )

    if order.order_type is SimulationOrderType.MARKET:
        return _filled(
            order,
            market,
            profile,
            reason="Market order fills at observable daily close",
            costs=costs,
        )

    assert order.limit_price is not None
    if not _legacy_should_fill(order, market.close):
        return _not_triggered(order, market, profile, reason=_not_triggered_reason(order))
    return _filled(order, market, profile, reason=_filled_reason(order), costs=costs)


def evaluate_range_stop(
    order: OrderIntent,
    market: MarketSnapshot,
    profile: ExecutionProfile,
    costs: CostModel = NO_COSTS,
) -> FillDecision:
    """A protective stop judged on the bar's range (A4.1, the DSL backtester).

    ``evaluate_order``'s ``STOP_LOSS`` is live trading's close-only rule. A
    backtest's stop is resting all day, so it is judged on the daily bar's
    open, high and low:

    - **sell stop** (protects a long): the open at or below the stop fills
      at the open (a gap through the stop); else a low at or below it fills
      at the stop; else not triggered;
    - **buy stop** (protects a short): the open at or above the stop fills at
      the open (gap); else a high at or above it fills at the stop.

    The bar's open always comes first, so a gap is never filled at a price
    the bar did not trade. ``costs`` move the fill against the trader as
    for any fill. ``profile`` is the run's profile, recorded as provenance:
    the rule is the same under ``next_open`` and ``next_close``.
    """

    if is_legacy_close(profile):
        profile = LEGACY_CLOSE
    elif is_next_open(profile):
        profile = NEXT_OPEN
    else:
        return _ineligible(
            order,
            profile,
            reason=f"Execution profile {profile.name!r} {profile.model_version!r} is not implemented",
        )
    if order.order_type is not SimulationOrderType.STOP_LOSS:
        return _ineligible(order, profile, reason="Range stops take stop_loss orders only")
    if _norm_ticker(order.ticker) != _norm_ticker(market.ticker):
        return _ineligible(
            order, profile, reason="Order ticker does not match market snapshot ticker"
        )
    if market.observed_at < order.submitted_at:
        return _ineligible(
            order, profile, reason="Market snapshot observed_at precedes order submitted_at"
        )
    assert order.limit_price is not None
    stop = order.limit_price
    if order.side is OrderSide.SELL:
        if market.open <= stop:
            reference, reason = market.open, "Gap through sell stop: fills at the bar's open"
        elif market.low <= stop:
            reference, reason = stop, "Sell stop touched by the bar's low: fills at the stop"
        else:
            return _not_triggered(
                order, market, profile, reason="Sell stop not reached by the bar's low"
            )
    else:
        if market.open >= stop:
            reference, reason = market.open, "Gap through buy stop: fills at the bar's open"
        elif market.high >= stop:
            reference, reason = stop, "Buy stop touched by the bar's high: fills at the stop"
        else:
            return _not_triggered(
                order, market, profile, reason="Buy stop not reached by the bar's high"
            )
    return _filled(order, market, profile, reason=reason, reference=reference, costs=costs)


def cost_adjusted(price: Decimal, side: OrderSide, costs: CostModel) -> Decimal:
    """``price`` moved against the trader by half the spread plus slippage."""
    if costs.is_free:
        return price
    move = (costs.spread_bps / 2 + costs.slippage_bps) / BPS
    factor = Decimal(1) + move if side is OrderSide.BUY else Decimal(1) - move
    return (price * factor).quantize(MICROS)


def _legacy_should_fill(order: OrderIntent, close: Decimal) -> bool:
    """Close-only LIMIT / STOP_LOSS / TAKE_PROFIT trigger rules."""

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
    reference: Decimal | None = None,
    costs: CostModel = NO_COSTS,
) -> FillDecision:
    remaining = _remaining(order)
    reference_price = market.close if reference is None else reference
    price = cost_adjusted(reference_price, order.side, costs)
    if not costs.is_free:
        reason = (
            f"{reason}; spread {costs.spread_bps} bps, slippage {costs.slippage_bps} bps "
            "against the trader"
        )
    return FillDecision(
        status=FillStatus.FILLED,
        fill_quantity=remaining,
        fill_price=price,
        remaining_quantity=Decimal(0),
        trace=_trace(profile, reference_price=reference_price, fill_price=price, reason=reason),
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
