"""Honest structure annotations (A9.5, M2.12): pivots and zones by stated rules.

Nothing here is called a "pattern" without the rule that drew it, and
nothing repaints:

- **Swing high** at bar ``i``: its high is above the highs of the ``n`` bars
  before it and at or above those of the ``n`` bars after it (a fractal pivot).
  **Swing low** mirrored. A pivot exists only once its ``n`` right-hand bars
  do, so the newest ``n`` bars never carry one (``confirmed_at`` is the bar
  that confirmed it).
- **Labels:** each swing high is a higher high (HH) or lower high (LH) against
  the previous swing high; each swing low a higher low (HL) or lower low (LL)
  against the previous swing low. The first of each kind has no label.
- **Zones:** pivot prices within ``ATR(14) / 2`` (at the latest bar) of each
  other are clustered (single linkage on sorted prices); a zone with at least
  two touches is shown with its price range, touches and the dates of its
  first and last touch. A zone above the last close is resistance, below it
  support, around it "at price".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

MIN_TOUCHES = 2
ATR_PERIOD = 14


@dataclass(frozen=True)
class Bar:
    day: date
    high: float
    low: float
    close: float


@dataclass
class Structure:
    n: int
    pivots: list[dict[str, object]] = field(default_factory=list)
    zones: list[dict[str, object]] = field(default_factory=list)
    atr: float | None = None
    rules: dict[str, str] = field(default_factory=dict)


def atr(bars: list[Bar], period: int = ATR_PERIOD) -> float | None:
    """Simple average true range over the last ``period`` bars."""
    if len(bars) < period + 1:
        return None
    trs = []
    for prev, cur in zip(bars[-period - 1 : -1], bars[-period:], strict=True):
        trs.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return sum(trs) / period


def pivots(bars: list[Bar], n: int) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    last_high: float | None = None
    last_low: float | None = None
    for i in range(n, len(bars) - n):
        left, right = bars[i - n : i], bars[i + 1 : i + n + 1]
        b = bars[i]
        if b.high > max(x.high for x in left) and b.high >= max(x.high for x in right):
            label = None if last_high is None else ("HH" if b.high > last_high else "LH")
            out.append({"day": b.day, "kind": "high", "price": b.high, "label": label,
                        "confirmed_at": bars[i + n].day})  # fmt: skip
            last_high = b.high
        if b.low < min(x.low for x in left) and b.low <= min(x.low for x in right):
            label = None if last_low is None else ("HL" if b.low > last_low else "LL")
            out.append({"day": b.day, "kind": "low", "price": b.low, "label": label,
                        "confirmed_at": bars[i + n].day})  # fmt: skip
            last_low = b.low
    return out


def zones(
    points: list[dict[str, object]], width: float, last_close: float
) -> list[dict[str, object]]:
    if width <= 0 or not points:
        return []
    ordered = sorted(points, key=lambda p: float(p["price"]))  # type: ignore[arg-type]
    clusters: list[list[dict[str, object]]] = [[ordered[0]]]
    for p in ordered[1:]:
        if float(p["price"]) - float(clusters[-1][-1]["price"]) <= width:  # type: ignore[arg-type]
            clusters[-1].append(p)
        else:
            clusters.append([p])
    out: list[dict[str, object]] = []
    for c in clusters:
        if len(c) < MIN_TOUCHES:
            continue
        prices = [float(p["price"]) for p in c]  # type: ignore[arg-type]
        days = sorted(p["day"] for p in c)  # type: ignore[type-var]
        lo, hi = min(prices), max(prices)
        side = "resistance" if lo > last_close else "support" if hi < last_close else "at price"
        out.append({"low": round(lo, 4), "high": round(hi, 4), "touches": len(c), "side": side,
                    "first": days[0], "last": days[-1]})  # fmt: skip
    return out


def structure(bars: list[Bar], n: int = 5) -> Structure:
    """Pivots, labels and zones on the given bars (pure)."""
    out = Structure(n=n)
    out.rules = {
        "pivot": f"A swing high's high tops the {n} bars before it and is at least the {n} "
        f"after it (lows mirrored); drawn once the {n} later bars exist",
        "labels": "HH/LH: against the previous swing high; HL/LL: against the previous low",
        "zones": f"Pivots within ATR({ATR_PERIOD}) / 2 of each other, {MIN_TOUCHES}+ touches",
    }
    out.pivots = pivots(bars, n)
    out.atr = atr(bars)
    if out.atr is not None and bars:
        out.zones = zones(out.pivots, out.atr / 2, bars[-1].close)
    return out
