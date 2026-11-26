"""Deterministic order-execution decisions.

Pure functions: no Session, settings, clock, or I/O. Fill economics for
``LEGACY_CLOSE`` match live paper trading: MARKET fills at the latest 1d
close, and pending LIMIT / STOP_LOSS / TAKE_PROFIT trigger on that close.
``NEXT_OPEN`` (Phase 5.3, backtests) fills MARKET orders at the bar's open.
``INTRABAR_OHLC`` (A6.9, replay and backtests) judges resting orders on the
bar's range with the open first, and :func:`evaluate_oco_exit` decides a
bracket's stop and target in one bar. Any may take a ``CostModel`` (spread and
slippage against the trader); live trading passes none, so its fills are
unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

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
    INTRABAR_OHLC,
    INTRABAR_UNKNOWN_LABEL,
    LEGACY_CLOSE,
    NEXT_OPEN,
    is_intrabar_ohlc,
    is_legacy_close,
    is_next_open,
)

MICROS = Decimal("0.000001")
BPS = Decimal(10_000)


def _canonical(profile: ExecutionProfile) -> ExecutionProfile | None:
    """The registered profile equal to ``profile``, or None (not implemented).

    Provenance is the canonical object, not a caller-built lookalike."""
    if is_legacy_close(profile):
        return LEGACY_CLOSE
    if is_next_open(profile):
        return NEXT_OPEN
    if is_intrabar_ohlc(profile):
        return INTRABAR_OHLC
    return None


def _not_implemented(order: OrderIntent, profile: ExecutionProfile) -> FillDecision:
    return _ineligible(
        order,
        profile,
        reason=f"Execution profile {profile.name!r} {profile.model_version!r} is not implemented",
    )


def evaluate_order(
    order: OrderIntent,
    market: MarketSnapshot,
    profile: ExecutionProfile,
    costs: CostModel = NO_COSTS,
) -> FillDecision:
    """Decide whether ``order`` fills against ``market`` under ``profile``."""

    canonical = _canonical(profile)
    if canonical is None:
        return _not_implemented(order, profile)
    profile = canonical

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
            reason=(
                "Market order fills at the observed bar's close"
                if profile is INTRABAR_OHLC
                else "Market order fills at observable daily close"
            ),
            costs=costs,
        )

    assert order.limit_price is not None
    if profile is INTRABAR_OHLC:
        return _intrabar(order, market, profile, costs)
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
    the rule is the same under ``next_open``, ``next_close`` and
    ``intrabar_ohlc`` (whose ``evaluate_order`` stop is this rule).
    """

    canonical = _canonical(profile)
    if canonical is None:
        return _not_implemented(order, profile)
    profile = canonical
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


def _range_touch(order: OrderIntent, market: MarketSnapshot) -> tuple[Decimal, str] | None:
    """(reference price, reason) when ``order``'s level is reached in
    ``market``'s range, the open first; None when it is not reached.

    - a buy limit (and a buy stop's mirror, unused) at or above the open
      fills at the open; else a low at or below the limit fills at the limit;
    - a sell limit and a take-profit: the open at or above fills at the
      open; else a high at or above fills at the level;
    - a sell stop: the open at or below fills at the open; else a low at or
      below fills at the stop.
    """
    assert order.limit_price is not None
    level = order.limit_price
    kind = order.order_type
    if kind is SimulationOrderType.LIMIT and order.side is OrderSide.BUY:
        if market.open <= level:
            return market.open, "Buy limit: the bar opened at or below it, fills at the open"
        if market.low <= level:
            return level, "Buy limit touched by the bar's low: fills at the limit"
        return None
    if kind is SimulationOrderType.STOP_LOSS:
        if market.open <= level:
            return market.open, "Gap through sell stop: fills at the bar's open"
        if market.low <= level:
            return level, "Sell stop touched by the bar's low: fills at the stop"
        return None
    # A sell limit or a take-profit (both sell above the market).
    label = "Target" if kind is SimulationOrderType.TAKE_PROFIT else "Sell limit"
    if market.open >= level:
        return market.open, f"{label}: the bar opened at or above it, fills at the open"
    if market.high >= level:
        return level, f"{label} touched by the bar's high: fills at the level"
    return None


def _intrabar(
    order: OrderIntent,
    market: MarketSnapshot,
    profile: ExecutionProfile,
    costs: CostModel,
) -> FillDecision:
    touch = _range_touch(order, market)
    if touch is None:
        return _not_triggered(
            order, market, profile, reason="Not reached by the bar's range (open, high, low)"
        )
    reference, reason = touch
    return _filled(order, market, profile, reason=reason, reference=reference, costs=costs)


OcoLeg = Literal["stop", "target"]
OcoBasis = Literal["bar", "minutes", "unknown"]


@dataclass(frozen=True, slots=True)
class OcoDecision:
    """A bracket's exit on one bar: which leg filled (None: neither), its
    decision, and what decided the order (``bar``: only one leg was in reach,
    or the open gapped through one; ``minutes``: the stored minutes;
    ``unknown``: both inside the bar with nothing finer, the stop first)."""

    leg: OcoLeg | None
    decision: FillDecision
    basis: OcoBasis

    @property
    def order_unknown(self) -> bool:
        return self.basis == "unknown"


def evaluate_oco_exit(
    stop: OrderIntent,
    target: OrderIntent,
    market: MarketSnapshot,
    profile: ExecutionProfile,
    *,
    path: Sequence[MarketSnapshot] | None = None,
    costs: CostModel = NO_COSTS,
) -> OcoDecision:
    """A long bracket's sell ``stop`` and sell ``target`` (take-profit), one
    cancels the other, judged on ``market`` (A6.9, M9.4).

    ``legacy_close``: each on the close (they cannot both trigger when the
    stop is below the target). ``intrabar_ohlc``: on the range, the open
    first, so an open through either fills that leg at the open. When only
    one level is in the range it fills. When both are inside the bar:

    - ``path`` (the bar's stored minutes, oldest first) decides: the first
      minute that reaches a level fills it, by the same rule; a minute that
      reaches both fills the stop and is labelled;
    - without a path (or one that reaches neither), the stop fills first,
      labelled :data:`INTRABAR_UNKNOWN_LABEL` (the worst case, design note
      question 11).
    """
    canonical = _canonical(profile)
    if canonical is None:
        return OcoDecision(None, _not_implemented(stop, profile), "bar")
    if canonical is NEXT_OPEN:
        return OcoDecision(
            None, _ineligible(stop, canonical, reason="next_open fills market orders only"), "bar"
        )
    profile = canonical
    if stop.order_type is not SimulationOrderType.STOP_LOSS or (
        target.order_type is not SimulationOrderType.TAKE_PROFIT
    ):
        return OcoDecision(
            None,
            _ineligible(stop, profile, reason="A bracket exit is a stop-loss and a take-profit"),
            "bar",
        )
    if profile is LEGACY_CLOSE:
        legs: tuple[tuple[OcoLeg, OrderIntent], ...] = (("stop", stop), ("target", target))
        for leg, order in legs:
            decision = evaluate_order(order, market, profile, costs)
            if decision.status is not FillStatus.NOT_TRIGGERED:
                return OcoDecision(leg if decision.status is FillStatus.FILLED else None,
                                   decision, "bar")  # fmt: skip
        return OcoDecision(None, decision, "bar")

    # intrabar_ohlc: validity first (ticker, clock, sell-only), as evaluate_order.
    for order in (stop, target):
        checked = evaluate_order(order, market, profile, costs)
        if checked.status is FillStatus.INELIGIBLE:
            return OcoDecision(None, checked, "bar")
    leg, touch, both = _oco_touch(stop, target, market)
    if leg is None or touch is None:
        return OcoDecision(
            None,
            _not_triggered(stop, market, profile, reason="Neither the stop nor the target reached"),
            "bar",
        )
    if not both:
        order = stop if leg == "stop" else target
        reference, reason = touch
        return OcoDecision(
            leg,
            _filled(order, market, profile, reason=reason, reference=reference, costs=costs),
            "bar",
        )
    for minute in path or ():
        m_leg, m_touch, m_both = _oco_touch(stop, target, minute)
        if m_leg is None or m_touch is None:
            continue
        order = stop if m_leg == "stop" else target
        reference, reason = m_touch
        if m_both:
            reason = (
                f"{INTRABAR_UNKNOWN_LABEL}: the stop and the target were both inside one "
                f"stored minute, so the stop fills first (worst case). {reason}"
            )
            basis: OcoBasis = "unknown"
        else:
            reason = f"{reason} (the stored minutes decide which came first)"
            basis = "minutes"
        return OcoDecision(
            m_leg,
            _filled(order, market, profile, reason=reason, reference=reference, costs=costs),
            basis,
        )
    assert stop.limit_price is not None
    return OcoDecision(
        "stop",
        _filled(
            stop,
            market,
            profile,
            reason=(
                f"{INTRABAR_UNKNOWN_LABEL}: the stop and the target were both inside the bar "
                "and no stored minutes say which came first, so the stop fills first "
                "(worst case)"
            ),
            reference=stop.limit_price,
            costs=costs,
        ),
        "unknown",
    )


def _oco_touch(
    stop: OrderIntent, target: OrderIntent, market: MarketSnapshot
) -> tuple[OcoLeg | None, tuple[Decimal, str] | None, bool]:
    """(leg, touch, both inside) for one bar or minute. An open through a
    level decides at once (the open comes first)."""
    assert stop.limit_price is not None and target.limit_price is not None
    if market.open <= stop.limit_price:
        return "stop", (market.open, "Gap through sell stop: fills at the bar's open"), False
    if market.open >= target.limit_price:
        return (
            "target",
            (market.open, "Target: the bar opened at or above it, fills at the open"),
            False,
        )
    stop_touch = _range_touch(stop, market)
    target_touch = _range_touch(target, market)
    if stop_touch is not None and target_touch is not None:
        return "stop", stop_touch, True
    if stop_touch is not None:
        return "stop", stop_touch, False
    if target_touch is not None:
        return "target", target_touch, False
    return None, None, False


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
