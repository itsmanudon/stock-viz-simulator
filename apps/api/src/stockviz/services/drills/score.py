"""A drill's score: process, not profit (A4.7, M9.3).

The trader writes a plan before the first order (planned entry, stop and
size, long). After the drill the trades are checked against it:

- **Entry:** the first buy filled within ``ENTRY_TOLERANCE`` (2%) of the
  planned entry price.
- **Stop:** replay fills at the bar's close, so a stop is honoured when no
  bar closed at or below the planned stop with shares still held after that
  bar's fills (a resting stop-loss at the plan's price, or a market sell on
  that bar, both exit at that close). A stop never reached while holding is
  not applicable: it was not tested.
- **Size:** the most shares held at any time is at most the planned size.

Score = checks passed of the checks that apply. No trade: nothing applies
and ``followed_plan`` is null. R achieved (total P&L, net of fees and marked
at the last bar, over the planned risk: (average buy price - stop) x peak
shares) is shown beside it and is explicitly not the score. Nothing ranks
one trader against another.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from stockviz.schemas import DrillCheckOut, DrillScoreOut

ENTRY_TOLERANCE = Decimal("0.02")
ZERO = Decimal(0)

RULES = {
    "entry": "Passed when the first buy filled within 2% of the planned entry price.",
    "stop": (
        "Passed when no bar closed at or below the planned stop while shares were still held "
        "after that bar's fills (fills are at the close, so a stop-loss at the plan's price or "
        "a sell on that bar exits in time). Not applicable when the stop was never reached "
        "while holding."
    ),
    "size": "Passed when the most shares held never exceeded the planned size.",
    "score": "Checks passed of the checks that apply. With no trade, nothing applies.",
    "r": (
        "R achieved = total P&L (net of fees, open shares marked at the last bar) / planned "
        "risk ((average buy price - planned stop) x most shares held). It is not the score."
    ),
}
R_NOTE = "R achieved is shown for reference. It is not the score: the score is the process."


@dataclass(frozen=True)
class PlanFacts:
    entry: Decimal
    stop: Decimal
    size: Decimal


@dataclass(frozen=True)
class FillFacts:
    side: str
    quantity: Decimal
    price: Decimal
    at: datetime


@dataclass(frozen=True)
class BarFacts:
    at: datetime
    close: Decimal


def _fmt(value: Decimal) -> str:
    return f"{value.normalize():f}"


def score_drill(
    plan: PlanFacts,
    fills: Sequence[FillFacts],
    bars: Sequence[BarFacts],
    *,
    total_pnl: Decimal,
) -> DrillScoreOut:
    """Pure. ``bars`` are the session's visible bars, oldest first."""
    ordered = sorted(fills, key=lambda f: f.at)
    buys = [f for f in ordered if f.side == "buy"]
    if not buys:
        keys: tuple[tuple[Literal["entry", "stop", "size"], str], ...] = (
            ("entry", "Entry"),
            ("stop", "Stop"),
            ("size", "Size"),
        )
        checks = [
            DrillCheckOut(key=k, label=lbl, status="not_applicable", detail="No trade was taken.")
            for k, lbl in keys
        ]
        return DrillScoreOut(
            checks=checks, passed=0, applicable=0, followed_plan=None, traded=False,
            r_achieved=None, r_note=R_NOTE, total_pnl=total_pnl, rules=RULES,
        )  # fmt: skip

    first = buys[0]
    off = abs(first.price - plan.entry) / plan.entry
    entry = DrillCheckOut(
        key="entry",
        label="Entry",
        status="passed" if off <= ENTRY_TOLERANCE else "failed",
        detail=(
            f"First buy at {_fmt(first.price)}, {float(off) * 100:.2f}% from the planned "
            f"{_fmt(plan.entry)} (2% allowed)."
        ),
    )

    held = ZERO
    peak = ZERO
    bought_qty = ZERO
    bought_cost = ZERO
    held_after: dict[datetime, Decimal] = {}
    for f in ordered:
        if f.side == "buy":
            held += f.quantity
            bought_qty += f.quantity
            bought_cost += f.quantity * f.price
        else:
            held -= f.quantity
        peak = max(peak, held)
        held_after[f.at] = held
    size = DrillCheckOut(
        key="size",
        label="Size",
        status="passed" if peak <= plan.size else "failed",
        detail=f"Most shares held {_fmt(peak)}; planned {_fmt(plan.size)}.",
    )

    running = ZERO
    breach: BarFacts | None = None
    tested = False
    fill_iter = iter(ordered)
    pending = next(fill_iter, None)
    for bar in bars:
        while pending is not None and pending.at <= bar.at:
            running += pending.quantity if pending.side == "buy" else -pending.quantity
            pending = next(fill_iter, None)
        if bar.at < first.at:
            continue
        if bar.close <= plan.stop:
            if running > 0:
                breach = bar
                break
            # Exited on this bar (or flat): a reached stop only counts while held
            # before the bar's fills.
            if held_after.get(bar.at) is not None:
                tested = True
    if breach is not None:
        stop = DrillCheckOut(
            key="stop",
            label="Stop",
            status="failed",
            detail=(
                f"A bar closed at {_fmt(breach.close)}, at or below the planned stop "
                f"{_fmt(plan.stop)}, with {_fmt(running)} shares still held."
            ),
        )
    elif tested:
        stop = DrillCheckOut(
            key="stop",
            label="Stop",
            status="passed",
            detail=f"The close reached the planned stop {_fmt(plan.stop)} and you were out by it.",
        )
    else:
        stop = DrillCheckOut(
            key="stop",
            label="Stop",
            status="not_applicable",
            detail=f"No bar closed at or below the planned stop {_fmt(plan.stop)} while you held.",
        )

    checks = [entry, stop, size]
    applicable = [c for c in checks if c.status != "not_applicable"]
    passed = sum(1 for c in applicable if c.status == "passed")
    avg_buy = bought_cost / bought_qty if bought_qty > 0 else first.price
    risk = (avg_buy - plan.stop) * peak
    r = float(total_pnl / risk) if risk > 0 else None
    return DrillScoreOut(
        checks=checks,
        passed=passed,
        applicable=len(applicable),
        followed_plan=passed == len(applicable),
        traded=True,
        r_achieved=round(r, 4) if r is not None else None,
        r_note=R_NOTE,
        total_pnl=total_pnl,
        rules=RULES,
    )


__all__ = ["ENTRY_TOLERANCE", "RULES", "BarFacts", "FillFacts", "PlanFacts", "score_drill"]
