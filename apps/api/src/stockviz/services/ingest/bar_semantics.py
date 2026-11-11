"""Provider-neutral semantics for canonical US market-data bars."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Protocol
from zoneinfo import ZoneInfo


class AdjustmentSemantics(StrEnum):
    """Transformations represented by a bar's OHLC and volume values."""

    UNADJUSTED = "unadjusted"
    SPLIT_ADJUSTED = "split_adjusted"
    SPLIT_DIVIDEND_ADJUSTED = "split_dividend_adjusted"


class SessionScope(StrEnum):
    """Trading activity included in a provider's daily aggregate."""

    REGULAR = "regular"
    PROVIDER_DAILY = "provider_daily"


NEW_YORK = ZoneInfo("America/New_York")


class DailyBarLike(Protocol):
    @property
    def ts(self) -> datetime: ...

    @property
    def interval(self) -> str: ...


def session_label(value: date) -> datetime:
    """Return the canonical naive-midnight label for a session date."""

    return datetime.combine(value, time.min)


def new_york_session_date(value: datetime) -> date:
    """Map an aware observation instant to its New York calendar date."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(NEW_YORK).date()


SESSION_COMPLETE_AT = time(16, 45)
"""New York time after which a weekday's daily bar counts as complete.

45 minutes after the US close. Every exchange StockViz carries (New York,
Toronto, London, Frankfurt, NSE, Tokyo) has closed by then.
"""


def latest_completed_session(now: datetime) -> date:
    """The newest weekday session whose daily bar is complete at ``now``.

    Today once New York has passed :data:`SESSION_COMPLETE_AT` on a weekday,
    otherwise the previous weekday. The 22:00 UTC cron (17:00 or 18:00 in
    New York) therefore stores the day's own session, not the one before
    (audit MD-3), and settlement asks for that same session. After a market
    holiday the newest bar predates this date, so orders wait a night rather
    than fill against an older close.
    """
    local = now.astimezone(NEW_YORK)
    day = local.date()
    if day.weekday() >= 5 or local.time() < SESSION_COMPLETE_AT:
        day -= timedelta(days=1)
    while day.weekday() >= 5:  # Saturday, Sunday
        day -= timedelta(days=1)
    return day


def completed_daily_bars[TBar: DailyBarLike](
    bars: Sequence[TBar],
    *,
    now: datetime | None = None,
) -> list[TBar]:
    """Keep only daily bars whose session is complete at ``now``.

    A daily bar is complete once its New York date is on or before
    :func:`latest_completed_session`: today after 16:45 New York time on a
    weekday, otherwise the day before (audit MD-3; the old rule waited for New
    York midnight, so the nightly job always stored the previous session).
    Non-daily bars pass through unchanged.
    """

    newest_complete = latest_completed_session(now or datetime.now(UTC))
    completed: list[TBar] = []
    for bar in bars:
        if bar.interval != "1d":
            completed.append(bar)
            continue
        bar_date = (
            new_york_session_date(bar.ts)
            if bar.ts.tzinfo is not None and bar.ts.utcoffset() is not None
            else bar.ts.date()
        )
        if bar_date <= newest_complete:
            completed.append(bar)
    return completed
