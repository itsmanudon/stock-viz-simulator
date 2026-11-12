"""News event studies (Phase 7.4): how prices behaved around news of a kind.

For each Aegis document linked to a stock that matches the asked sentiment
label and/or event type:

- **Event day** is the first stored bar of the stock whose session closed
  after the document's ``available_at``: the market could not react before
  the news was available (point in time; never ``published_at``, AG-12).
- **Abnormal return** on each day is the stock's log return minus its
  market index's (market-adjusted model): ``^GSPC`` for US listings, ``^NSEI``
  for Indian ones, aligned on the dates both traded.
- **CAR** (cumulative abnormal return) runs from ``-pre`` to ``+post``
  sessions around the event day. Events without the full window are counted
  and left out.

Across events: the mean CAR at each offset, its standard error and the
t-statistic, for a few standard windows. Fewer than ``MIN_EVENTS`` events
gives counts but no figures. A document linked to several tickers counts once
per ticker; windows that overlap on one stock are counted and flagged. This
measures association, not cause.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from itertools import pairwise

from sqlmodel import Session, col, select

from stockviz.models import AegisEvent, PriceBar
from stockviz.services.aegis.read import _latest_analyses, documents_for_ticker
from stockviz.services.instruments import instrument_of
from stockviz.services.markets.calendar import (
    COMPLETE_AFTER_CLOSE,
    session_complete_at,
    venue_for_ticker,
)

MIN_EVENTS = 10
"""Below this many complete events, no averages are reported."""

MAX_DOCUMENTS_PER_TICKER = 1000
WINDOWS: tuple[tuple[int, int], ...] = ((0, 1), (0, 5), (-5, -1), (0, 20))
"""(from, to) offsets reported in the summary; the full path is returned too."""

BENCHMARK_BY_VENUE = {"XNYS": "^GSPC", "XNAS": "^GSPC", "XBOM": "^NSEI", "XNSE": "^NSEI"}


@dataclass(frozen=True)
class EventRow:
    ticker: str
    document_id: str
    title: str
    available_at: datetime
    event_date: date
    car: float  # over the whole window


@dataclass(frozen=True)
class WindowStat:
    start: int
    end: int
    mean_car: float | None
    std_error: float | None
    t_stat: float | None


@dataclass
class EventStudy:
    tickers: list[str]
    sentiment: str | None
    event_type: str | None
    pre: int
    post: int
    events_found: int = 0
    events_used: int = 0
    events_incomplete: int = 0
    overlapping: int = 0
    no_benchmark: list[str] = field(default_factory=list)
    benchmarks: dict[str, str] = field(default_factory=dict)
    path: list[tuple[int, float | None, float | None]] = field(default_factory=list)
    windows: list[WindowStat] = field(default_factory=list)
    events: list[EventRow] = field(default_factory=list)
    enough: bool = False


def benchmark_for(ticker: str) -> str | None:
    return BENCHMARK_BY_VENUE.get(venue_for_ticker(ticker))


def _closes(session: Session, ticker: str) -> list[tuple[date, float]]:
    rows = session.exec(
        select(col(PriceBar.ts), col(PriceBar.close))
        .where(PriceBar.instrument_id == instrument_of(ticker), PriceBar.interval == "1d")
        .order_by(col(PriceBar.ts))
    ).all()
    return [(ts.date(), float(close)) for ts, close in rows if close and close > 0]


def _abnormal_returns(
    stock: list[tuple[date, float]], bench: list[tuple[date, float]]
) -> tuple[list[date], list[float]]:
    """Dates both traded, and stock minus index log returns on each."""
    index_close = dict(bench)
    joined = [(d, c, index_close[d]) for d, c in stock if d in index_close]
    dates: list[date] = []
    ars: list[float] = []
    for (_d0, s0, b0), (d1, s1, b1) in pairwise(joined):
        dates.append(d1)
        ars.append(math.log(s1 / s0) - math.log(b1 / b0))
    return dates, ars


def _event_index(dates: list[date], available_at: datetime, venue: str) -> int | None:
    """First aligned date whose session closed after ``available_at``."""
    when = available_at if available_at.tzinfo else available_at.replace(tzinfo=UTC)
    for i, d in enumerate(dates):
        if session_complete_at(d, venue) - COMPLETE_AFTER_CLOSE > when:
            return i
    return None


def _mean_se(values: list[float]) -> tuple[float | None, float | None, float | None]:
    n = len(values)
    if n == 0:
        return None, None, None
    mean = sum(values) / n
    if n < 2:
        return mean, None, None
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    se = math.sqrt(var / n)
    return mean, se, (mean / se if se > 0 else None)


def run_event_study(
    session: Session,
    *,
    tickers: list[str],
    sentiment: str | None = None,
    event_type: str | None = None,
    pre: int = 5,
    post: int = 20,
    as_of: datetime | None = None,
) -> EventStudy:
    study = EventStudy(
        tickers=tickers, sentiment=sentiment, event_type=event_type, pre=pre, post=post
    )
    wanted_type = event_type.lower() if event_type else None
    car_paths: list[list[float]] = []
    for ticker in tickers:
        bench = benchmark_for(ticker)
        if bench is None:
            study.no_benchmark.append(ticker)
            continue
        study.benchmarks[ticker] = bench
        docs = documents_for_ticker(session, ticker, as_of=as_of, limit=MAX_DOCUMENTS_PER_TICKER)
        ids = [d.document_id for d in docs]
        labels = _latest_analyses(session, ids, "sentiment") if sentiment else {}
        types: dict[str, set[str]] = {}
        if wanted_type and ids:
            for doc_id, kind in session.exec(
                select(AegisEvent.document_id, AegisEvent.event_type).where(
                    col(AegisEvent.document_id).in_(ids)
                )
            ).all():
                if kind:
                    types.setdefault(doc_id, set()).add(kind.lower())
        matched = [
            d
            for d in docs
            if (
                not sentiment
                or (d.document_id in labels and labels[d.document_id].label == sentiment)
            )
            and (not wanted_type or wanted_type in types.get(d.document_id, set()))
        ]
        study.events_found += len(matched)
        if not matched:
            continue
        dates, ars = _abnormal_returns(_closes(session, ticker), _closes(session, bench))
        venue = venue_for_ticker(ticker)
        used_days: list[int] = []
        for doc in sorted(matched, key=lambda d: d.available_at):
            i = _event_index(dates, doc.available_at, venue)
            if i is None or i - pre < 0 or i + post >= len(ars):
                study.events_incomplete += 1
                continue
            if any(abs(i - j) <= pre + post for j in used_days):
                study.overlapping += 1
            used_days.append(i)
            window = ars[i - pre : i + post + 1]
            path, total = [], 0.0
            for ar in window:
                total += ar
                path.append(total)
            car_paths.append(path)
            study.events.append(
                EventRow(ticker, doc.document_id, doc.title, doc.available_at, dates[i], total)
            )
    study.events_used = len(car_paths)
    study.enough = study.events_used >= MIN_EVENTS
    offsets = list(range(-pre, post + 1))
    if study.enough:
        for k, offset in enumerate(offsets):
            mean, se, _t = _mean_se([p[k] for p in car_paths])
            study.path.append((offset, mean, se))
        for start, end in WINDOWS:
            if start < -pre or end > post:
                continue
            a, b = offsets.index(start), offsets.index(end)
            values = [p[b] - (p[a - 1] if a > 0 else 0.0) for p in car_paths]
            mean, se, t = _mean_se(values)
            study.windows.append(WindowStat(start, end, mean, se, t))
    study.events.sort(key=lambda e: e.available_at, reverse=True)
    return study
