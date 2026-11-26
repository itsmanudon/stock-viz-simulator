"""Seasonality and the post-earnings drift (A9.1, M3.6, M6.6), from stored bars.

**Seasonality.** Monthly returns are month-end close over the previous
month-end close (the last stored bar of each calendar month, the symbol's
venue dates); weekday returns are close over the previous stored close. Per
calendar month and per weekday: count, mean, median, hit rate (share above
zero) and the t-statistic of the mean (mean / (sd / sqrt(n))). A month with
fewer than ``MIN_YEARS`` years of data is flagged ``thin``. Association, not a
forecast.

**Earnings reaction and drift.** For each stored earnings event (Phase 7):
the reaction session is the event date when the report was before the open,
the next session when after the close, and the event date (flagged
``assumed``) when the time is unknown. The reaction is that session's close
over the previous close; the drift is the close 1, 5 and 20 sessions later
over the reaction close. Events are grouped by the sign of the EPS surprise;
the average absolute reaction is compared with the average absolute daily
move over the same stored history.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from itertools import pairwise
from statistics import median

from sqlmodel import Session, col, select

from stockviz.models import PriceBar
from stockviz.models.earnings import EarningsEvent

MIN_YEARS = 10
DRIFT_HORIZONS = (1, 5, 20)
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")


def _stats(values: list[float]) -> dict[str, float | int | None]:
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "hit_rate": None, "t_stat": None}
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1)) if n > 1 else 0.0
    t = mean / (sd / math.sqrt(n)) if n > 1 and sd > 0 else None
    return {
        "n": n,
        "mean": round(mean * 100, 4),
        "median": round(median(values) * 100, 4),
        "hit_rate": round(sum(1 for v in values if v > 0) / n, 4),
        "t_stat": None if t is None else round(t, 3),
    }


def closes(session: Session, ticker: str) -> list[tuple[date, float]]:
    rows = session.exec(
        select(PriceBar)
        .where(col(PriceBar.ticker) == ticker, col(PriceBar.interval) == "1d")
        .order_by(col(PriceBar.ts))
    ).all()
    return [(r.ts.date(), float(r.close)) for r in rows]


def bars_hlc(
    session: Session, ticker: str
) -> tuple[list[date], list[float], list[float], list[float]]:
    """A9.2: dates, highs, lows and closes of the stored daily bars."""
    rows = session.exec(
        select(PriceBar)
        .where(col(PriceBar.ticker) == ticker, col(PriceBar.interval) == "1d")
        .order_by(col(PriceBar.ts))
    ).all()
    return ([r.ts.date() for r in rows], [float(r.high) for r in rows],
            [float(r.low) for r in rows], [float(r.close) for r in rows])  # fmt: skip


def seasonality(series: list[tuple[date, float]]) -> dict[str, object]:
    """Monthly and weekday statistics (pure)."""
    month_end: dict[tuple[int, int], float] = {}
    for day, close in series:
        month_end[(day.year, day.month)] = close
    keys = sorted(month_end)
    by_month: dict[int, list[float]] = {m: [] for m in range(1, 13)}
    for prev, cur in pairwise(keys):
        expected = (prev[0] + (prev[1] == 12), prev[1] % 12 + 1)
        if cur != expected:
            continue  # a gap of a month or more: not a monthly return
        by_month[cur[1]].append(month_end[cur] / month_end[prev] - 1)
    by_day: dict[int, list[float]] = {d: [] for d in range(5)}
    for (_d0, c0), (d1, c1) in pairwise(series):
        if d1.weekday() < 5 and c0 > 0:
            by_day[d1.weekday()].append(c1 / c0 - 1)
    months = [
        {"key": MONTHS[m - 1], **_stats(v), "thin": len(v) < MIN_YEARS} for m, v in by_month.items()
    ]
    days = [{"key": WEEKDAYS[d], **_stats(v), "thin": False} for d, v in by_day.items()]
    first = series[0][0] if series else None
    last = series[-1][0] if series else None
    return {"months": months, "weekdays": days, "first": first, "last": last}


def reaction_index(
    dates: list[date], event: date, report_time: str | None
) -> tuple[int | None, bool]:
    """(index of the reaction session, assumed) for an event."""
    text = (report_time or "").lower()
    after = any(w in text for w in ("after", "amc", "post"))
    before = any(w in text for w in ("before", "bmo", "pre"))
    for i, d in enumerate(dates):
        if d > event or (d == event and not after):
            return i, not (before or after)
    return None, False


@dataclass
class EarningsDrift:
    events: list[dict[str, object]] = field(default_factory=list)
    groups: list[dict[str, object]] = field(default_factory=list)
    avg_abs_reaction: float | None = None
    avg_abs_day: float | None = None


def earnings_drift(series: list[tuple[date, float]], events: list[EarningsEvent]) -> EarningsDrift:
    """Reaction and drift per event, grouped by the surprise's sign (pure)."""
    out = EarningsDrift()
    dates = [d for d, _c in series]
    prices = [c for _d, c in series]
    daily = [abs(prices[i] / prices[i - 1] - 1) for i in range(1, len(prices)) if prices[i - 1] > 0]
    out.avg_abs_day = round(sum(daily) / len(daily) * 100, 4) if daily else None
    reactions: list[float] = []
    groups: dict[str, dict[int, list[float]]] = {"beat": {}, "miss": {}, "no_surprise": {}}
    for ev in sorted(events, key=lambda e: e.event_date):
        i, assumed = reaction_index(dates, ev.event_date, ev.report_time)
        if i is None or i == 0:
            continue
        reaction = prices[i] / prices[i - 1] - 1
        reactions.append(abs(reaction))
        surprise = float(ev.surprise_pct) if ev.surprise_pct is not None else None
        bucket = (
            "no_surprise"
            if surprise is None or surprise == 0
            else ("beat" if surprise > 0 else "miss")
        )
        drift: dict[str, float | None] = {}
        for h in DRIFT_HORIZONS:
            if i + h < len(prices):
                value = prices[i + h] / prices[i] - 1
                drift[f"d{h}"] = round(value * 100, 4)
                groups[bucket].setdefault(h, []).append(value)
            else:
                drift[f"d{h}"] = None
        out.events.append({
            "event_date": ev.event_date, "reaction_date": dates[i], "assumed": assumed,
            "surprise_pct": surprise, "reaction": round(reaction * 100, 4), **drift,
        })  # fmt: skip
    out.avg_abs_reaction = round(sum(reactions) / len(reactions) * 100, 4) if reactions else None
    for bucket, by_h in groups.items():
        out.groups.append({
            "group": bucket,
            "horizons": [{"sessions": h, **_stats(by_h.get(h, []))} for h in DRIFT_HORIZONS],
        })  # fmt: skip
    return out


def events_for(session: Session, ticker: str) -> list[EarningsEvent]:
    return list(
        session.exec(select(EarningsEvent).where(col(EarningsEvent.ticker) == ticker)).all()
    )
