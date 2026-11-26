"""Drawing bindings for the Rule DSL (A3.3, M2.5): pure.

``drawing("label").price`` / ``.top`` / ``.bottom`` and ``avwap("label")``
read the rule owner's chart drawings on the symbol (A3.2's ``drawings``
table). They are **user-scoped**: :class:`Drawings` is loaded only for an
owner (``load_symbol(..., user_id=)``); without one every value is unknown.

Values on a daily bar dated ``d``:

- **hline**: its price on every bar.
- **trendline**: linear between its two anchors, by weekdays (Monday to
  Friday, ``numpy.busday_count``); defined only from the earlier anchor's
  date to the later one's, inclusive. Before or after: unknown. It is not
  extended (draw a ray for that).
- **ray**: linear through its two anchors and extended past the second.
  It starts at its first point and runs towards the second: rightwards
  (the usual case) it is defined on every bar from the first point's date
  on; drawn leftwards, on every bar up to it.
- **rectangle**: ``.top`` / ``.bottom`` are its higher and lower price, on
  every bar from its left edge on (a zone keeps its level after it is
  drawn); unknown before it.
- **avwap**: ``services/avwap.py`` from its anchor date over the daily bars
  up to each bar; unknown before the anchor.

The daily chart draws a line straight through its bars, so it is linear in
*sessions*; here it is linear in *weekdays*, which differ only by the
exchange holidays between the anchors (a few sessions of slope at most).
Weekdays are known in advance, so a value never depends on which bars exist
later: an anchor after ``t`` only decides whether a line exists at ``t``
(``point(t) == vector[t]`` and no look-ahead, as the conformance suite
checks). A drawing a user drew later is still applied to earlier bars: it is
their geometry, not data.

Labels match ignoring case and repeated spaces (``canonical.ref_label``).
No match is unknown ("drawing 'x' not found"), so deleting or renaming a
drawing turns a rule unknown and never crashes it (an alert on it stays
quiet); two drawings of one kind with the same label are unknown too.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from stockviz.services import avwap as avwap_math
from stockviz.services.dsl import ast
from stockviz.services.dsl.canonical import ref_label

NAN = float("nan")
LINE_KINDS = ("hline", "trendline", "ray")
ZONE_KINDS = ("rectangle",)


@dataclass(frozen=True)
class DrawingRef:
    id: int
    kind: str
    label: str | None
    points: tuple[tuple[date | None, float | None], ...]


@dataclass(frozen=True)
class Drawings:
    """The owner's drawings on one symbol (any kind; matched by label)."""

    owner_id: int
    items: tuple[DrawingRef, ...] = ()

    def matching(self, ref: ast.Ref) -> list[DrawingRef]:
        want = ref_label(ref.label)
        return [
            d
            for d in self.items
            if d.label is not None
            and ref_label(d.label) == want
            and ((d.kind == "avwap") == (ref.kind == "avwap"))
        ]


@dataclass(frozen=True)
class RefResult:
    values: np.ndarray
    problem: str | None = None
    """Why every bar is unknown (not found, wrong kind, no owner), else None."""
    starts: date | None = None
    ends: date | None = None
    """Where the value is defined, when it is bounded (for the reasons)."""


def _weekdays(days: np.ndarray) -> np.ndarray:
    return np.busday_count(np.datetime64("1970-01-05", "D"), days).astype(float)


def _wd(day: date) -> float:
    return float(np.busday_count(np.datetime64("1970-01-05", "D"), np.datetime64(day, "D")))


def _line(days: np.ndarray, p1: tuple[date, float], p2: tuple[date, float], *, ray: bool):
    (d1, y1), (d2, y2) = p1, p2
    x1, x2 = _wd(d1), _wd(d2)
    if x1 == x2:
        return None
    x = _weekdays(days)
    values = y1 + (y2 - y1) * (x - x1) / (x2 - x1)
    d = days.astype("datetime64[D]")
    a, b = np.datetime64(d1, "D"), np.datetime64(d2, "D")
    if ray:
        mask = d >= a if d2 > d1 else d <= a
        bounds = (d1, None) if d2 > d1 else (None, d1)
    else:
        lo, hi = (a, b) if a <= b else (b, a)
        mask = (d >= lo) & (d <= hi)
        bounds = (min(d1, d2), max(d1, d2))
    return np.where(mask, values, NAN), bounds


def _kind_hint(kind: str) -> str:
    return {
        "trendline": "trend line",
        "fib_retracement": "Fibonacci retracement",
        "fib_extension": "Fibonacci extension",
        "position_long": "long position",
        "position_short": "short position",
    }.get(kind, kind)


def resolve(
    ref: ast.Ref,
    drawings: Drawings | None,
    days: np.ndarray,
    bars,
) -> RefResult:
    """Values of ``ref`` on each daily bar (``days`` datetime64[D], ``bars``
    the daily frame), NaN where unknown."""
    n = len(days)
    unknown = np.full(n, NAN)
    word = "anchored VWAP" if ref.kind == "avwap" else "drawing"
    if drawings is None:
        return RefResult(
            unknown,
            f'{ref.kind}("{ref.label}"): rules that read drawings run only for their owner',
        )
    found = drawings.matching(ref)
    if not found:
        return RefResult(unknown, f"{word} '{ref.label}' not found")
    if len(found) > 1:
        return RefResult(
            unknown, f"{len(found)} of your {word}s are labelled '{ref.label}'; rename one"
        )
    d = found[0]
    if ref.kind == "avwap":
        anchor = d.points[0][0] if d.points else None
        if anchor is None:  # pragma: no cover - the API refuses it
            return RefResult(unknown, f"anchored VWAP '{ref.label}' has no anchor date")
        series = avwap_math.compute(
            days,
            bars["high"].to_numpy(dtype=float),
            bars["low"].to_numpy(dtype=float),
            bars["close"].to_numpy(dtype=float),
            bars["volume"].to_numpy(dtype=float),
            anchor,
        )
        k = {"upper1": 1, "lower1": -1, "upper2": 2, "lower2": -2}.get(ref.output or "vwap", 0)
        return RefResult(series.band(k) if k else series.vwap, starts=anchor)

    output = ref.output or "price"
    if d.kind in ZONE_KINDS:
        if output == "price":
            return RefResult(unknown, f"drawing '{ref.label}' is a rectangle: read .top or .bottom")
        prices = [p for _ts, p in d.points if p is not None]
        dates = [ts for ts, _p in d.points if ts is not None]
        level = max(prices) if output == "top" else min(prices)
        start = min(dates)
        mask = days.astype("datetime64[D]") >= np.datetime64(start, "D")
        return RefResult(np.where(mask, level, NAN), starts=start)
    if d.kind not in LINE_KINDS:
        return RefResult(
            unknown,
            f"drawing '{ref.label}' is a {_kind_hint(d.kind)}; drawing() reads a horizontal "
            "line, trend line or ray (.price) and a rectangle (.top, .bottom)",
        )
    if output != "price":
        return RefResult(unknown, f"drawing '{ref.label}' is a {_kind_hint(d.kind)}: read .price")
    if d.kind == "hline":
        price = d.points[0][1]
        return RefResult(np.full(n, NAN if price is None else float(price)))
    (t1, y1), (t2, y2) = d.points[0], d.points[1]
    if t1 is None or t2 is None or y1 is None or y2 is None:  # pragma: no cover - API refuses
        return RefResult(unknown, f"drawing '{ref.label}' is missing an anchor")
    line = _line(days, (t1, y1), (t2, y2), ray=d.kind == "ray")
    if line is None:
        return RefResult(unknown, f"drawing '{ref.label}' has both anchors on the same day")
    values, (starts, ends) = line
    return RefResult(values, starts=starts, ends=ends)


def reason(ref: ast.Ref, result: RefResult, day: date) -> str:
    """Why ``ref`` is unknown on the bar dated ``day``."""
    text = f'{ref.kind}("{ref.label}")' + (f".{ref.output}" if ref.output else "")
    if result.problem:
        return result.problem
    if result.starts is not None and day < result.starts:
        what = "its anchor" if ref.kind == "avwap" else "its first anchor"
        return f"{text}: {day.isoformat()} is before {what} on {result.starts.isoformat()}"
    if result.ends is not None and day > result.ends:
        return f"{text}: {day.isoformat()} is after the line ends on {result.ends.isoformat()}"
    if ref.kind == "avwap":
        return f"{text}: no volume since its anchor"
    return f"{text}: no value"


__all__ = ["DrawingRef", "Drawings", "RefResult", "reason", "resolve"]
