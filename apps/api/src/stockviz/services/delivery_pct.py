"""Delivery % and its 20-session average for the chart (A3.5, M2.7).

From ``eod_extras`` (A1.1's NSE ``sec_bhavdata_full`` loads), one value per
session, the first series of ``DELIVERY_SERIES_ORDER`` (EQ first) when a
session has several, like the Rule DSL's ``delivery_pct``. The average is
the mean of the last ``AVG_SESSIONS`` sessions that hold a value, null
until there are that many. On weekly and monthly bars a point is the
period's mean delivery % and the average as of its last session with a
value, dated on that session (the web places it on the period's bar).

Only NSE and BSE publish delivery figures; other markets have none.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlmodel import Session, col, select

from stockviz.models.eod import EodExtras
from stockviz.services.bars.resample import period_start
from stockviz.services.dsl.data import DELIVERY_SERIES_ORDER
from stockviz.services.instruments import instrument_ids

AVG_SESSIONS = 20


@dataclass(frozen=True)
class DeliveryPoint:
    day: date
    delivery_pct: float
    avg_20: float | None


def daily_delivery(session: Session, ticker: str) -> list[tuple[date, float]]:
    instrument_id = instrument_ids(session, [ticker]).get(ticker)
    if instrument_id is None:
        return []
    rows = session.exec(
        select(EodExtras).where(
            EodExtras.instrument_id == instrument_id, col(EodExtras.delivery_pct).is_not(None)
        )
    ).all()
    rank = {s: i for i, s in enumerate(DELIVERY_SERIES_ORDER)}
    chosen: dict[date, EodExtras] = {}
    for row in rows:
        best = chosen.get(row.session_date)
        if best is None or (rank.get(row.series, 99), row.series) < (
            rank.get(best.series, 99),
            best.series,
        ):
            chosen[row.session_date] = row
    return sorted(
        (d, float(r.delivery_pct)) for d, r in chosen.items() if r.delivery_pct is not None
    )


def with_average(values: list[tuple[date, float]], n: int = AVG_SESSIONS) -> list[DeliveryPoint]:
    out: list[DeliveryPoint] = []
    for i, (day, pct) in enumerate(values):
        window = values[max(0, i - n + 1) : i + 1]
        avg = sum(v for _, v in window) / n if len(window) == n else None
        out.append(DeliveryPoint(day, pct, avg))
    return out


def resample_points(points: list[DeliveryPoint], interval: str) -> list[DeliveryPoint]:
    if interval == "1d":
        return points
    groups: dict[date, list[DeliveryPoint]] = {}
    for p in points:
        groups.setdefault(period_start(p.day, interval), []).append(p)
    out = []
    for _, group in sorted(groups.items()):
        last = group[-1]
        out.append(
            DeliveryPoint(last.day, sum(p.delivery_pct for p in group) / len(group), last.avg_20)
        )
    return out


def delivery_series(
    session: Session,
    ticker: str,
    *,
    interval: str = "1d",
    start: date | None = None,
    end: date | None = None,
) -> tuple[list[DeliveryPoint], bool]:
    """Points in [start, end] and whether the symbol holds any delivery row at all."""
    daily = daily_delivery(session, ticker)
    points = resample_points(with_average(daily), interval)
    if start is not None:
        points = [p for p in points if p.day >= start]
    if end is not None:
        points = [p for p in points if p.day <= end]
    return points, bool(daily)
