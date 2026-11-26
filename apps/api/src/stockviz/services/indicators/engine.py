"""Indicator engine: OHLCV in, a registry of indicators with lookbacks (Phase 6.1).

Every indicator is registered with its parameters, outputs, the chart pane it
belongs on, and its **lookback**: how many bars before the first shown value
it needs so that value does not depend on where the data starts. The API
loads that many extra bars before the requested window and returns values
inside the window only (audit RS-1), so RSI on a one-month chart equals RSI
on a one-year chart for the same day.

- Windowed indicators (SMA, Bollinger, Donchian, ...) need ``n - 1`` bars.
- Recursive ones (EMA, Wilder's RSI/ATR/ADX, MACD) remember every earlier
  bar with a decaying weight. Their lookback is chosen so the starting point
  contributes under 0.01% (EMA: 5 x (n + 1); Wilder: 10 x n).
- Cumulative ones (OBV, accumulation/distribution) have no true start: their
  level starts at 0 on the first bar loaded. Read their shape, not the number
  (``anchored`` in the metadata says so).

Definitions follow the usual references (Wilder for RSI, ATR and ADX; Lane
for the Stochastic; Lambert for CCI; Bollinger; Chande-style Supertrend).
``tests/test_indicator_engine.py`` checks each against a plain loop written
from its definition, and small cases by hand.
"""

# pandas-stubs type rolling/arithmetic results as "DataFrame | Series"; every
# value here is a Series by construction, and the tests check each output.
# pyright: reportArgumentType=false, reportReturnType=false, reportAttributeAccessIssue=false, reportOperatorIssue=false, reportCallIssue=false

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from math import sqrt
from typing import Literal

import numpy as np
import pandas as pd

Pane = Literal["price", "separate"]
Frame = pd.DataFrame  # columns: open, high, low, close, volume; DatetimeIndex


def _wilder(series: pd.Series, n: int) -> pd.Series:
    """Wilder's smoothing: first value is the mean of n, then (prev x (n-1) + x) / n."""
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    valid = ~np.isnan(values)
    idx = np.flatnonzero(valid)
    if len(idx) < n:
        return pd.Series(out, index=series.index)
    start = idx[n - 1]
    out[start] = values[idx[:n]].mean()
    for i in range(start + 1, len(values)):
        out[i] = (out[i - 1] * (n - 1) + values[i]) / n
    return pd.Series(out, index=series.index)


def _ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False, min_periods=n).mean()


def _true_range(f: Frame) -> pd.Series:
    prev = f["close"].shift(1)
    return (
        pd.concat([f["high"] - f["low"], (f["high"] - prev).abs(), (f["low"] - prev).abs()], axis=1)
        .max(axis=1, skipna=False)
        .fillna(f["high"] - f["low"])
    )


def _typical(f: Frame) -> pd.Series:
    return (f["high"] + f["low"] + f["close"]) / 3


# --- indicators -------------------------------------------------------------


def sma(f: Frame, n: int) -> dict[str, pd.Series]:
    return {"value": f["close"].rolling(n, min_periods=n).mean()}


def ema(f: Frame, n: int) -> dict[str, pd.Series]:
    return {"value": _ema(f["close"], n)}


def wma(f: Frame, n: int) -> dict[str, pd.Series]:
    weights = np.arange(1, n + 1, dtype=float)
    return {
        "value": f["close"]
        .rolling(n, min_periods=n)
        .apply(lambda x: float(np.dot(x, weights) / weights.sum()), raw=True)
    }


def vwap(f: Frame, n: int) -> dict[str, pd.Series]:
    """Rolling VWAP over n bars of typical price (daily bars have no intraday anchor)."""
    pv = (_typical(f) * f["volume"]).rolling(n, min_periods=n).sum()
    vol = f["volume"].rolling(n, min_periods=n).sum()
    return {"value": pv / vol.replace(0, np.nan)}


def rsi(f: Frame, n: int) -> dict[str, pd.Series]:
    delta = f["close"].diff()
    gain = _wilder(delta.clip(lower=0), n)
    loss = _wilder((-delta).clip(lower=0), n)
    rs = gain / loss.replace(0, np.nan)
    value = 100 - 100 / (1 + rs)
    return {"value": value.where(~(loss == 0) | gain.isna(), 100.0)}


def macd(f: Frame, fast: int, slow: int, signal: int) -> dict[str, pd.Series]:
    line = _ema(f["close"], fast) - _ema(f["close"], slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return {"macd": line, "signal": sig, "histogram": line - sig}


def stoch(f: Frame, k: int, d: int) -> dict[str, pd.Series]:
    low = f["low"].rolling(k, min_periods=k).min()
    high = f["high"].rolling(k, min_periods=k).max()
    pct_k = 100 * (f["close"] - low) / (high - low).replace(0, np.nan)
    return {"k": pct_k, "d": pct_k.rolling(d, min_periods=d).mean()}


def cci(f: Frame, n: int) -> dict[str, pd.Series]:
    tp = _typical(f)
    mean = tp.rolling(n, min_periods=n).mean()
    mad = tp.rolling(n, min_periods=n).apply(
        lambda x: float(np.mean(np.abs(x - x.mean()))), raw=True
    )
    return {"value": (tp - mean) / (0.015 * mad.replace(0, np.nan))}


def roc(f: Frame, n: int) -> dict[str, pd.Series]:
    return {"value": 100 * (f["close"] / f["close"].shift(n) - 1)}


def willr(f: Frame, n: int) -> dict[str, pd.Series]:
    high = f["high"].rolling(n, min_periods=n).max()
    low = f["low"].rolling(n, min_periods=n).min()
    return {"value": -100 * (high - f["close"]) / (high - low).replace(0, np.nan)}


def bb(f: Frame, n: int, k: float) -> dict[str, pd.Series]:
    mid = f["close"].rolling(n, min_periods=n).mean()
    sd = f["close"].rolling(n, min_periods=n).std(ddof=0)
    return {"upper": mid + k * sd, "middle": mid, "lower": mid - k * sd}


def atr(f: Frame, n: int) -> dict[str, pd.Series]:
    return {"value": _wilder(_true_range(f), n)}


def hv(f: Frame, n: int) -> dict[str, pd.Series]:
    """Annualised historical volatility of daily log returns, in percent (252 days)."""
    log_ret = np.log(f["close"] / f["close"].shift(1))
    return {"value": log_ret.rolling(n, min_periods=n).std(ddof=1) * sqrt(252) * 100}


def donchian(f: Frame, n: int) -> dict[str, pd.Series]:
    upper = f["high"].rolling(n, min_periods=n).max()
    lower = f["low"].rolling(n, min_periods=n).min()
    return {"upper": upper, "middle": (upper + lower) / 2, "lower": lower}


def keltner(f: Frame, n: int, k: float, atr_n: int) -> dict[str, pd.Series]:
    mid = _ema(f["close"], n)
    band = k * _wilder(_true_range(f), atr_n)
    return {"upper": mid + band, "middle": mid, "lower": mid - band}


def obv(f: Frame) -> dict[str, pd.Series]:
    direction = np.sign(f["close"].diff()).fillna(0)
    return {"value": (direction * f["volume"]).cumsum()}


def mfi(f: Frame, n: int) -> dict[str, pd.Series]:
    tp = _typical(f)
    flow = tp * f["volume"]
    up = flow.where(tp > tp.shift(1), 0.0)
    down = flow.where(tp < tp.shift(1), 0.0)
    pos = up.rolling(n, min_periods=n).sum()
    neg = down.rolling(n, min_periods=n).sum()
    value = 100 - 100 / (1 + pos / neg.replace(0, np.nan))
    value = value.where(~((neg == 0) & pos.notna()), 100.0)
    value.iloc[:n] = np.nan  # needs n changes, so n + 1 bars
    return {"value": value}


def ad(f: Frame) -> dict[str, pd.Series]:
    span = (f["high"] - f["low"]).replace(0, np.nan)
    clv = ((f["close"] - f["low"]) - (f["high"] - f["close"])) / span
    return {"value": (clv.fillna(0) * f["volume"]).cumsum()}


def rvol(f: Frame, n: int) -> dict[str, pd.Series]:
    """Today's volume over the average of the previous n days."""
    avg = f["volume"].shift(1).rolling(n, min_periods=n).mean()
    return {"value": f["volume"] / avg.replace(0, np.nan)}


def adx(f: Frame, n: int) -> dict[str, pd.Series]:
    up = f["high"].diff()
    down = -f["low"].diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    plus_dm.iloc[0] = np.nan
    minus_dm.iloc[0] = np.nan
    tr = _true_range(f)
    tr.iloc[0] = np.nan
    tr_n = _wilder(tr, n)
    plus_di = 100 * _wilder(plus_dm, n) / tr_n
    minus_di = 100 * _wilder(minus_dm, n) / tr_n
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return {"adx": _wilder(dx, n), "plus_di": plus_di, "minus_di": minus_di}


def supertrend(f: Frame, n: int, k: float) -> dict[str, pd.Series]:
    """Supertrend on an ATR(n) band of k; direction 1 up, -1 down."""
    hl2 = ((f["high"] + f["low"]) / 2).to_numpy(dtype=float)
    band = k * _wilder(_true_range(f), n).to_numpy(dtype=float)
    close = f["close"].to_numpy(dtype=float)
    size = len(close)
    line = np.full(size, np.nan)
    direction = np.full(size, np.nan)
    upper = lower = np.nan
    for i in range(size):
        if np.isnan(band[i]):
            continue
        basic_up, basic_low = hl2[i] + band[i], hl2[i] - band[i]
        if np.isnan(upper):
            upper, lower, trend = basic_up, basic_low, 1.0
        else:
            upper = basic_up if basic_up < upper or close[i - 1] > upper else upper
            lower = basic_low if basic_low > lower or close[i - 1] < lower else lower
            trend = direction[i - 1]
            if trend == 1 and close[i] < lower:
                trend = -1.0
            elif trend == -1 and close[i] > upper:
                trend = 1.0
        direction[i] = trend
        line[i] = lower if trend == 1 else upper
    index = f.index
    return {"line": pd.Series(line, index=index), "direction": pd.Series(direction, index=index)}


# --- A3.4 (M2.6): the studies added to reach about 45 -----------------------
#
# Each one reads only bars at or before the bar it is written on (no
# look-ahead; the Rule DSL conformance suite checks point mode against vector
# mode for every one), and each has a reference test in
# ``tests/test_indicator_studies.py`` (published worked examples where one
# exists, otherwise a small case worked by hand, said so in the test).


def _wma_series(series: pd.Series, n: int) -> pd.Series:
    weights = np.arange(1, n + 1, dtype=float)
    total = weights.sum()
    return series.rolling(n, min_periods=n).apply(
        lambda x: float(np.dot(x, weights) / total), raw=True
    )


def _mid(f: Frame, n: int) -> pd.Series:
    """Midpoint of the n-bar high and low (Ichimoku's lines)."""
    return (
        f["high"].rolling(n, min_periods=n).max() + f["low"].rolling(n, min_periods=n).min()
    ) / 2


def ichimoku(f: Frame, tenkan: int, kijun: int, senkou: int, shift: int) -> dict[str, pd.Series]:
    """Ichimoku Kinko Hyo (Hosoda). The leading spans are drawn ``shift`` bars
    ahead of the bar they are computed on; here each bar carries the span
    *drawn on it*, computed ``shift`` bars earlier, so nothing on a bar uses a
    later bar (the cloud past the last bar is not drawn, and the lagging span,
    which is today's close drawn ``shift`` bars back, is left out: it would put
    a later close on an earlier bar)."""
    t = _mid(f, tenkan)
    k = _mid(f, kijun)
    return {
        "tenkan": t,
        "kijun": k,
        "senkou_a": ((t + k) / 2).shift(shift),
        "senkou_b": _mid(f, senkou).shift(shift),
    }


def hma(f: Frame, n: int) -> dict[str, pd.Series]:
    """Hull moving average: WMA(2 WMA(n/2) - WMA(n), sqrt n), lengths floored."""
    half, root = max(1, n // 2), max(1, int(sqrt(n)))
    raw = 2 * _wma_series(f["close"], half) - _wma_series(f["close"], n)
    return {"value": _wma_series(raw, root)}


def kama(f: Frame, n: int, fast: int, slow: int) -> dict[str, pd.Series]:
    """Kaufman's adaptive moving average (Kaufman, *Smarter Trading*, 1995),
    seeded with the close on bar n - 1 as StockCharts' worked example does."""
    close = f["close"].to_numpy(dtype=float)
    out = np.full(len(close), np.nan)
    if len(close) < n:
        return {"value": pd.Series(out, index=f.index)}
    fast_sc, slow_sc = 2 / (fast + 1), 2 / (slow + 1)
    step = np.abs(f["close"].diff())
    volatility = step.rolling(n, min_periods=n).sum().to_numpy(dtype=float)
    direction = np.abs(f["close"] - f["close"].shift(n)).to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        er = np.where(volatility > 0, direction / volatility, 0.0)
    sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
    out[n - 1] = close[n - 1]
    prev = close[n - 1]
    for i in range(n, len(close)):
        prev = prev + sc[i] * (close[i] - prev)
        out[i] = prev
    return {"value": pd.Series(out, index=f.index)}


def psar(f: Frame, step: float, maximum: float) -> dict[str, pd.Series]:
    """Wilder's parabolic stop and reverse (*New Concepts*, 1978).

    ``sar`` on a bar is the stop in force during that bar, computed from the
    bars before it; ``direction`` is the trend at the bar's close (1 up, -1
    down), after the reversal check. The first trend is up when the second
    close is at or above the first. Path-dependent: two runs that start on
    different bars agree once they share a trend through a reversal."""
    # Plain floats: this loop runs once per bar in point mode too.
    high, low = f["high"].to_numpy(dtype=float).tolist(), f["low"].to_numpy(dtype=float).tolist()
    close = f["close"].to_numpy(dtype=float).tolist()
    size = len(close)
    sar_out = np.full(size, np.nan)
    direction = np.full(size, np.nan)
    if size < 2:
        index = f.index
        return {
            "sar": pd.Series(sar_out, index=index),
            "direction": pd.Series(direction, index=index),
        }
    long = close[1] >= close[0]
    sar = low[0] if long else high[0]
    ep = high[0] if long else low[0]
    af = step
    for i in range(1, size):
        sar_out[i] = sar
        if long and low[i] < sar:
            long, sar, ep, af = False, ep, low[i], step
        elif not long and high[i] > sar:
            long, sar, ep, af = True, ep, high[i], step
        else:
            if long and high[i] > ep:
                ep, af = high[i], min(af + step, maximum)
            elif not long and low[i] < ep:
                ep, af = low[i], min(af + step, maximum)
            sar = sar + af * (ep - sar)
            sar = min(sar, low[i], low[i - 1]) if long else max(sar, high[i], high[i - 1])
        direction[i] = 1.0 if long else -1.0
    index = f.index
    return {"sar": pd.Series(sar_out, index=index), "direction": pd.Series(direction, index=index)}


def _mf_volume(f: Frame) -> pd.Series:
    span = (f["high"] - f["low"]).replace(0, np.nan)
    clv = ((f["close"] - f["low"]) - (f["high"] - f["close"])) / span
    return clv.fillna(0) * f["volume"]


def cmf(f: Frame, n: int) -> dict[str, pd.Series]:
    """Chaikin money flow: n-bar money-flow volume over n-bar volume."""
    vol = f["volume"].rolling(n, min_periods=n).sum()
    return {"value": _mf_volume(f).rolling(n, min_periods=n).sum() / vol.replace(0, np.nan)}


def chaikin(f: Frame, fast: int, slow: int) -> dict[str, pd.Series]:
    """Chaikin oscillator: EMA(fast) - EMA(slow) of the A/D line. The line's
    starting level cancels in the difference, so this is not anchored."""
    line = _mf_volume(f).cumsum()
    return {"value": _ema(line, fast) - _ema(line, slow)}


def tsi(f: Frame, long: int, short: int, signal: int) -> dict[str, pd.Series]:
    """Blau's true strength index (*Momentum, Direction and Divergence*, 1995)."""
    mo = f["close"].diff()
    num = _ema(_ema(mo, long), short)
    den = _ema(_ema(mo.abs(), long), short)
    value = 100 * num / den.replace(0, np.nan)
    return {"tsi": value, "signal": _ema(value, signal)}


def natr(f: Frame, n: int) -> dict[str, pd.Series]:
    """ATR as a percent of the close (StockCharts' ATRP)."""
    return {"value": 100 * _wilder(_true_range(f), n) / f["close"].replace(0, np.nan)}


_PIVOT_PERIODS = {2: "W", 3: "M", 4: "Y"}


def pivots(f: Frame, basis: int) -> dict[str, pd.Series]:
    """Classic floor pivots from the prior period's high, low and close.

    ``basis`` 1 is the prior bar, 2 the prior calendar week, 3 the prior month
    (StockCharts' choice for daily charts), 4 the prior year. A period's
    figures apply from the first bar of the next period, so a bar never sees
    its own period. The first period held may be partial, so the period after
    it gets no pivots."""
    high, low, close = f["high"], f["low"], f["close"]
    if basis == 1:
        h, lo, c = high.shift(1), low.shift(1), close.shift(1)
    else:
        if f.empty:
            h = lo = c = close.copy()
        else:
            key = pd.Series(f.index.to_period(_PIVOT_PERIODS[basis]), index=f.index)
            grouped = pd.DataFrame({"h": high, "l": low, "c": close, "k": key}).groupby(
                "k", sort=True
            )
            per = pd.DataFrame(
                {"h": grouped["h"].max(), "l": grouped["l"].min(), "c": grouped["c"].last()}
            )
            prior = per.shift(1)
            prior.iloc[:2] = np.nan  # the first period may be partial
            h = key.map(prior["h"]).astype(float)
            lo = key.map(prior["l"]).astype(float)
            c = key.map(prior["c"]).astype(float)
    pp = (h + lo + c) / 3
    return {
        "pp": pp,
        "r1": 2 * pp - lo,
        "s1": 2 * pp - h,
        "r2": pp + (h - lo),
        "s2": pp - (h - lo),
    }


def rmv(f: Frame, n: int, lookback: int) -> dict[str, pd.Series]:
    """RMV tightness (StockViz's definition): the last n bars' high-low range
    as a percent of the close, placed between its lowest (0) and highest
    (100) value over ``lookback`` bars. Near 0: the tightest range in that
    time. After Deepvue's RMV and Minervini's volatility contraction; Deepvue
    does not publish its formula, so this is not theirs."""
    span = f["high"].rolling(n, min_periods=n).max() - f["low"].rolling(n, min_periods=n).min()
    rng = 100 * span / f["close"].replace(0, np.nan)
    lo = rng.rolling(lookback, min_periods=lookback).min()
    hi = rng.rolling(lookback, min_periods=lookback).max()
    width = (hi - lo).replace(0, np.nan)
    value = 100 * (rng - lo) / width
    return {"value": value.where(~((hi - lo) == 0), 0.0).where(lo.notna())}


def rsline(f: Frame) -> dict[str, pd.Series]:
    """Relative-strength line (price relative): the close over the venue
    index's close (``^GSPC`` for US listings, ``^NSEI`` for Indian ones),
    the index forward-filled at most 5 bars. Missing without the index."""
    if "bench" not in f:
        return {"value": pd.Series(np.nan, index=f.index, dtype=float)}
    return {"value": f["close"] / f["bench"].replace(0, np.nan)}


def dema(f: Frame, n: int) -> dict[str, pd.Series]:
    """Mulloy's double EMA (*Stocks & Commodities*, Feb 1994): 2 E - E(E)."""
    e1 = _ema(f["close"], n)
    return {"value": 2 * e1 - _ema(e1, n)}


def tema(f: Frame, n: int) -> dict[str, pd.Series]:
    """Mulloy's triple EMA: 3 E - 3 E(E) + E(E(E))."""
    e1 = _ema(f["close"], n)
    e2 = _ema(e1, n)
    return {"value": 3 * e1 - 3 * e2 + _ema(e2, n)}


def _bars_since_extreme(values: np.ndarray, n: int, take_max: bool) -> np.ndarray:
    out = np.full(len(values), np.nan)
    if len(values) <= n:
        return out
    windows = np.lib.stride_tricks.sliding_window_view(values, n + 1)[:, ::-1]
    picked = np.argmax(windows, axis=1) if take_max else np.argmin(windows, axis=1)
    # Reversed, so the first hit is the most recent on a tie; NaN windows drop.
    since = picked.astype(float)
    since[np.isnan(windows).any(axis=1)] = np.nan
    out[n:] = since
    return out


def aroon(f: Frame, n: int) -> dict[str, pd.Series]:
    """Chande's Aroon (1995): 100 x (n - bars since the n-bar high) / n, over
    the current bar and the n before it."""
    since_high = _bars_since_extreme(f["high"].to_numpy(dtype=float), n, True)
    since_low = _bars_since_extreme(f["low"].to_numpy(dtype=float), n, False)
    index = f.index
    return {
        "up": pd.Series(100 * (n - since_high) / n, index=index),
        "down": pd.Series(100 * (n - since_low) / n, index=index),
    }


def vortex(f: Frame, n: int) -> dict[str, pd.Series]:
    """Botes and Siepman's vortex indicator (*Stocks & Commodities*, Jan 2010)."""
    plus = (f["high"] - f["low"].shift(1)).abs()
    minus = (f["low"] - f["high"].shift(1)).abs()
    tr = _true_range(f).where(f["close"].shift(1).notna())
    tr_n = tr.rolling(n, min_periods=n).sum().replace(0, np.nan)
    return {
        "plus": plus.rolling(n, min_periods=n).sum() / tr_n,
        "minus": minus.rolling(n, min_periods=n).sum() / tr_n,
    }


def uo(f: Frame, short: int, mid: int, long: int) -> dict[str, pd.Series]:
    """Larry Williams' ultimate oscillator (1985), weights 4, 2, 1."""
    prev = f["close"].shift(1)
    floor = pd.concat([f["low"], prev], axis=1).min(axis=1, skipna=False)
    ceiling = pd.concat([f["high"], prev], axis=1).max(axis=1, skipna=False)
    bp, tr = f["close"] - floor, ceiling - floor

    def avg(n: int) -> pd.Series:
        return bp.rolling(n, min_periods=n).sum() / tr.rolling(n, min_periods=n).sum().replace(
            0, np.nan
        )

    return {"value": 100 * (4 * avg(short) + 2 * avg(mid) + avg(long)) / 7}


def chop(f: Frame, n: int) -> dict[str, pd.Series]:
    """Dreiss's choppiness index: 100 log10(sum of n true ranges / n-bar range)
    / log10(n). High: choppy; low: trending."""
    tr_sum = _true_range(f).where(f["close"].shift(1).notna()).rolling(n, min_periods=n).sum()
    span = f["high"].rolling(n, min_periods=n).max() - f["low"].rolling(n, min_periods=n).min()
    return {"value": 100 * np.log10(tr_sum / span.replace(0, np.nan)) / np.log10(n)}


def elder(f: Frame, n: int) -> dict[str, pd.Series]:
    """Elder ray (*Trading for a Living*, 1993): high and low against EMA(n)."""
    base = _ema(f["close"], n)
    return {"bull": f["high"] - base, "bear": f["low"] - base}


def stoch_of(series: pd.Series, n: int) -> pd.Series:
    """Where a series sits in its own n-bar range, 0 to 100."""
    lo = series.rolling(n, min_periods=n).min()
    hi = series.rolling(n, min_periods=n).max()
    return 100 * (series - lo) / (hi - lo).replace(0, np.nan)


def stochrsi(f: Frame, rsi_n: int, n: int, k: int, d: int) -> dict[str, pd.Series]:
    """Chande and Kroll's StochRSI (1994), on a 0-100 scale (StockCharts shows
    0-1), with %K smoothed over k bars and %D over d (k = 1 is the raw value)."""
    raw = stoch_of(rsi(f, rsi_n)["value"], n)
    pct_k = raw.rolling(k, min_periods=k).mean()
    return {"k": pct_k, "d": pct_k.rolling(d, min_periods=d).mean()}


def trix(f: Frame, n: int) -> dict[str, pd.Series]:
    """Hutson's TRIX: one-bar percent change of a triple-smoothed EMA."""
    e3 = _ema(_ema(_ema(f["close"], n), n), n)
    return {"value": 100 * (e3 / e3.shift(1) - 1)}


def ppo(f: Frame, fast: int, slow: int, signal: int) -> dict[str, pd.Series]:
    """Percentage price oscillator: MACD as a percent of the slow EMA."""
    slow_ema = _ema(f["close"], slow)
    line = 100 * (_ema(f["close"], fast) - slow_ema) / slow_ema.replace(0, np.nan)
    sig = _ema(line, signal)
    return {"ppo": line, "signal": sig, "histogram": line - sig}


def cmo(f: Frame, n: int) -> dict[str, pd.Series]:
    """Chande momentum oscillator (*The New Technical Trader*, 1994)."""
    delta = f["close"].diff()
    up = delta.clip(lower=0).rolling(n, min_periods=n).sum()
    down = (-delta).clip(lower=0).rolling(n, min_periods=n).sum()
    return {"value": 100 * (up - down) / (up + down).replace(0, np.nan)}


def force(f: Frame, n: int) -> dict[str, pd.Series]:
    """Elder's force index: EMA(n) of the close change times volume."""
    return {"value": _ema(f["close"].diff() * f["volume"], n)}


EOM_SCALE = 100_000_000
"""Volume divisor in the box ratio (StockCharts' worked example)."""


def eom(f: Frame, n: int) -> dict[str, pd.Series]:
    """Arms' ease of movement: n-bar SMA of the midpoint move over the box
    ratio (volume / 100,000,000 over the high-low range)."""
    mid = (f["high"] + f["low"]) / 2
    box = (f["volume"] / EOM_SCALE) / (f["high"] - f["low"]).replace(0, np.nan)
    one = (mid - mid.shift(1)) / box.replace(0, np.nan)
    return {"value": one.rolling(n, min_periods=n).mean()}


def massi(f: Frame, n: int, total: int) -> dict[str, pd.Series]:
    """Dorsey's mass index (1992): sum over ``total`` bars of EMA(n) of the
    high-low range over EMA(n) of that EMA."""
    e1 = _ema(f["high"] - f["low"], n)
    ratio = e1 / _ema(e1, n).replace(0, np.nan)
    return {"value": ratio.rolling(total, min_periods=total).sum()}


def coppock(f: Frame, long: int, short: int, n: int) -> dict[str, pd.Series]:
    """Coppock curve (*Barron's*, 1962): WMA(n) of ROC(long) + ROC(short).
    Coppock used monthly bars."""
    close = f["close"]
    total = 100 * (close / close.shift(long) - 1) + 100 * (close / close.shift(short) - 1)
    return {"value": _wma_series(total, n)}


# --- registry ---------------------------------------------------------------


@dataclass(frozen=True)
class Param:
    """One study parameter (A3.4): its bounds are what the API, the Rule DSL
    and the chart's editor all accept.

    Whole numbers are accepted from ``lo`` to ``hi`` inclusive; decimals
    above ``lo`` (exclusive) up to ``hi``. ``choices`` names the whole-number
    values 1..len(choices) when a parameter picks an option (pivot basis)."""

    name: str
    default: float
    lo: float = 1
    hi: float = 500
    integer: bool = True
    label: str = ""
    choices: tuple[str, ...] = ()

    @property
    def step(self) -> float:
        if self.integer:
            return 1
        return 0.01 if self.hi <= 1 else 0.1

    def check(self, key: str, value: float) -> float | int:
        if self.integer:
            if value != int(value) or not self.lo <= value <= self.hi:
                raise ValueError(
                    f"{key} {self.name} must be a whole number from {self.lo:g} to {self.hi:g}"
                )
            return int(value)
        if not self.lo < value <= self.hi:
            raise ValueError(f"{key} {self.name} must be above {self.lo:g} and at most {self.hi:g}")
        return value

    def schema(self) -> dict[str, object]:
        return {
            "name": self.name,
            "label": self.label or self.name,
            "type": "int" if self.integer else "float",
            "default": float(self.default),
            "min": float(self.lo),
            "max": float(self.hi),
            "min_exclusive": not self.integer,
            "step": self.step,
            "choices": list(self.choices),
        }


def _p(name: str, default: float, hi: float = 500, lo: float = 1, label: str = "") -> Param:
    return Param(name, default, lo, hi, True, label)


def _k(name: str, default: float, hi: float = 10, lo: float = 0, label: str = "") -> Param:
    return Param(name, default, lo, hi, False, label)


@dataclass(frozen=True)
class Spec:
    key: str
    label: str
    parameters: tuple[Param, ...]
    outputs: tuple[str, ...]
    pane: Pane
    compute: Callable[..., dict[str, pd.Series]]
    lookback: Callable[..., int]
    anchored: Literal["none", "start"] = "none"
    group: str = "trend"
    needs_benchmark: bool = False
    """Reads the venue index's close as a ``bench`` column (the RS line)."""
    description: str = ""
    source: str = ""
    """Where the definition comes from (shown with the study)."""

    @property
    def params(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.parameters)

    @property
    def defaults(self) -> tuple[float, ...]:
        return tuple(p.default for p in self.parameters)

    @property
    def integer(self) -> tuple[bool, ...]:
        return tuple(p.integer for p in self.parameters)

    def coerce(self, raw: list[str]) -> tuple[float, ...]:
        if len(raw) > len(self.parameters):
            raise ValueError(f"{self.key} takes at most {len(self.parameters)} parameters")
        values = [float(p.default) for p in self.parameters]
        for i, text in enumerate(raw):
            values[i] = float(text)
        return tuple(p.check(self.key, v) for p, v in zip(self.parameters, values, strict=True))

    def default_key(self) -> str:
        """The key with every parameter at its default (``rsi_14``, ``obv``)."""
        return "_".join([self.key, *(f"{p.default:g}" for p in self.parameters)])


def _ema_lb(n: int, *_: float) -> int:
    return 5 * (n + 1)


def _wilder_lb(n: int, *_: float) -> int:
    return 10 * n


def _kama_lb(n: int, _fast: int, slow: int) -> int:
    """Bars until the seed weighs under 0.01% at the slowest smoothing."""
    slowest = (2 / (slow + 1)) ** 2
    return n + int(np.ceil(np.log(1e-4) / np.log(1 - slowest)))


_N = _p("n", 20)

REGISTRY: dict[str, Spec] = {
    s.key: s
    for s in (
        # --- trend: moving averages and price overlays
        Spec("sma", "SMA", (_N,), ("value",), "price", sma, lambda n: n - 1),
        Spec("ema", "EMA", (_N,), ("value",), "price", ema, _ema_lb),
        Spec("wma", "WMA", (_N,), ("value",), "price", wma, lambda n: n - 1),
        Spec("vwap", "VWAP (rolling)", (_N,), ("value",), "price", vwap, lambda n: n - 1),
        Spec("hma", "Hull MA", (_p("n", 20, lo=2),), ("value",), "price", hma,
             lambda n: n + int(sqrt(n)) - 2, source="Alan Hull, 2005"),
        Spec("dema", "DEMA", (_p("n", 20, hi=300),), ("value",), "price", dema,
             lambda n: 10 * (n + 1), source="Patrick Mulloy, Stocks & Commodities, Feb 1994"),
        Spec("tema", "TEMA", (_p("n", 20, hi=300),), ("value",), "price", tema,
             lambda n: 15 * (n + 1), source="Patrick Mulloy, Stocks & Commodities, Feb 1994"),
        Spec("kama", "KAMA", (_p("n", 10, hi=100), _p("fast", 2, hi=20),
                              _p("slow", 30, hi=40, lo=2)), ("value",), "price", kama, _kama_lb,
             source="Perry Kaufman, Smarter Trading, 1995"),
        Spec("supertrend", "Supertrend", (_p("n", 10), _k("k", 3)), ("line", "direction"),
             "price", supertrend, lambda n, k: 10 * n),
        Spec("psar", "Parabolic SAR", (_k("step", 0.02, hi=0.5), _k("max", 0.2, hi=1)),
             ("sar", "direction"), "price", psar, lambda step, mx: 250,
             description="Path-dependent: warmed up on 250 bars.",
             source="J. Welles Wilder, New Concepts in Technical Trading Systems, 1978"),
        Spec("ichimoku", "Ichimoku Cloud",
             (_p("tenkan", 9, hi=200), _p("kijun", 26, hi=200), _p("senkou", 52, hi=400),
              _p("shift", 26, hi=200, label="displacement")),
             ("tenkan", "kijun", "senkou_a", "senkou_b"), "price", ichimoku,
             lambda t, k, s, d: max(t, k, s) - 1 + d,
             description="Each bar carries the cloud drawn on it, computed `displacement` "
                         "bars earlier; the cloud past the last bar and the lagging span are "
                         "not drawn.",
             source="Goichi Hosoda (Ichimoku Kinko Hyo, 1969)"),
        Spec("pivots", "Pivot points (classic)",
             (Param("basis", 3, 1, 4, True, "from the prior", ("bar", "week", "month", "year")),),
             ("pp", "r1", "r2", "s1", "s2"), "price", pivots,
             lambda basis: {1: 1, 2: 15, 3: 66, 4: 520}[int(basis)],
             description="Floor pivots from the prior period's high, low and close.",
             source="StockCharts ChartSchool, Pivot Points"),
        Spec("adx", "ADX", (_p("n", 14, hi=250),), ("adx", "plus_di", "minus_di"), "separate",
             adx, lambda n: 20 * n),
        Spec("aroon", "Aroon", (_p("n", 25),), ("up", "down"), "separate", aroon,
             lambda n: n, source="Tushar Chande, 1995"),
        Spec("vortex", "Vortex", (_p("n", 14, lo=2),), ("plus", "minus"), "separate", vortex,
             lambda n: n, source="Etienne Botes and Douglas Siepman, Stocks & Commodities, "
                                 "Jan 2010"),
        Spec("chop", "Choppiness Index", (_p("n", 14, lo=2),), ("value",), "separate", chop,
             lambda n: n, source="E. W. Dreiss"),
        Spec("trix", "TRIX", (_p("n", 15, hi=300),), ("value",), "separate", trix,
             lambda n: 15 * (n + 1) + 1, source="Jack Hutson, Stocks & Commodities, 1983"),
        Spec("elder", "Elder Ray", (_p("n", 13),), ("bull", "bear"), "separate", elder, _ema_lb,
             source="Alexander Elder, Trading for a Living, 1993"),
        # --- momentum
        Spec("rsi", "RSI", (_p("n", 14),), ("value",), "separate", rsi, _wilder_lb,
             group="momentum"),
        Spec("macd", "MACD", (_p("fast", 12), _p("slow", 26), _p("signal", 9)),
             ("macd", "signal", "histogram"), "separate", macd,
             lambda fast, slow, sig: 5 * (slow + 1) + sig, group="momentum"),
        Spec("ppo", "PPO", (_p("fast", 12), _p("slow", 26), _p("signal", 9, hi=200)),
             ("ppo", "signal", "histogram"), "separate", ppo,
             lambda fast, slow, sig: 5 * (slow + 1) + 5 * (sig + 1), group="momentum",
             source="StockCharts ChartSchool, Percentage Price Oscillator"),
        Spec("stoch", "Stochastic", (_p("k", 14), _p("d", 3)), ("k", "d"), "separate", stoch,
             lambda k, d: k + d - 2, group="momentum"),
        Spec("stochrsi", "Stochastic RSI",
             (_p("rsi_n", 14, hi=250), _p("n", 14), _p("k", 3, hi=50), _p("d", 3, hi=50)),
             ("k", "d"), "separate", stochrsi,
             lambda r, n, k, d: 10 * r + n + k + d - 3, group="momentum",
             source="Tushar Chande and Stanley Kroll, The New Technical Trader, 1994"),
        Spec("cci", "CCI", (_N,), ("value",), "separate", cci, lambda n: n - 1,
             group="momentum"),
        Spec("roc", "ROC", (_p("n", 12),), ("value",), "separate", roc, lambda n: n,
             group="momentum"),
        Spec("willr", "Williams %R", (_p("n", 14),), ("value",), "separate", willr,
             lambda n: n - 1, group="momentum"),
        Spec("tsi", "True Strength Index", (_p("long", 25, hi=200), _p("short", 13, hi=200),
                                            _p("signal", 7, hi=200)),
             ("tsi", "signal"), "separate", tsi,
             lambda long, short, sig: 5 * (long + 1) + 5 * (short + 1) + 5 * (sig + 1),
             group="momentum", source="William Blau, Momentum, Direction and Divergence, 1995"),
        Spec("uo", "Ultimate Oscillator", (_p("short", 7), _p("mid", 14), _p("long", 28)),
             ("value",), "separate", uo, lambda s, m, lg: max(s, m, lg), group="momentum",
             source="Larry Williams, 1985"),
        Spec("cmo", "Chande Momentum", (_p("n", 9),), ("value",), "separate", cmo,
             lambda n: n, group="momentum",
             source="Tushar Chande and Stanley Kroll, The New Technical Trader, 1994"),
        Spec("coppock", "Coppock Curve", (_p("long", 14), _p("short", 11), _p("n", 10)),
             ("value",), "separate", coppock, lambda lg, s, n: max(lg, s) + n - 1,
             group="momentum", description="Coppock used monthly bars.",
             source="Edwin Coppock, Barron's, 1962"),
        Spec("rsline", "RS line (vs index)", (), ("value",), "separate", rsline, lambda: 0,
             group="momentum", needs_benchmark=True,
             description="Close over the venue index (^GSPC for US listings, ^NSEI for Indian "
                         "ones). Read its slope: a rising line is outperforming.",
             source="StockCharts ChartSchool, Price Relative"),
        # --- volatility
        Spec("bb", "Bollinger Bands", (_N, _k("k", 2)), ("upper", "middle", "lower"), "price",
             bb, lambda n, k: n - 1, group="volatility"),
        Spec("atr", "ATR", (_p("n", 14),), ("value",), "separate", atr, _wilder_lb,
             group="volatility"),
        Spec("natr", "ATR %", (_p("n", 14),), ("value",), "separate", natr, _wilder_lb,
             group="volatility", source="StockCharts ChartSchool, ATR Percent (ATRP)"),
        Spec("hv", "Historical volatility", (_N,), ("value",), "separate", hv, lambda n: n,
             group="volatility"),
        Spec("donchian", "Donchian Channels", (_N,), ("upper", "middle", "lower"), "price",
             donchian, lambda n: n - 1, group="volatility"),
        Spec("keltner", "Keltner Channels", (_N, _k("k", 2), _p("atr_n", 10)),
             ("upper", "middle", "lower"), "price", keltner,
             lambda n, k, a: max(5 * (n + 1), 10 * a), group="volatility"),
        Spec("massi", "Mass Index", (_p("n", 9, hi=100), _p("total", 25, hi=200)), ("value",),
             "separate", massi, lambda n, t: 10 * (n + 1) + t - 1, group="volatility",
             source="Donald Dorsey, Stocks & Commodities, 1992"),
        Spec("rmv", "RMV tightness", (_p("n", 5, hi=100), _p("lookback", 50, lo=2, hi=500)),
             ("value",), "separate", rmv, lambda n, lb: n + lb - 2, group="volatility",
             description="Where the last n bars' high-low range (as % of close) sits between "
                         "its lowest (0) and highest (100) of `lookback` bars. Near 0: tight.",
             source="StockViz's definition, after Deepvue's RMV (formula not published) and "
                    "Minervini's volatility contraction"),
        # --- volume
        Spec("obv", "OBV", (), ("value",), "separate", obv, lambda: 0, anchored="start",
             group="volume"),
        Spec("mfi", "MFI", (_p("n", 14),), ("value",), "separate", mfi, lambda n: n,
             group="volume"),
        Spec("ad", "Accumulation/Distribution", (), ("value",), "separate", ad, lambda: 0,
             anchored="start", group="volume"),
        Spec("cmf", "Chaikin Money Flow", (_N,), ("value",), "separate", cmf, lambda n: n - 1,
             group="volume", source="Marc Chaikin"),
        Spec("chaikin", "Chaikin Oscillator", (_p("fast", 3), _p("slow", 10)), ("value",),
             "separate", chaikin, lambda fast, slow: 5 * (max(fast, slow) + 1),
             group="volume", source="Marc Chaikin"),
        Spec("force", "Force Index", (_p("n", 13),), ("value",), "separate", force,
             lambda n: 5 * (n + 1) + 1, group="volume",
             source="Alexander Elder, Trading for a Living, 1993"),
        Spec("eom", "Ease of Movement", (_p("n", 14),), ("value",), "separate", eom,
             lambda n: n, group="volume", source="Richard Arms"),
        Spec("rvol", "Relative volume", (_N,), ("value",), "separate", rvol, lambda n: n,
             group="volume"),
    )
}  # fmt: skip

_TOKEN = re.compile(r"^([a-z]+)((?:_[0-9]+(?:\.[0-9]+)?)*)$")


@dataclass(frozen=True)
class Request:
    name: str  # the token as asked, e.g. "bb_20_2"
    spec: Spec
    args: tuple[float, ...]

    @property
    def lookback(self) -> int:
        return int(self.spec.lookback(*self.args))


def parse(token: str) -> Request:
    """``"rsi_14"``, ``"bb_20_2"``, ``"macd"`` (defaults) -> a ``Request``."""
    text = token.strip().lower()
    match = _TOKEN.match(text)
    if not match or match.group(1) not in REGISTRY:
        raise ValueError(f"Unknown indicator: {token!r}")
    spec = REGISTRY[match.group(1)]
    raw = [p for p in match.group(2).split("_") if p]
    return Request(name=text, spec=spec, args=spec.coerce(raw))


def frame(rows: list[tuple], bench: pd.Series | None = None) -> Frame:
    """``(ts, open, high, low, close, volume)`` rows -> a float frame.

    ``bench`` (the venue index's daily closes) adds a ``bench`` column, the
    index close on each bar's date or the latest before it, at most 5 bars
    back, for the RS line."""
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"], dtype=float)
    index = pd.DatetimeIndex([r[0] for r in rows])
    data = {
        name: [float(r[i]) for r in rows]
        for i, name in enumerate(("open", "high", "low", "close", "volume"), start=1)
    }
    out = pd.DataFrame(data, index=index, dtype=float)
    if bench is not None:
        out["bench"] = bench_on(bench, index)
    return out


def bench_on(bench: pd.Series, index: pd.DatetimeIndex) -> np.ndarray:
    """The index close on or before each bar's date, forward-filled at most 5
    index bars (the Rule DSL's ``index_close`` rule)."""
    if bench.empty:
        return np.full(len(index), np.nan)
    days = pd.DatetimeIndex(index.normalize())
    series = bench.copy()
    series.index = pd.DatetimeIndex(series.index).normalize()
    series = series[~series.index.duplicated(keep="last")].sort_index()
    union = series.index.union(days)
    filled = series.reindex(union).ffill(limit=5)
    return filled.reindex(days).to_numpy(dtype=float)


def compute(request: Request, f: Frame) -> dict[str, pd.Series]:
    return request.spec.compute(f, *request.args)
