"""Chart drawings (A3.2, M2.4): validation per kind, the position tool's
figures and the read shape. The router writes.

Rules:

- Points per kind (``POINT_COUNTS``); every price > 0 (the schema).
- An anchor's ``ts`` is a daily bar's venue date between the instrument's
  first and last stored daily bar. Nothing is anchored in the future: a ray
  extends to the right on its own, and a position's stop and target are
  prices only (their ``ts`` must be null). An hline is a price; its ``ts``
  may be null.
- A Fibonacci retracement's two prices differ, an extension's first two do.
- A text note needs a label.
- Position tools: long has stop < entry < target, short target < entry < stop.
- At most ``MAX_DRAWINGS_PER_INSTRUMENT`` per user and instrument.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlmodel import Session, col, func, select

from stockviz.models import PriceBar
from stockviz.models.drawing import MAX_DRAWINGS_PER_INSTRUMENT, Drawing
from stockviz.schemas import (
    DrawingOut,
    DrawingPoint,
    DrawingStyle,
    PositionMetricsOut,
)
from stockviz.services.bars.resample import bar_date
from stockviz.services.markets.calendar import venue_for_ticker

POINT_COUNTS: dict[str, int] = {
    "trendline": 2,
    "ray": 2,
    "hline": 1,
    "rectangle": 2,
    "channel": 3,
    "fib_retracement": 2,
    "fib_extension": 3,
    "ruler": 2,
    "text": 1,
    "position_long": 3,
    "position_short": 3,
}
POSITION_KINDS = ("position_long", "position_short")
FIB_RETRACEMENT_LEVELS = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)
FIB_EXTENSION_LEVELS = (0.0, 0.618, 1.0, 1.272, 1.618, 2.618)

_CENT = Decimal("0.000001")
_RATIO = Decimal("0.01")


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def bar_range(session: Session, instrument_id: int, ticker: str) -> tuple[date | None, date | None]:
    """The venue dates of the instrument's first and last stored daily bar."""
    first, last = session.exec(
        select(func.min(PriceBar.ts), func.max(PriceBar.ts)).where(
            col(PriceBar.instrument_id) == instrument_id, col(PriceBar.interval) == "1d"
        )
    ).one()
    if first is None or last is None:
        return None, None
    venue = venue_for_ticker(ticker)
    return bar_date(first, venue), bar_date(last, venue)


def validate_points(
    kind: str,
    points: list[DrawingPoint],
    label: str | None,
    first_bar: date | None,
    last_bar: date | None,
) -> None:
    """Raise 422 when ``points`` do not fit ``kind`` (see the module rules)."""
    expected = POINT_COUNTS[kind]
    if len(points) != expected:
        raise _unprocessable(f"A {kind} takes {expected} point{'s' if expected > 1 else ''}")
    for index, point in enumerate(points):
        price_only = kind == "hline" or (kind in POSITION_KINDS and index > 0)
        if point.ts is None:
            if not price_only:
                raise _unprocessable(f"Point {index + 1} needs a date")
            continue
        if kind in POSITION_KINDS and index > 0:
            raise _unprocessable("A position's stop and target are prices only")
        if first_bar is None or last_bar is None:
            raise _unprocessable("No stored bars to anchor a drawing to")
        if point.ts < first_bar or point.ts > last_bar:
            raise _unprocessable(
                f"Point {index + 1} is dated {point.ts.isoformat()}; anchors must be between "
                f"{first_bar.isoformat()} and {last_bar.isoformat()} (the stored bars)"
            )
    if kind in ("fib_retracement", "fib_extension") and points[0].price == points[1].price:
        raise _unprocessable("The first two prices must differ")
    if kind == "text" and not (label or "").strip():
        raise _unprocessable("A text note needs a label")
    if kind in POSITION_KINDS:
        entry, stop, target = (p.price for p in points)
        if kind == "position_long" and not (stop < entry < target):
            raise _unprocessable("A long position needs stop < entry < target")
        if kind == "position_short" and not (target < entry < stop):
            raise _unprocessable("A short position needs target < entry < stop")


def position_metrics(kind: str, points: list[DrawingPoint]) -> PositionMetricsOut | None:
    """Risk, reward and R:R for a position tool; None for other kinds."""
    if kind not in POSITION_KINDS or len(points) != 3:
        return None
    entry, stop, target = (p.price for p in points)
    risk = abs(entry - stop)
    reward = abs(target - entry)
    if risk == 0 or entry == 0:
        return None
    return PositionMetricsOut(
        side="long" if kind == "position_long" else "short",
        entry=entry,
        stop=stop,
        target=target,
        risk_per_share=risk.quantize(_CENT, ROUND_HALF_UP),
        reward_per_share=reward.quantize(_CENT, ROUND_HALF_UP),
        reward_risk=(reward / risk).quantize(_RATIO, ROUND_HALF_UP),
        stop_pct=((stop - entry) / entry * 100).quantize(_RATIO, ROUND_HALF_UP),
        target_pct=((target - entry) / entry * 100).quantize(_RATIO, ROUND_HALF_UP),
    )


def points_json(points: list[DrawingPoint]) -> list[dict[str, Any]]:
    return [
        {"ts": p.ts.isoformat() if p.ts else None, "price": format(p.price.normalize(), "f")}
        for p in points
    ]


def points_of(row: Drawing) -> list[DrawingPoint]:
    return [DrawingPoint.model_validate(p) for p in row.points]


def drawing_out(row: Drawing, ticker: str) -> DrawingOut:
    assert row.id is not None
    points = points_of(row)
    return DrawingOut(
        id=row.id,
        ticker=ticker,
        kind=row.kind,  # pyright: ignore[reportArgumentType]
        points=points,
        style=DrawingStyle.model_validate(row.style),
        label=row.label,
        locked=row.locked,
        position=position_metrics(row.kind, points),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def count_for(session: Session, user_id: int, instrument_id: int) -> int:
    return session.exec(
        select(func.count())
        .select_from(Drawing)
        .where(col(Drawing.user_id) == user_id, col(Drawing.instrument_id) == instrument_id)
    ).one()


__all__ = [
    "FIB_EXTENSION_LEVELS",
    "FIB_RETRACEMENT_LEVELS",
    "MAX_DRAWINGS_PER_INSTRUMENT",
    "POINT_COUNTS",
    "POSITION_KINDS",
    "bar_range",
    "count_for",
    "drawing_out",
    "points_json",
    "points_of",
    "position_metrics",
    "validate_points",
]
