"""Weekly and monthly frames for the Rule DSL, and the alignment rule (A2.1).

Periods are A1.4a's (``services/bars/resample.py``): the ISO week and the
calendar month by the bar's venue date, open first, high/low extremes,
close last, volume summed. ``tests/test_dsl_timeframes.py`` holds the OHLCV
equal to ``resample`` for every closed period.

**When a period is closed.** At daily bar ``d`` in period ``P``, ``P`` is
closed when ``d`` is on or after the venue calendar's last session in ``P``
(a Friday, or the Thursday before a Friday holiday). Every earlier period is
closed. A period's bar holds its daily bars up to that last session (a bar
stored on a later non-session day of the same period is left out), so its
values never change once it is closed.

**Alignment.** A ``weekly.`` (``monthly.``) value on daily bar ``d`` is the
value on the last *closed* period at or before ``d``: the current period on
its last session, otherwise the one before. The partial period still
running is never used. Both rules read only bars up to ``d``, so the same
answer comes from the whole history and from the history cut at ``d``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache

import numpy as np
import pandas as pd

from stockviz.services.bars.resample import last_session_in_period


@lru_cache(maxsize=65536)
def _final_session(start: date, interval: str, venue: str) -> date | None:
    return last_session_in_period(start, interval, venue)


@dataclass(frozen=True)
class Resampled:
    frame: pd.DataFrame
    """One row per period with content, oldest first, indexed by the period's
    last stored session date."""
    align: np.ndarray
    """Per daily row: the row of ``frame`` aligned to it, or -1."""


def _period_starts(days: np.ndarray, interval: str) -> np.ndarray:
    if interval == "1wk":
        weekday = (days.astype(np.int64) + 3) % 7  # 1970-01-01 was a Thursday
        return days - weekday.astype("timedelta64[D]")
    if interval == "1mo":
        return days.astype("datetime64[M]").astype("datetime64[D]")
    raise ValueError(f"cannot resample to {interval!r}")


def resample_frame(daily: pd.DataFrame, interval: str, venue: str) -> Resampled:
    """``daily`` (DatetimeIndex of venue dates, oldest first) as ``interval``
    bars, and the daily-to-period alignment."""
    days = daily.index.to_numpy(dtype="datetime64[D]")
    starts = _period_starts(days, interval)
    unique = np.unique(starts)
    final_of = {
        k: _final_session(k.item(), interval, venue)
        for k in unique  # pyright: ignore[reportArgumentType]
    }
    finals = np.array(
        [np.datetime64(final_of[k], "D") if final_of[k] else np.datetime64("NaT") for k in unique],
        dtype="datetime64[D]",
    )
    final = finals[np.searchsorted(unique, starts)] if len(days) else finals
    has_final = ~np.isnat(final)
    content = ~has_final | (days <= final)

    rows = np.flatnonzero(content)
    keys = starts[rows]
    if len(rows):
        first = np.concatenate(([0], np.flatnonzero(keys[1:] != keys[:-1]) + 1))
        last = np.concatenate((first[1:] - 1, [len(rows) - 1]))
        cols: dict[str, np.ndarray] = {}
        values = {c: daily[c].to_numpy(dtype=float)[rows] for c in daily.columns}
        if "open" in values:
            cols["open"] = values["open"][first]
            cols["high"] = np.maximum.reduceat(values["high"], first)
            cols["low"] = np.minimum.reduceat(values["low"], first)
            cols["close"] = values["close"][last]
            cols["volume"] = np.add.reduceat(values["volume"], first)
        if "bench" in values:
            cols["bench"] = values["bench"][last]
        frame = pd.DataFrame(cols, index=pd.DatetimeIndex(days[rows][last]))
        period_keys = keys[first]
    else:
        frame = pd.DataFrame(columns=["open", "high", "low", "close", "volume"], dtype=float)
        period_keys = np.array([], dtype="datetime64[D]")

    pos = np.searchsorted(period_keys, starts, side="left")
    if len(period_keys):
        has = (pos < len(period_keys)) & (
            period_keys[np.minimum(pos, len(period_keys) - 1)] == starts
        )
    else:
        has = np.zeros(len(days), dtype=bool)
    closed = has & has_final & (days >= final)
    align = np.where(closed, pos, pos - 1).astype(int)
    return Resampled(frame, align)


__all__ = ["Resampled", "resample_frame"]
