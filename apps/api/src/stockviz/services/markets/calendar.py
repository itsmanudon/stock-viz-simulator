"""Exchange calendars: which sessions a venue holds and when they are complete.

Phase 4, batch 4.1 (workspace ``docs/phase-4-design-note.md``). Before this,
every market used one rule: a weekday's bar is complete once New York passes
16:45, with no holidays. The rules here come from the open-source
``exchange_calendars`` package, imported only in this module.

Until instruments carry a venue (Phase 4 identity work), the venue comes from
the Yahoo ticker suffix (:func:`venue_for_ticker`). NSE has no calendar in the
package; BSE (``XBOM``) keeps the same holidays and stands in for it.

A calendar covers a fixed range (about 20 years back to a year ahead, and
``XBOM`` only to the end of 2026). Outside it, and for an unknown venue, the
functions fall back to the old weekday rule rather than fail, and log once.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

NEW_YORK_VENUE = "XNYS"
"""Default venue: US listings, and the session the nightly jobs are dated by."""

VENUE_BY_SUFFIX: dict[str, str] = {
    ".NS": "XBOM",  # NSE: no calendar in the package; BSE shares its holidays
    ".BO": "XBOM",
    ".L": "XLON",
    ".DE": "XETR",
    ".TO": "XTSE",
    ".T": "XTKS",
}

COMPLETE_AFTER_CLOSE = timedelta(minutes=45)
"""A session's daily bar counts as complete this long after the venue closes,
which leaves the provider time to publish it (the old rule's 16:45 is the
New York close plus the same margin)."""

_FALLBACK_CLOSE = time(16, 45)
_FALLBACK_TZ = ZoneInfo("America/New_York")
_LOOKBACK_DAYS = 14
_warned: set[str] = set()


INDEX_VENUES: dict[str, str] = {
    "^GSPC": "XNYS",  # S&P 500 (Phase 7.4 benchmark)
    "^NSEI": "XBOM",  # NIFTY 50: NSE hours and holidays
}
"""Benchmarks have no suffix; they are dated by their market's sessions."""


def venue_for_ticker(ticker: str) -> str:
    """The MIC a Yahoo-style ticker trades on; US listings have no suffix."""
    upper = ticker.upper()
    if upper in INDEX_VENUES:
        return INDEX_VENUES[upper]
    for suffix, venue in VENUE_BY_SUFFIX.items():
        if upper.endswith(suffix):
            return venue
    return NEW_YORK_VENUE


@lru_cache(maxsize=16)
def _calendar(venue: str) -> Any | None:
    import exchange_calendars as xcals

    try:
        return xcals.get_calendar(venue)
    except Exception:  # unknown venue name
        _warn_once(venue, "no calendar for %s; using weekdays", venue)
        return None


def venue_zone(venue: str) -> ZoneInfo:
    """The time zone ``venue`` trades in (New York when it has no calendar)."""
    calendar = _calendar(venue)
    return ZoneInfo(str(calendar.tz)) if calendar is not None else _FALLBACK_TZ


def _warn_once(key: str, message: str, *args: object) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning(message, *args)


def _in_range(calendar: Any, day: date) -> bool:
    return calendar.first_session.date() <= day <= calendar.last_session.date()


def is_session(day: date, venue: str = NEW_YORK_VENUE) -> bool:
    """Whether ``venue`` trades on ``day`` (weekdays outside the calendar)."""
    calendar = _calendar(venue)
    if calendar is None or not _in_range(calendar, day):
        if calendar is not None:
            _warn_once(
                f"{venue}:range", "%s calendar does not cover %s; using weekdays", venue, day
            )
        return day.weekday() < 5
    return bool(calendar.is_session(day.isoformat()))


def session_on_or_before(day: date, venue: str = NEW_YORK_VENUE) -> date:
    """The last session of ``venue`` on or before ``day``."""
    for back in range(_LOOKBACK_DAYS):
        candidate = day - timedelta(days=back)
        if is_session(candidate, venue):
            return candidate
    return day  # no session in two weeks: a calendar gap, not a market


def session_complete_at(day: date, venue: str = NEW_YORK_VENUE) -> datetime:
    """When ``day``'s daily bar on ``venue`` counts as complete (aware, UTC-comparable)."""
    return _session_complete_at(day, venue)


def _session_complete_at(day: date, venue: str) -> datetime:
    calendar = _calendar(venue)
    if calendar is None or not _in_range(calendar, day):
        return datetime.combine(day, _FALLBACK_CLOSE, tzinfo=_FALLBACK_TZ)
    close = calendar.session_close(day.isoformat()).to_pydatetime()
    return close + COMPLETE_AFTER_CLOSE


def previous_session(day: date, venue: str = NEW_YORK_VENUE) -> date:
    """The session of ``venue`` before ``day`` (weekdays outside the calendar)."""
    for back in range(1, _LOOKBACK_DAYS):
        candidate = day - timedelta(days=back)
        if is_session(candidate, venue):
            return candidate
    return day - timedelta(days=1)


def latest_completed_session(now: datetime, venue: str = NEW_YORK_VENUE) -> date:
    """The newest session of ``venue`` whose daily bar is complete at ``now``.

    A session is complete :data:`COMPLETE_AFTER_CLOSE` after the venue's close
    that day (early closes included). Weekends and the venue's holidays are
    skipped, so on a market holiday the answer is the session before.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    calendar = _calendar(venue)
    zone = ZoneInfo(str(calendar.tz)) if calendar is not None else _FALLBACK_TZ
    local_day = now.astimezone(zone).date()
    for back in range(_LOOKBACK_DAYS):
        day = local_day - timedelta(days=back)
        if is_session(day, venue) and _session_complete_at(day, venue) <= now.astimezone(UTC):
            return day
    return local_day - timedelta(days=1)
