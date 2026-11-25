"""The backtest fill path (A4.1): one order, one bar, through the kernel.

Every fill the DSL backtester makes goes through :func:`book`: the kernel
decides price and quantity (``evaluate_order`` for market, limit and the
close-only stop; ``evaluate_range_stop`` for a resting stop judged on the
bar's range), the fee schedule prices the fill, and ``SimLedger`` books it.
Nothing here re-implements a fill. The three-way kernel equality test
(``tests/test_kernel_three_way.py``) drives this same function beside live
``apply_fill`` and replay's ``submit_replay_order``.

Pure: no Session, clock or I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from stockviz.services.simulation import (
    NO_COSTS,
    CostModel,
    ExecutionProfile,
    FeeBreakdown,
    FeeSchedule,
    FillDecision,
    FillStatus,
    MarketSnapshot,
    OrderIntent,
    OrderSide,
    SimFill,
    SimLedger,
    evaluate_order,
    evaluate_range_stop,
)


@dataclass(frozen=True)
class BookedFill:
    decision: FillDecision
    fees: FeeBreakdown
    fill: SimFill
    cash_change: Decimal
    """Ledger cash after minus before: the fill's whole cash effect, fees included."""

    @property
    def price(self) -> Decimal:
        assert self.decision.fill_price is not None
        return self.decision.fill_price

    @property
    def reference(self) -> Decimal:
        ref = self.decision.trace.reference_price
        return ref if ref is not None else self.price


def decide(
    order: OrderIntent,
    market: MarketSnapshot,
    profile: ExecutionProfile,
    costs: CostModel = NO_COSTS,
    *,
    range_stop: bool = False,
) -> FillDecision:
    """The kernel's decision for ``order`` on ``market``."""
    if range_stop:
        return evaluate_range_stop(order, market, profile, costs)
    return evaluate_order(order, market, profile, costs)


def book(
    ledger: SimLedger,
    order: OrderIntent,
    market: MarketSnapshot,
    profile: ExecutionProfile,
    *,
    costs: CostModel = NO_COSTS,
    schedule: FeeSchedule,
    commission_bps: Decimal = Decimal(0),
    range_stop: bool = False,
    short: bool = False,
) -> BookedFill | None:
    """Decide ``order`` on ``market`` and book it in ``ledger``; None when the
    kernel does not fill it. ``short`` books a short sale (``SELL``) or a cover
    (``BUY``) instead of a long trade. Ledger refusals propagate unchanged."""
    decision = decide(order, market, profile, costs, range_stop=range_stop)
    if decision.status is not FillStatus.FILLED or decision.fill_price is None:
        return None
    quantity = decision.fill_quantity
    fees = schedule.fees(order.side, quantity, decision.fill_price, commission_bps=commission_bps)
    before = ledger.cash
    if short:
        fill = ledger.apply_short(
            order.side, order.ticker, quantity, decision.fill_price, fees=fees.total
        )
    else:
        fill = ledger.apply(
            order.side, order.ticker, quantity, decision.fill_price, fees=fees.total
        )
    return BookedFill(decision, fees, fill, ledger.cash - before)


__all__ = ["BookedFill", "OrderSide", "book", "decide"]
