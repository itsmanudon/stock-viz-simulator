"""Provider-neutral semantics for canonical US market-data bars."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time
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
    ts: datetime
    interval: str


def session_label(value: date) -> datetime:
    """Return the canonical naive-midnight label for a session date."""

    return datetime.combine(value, time.min)


def new_york_session_date(value: datetime) -> date:
    """Map an aware observation instant to its New York calendar date."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(NEW_YORK).date()


def completed_daily_bars[TBar: DailyBarLike](
    bars: Sequence[TBar],
    *,
    now: datetime | None = None,
) -> list[TBar]:
    """Remove daily bars for the current New York calendar date.

    A future exchange calendar can make this less conservative. Until then,
    StockViz persists a daily session only after New York has advanced to the
    next calendar date. Non-daily bars pass through unchanged.
    """

    current_session_date = new_york_session_date(now or datetime.now(UTC))
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
        if bar_date < current_session_date:
            completed.append(bar)
    return completed
