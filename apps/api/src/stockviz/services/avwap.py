"""Anchored VWAP (A3.3, M2.5): pure, on daily bars.

From the anchor bar (the first daily bar dated on or after the anchor date)
forward, each bar's AVWAP is

    sum(typical price x volume) / sum(volume),  typical price = (H + L + C) / 3,

summed over the bars from the anchor to that bar, inclusive. A bar only ever
reads bars at or before it, so the value on bar ``t`` never changes when a
later bar arrives (the Rule DSL's ``avwap()`` relies on that).

**Bands** are the volume-weighted standard deviation of the typical price
over the same bars, ``sqrt(sum(v x tp^2) / sum(v) - vwap^2)`` (clamped at 0
against rounding), drawn at +-1 and +-2 deviations.

**Precision.** float64 (numpy), summed in bar order with ``cumsum``; the API
rounds to 4 decimals. Adjusted prices and volumes, as every indicator.
Bars before the anchor, and bars while the summed volume is still 0, have no
value (NaN here, null in the API).

**Weekly and monthly.** The AVWAP is always computed from **daily** bars.
A weekly or monthly chart shows it sampled at each period's bar time, which
is the period's last stored session (``services/bars/resample.py``): the
honest definition, since a VWAP of resampled bars would weight a whole week
by one typical price.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

NAN = float("nan")
API_DECIMALS = 4


@dataclass(frozen=True)
class AvwapSeries:
    """One value per daily bar given (NaN before the anchor)."""

    anchor_index: int | None
    """Row of the anchor bar; None when no bar is on or after the anchor."""
    vwap: np.ndarray
    sd: np.ndarray

    def band(self, k: float) -> np.ndarray:
        return self.vwap + k * self.sd


def anchor_index(dates: list[date] | np.ndarray, anchor: date) -> int | None:
    """Row of the first bar dated on or after ``anchor`` (dates oldest first)."""
    days = np.asarray(dates, dtype="datetime64[D]")
    i = int(np.searchsorted(days, np.datetime64(anchor, "D"), side="left"))
    return i if i < len(days) else None


def compute(
    dates: list[date] | np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    anchor: date,
) -> AvwapSeries:
    """The anchored VWAP and its deviation on every daily bar (oldest first)."""
    n = len(close)
    vwap = np.full(n, NAN)
    sd = np.full(n, NAN)
    start = anchor_index(dates, anchor)
    if start is None:
        return AvwapSeries(None, vwap, sd)
    h = np.asarray(high[start:], dtype=float)
    lo = np.asarray(low[start:], dtype=float)
    c = np.asarray(close[start:], dtype=float)
    v = np.asarray(volume[start:], dtype=float)
    tp = (h + lo + c) / 3.0
    # A bar with a missing price or volume adds nothing (never a NaN that
    # would poison every later bar).
    bad = ~(np.isfinite(tp) & np.isfinite(v))
    tp = np.where(bad, 0.0, tp)
    v = np.where(bad | (v < 0), 0.0, v)
    cum_v = np.cumsum(v)
    cum_pv = np.cumsum(tp * v)
    cum_p2v = np.cumsum(tp * tp * v)
    with np.errstate(divide="ignore", invalid="ignore"):
        mean = cum_pv / cum_v
        var = cum_p2v / cum_v - mean * mean
    ok = cum_v > 0
    vwap[start:] = np.where(ok, mean, NAN)
    sd[start:] = np.where(ok, np.sqrt(np.maximum(var, 0.0)), NAN)
    return AvwapSeries(start, vwap, sd)


def sample_last_of_period(period_keys: list, values: np.ndarray) -> list[tuple[int, float]]:
    """(row, value) of each period's last daily row, for weekly/monthly charts.

    ``period_keys`` gives each daily row's period (equal keys are adjacent,
    oldest first)."""
    out: list[tuple[int, float]] = []
    for i, key in enumerate(period_keys):
        if i + 1 == len(period_keys) or period_keys[i + 1] != key:
            out.append((i, float(values[i])))
    return out


__all__ = ["API_DECIMALS", "AvwapSeries", "anchor_index", "compute", "sample_last_of_period"]
