"""``stockviz.cli intraday-backfill``: US minute history into ``intraday_bars`` (A6.3).

A dry run by default: the plan (sessions, calls needed, the least time the
provider's documented rate limit allows) and nothing fetched. ``apply``
fetches each symbol and writes its regular-session minutes with the
provider's feed tag (``iex`` / ``sip``), ``ON CONFLICT DO NOTHING``: a rerun
inserts nothing and a stored row is never changed. US provider data is not
the owner's files, so any database is allowed (no local-only guard), but
the command only runs when the provider's key is set.

- **Sessions:** XNYS regular hours from ``calendar.session_minutes`` (early
  closes included; no pre- or post-market). A minute outside every session
  is counted ``off_session`` and not stored.
- **Alpaca SIP:** the range end is clipped to 15 minutes ago (the free
  plan's rule); IEX is not clipped.
- **Massive:** the range start is clipped to 2 years ago (the Basic plan).
- **Errors:** a key refused (``auth``) or the rate limit still hit after the
  retries (``rate``) stops the run; a network or provider error skips that
  symbol and goes on. Messages are fixed (``FeedError``), never the key or
  the provider's text.
- **Symbols:** US tickers only (``us_symbol``); a ticker the database has no
  instrument for is reported and skipped (add it with ``ingest`` first).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from stockviz._time import utcnow
from stockviz.models.intraday import IntradayBar
from stockviz.services.feeds.alpaca import PAGE_LIMIT, SIP_DELAY, AlpacaFeed
from stockviz.services.feeds.base import MINUTE, FeedBar, FeedError, us_symbol
from stockviz.services.feeds.massive import CHUNK_DAYS as MASSIVE_CHUNK_DAYS
from stockviz.services.feeds.massive import MassiveFeed, history_floor
from stockviz.services.feeds.provider import HttpFeed
from stockviz.services.feeds.ratelimit import estimate_seconds
from stockviz.services.feeds.tiingo import CHUNK_DAYS as TIINGO_CHUNK_DAYS
from stockviz.services.feeds.tiingo import TiingoFeed, chunks
from stockviz.services.instruments import instrument_ids
from stockviz.services.intraday.partitions import ensure_month_partitions, month_of
from stockviz.services.markets.calendar import NEW_YORK_VENUE, SessionHours, session_minutes

REGULAR_MINUTES = 390
WRITE_CHUNK = 1000
STOPPING_KINDS = frozenset({"auth", "rate"})


def now_utc() -> datetime:
    """The wall clock (tests patch it)."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime
    sessions: tuple[SessionHours, ...]
    notes: tuple[str, ...] = ()

    @property
    def minutes(self) -> int:
        return sum(s.minutes for s in self.sessions)


@dataclass(frozen=True)
class Plan:
    provider: str
    label: str
    feed: str
    symbols: tuple[str, ...]
    window: Window | None
    calls_per_symbol: int
    rate_limits: str

    @property
    def calls(self) -> int:
        return self.calls_per_symbol * len(self.symbols)

    def seconds(self, feed: HttpFeed) -> float:
        return estimate_seconds(feed.capabilities.rate_limits, self.calls)


@dataclass
class SymbolResult:
    symbol: str
    status: str = "planned"  # planned | written | unknown_symbol | failed | skipped
    fetched: int = 0
    off_session: int = 0
    inserted: int = 0
    already_stored: int = 0
    error_kind: str | None = None
    error: str | None = None


@dataclass
class BackfillReport:
    plan: Plan
    results: list[SymbolResult] = field(default_factory=list)
    stopped: str | None = None
    waited_seconds: float = 0.0

    @property
    def errors(self) -> list[SymbolResult]:
        return [r for r in self.results if r.status == "failed"]

    def summary(self) -> str | None:
        """Fixed text for ``job_runs.error`` (None when nothing failed)."""
        failed = self.errors
        if not failed:
            return None
        kinds = sorted({r.error_kind or "provider" for r in failed})
        return f"{self.plan.label}: {'/'.join(kinds)} error on {len(failed)} symbol(s)"


def feed_tag(feed: HttpFeed) -> str:
    if isinstance(feed, AlpacaFeed):
        return feed.feed
    return feed.capabilities.coverage[0] if feed.capabilities.coverage else "?"


def window_for(feed: HttpFeed, first: date, last: date, now: datetime) -> Window | None:
    """The [start, end) instants to ask for, from XNYS sessions first..last, clipped."""
    notes: list[str] = []
    if isinstance(feed, MassiveFeed):
        floor = history_floor(now.date())
        if first < floor:
            notes.append(f"start clipped to {floor.isoformat()} (Massive Basic: 2 years)")
            first = floor
    sessions: list[SessionHours] = []
    day = first
    while day <= last:
        hours = session_minutes(day, NEW_YORK_VENUE)
        if hours is not None and hours.open < now:
            sessions.append(hours)
        day += timedelta(days=1)
    if not sessions:
        return None
    start = sessions[0].open
    end = min(sessions[-1].close, now)
    if isinstance(feed, AlpacaFeed) and feed.feed == "sip":
        latest = now - SIP_DELAY
        if end > latest:
            notes.append("end clipped to 15 minutes ago (Alpaca: SIP history on the free plan)")
            end = latest
            sessions = [s for s in sessions if s.open < end]
    if not sessions or start >= end:
        return None
    return Window(start=start, end=end, sessions=tuple(sessions), notes=tuple(notes))


def calls_per_symbol(feed: HttpFeed, window: Window | None) -> int:
    if window is None:
        return 0
    if isinstance(feed, AlpacaFeed):
        return max(1, math.ceil(len(window.sessions) * REGULAR_MINUTES / PAGE_LIMIT))
    first = window.start.date()
    last = (window.end - timedelta(microseconds=1)).date()
    if isinstance(feed, TiingoFeed):
        return len(chunks(first, last, TIINGO_CHUNK_DAYS))
    if isinstance(feed, MassiveFeed):
        return len(chunks(first, last, MASSIVE_CHUNK_DAYS))
    return 0


def make_plan(
    feed: HttpFeed, symbols: Sequence[str], first: date, last: date, now: datetime
) -> Plan:
    tickers = tuple(dict.fromkeys(us_symbol(s) for s in symbols))
    window = window_for(feed, first, last, now)
    limits = ", ".join(
        f"{s.calls} per {_period(s.per_seconds)}" for s in feed.capabilities.rate_limits
    )
    return Plan(
        provider=feed.name,
        label=feed.label,
        feed=feed_tag(feed),
        symbols=tickers,
        window=window,
        calls_per_symbol=calls_per_symbol(feed, window),
        rate_limits=limits or "not stated",
    )


def _period(seconds: float) -> str:
    return {60: "minute", 3600: "hour", 86400: "day"}.get(int(seconds), f"{seconds:g} s")


def _session_of(sessions: Sequence[SessionHours], ts: datetime) -> SessionHours | None:
    for hours in sessions:
        if hours.contains(ts):
            return hours
    return None


def _rows(bars: Sequence[FeedBar], instrument_id: int, sessions: Sequence[SessionHours]):
    now = utcnow()
    rows: list[dict[str, object]] = []
    off = 0
    for bar in bars:
        hours = _session_of(sessions, bar.ts)
        if hours is None:
            off += 1
            continue
        available = min(bar.ts + MINUTE, hours.close)
        rows.append(
            {
                "instrument_id": instrument_id,
                "feed": bar.feed,
                "interval": "1m",
                "ts": bar.ts.astimezone(UTC).replace(tzinfo=None),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "source": bar.source,
                "file_id": None,
                "ingested_at": now,
                "available_at": available.astimezone(UTC).replace(tzinfo=None),
            }
        )
    return rows, off


def write_rows(session: Session, rows: list[dict[str, object]]) -> int:
    """Insert, skipping rows already stored; return the number inserted."""
    if not rows:
        return 0
    conn = session.connection()
    table = IntradayBar.__table__  # pyright: ignore[reportAttributeAccessIssue]
    ensure_month_partitions(conn, {month_of(r["ts"]) for r in rows})  # pyright: ignore[reportArgumentType]
    inserted = 0
    for i in range(0, len(rows), WRITE_CHUNK):
        batch = rows[i : i + WRITE_CHUNK]
        # RETURNING counts the rows actually inserted (rowcount is -1 on
        # psycopg for a multi-row INSERT ... ON CONFLICT DO NOTHING).
        insert = pg_insert if conn.dialect.name == "postgresql" else sqlite_insert
        stmt = insert(table).values(batch).on_conflict_do_nothing().returning(table.c.ts)
        inserted += len(conn.execute(stmt).all())
    return inserted


def run_backfill(
    session: Session,
    feed: HttpFeed,
    plan: Plan,
    *,
    apply: bool,
    progress: Callable[[int, int, SymbolResult], None] | None = None,
) -> BackfillReport:
    report = BackfillReport(plan=plan)
    if not apply or plan.window is None:
        report.results = [SymbolResult(symbol=s) for s in plan.symbols]
        return report
    window = plan.window
    ids = instrument_ids(session, list(plan.symbols))
    for index, symbol in enumerate(plan.symbols, start=1):
        result = SymbolResult(symbol=symbol)
        report.results.append(result)
        if report.stopped is not None:
            result.status = "skipped"
        elif symbol not in ids:
            result.status = "unknown_symbol"
        else:
            try:
                bars = feed.minute_bars(symbol, window.start, window.end)
            except FeedError as exc:
                result.status = "failed"
                result.error_kind = exc.kind
                result.error = str(exc)
                if exc.kind in STOPPING_KINDS:
                    report.stopped = f"{exc.kind} error: the remaining symbols were not fetched"
            else:
                rows, off = _rows(bars, ids[symbol], window.sessions)
                result.fetched = len(bars)
                result.off_session = off
                result.inserted = write_rows(session, rows)
                result.already_stored = len(rows) - result.inserted
                session.commit()
                result.status = "written"
        if progress is not None:
            progress(index, len(plan.symbols), result)
    report.waited_seconds = feed.limiter.waited
    return report
