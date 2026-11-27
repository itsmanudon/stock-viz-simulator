"""Reverse DCF (A7.4, M5.3): the growth today's enterprise value implies.

A two-stage free-cash-flow model. With base free cash flow ``F`` (the
trailing twelve months, or revenue x an overridden FCF margin), discount
rate ``w`` (WACC), terminal growth ``gt`` and an explicit horizon of ``N``
years at growth ``g``:

    EV(g) = sum_{i=1..N} F (1+g)^i / (1+w)^i  +  TV / (1+w)^N,
    TV    = F (1+g)^N (1+gt) / (w - gt)            (Gordon growth)

``implied_growth`` solves EV(g) = today's EV by bisection over
[``G_LOW``, ``G_HIGH``] (EV is increasing in g when w > gt). Nothing solves
when the base cash flow is not positive, when w <= gt, or when today's EV is
outside the range: each case gives a reason, never a number.

The reconciliation runs back from EV to the share price: equity = EV - debt +
cash, price = equity / shares, the same figures the valuation route uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field

G_LOW, G_HIGH = -0.5, 1.0
TOLERANCE = 1e-9
MAX_STEPS = 200


def present_value(fcf: float, growth: float, wacc: float, terminal: float, years: int) -> float:
    pv = 0.0
    cash = fcf
    for i in range(1, years + 1):
        cash *= 1 + growth
        pv += cash / (1 + wacc) ** i
    tv = cash * (1 + terminal) / (wacc - terminal)
    return pv + tv / (1 + wacc) ** years


def implied_growth(
    ev: float, fcf: float, wacc: float, terminal: float, years: int
) -> tuple[float | None, str | None]:
    """(g, None) or (None, reason)."""
    if fcf <= 0:
        return None, "Free cash flow is not positive, so no growth rate explains the price."
    if wacc <= terminal:
        return None, "WACC must be above terminal growth."
    if ev <= 0:
        return None, "Enterprise value is not positive."
    low, high = G_LOW, G_HIGH
    if present_value(fcf, low, wacc, terminal, years) > ev:
        return None, f"Even {G_LOW:.0%} a year for {years} years is worth more than today's EV."
    if present_value(fcf, high, wacc, terminal, years) < ev:
        return None, f"Today's EV needs more than {G_HIGH:.0%} a year for {years} years."
    for _ in range(MAX_STEPS):
        mid = (low + high) / 2
        if present_value(fcf, mid, wacc, terminal, years) < ev:
            low = mid
        else:
            high = mid
        if high - low < TOLERANCE:
            break
    return (low + high) / 2, None


@dataclass
class ReverseDcf:
    implied_growth: float | None
    reason: str | None
    base_fcf: float | None
    base_fcf_source: str
    wacc: float
    terminal_growth: float
    years: int
    enterprise_value: float | None
    grid: list[dict[str, float | None]] = field(default_factory=list)
    reconciliation: list[tuple[str, float | None]] = field(default_factory=list)


def sensitivity(
    ev: float, fcf: float, wacc: float, terminal: float, years: int
) -> list[dict[str, float | None]]:
    """Implied growth across WACC +-1 point and terminal growth +-0.5 point."""
    rows: list[dict[str, float | None]] = []
    for dw in (-0.01, 0.0, 0.01):
        for dt in (-0.005, 0.0, 0.005):
            g, _reason = implied_growth(ev, fcf, wacc + dw, terminal + dt, years)
            rows.append({"wacc": round(wacc + dw, 4), "terminal_growth": round(terminal + dt, 4),
                         "implied_growth": None if g is None else round(g, 6)})  # fmt: skip
    return rows


def reverse_dcf(
    *,
    enterprise_value: float | None,
    fcf_ttm: float | None,
    revenue_ttm: float | None,
    fcf_margin: float | None,
    wacc: float,
    terminal_growth: float,
    years: int,
    debt: float | None,
    cash: float | None,
    shares: float | None,
) -> ReverseDcf:
    if fcf_margin is not None and revenue_ttm is not None:
        base, source = revenue_ttm * fcf_margin, f"revenue x {fcf_margin:.1%} margin (override)"
    else:
        base, source = fcf_ttm, "trailing free cash flow"
    out = ReverseDcf(None, None, base, source, wacc, terminal_growth, years, enterprise_value)
    if enterprise_value is None:
        out.reason = "No enterprise value: a close, shares outstanding or an FX rate is missing."
        return out
    if base is None:
        out.reason = "No free cash flow stored (and no margin override)."
        return out
    out.implied_growth, out.reason = implied_growth(enterprise_value, base, wacc,
                                                    terminal_growth, years)  # fmt: skip
    if out.implied_growth is not None:
        out.grid = sensitivity(enterprise_value, base, wacc, terminal_growth, years)
    equity = enterprise_value - (debt or 0.0) + (cash or 0.0)
    out.reconciliation = [
        ("enterprise_value", enterprise_value),
        ("less_debt", -(debt or 0.0)),
        ("plus_cash", cash or 0.0),
        ("equity_value", equity),
        ("shares", shares),
        ("price", equity / shares if shares else None),
    ]
    return out
