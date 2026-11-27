"""Intraday bars on read (A6.2, M2.2): workspace ``docs/a6-design-note.md``.

``intraday_bars`` (A6.1) stores ``1m`` bars, and ``60m`` bars where only the
owner's hourly files exist. Every other interval is built here on read and
never stored.

**Intervals.** ``1m`` is the stored minutes. ``5m``, ``15m`` and ``30m`` are
resampled from the minutes. ``60m`` is resampled from the minutes for every
session that has minutes, and is the stored hourly bar for a session that has
none (the hourly files reach back to 2015, the minute files to 2023). So for
one session the 60-minute bars are never a mix of the two, and each bar's
``source`` says which it is (``bulk_1m`` or ``bulk_1h``).

**Buckets never cross a session or a pause.** A bucket starts at the open of
a trading span (``calendar.session_minutes``: the session's open, or the
restart after a disaster-recovery pause) and every N minutes after it; the
last bucket of a span is clipped at the span's end. So a 60-minute NSE day is
09:15, 10:15, ..., 14:15 and 15:15-15:30; a Muhurat evening (18:15-19:15) is
one bar; the 2024 DR sessions (09:15-10:00, 11:30-12:30) give 09:15-10:00
and then 11:30-12:30. Nights, weekends and holidays have no bar at all.
A minute outside every span (none are loaded, but a feed could send one) is
left out; a day the calendar does not cover is bucketed from midnight UTC.

**Times.** ``ts`` is the bar's open instant and ``closed_at`` its close
(bucket end, clipped), both naive UTC like the store. ``session_date`` is the
venue's date of the session the bar belongs to.

**Partial (closed-bar semantics).** Only the newest bar can be partial: when
its ``closed_at`` is after now, or (a resampled bar) its last stored minute
ends before ``closed_at`` and now is within :data:`LATE_MINUTE_GRACE` of the
close, so a minute still on its way keeps the bar open. Every older bar has a
later bar after it, so it is closed: a gap in old minutes is a gap, not "so
far". Indicators leave a partial bar out.

**Feeds.** Bars of one feed only per response. The default is the best feed
stored for the symbol (:data:`FEED_RANK`: consolidated SIP, then Kite, then
IEX, then the owner's files, then A6.5's replayed bars). Each feed has a badge the chart shows
(:data:`FEED_BADGES`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Select, func
from sqlalchemy import select as sa_select
from sqlmodel import Session, col, select

from stockviz.models.intraday import IntradayBar
from stockviz.services.markets.calendar import SessionHours, session_minutes, venue_zone

INTRADAY_INTERVALS: tuple[str, ...] = ("1m", "5m", "15m", "30m", "60m")
INTERVAL_MINUTES: dict[str, int] = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60}
INTRADAY_PATTERN = r"^(1m|5m|15m|30m|60m)$"

FEED_RANK: tuple[str, ...] = ("sip", "kite", "iex", "file", "replayed")
"""Which stored feed a request without ``feed`` reads: the first one stored.
``replayed`` (A6.5) is last: a symbol shows its replayed bars by default only
when it has no real ones."""

FEED_BADGES: dict[str, str] = {
    "file": "File (local)",
    "iex": "IEX only",
    "sip": "SIP",
    "kite": "Kite",
    "replayed": "Replayed",
}
"""The source badge per feed. ``file`` is the owner's local files, which never
reach production (``services/intraday/guard.py``)."""

LATE_MINUTE_GRACE = timedelta(minutes=2)
"""How long after a bucket's close a missing last minute still makes the
newest bar partial (a minute bar can be written a little after its close)."""

ONE_MINUTE = timedelta(minutes=1)


def now_utc() -> datetime:
    """The clock the partial rule reads; tests patch it."""
    return datetime.now(UTC)


def _naive(instant: datetime) -> datetime:
    return instant.astimezone(UTC).replace(tzinfo=None) if instant.tzinfo else instant


@dataclass(frozen=True)
class IntradayOut:
    ts: datetime
    closed_at: datetime
    session_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    minutes: int
    """Stored 1-minute bars in it (a stored 60m bar counts its length)."""
    partial: bool
    source: str | None
    feed: str
    badge: str
    last_available: datetime | None = None
    """When the bar's newest stored minute (or the stored bar) was complete;
    the partial rule reads it. Not sent by the API."""


@dataclass(frozen=True)
class Coverage:
    feed: str
    interval: str
    first: datetime
    last: datetime


@dataclass(frozen=True)
class IntradayInfo:
    feed: str
    badge: str
    intervals: list[str]
    first: datetime
    last: datetime
    coverage: list[Coverage]
    feeds: list[str]


def coverage(session: Session, instrument_id: int) -> list[Coverage]:
    """What intraday bars an instrument has, per stored feed and interval.

    One min/max per (feed, interval) pair: each uses the key's index, and on
    PostgreSQL the ordered partitions stop at the first that has a row.
    """
    out: list[Coverage] = []
    for feed in FEED_RANK:
        for interval in ("1m", "60m"):
            row = session.exec(
                select(func.min(IntradayBar.ts), func.max(IntradayBar.ts)).where(
                    col(IntradayBar.instrument_id) == instrument_id,
                    col(IntradayBar.feed) == feed,
                    col(IntradayBar.interval) == interval,
                )
            ).one()
            if row[0] is not None and row[1] is not None:
                out.append(Coverage(feed, interval, row[0], row[1]))
    return out


def intraday_info(session: Session, instrument_id: int) -> IntradayInfo | None:
    """The default feed's intervals and range, or None with no intraday bars."""
    cov = coverage(session, instrument_id)
    if not cov:
        return None
    feeds = [f for f in FEED_RANK if any(c.feed == f for c in cov)]
    feed = feeds[0]
    mine = [c for c in cov if c.feed == feed]
    stored = {c.interval for c in mine}
    intervals = list(INTRADAY_INTERVALS) if "1m" in stored else ["60m"]
    return IntradayInfo(
        feed=feed,
        badge=FEED_BADGES[feed],
        intervals=intervals,
        first=min(c.first for c in mine),
        last=max(c.last for c in mine),
        coverage=cov,
        feeds=feeds,
    )


class NoIntradayData(LookupError):
    """The symbol has no bars to build this interval from (the router's 404)."""


def pick_feed(cov: Sequence[Coverage], interval: str, feed: str | None, ticker: str) -> str:
    """The feed a request reads, or :class:`NoIntradayData` with the reason."""
    if not cov:
        raise NoIntradayData(
            f"No intraday bars are stored for {ticker}. Minute bars exist only where "
            "a feed or a local file has been loaded."
        )
    stored = [c for c in cov if feed is None or c.feed == feed]
    if not stored:
        have = ", ".join(sorted({c.feed for c in cov}))
        raise NoIntradayData(f"No intraday bars from feed {feed!r} for {ticker} (stored: {have}).")
    chosen = feed or next(f for f in FEED_RANK if any(c.feed == f for c in stored))
    intervals = {c.interval for c in stored if c.feed == chosen}
    if interval != "60m" and "1m" not in intervals:
        raise NoIntradayData(
            f"{ticker} has no 1-minute bars on feed {chosen!r}, so {interval} bars cannot be "
            "built; 60m is available."
        )
    return chosen


# --- the pure resampler -------------------------------------------------------

Row = tuple[datetime, Decimal, Decimal, Decimal, Decimal, int, str | None, datetime]
"""(ts, open, high, low, close, volume, source, available_at), naive UTC."""


class _Sessions:
    """``session_minutes`` per venue date, cached for one request."""

    def __init__(self, venue: str) -> None:
        self.venue = venue
        self.zone = venue_zone(venue)
        self._cache: dict[date, SessionHours | None] = {}

    def day_of(self, ts: datetime) -> date:
        return ts.replace(tzinfo=UTC).astimezone(self.zone).date()

    def hours(self, day: date) -> SessionHours | None:
        if day not in self._cache:
            self._cache[day] = session_minutes(day, self.venue)
        return self._cache[day]

    def bucket(self, ts: datetime, minutes: int) -> tuple[date, datetime, datetime] | None:
        """(session date, bucket open, bucket close) for a bar opening at ``ts``."""
        day = self.day_of(ts)
        hours = self.hours(day)
        if hours is None:
            # No calendar for the day: buckets from the UTC midnight.
            midnight = datetime.combine(ts.date(), datetime.min.time())
            k = int((ts - midnight).total_seconds() // 60) // minutes
            start = midnight + timedelta(minutes=k * minutes)
            return day, start, start + timedelta(minutes=minutes)
        aware = ts.replace(tzinfo=UTC)
        for span_start, span_end in hours.spans:
            if span_start <= aware < span_end:
                k = int((aware - span_start).total_seconds() // 60) // minutes
                start = span_start + timedelta(minutes=k * minutes)
                end = min(start + timedelta(minutes=minutes), span_end)
                return day, _naive(start), _naive(end)
        return None  # outside every trading span


def resample_minutes(
    rows: Sequence[Row], interval: str, *, venue: str, feed: str
) -> list[IntradayOut]:
    """1-minute ``rows`` (oldest first, one feed) as ``interval`` bars, oldest first.

    No partial flag here (:func:`mark_partial` sets it on the newest bar).
    """
    minutes = INTERVAL_MINUTES[interval]
    sessions = _Sessions(venue)
    out: list[IntradayOut] = []
    group: list[Row] = []
    key: tuple[date, datetime, datetime] | None = None

    def flush() -> None:
        if not group or key is None:
            return
        sources = {r[6] for r in group}
        out.append(
            IntradayOut(
                ts=key[1],
                closed_at=key[2],
                session_date=key[0],
                open=group[0][1],
                high=max(r[2] for r in group),
                low=min(r[3] for r in group),
                close=group[-1][4],
                volume=sum(int(r[5]) for r in group),
                minutes=len(group),
                partial=False,
                source=next(iter(sources)) if len(sources) == 1 else "mixed",
                feed=feed,
                badge=FEED_BADGES.get(feed, feed),
                last_available=max(r[7] for r in group),
            )
        )

    for row in sorted(rows, key=lambda r: r[0]):
        bucket = sessions.bucket(row[0], minutes)
        if bucket is None:
            continue
        if bucket != key:
            flush()
            group = []
            key = bucket
        group.append(row)
    flush()
    return out


def stored_bars(rows: Sequence[Row], *, venue: str, feed: str) -> list[IntradayOut]:
    """Stored 60-minute rows as output bars (their own open and availability)."""
    sessions = _Sessions(venue)
    out: list[IntradayOut] = []
    for ts, o, h, lo, c, v, source, available in sorted(rows, key=lambda r: r[0]):
        out.append(
            IntradayOut(
                ts=ts,
                closed_at=available,
                session_date=sessions.day_of(ts),
                open=o,
                high=h,
                low=lo,
                close=c,
                volume=int(v),
                minutes=int((available - ts).total_seconds() // 60),
                partial=False,
                source=source,
                feed=feed,
                badge=FEED_BADGES.get(feed, feed),
                last_available=available,
            )
        )
    return out


def mark_partial(bars: list[IntradayOut], now: datetime) -> list[IntradayOut]:
    """Flag the newest bar when it is not closed at ``now`` (aware)."""
    if not bars:
        return bars
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    clock = _naive(now)
    newest = bars[-1]
    partial = newest.closed_at > clock
    last_available = newest.last_available
    if not partial and last_available is not None and last_available < newest.closed_at:
        partial = clock < newest.closed_at + LATE_MINUTE_GRACE
    if partial:
        bars[-1] = replace(newest, partial=True)
    return bars


# --- loading -------------------------------------------------------------------


def _row_select() -> Select:
    """The columns a :data:`Row` holds (SQLAlchemy core: eight columns)."""
    return sa_select(
        col(IntradayBar.ts),
        col(IntradayBar.open),
        col(IntradayBar.high),
        col(IntradayBar.low),
        col(IntradayBar.close),
        col(IntradayBar.volume),
        col(IntradayBar.source),
        col(IntradayBar.available_at),
    )


def _rows(
    session: Session,
    instrument_id: int,
    feed: str,
    interval: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    newest: int | None = None,
) -> list[Row]:
    stmt = _row_select().where(
        col(IntradayBar.instrument_id) == instrument_id,
        col(IntradayBar.feed) == feed,
        col(IntradayBar.interval) == interval,
    )
    if start is not None:
        stmt = stmt.where(col(IntradayBar.ts) >= start)
    if end is not None:
        stmt = stmt.where(col(IntradayBar.ts) < end)
    if newest is not None:
        rows = list(session.execute(stmt.order_by(col(IntradayBar.ts).desc()).limit(newest)).all())
        rows.reverse()
    else:
        rows = list(session.execute(stmt.order_by(col(IntradayBar.ts))).all())
    return [tuple(r) for r in rows]  # type: ignore[misc]


def load_intraday(
    session: Session,
    instrument_id: int,
    interval: str,
    *,
    venue: str,
    feed: str,
    bars_wanted: int,
    from_: datetime | None = None,
    to: datetime | None = None,
    now: datetime | None = None,
) -> list[IntradayOut]:
    """The newest ``bars_wanted`` ``interval`` bars with ``from_ <= ts <= to``, oldest first.

    ``from_``/``to`` are naive UTC and select bars by their open. A bar that
    opens at or before ``to`` is loaded whole (its minutes after ``to`` too).
    """
    minutes = INTERVAL_MINUTES[interval]
    end = to + timedelta(minutes=minutes) if to is not None else None
    cap = (bars_wanted + 1) * minutes
    rows = _rows(session, instrument_id, feed, "1m", start=from_, end=end, newest=cap)
    bars = resample_minutes(rows, interval, venue=venue, feed=feed)
    if len(rows) == cap and bars:
        bars = bars[1:]  # the oldest bucket may be cut short by the cap
    if interval == "60m":
        bars = _with_stored_hours(
            session,
            instrument_id,
            venue,
            feed,
            bars,
            bars_wanted,
            from_,
            end,
            full=len(rows) == cap,
        )
    if from_ is not None:
        bars = [b for b in bars if b.ts >= from_]
    if to is not None:
        bars = [b for b in bars if b.ts <= to]
    bars = bars[-bars_wanted:]
    return mark_partial(bars, now or now_utc())


def _with_stored_hours(
    session: Session,
    instrument_id: int,
    venue: str,
    feed: str,
    resampled: list[IntradayOut],
    bars_wanted: int,
    from_: datetime | None,
    end: datetime | None,
    *,
    full: bool,
) -> list[IntradayOut]:
    """60m: stored hourly bars for the sessions without minutes.

    Within the minutes' range, stored hours fill only sessions that have no
    minute at all. Before it (when the minutes ran out rather than the cap),
    the newest stored hours are read up to the number still wanted.
    """
    have_minutes = {b.session_date for b in resampled}
    lower = resampled[0].ts if resampled else None
    inside = (
        _rows(session, instrument_id, feed, "60m", start=lower, end=end)
        if lower is not None
        else []
    )
    hours = [
        b for b in stored_bars(inside, venue=venue, feed=feed) if b.session_date not in have_minutes
    ]
    older: list[IntradayOut] = []
    still = bars_wanted - len(resampled) - len(hours)
    if not full and still > 0:
        upper = lower if lower is not None else end
        older_rows = _rows(
            session, instrument_id, feed, "60m", start=from_, end=upper, newest=still + 1
        )
        older = [
            b
            for b in stored_bars(older_rows, venue=venue, feed=feed)
            if b.session_date not in have_minutes
        ]
    return sorted([*older, *hours, *resampled], key=lambda b: b.ts)


def minute_rows_from(
    session: Session,
    instrument_id: int,
    feed: str,
    start: datetime,
    *,
    limit: int,
) -> list[Row]:
    """1-minute rows from ``start`` on, oldest first, at most ``limit + 1``
    (so a caller can tell the limit was passed)."""
    stmt = (
        _row_select()
        .where(
            col(IntradayBar.instrument_id) == instrument_id,
            col(IntradayBar.feed) == feed,
            col(IntradayBar.interval) == "1m",
            col(IntradayBar.ts) >= start,
        )
        .order_by(col(IntradayBar.ts))
        .limit(limit + 1)
    )
    return [tuple(r) for r in session.execute(stmt).all()]  # type: ignore[misc]


def session_open(day: date, venue: str) -> datetime | None:
    """The naive UTC open of ``day``'s session, or None when it does not trade."""
    hours = session_minutes(day, venue)
    return _naive(hours.open) if hours is not None else None


__all__ = [
    "FEED_BADGES",
    "FEED_RANK",
    "INTERVAL_MINUTES",
    "INTRADAY_INTERVALS",
    "INTRADAY_PATTERN",
    "Coverage",
    "IntradayInfo",
    "IntradayOut",
    "NoIntradayData",
    "coverage",
    "intraday_info",
    "load_intraday",
    "mark_partial",
    "minute_rows_from",
    "now_utc",
    "pick_feed",
    "resample_minutes",
    "session_open",
    "stored_bars",
]
