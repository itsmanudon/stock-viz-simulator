"""Provider-neutral semantics for canonical US market-data bars."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import Protocol
from zoneinfo import ZoneInfo

from stockviz.services.markets.calendar import NEW_YORK_VENUE
from stockviz.services.markets.calendar import (
    latest_completed_session as calendar_latest_completed_session,
)


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


def latest_completed_session(now: datetime, venue: str = NEW_YORK_VENUE) -> date:
    """The newest session of ``venue`` whose daily bar is complete at ``now``.

    Delegates to the exchange calendar (``services/markets/calendar.py``,
    Phase 4 batch 4.1): a session is complete 45 minutes after the venue's
    close, and weekends and the venue's holidays are skipped. The default
    venue is New York, which dates the nightly jobs: the 22:00 UTC cron stores
    and settles the day's own session (audit MD-3), and on a US holiday it
    asks for the session before instead of a date with no bar. Before 4.1 this
    was a weekday rule at 16:45 New York for every market.
    """
    return calendar_latest_completed_session(now, venue)


def completed_daily_bars[TBar: DailyBarLike](
    bars: Sequence[TBar],
    *,
    now: datetime | None = None,
    venue: str = NEW_YORK_VENUE,
) -> list[TBar]:
    """Keep only daily bars whose session is complete at ``now``.

    A daily bar is complete once its date is on or before ``venue``'s
    :func:`latest_completed_session` (audit MD-3; the old rule waited for New
    York midnight, so the nightly job always stored the previous session).
    Pass the bars' venue: a London bar is complete hours before a New York
    one, and a US holiday must not hold it back. Non-daily bars pass through
    unchanged.
    """

    newest_complete = latest_completed_session(now or datetime.now(UTC), venue)
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
