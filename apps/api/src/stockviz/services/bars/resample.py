"""Weekly and monthly bars resampled on read from a venue's daily bars (A1.4a).

Workspace ``docs/a1-design-note.md`` section 6. Nothing is stored: the bars
and indicators routers call :func:`resample` on the ``1d`` rows they load.

The rules:

- a week is the ISO week, Monday to Sunday, and a month the calendar month,
  both by the bar's own venue date (a daily bar's label is its venue's date,
  Phase 4.1b);
- open is the first session's open, high and low the extremes, close the last
  session's close, volume the sum; all prices stay ``Decimal``;
- the bar's timestamp is its **last stored session**, and ``sessions`` counts
  the daily bars in it;
- ``source`` and ``adjustment_semantics`` are the daily bars' own when they
  all agree, else ``"mixed"``;
- only the newest bar can be ``partial``: it is when the venue calendar still
  has a session in its period after the last stored one, or when that last
  stored session is not complete at ``now`` (``session_complete_at``). Every
  older bar has a later bar after it, so its period is over and it holds
  every session that was stored for it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal, Protocol

from stockviz.services.markets.calendar import is_session, session_complete_at, venue_zone

ResampleInterval = Literal["1wk", "1mo"]
RESAMPLED_INTERVALS: tuple[ResampleInterval, ...] = ("1wk", "1mo")

MAX_SESSIONS_PER_PERIOD: dict[str, int] = {"1wk": 7, "1mo": 31}
"""The most daily bars one period can hold (every calendar day a session).
Routers load ``(bars wanted + 1) x this`` daily rows so a limit counted in
output bars is always filled."""

MIXED = "mixed"


class DailyBar(Protocol):
    @property
    def ts(self) -> datetime: ...
    @property
    def open(self) -> Decimal: ...
    @property
    def high(self) -> Decimal: ...
    @property
    def low(self) -> Decimal: ...
    @property
    def close(self) -> Decimal: ...
    @property
    def volume(self) -> int: ...
    @property
    def source(self) -> str | None: ...
    @property
    def adjustment_semantics(self) -> str: ...


@dataclass(frozen=True)
class ResampledBar:
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    sessions: int
    partial: bool
    source: str | None
    adjustment_semantics: str | None


def bar_date(ts: datetime, venue: str) -> date:
    """A daily bar's venue date: the naive label's date, or an aware stamp's
    date in the venue's time zone."""
    if ts.tzinfo is not None and ts.utcoffset() is not None:
        return ts.astimezone(venue_zone(venue)).date()
    return ts.date()


def period_start(day: date, interval: str) -> date:
    """Monday of ``day``'s ISO week, or the first of its month."""
    if interval == "1wk":
        return day - timedelta(days=day.weekday())
    if interval == "1mo":
        return day.replace(day=1)
    raise ValueError(f"cannot resample to {interval!r}")


def period_end(day: date, interval: str) -> date:
    """Sunday of ``day``'s ISO week, or the last day of its month."""
    start = period_start(day, interval)
    if interval == "1wk":
        return start + timedelta(days=6)
    next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return next_month - timedelta(days=1)


def last_session_in_period(day: date, interval: str, venue: str) -> date | None:
    """The venue calendar's last session in ``day``'s period, if it has one."""
    start = period_start(day, interval)
    candidate = period_end(day, interval)
    while candidate >= start:
        if is_session(candidate, venue):
            return candidate
        candidate -= timedelta(days=1)
    return None


def _complete_at(day: date, venue: str) -> datetime:
    if is_session(day, venue):
        return session_complete_at(day, venue)
    # A bar stored on a day the calendar does not list: complete when the
    # venue's day is over.
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=venue_zone(venue))


def _one(values: set[str | None]) -> str | None:
    if len(values) == 1:
        return next(iter(values))
    return MIXED if values else None


def is_partial(last_stored: date, interval: str, venue: str, now: datetime) -> bool:
    """Whether a period whose newest stored session is ``last_stored`` is not
    over at the venue at ``now``."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    final = last_session_in_period(last_stored, interval, venue)
    if final is not None and final > last_stored:
        return True
    return _complete_at(last_stored, venue) > now.astimezone(UTC)


def resample(
    bars: Sequence[DailyBar],
    interval: str,
    *,
    venue: str,
    now: datetime,
) -> list[ResampledBar]:
    """Daily ``bars`` (oldest first, one venue) as ``interval`` bars, oldest first."""
    if interval not in RESAMPLED_INTERVALS:
        raise ValueError(f"cannot resample to {interval!r}")
    groups: list[list[DailyBar]] = []
    keys: list[date] = []
    for bar in sorted(bars, key=lambda b: bar_date(b.ts, venue)):
        key = period_start(bar_date(bar.ts, venue), interval)
        if keys and keys[-1] == key:
            groups[-1].append(bar)
        else:
            keys.append(key)
            groups.append([bar])

    out: list[ResampledBar] = []
    for index, group in enumerate(groups):
        last = group[-1]
        newest = index == len(groups) - 1
        out.append(
            ResampledBar(
                ts=last.ts,
                open=group[0].open,
                high=max(b.high for b in group),
                low=min(b.low for b in group),
                close=last.close,
                volume=sum(int(b.volume) for b in group),
                sessions=len(group),
                partial=newest and is_partial(bar_date(last.ts, venue), interval, venue, now),
                source=_one({b.source for b in group}),
                adjustment_semantics=_one({str(b.adjustment_semantics) for b in group}),
            )
        )
    return out


__all__ = [
    "MAX_SESSIONS_PER_PERIOD",
    "MIXED",
    "RESAMPLED_INTERVALS",
    "ResampledBar",
    "bar_date",
    "is_partial",
    "last_session_in_period",
    "period_end",
    "period_start",
    "resample",
]
