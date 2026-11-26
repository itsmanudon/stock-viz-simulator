"""Intraday replay bars (A6.9, M9.4): sessions on 1, 5, 15 or 60 minutes.

A session's bars are built on read from the stored 1-minute bars of one feed
(``services/bars/intraday.resample_minutes``, A6.2's buckets: never across a
session or a pause, the last bucket of a span clipped). Only minutes are
used, never the stored hourly files, so a 60-minute replay bar is always
made of its minutes. Every query here is bounded by the instants it is
given; the callers in ``market.py`` clip them to the session's frozen range
and clock, so no bar after ``current_at`` is read.

The same minutes decide a bracket's stop and target when both are inside one
bar (``minutes_inside``): a daily bar's minutes are those of its venue
session (``calendar.session_minutes``), an intraday bar's those between its
open and its close.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy import select as sa_select
from sqlmodel import Session, col, select

from stockviz.models.intraday import IntradayBar
from stockviz.services.bars.intraday import (
    FEED_RANK,
    INTERVAL_MINUTES,
    IntradayOut,
    Row,
    resample_minutes,
)
from stockviz.services.instruments import instrument_of
from stockviz.services.markets.calendar import session_minutes, venue_for_ticker
from stockviz.services.simulation import MarketSnapshot

REPLAY_INTRADAY_INTERVALS: tuple[str, ...] = ("1m", "5m", "15m", "60m")
"""The intraday intervals a replay session can run on (design note M9.4)."""
DAILY = "1d"
ONE_MINUTE = timedelta(minutes=1)


def minute_feed(session: Session, ticker: str) -> str | None:
    """The best feed (``FEED_RANK``) that stores 1-minute bars for ``ticker``."""
    iid = instrument_of(ticker)
    for feed in FEED_RANK:
        found = session.exec(
            select(IntradayBar.ts)
            .where(
                col(IntradayBar.instrument_id) == iid,
                col(IntradayBar.feed) == feed,
                col(IntradayBar.interval) == "1m",
            )
            .limit(1)
        ).first()
        if found is not None:
            return feed
    return None


def minute_range(session: Session, ticker: str, feed: str) -> tuple[datetime, datetime] | None:
    """(first, last) stored minute of ``ticker`` on ``feed``."""
    row = session.exec(
        select(func.min(IntradayBar.ts), func.max(IntradayBar.ts)).where(
            col(IntradayBar.instrument_id) == instrument_of(ticker),
            col(IntradayBar.feed) == feed,
            col(IntradayBar.interval) == "1m",
        )
    ).one()
    if row[0] is None or row[1] is None:
        return None
    return row[0], row[1]


def _rows(
    session: Session,
    iid: Any,
    feed: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    oldest: int | None = None,
    newest: int | None = None,
) -> list[Row]:
    """Stored minutes with ``start <= ts < end``, oldest first, limited to the
    ``oldest`` first or the ``newest`` last ones."""
    stmt = sa_select(
        col(IntradayBar.ts),
        col(IntradayBar.open),
        col(IntradayBar.high),
        col(IntradayBar.low),
        col(IntradayBar.close),
        col(IntradayBar.volume),
        col(IntradayBar.source),
        col(IntradayBar.available_at),
    ).where(
        col(IntradayBar.instrument_id) == iid,
        col(IntradayBar.feed) == feed,
        col(IntradayBar.interval) == "1m",
    )
    if start is not None:
        stmt = stmt.where(col(IntradayBar.ts) >= start)
    if end is not None:
        stmt = stmt.where(col(IntradayBar.ts) < end)
    if newest is not None:
        rows = list(session.execute(stmt.order_by(col(IntradayBar.ts).desc()).limit(newest)).all())
        rows.reverse()
    else:
        stmt = stmt.order_by(col(IntradayBar.ts))
        if oldest is not None:
            stmt = stmt.limit(oldest)
        rows = list(session.execute(stmt).all())
    return [tuple(r) for r in rows]  # type: ignore[misc]


@dataclass(frozen=True)
class IntradaySource:
    """One session's bar maker: ``ticker``'s ``feed`` minutes as ``interval`` bars."""

    ticker: str
    interval: str
    feed: str

    @property
    def minutes(self) -> int:
        return INTERVAL_MINUTES[self.interval]

    @property
    def span(self) -> timedelta:
        return timedelta(minutes=self.minutes)

    def _resample(self, rows: Sequence[Row]) -> list[IntradayOut]:
        return resample_minutes(
            rows, self.interval, venue=venue_for_ticker(self.ticker), feed=self.feed
        )

    def _iid(self) -> Any:
        return instrument_of(self.ticker)

    def between(self, session: Session, start: datetime, end: datetime) -> list[IntradayOut]:
        """Bars opening in ``[start, end]``, whole (a bar opening at ``end``
        is loaded with all its minutes)."""
        rows = _rows(session, self._iid(), self.feed, start=start, end=end + self.span)
        return [b for b in self._resample(rows) if start <= b.ts <= end]

    def first_at_or_after(self, session: Session, ts: datetime) -> IntradayOut | None:
        rows = _rows(session, self._iid(), self.feed, start=ts, oldest=2 * self.minutes)
        return next((b for b in self._resample(rows) if b.ts >= ts), None)

    def last_at_or_before(self, session: Session, ts: datetime) -> IntradayOut | None:
        rows = _rows(session, self._iid(), self.feed, end=ts + self.span, newest=2 * self.minutes)
        bars = [b for b in self._resample(rows) if b.ts <= ts]
        return bars[-1] if bars else None

    def at(self, session: Session, ts: datetime) -> IntradayOut | None:
        rows = _rows(session, self._iid(), self.feed, start=ts, end=ts + self.span)
        return next((b for b in self._resample(rows) if b.ts == ts), None)

    def after(self, session: Session, ts: datetime, end: datetime) -> IntradayOut | None:
        """The first bar opening after ``ts`` and at or before ``end``."""
        rows = _rows(
            session, self._iid(), self.feed, start=ts + ONE_MINUTE, oldest=2 * self.minutes + 1
        )
        nxt = next((b for b in self._resample(rows) if b.ts > ts), None)
        return nxt if nxt is not None and nxt.ts <= end else None

    def before(self, session: Session, ts: datetime, n: int) -> list[IntradayOut]:
        """Up to ``n`` whole bars opening before ``ts``, oldest first."""
        if n <= 0:
            return []
        rows = _rows(session, self._iid(), self.feed, end=ts, newest=(n + 1) * self.minutes)
        bars = self._resample(rows)
        if len(rows) == (n + 1) * self.minutes and bars:
            bars = bars[1:]  # the oldest bucket may be cut short by the limit
        return [b for b in bars if b.ts < ts][-n:]


def snapshots(rows: Sequence[Row], ticker: str) -> list[MarketSnapshot]:
    """Stored minutes as kernel snapshots (a bracket's path inside one bar)."""
    return [
        MarketSnapshot(
            ticker=ticker,
            observed_at=r[0].replace(tzinfo=UTC),
            interval="1m",
            open=r[1],
            high=r[2],
            low=r[3],
            close=r[4],
            volume=Decimal(int(r[5])),
        )
        for r in rows
    ]


def minutes_inside(
    session: Session,
    *,
    ticker: str,
    interval: str,
    feed: str | None,
    bar_ts: datetime,
    closed_at: datetime | None,
) -> list[MarketSnapshot]:
    """The stored minutes inside one replay bar, oldest first ([] when none).

    A daily bar (``interval`` ``1d``, ``bar_ts`` its date label) reads its
    venue session's minutes on the best minute feed; an intraday bar reads
    its own feed's minutes from its open to its close.
    """
    iid = instrument_of(ticker)
    if interval == DAILY:
        chosen = minute_feed(session, ticker)
        if chosen is None:
            return []
        day: date = bar_ts.date()
        hours = session_minutes(day, venue_for_ticker(ticker))
        if hours is None:
            return []
        start = hours.open.astimezone(UTC).replace(tzinfo=None)
        end = hours.close.astimezone(UTC).replace(tzinfo=None)
        return snapshots(_rows(session, iid, chosen, start=start, end=end), ticker)
    if feed is None:
        return []
    until = closed_at or bar_ts + timedelta(minutes=INTERVAL_MINUTES[interval])
    rows = _rows(session, iid, feed, start=bar_ts, end=until)
    return snapshots(rows, ticker)


__all__ = [
    "DAILY",
    "REPLAY_INTRADAY_INTERVALS",
    "IntradaySource",
    "minute_feed",
    "minute_range",
    "minutes_inside",
    "snapshots",
]
