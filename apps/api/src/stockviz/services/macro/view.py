"""Reads for the macro page (A9.7): the overview, one series, the spreads.

Nothing is computed at fetch time. Changes compare the newest value with the
last value on or before the same date a year (or a month) earlier. A series
is ``stale`` when its newest date is further behind today than its frequency
allows (``STALE_AFTER``), so a monthly series a few weeks old is not stale.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlmodel import Session, col, select

from stockviz.models import MacroObservation, MacroSeries
from stockviz.services.macro.catalogue import (
    CATALOGUE,
    SPREAD_STALE_DAYS,
    SPREADS,
    CatalogueSeries,
    Spread,
)

STALE_AFTER: dict[str, int] = {
    "daily": 10,
    "weekly": 21,
    "biweekly": 35,
    "monthly": 75,
    "quarterly": 160,
    "semiannual": 250,
    "annual": 800,
}
SPARK_POINTS = 120
SPARK_YEARS = 3


@dataclass(frozen=True)
class Point:
    day: date
    value: float


def _frequency_key(freq: str) -> str:
    head = freq.lower().split(",")[0].strip()
    return head.replace("-", "").replace(" ", "")


def stale_after_days(freq: str) -> int:
    return STALE_AFTER.get(_frequency_key(freq), 75)


def _points(session: Session, series_id: str, since: date | None = None) -> list[Point]:
    query = select(col(MacroObservation.obs_date), col(MacroObservation.value)).where(
        MacroObservation.series_id == series_id, col(MacroObservation.value).is_not(None)
    )
    if since is not None:
        query = query.where(MacroObservation.obs_date >= since)
    rows = session.exec(query.order_by(col(MacroObservation.obs_date))).all()
    return [Point(d, float(v)) for d, v in rows if v is not None]


def value_on_or_before(points: list[Point], day: date) -> Point | None:
    days = [p.day for p in points]
    i = bisect.bisect_right(days, day) - 1
    return points[i] if i >= 0 else None


def thin(points: list[Point], n: int = SPARK_POINTS) -> list[Point]:
    """At most ``n`` points, evenly spaced, always keeping the last."""
    if len(points) <= n:
        return points
    step = len(points) / n
    picked = [points[int(i * step)] for i in range(n - 1)]
    return [*picked, points[-1]]


@dataclass(frozen=True)
class SeriesSummary:
    entry: CatalogueSeries
    meta: MacroSeries | None
    latest: Point | None
    year_ago: Point | None
    month_ago: Point | None
    stale: bool
    spark: list[Point]


def _change(latest: Point | None, before: Point | None) -> float | None:
    if latest is None or before is None or before.day == latest.day:
        return None
    return latest.value - before.value


def summarise(session: Session, entry: CatalogueSeries, today: date) -> SeriesSummary:
    meta = session.get(MacroSeries, entry.series_id)
    points = _points(session, entry.series_id, today - timedelta(days=366 * (SPARK_YEARS + 1)))
    latest = points[-1] if points else None
    year_ago = value_on_or_before(points, latest.day - timedelta(days=365)) if latest else None
    month_ago = value_on_or_before(points, latest.day - timedelta(days=30)) if latest else None
    stale = latest is None or (
        (today - latest.day).days > stale_after_days(meta.frequency if meta else "")
    )
    spark_from = (latest.day if latest else today) - timedelta(days=365 * SPARK_YEARS)
    return SeriesSummary(
        entry=entry,
        meta=meta,
        latest=latest,
        year_ago=year_ago,
        month_ago=month_ago,
        stale=stale,
        spark=thin([p for p in points if p.day >= spark_from]),
    )


def change(summary: SeriesSummary, which: str) -> float | None:
    return _change(summary.latest, summary.year_ago if which == "year" else summary.month_ago)


def overview(session: Session, today: date) -> list[SeriesSummary]:
    return [summarise(session, entry, today) for entry in CATALOGUE]


@dataclass(frozen=True)
class SpreadSeries:
    spread: Spread
    points: list[Point]
    reason: str | None


def spread_points(a: list[Point], b: list[Point]) -> list[Point]:
    """``a - b`` on each of ``a``'s dates, ``b`` as of that date (at most a week old)."""
    out: list[Point] = []
    b_days = [p.day for p in b]
    for p in a:
        i = bisect.bisect_right(b_days, p.day) - 1
        if i < 0 or (p.day - b[i].day).days > SPREAD_STALE_DAYS:
            continue
        out.append(Point(p.day, round(p.value - b[i].value, 6)))
    return out


def spread_series(session: Session, spread: Spread, since: date) -> SpreadSeries:
    a = _points(session, spread.a, since)
    b = _points(session, spread.b, since - timedelta(days=SPREAD_STALE_DAYS))
    if not a or not b:
        missing = ", ".join(s for s, pts in ((spread.a, a), (spread.b, b)) if not pts)
        return SpreadSeries(spread, [], f"No stored values for {missing}.")
    return SpreadSeries(spread, spread_points(a, b), None)


def spreads(session: Session, since: date) -> list[SpreadSeries]:
    return [spread_series(session, s, since) for s in SPREADS]


def observations(
    session: Session, series_id: str, since: date | None
) -> list[tuple[date, Decimal | None]]:
    query = select(col(MacroObservation.obs_date), col(MacroObservation.value)).where(
        MacroObservation.series_id == series_id
    )
    if since is not None:
        query = query.where(MacroObservation.obs_date >= since)
    return list(session.exec(query.order_by(col(MacroObservation.obs_date))).all())
