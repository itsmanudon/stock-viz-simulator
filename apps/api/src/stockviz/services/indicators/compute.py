"""Pandas-backed indicator computations.

All four indicators here are stateless and unit-tested against the canonical
definitions. Wilder's smoothing for RSI (the version that matches
TradingView / yfinance), 12/26/9 default MACD. Outputs are floats — the
caller is responsible for rounding for display.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import cast

import pandas as pd


@dataclass(frozen=True, slots=True)
class IndicatorPoint:
    ts: datetime
    value: float


def _close_series(bars: list[tuple[datetime, Decimal]]) -> pd.Series:
    if not bars:
        return pd.Series([], dtype="float64")
    index = pd.DatetimeIndex([b[0] for b in bars])
    return pd.Series([float(b[1]) for b in bars], index=index, dtype="float64")


def _coerce_ts(raw: object) -> datetime:
    """``pd.Timestamp -> datetime`` for the wire format. Indexes always hand back Hashable; we know it's a Timestamp."""
    if isinstance(raw, pd.Timestamp):
        return raw.to_pydatetime()
    if isinstance(raw, datetime):
        return raw
    raise TypeError(f"Unexpected index type: {type(raw)!r}")


def _to_points(series: pd.Series) -> list[IndicatorPoint]:
    """Drop NaNs and convert to the wire representation."""
    cleaned = series.dropna()
    out: list[IndicatorPoint] = []
    for raw_ts, value in cleaned.items():
        out.append(IndicatorPoint(ts=_coerce_ts(raw_ts), value=float(value)))
    return out


def compute_sma(bars: list[tuple[datetime, Decimal]], *, period: int) -> list[IndicatorPoint]:
    """Simple moving average over the close. Drops the first ``period-1`` NaNs."""
    if period <= 0:
        raise ValueError("period must be positive")
    series = _close_series(bars)
    rolled = cast(pd.Series, series.rolling(window=period, min_periods=period).mean())
    return _to_points(rolled)


def compute_ema(bars: list[tuple[datetime, Decimal]], *, period: int) -> list[IndicatorPoint]:
    """Exponential moving average using pandas' adjust=False (Wilder-style start)."""
    if period <= 0:
        raise ValueError("period must be positive")
    series = _close_series(bars)
    ema = cast(pd.Series, series.ewm(span=period, adjust=False, min_periods=period).mean())
    return _to_points(ema)


def compute_rsi(bars: list[tuple[datetime, Decimal]], *, period: int = 14) -> list[IndicatorPoint]:
    """RSI with Wilder's smoothing (alpha = 1/period).

    Output range is [0, 100]. Returns no points until ``period`` deltas have
    been observed, matching the convention most charting libraries use.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    series = _close_series(bars)
    if len(series) < period + 1:
        return []

    delta = series.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)

    # Wilder's smoothing: alpha = 1/period, equivalent to ``com = period - 1``.
    avg_gain = cast(
        pd.Series, gains.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    )
    avg_loss = cast(
        pd.Series, losses.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    )

    # Avoid divide-by-zero on a flat / monotonically increasing series.
    rs = avg_gain / avg_loss.replace(0.0, pd.NA)
    rsi = cast(pd.Series, 100.0 - (100.0 / (1.0 + rs)))
    # When avg_loss == 0 across the window, RSI is 100 by convention.
    rsi = rsi.where(~avg_loss.eq(0.0), 100.0)
    return _to_points(rsi)


@dataclass(frozen=True, slots=True)
class MACDPoint:
    ts: datetime
    macd: float
    signal: float
    histogram: float


def compute_macd(
    bars: list[tuple[datetime, Decimal]],
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> list[MACDPoint]:
    """MACD (12, 26, 9 by default). Returns macd, signal, histogram per bar."""
    if min(fast, slow, signal) <= 0:
        raise ValueError("MACD periods must be positive")
    if fast >= slow:
        raise ValueError("fast period must be less than slow period")
    series = _close_series(bars)
    if len(series) < slow + signal:
        return []

    ema_fast = cast(pd.Series, series.ewm(span=fast, adjust=False, min_periods=fast).mean())
    ema_slow = cast(pd.Series, series.ewm(span=slow, adjust=False, min_periods=slow).mean())
    macd_line = cast(pd.Series, ema_fast - ema_slow)
    signal_line = cast(
        pd.Series, macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    )
    histogram = cast(pd.Series, macd_line - signal_line)

    out: list[MACDPoint] = []
    for raw_ts, hist_val in histogram.dropna().items():
        out.append(
            MACDPoint(
                ts=_coerce_ts(raw_ts),
                macd=float(macd_line.loc[raw_ts]),
                signal=float(signal_line.loc[raw_ts]),
                histogram=float(hist_val),
            )
        )
    return out
