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
from dataclasses import dataclass, field
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


# --- registry ---------------------------------------------------------------


@dataclass(frozen=True)
class Spec:
    key: str
    label: str
    params: tuple[str, ...]
    defaults: tuple[float, ...]
    outputs: tuple[str, ...]
    pane: Pane
    compute: Callable[..., dict[str, pd.Series]]
    lookback: Callable[..., int]
    anchored: Literal["none", "start"] = "none"
    group: str = "trend"
    integer: tuple[bool, ...] = field(default=())

    def coerce(self, raw: list[str]) -> tuple[float, ...]:
        if len(raw) > len(self.params):
            raise ValueError(f"{self.key} takes at most {len(self.params)} parameters")
        values = list(self.defaults)
        for i, text in enumerate(raw):
            values[i] = float(text)
        ints = self.integer or tuple(True for _ in self.params)
        out = []
        for name, value, is_int in zip(self.params, values, ints, strict=True):
            if is_int:
                if value != int(value) or not 1 <= value <= 500:
                    raise ValueError(f"{self.key} {name} must be a whole number from 1 to 500")
                out.append(int(value))
            else:
                if not 0 < value <= 10:
                    raise ValueError(f"{self.key} {name} must be above 0 and at most 10")
                out.append(value)
        return tuple(out)


def _ema_lb(n: int, *_: float) -> int:
    return 5 * (n + 1)


def _wilder_lb(n: int, *_: float) -> int:
    return 10 * n


REGISTRY: dict[str, Spec] = {
    s.key: s
    for s in (
        Spec("sma", "SMA", ("n",), (20,), ("value",), "price", sma, lambda n: n - 1),
        Spec("ema", "EMA", ("n",), (20,), ("value",), "price", ema, _ema_lb),
        Spec("wma", "WMA", ("n",), (20,), ("value",), "price", wma, lambda n: n - 1),
        Spec("vwap", "VWAP (rolling)", ("n",), (20,), ("value",), "price", vwap, lambda n: n - 1),
        Spec("supertrend", "Supertrend", ("n", "k"), (10, 3), ("line", "direction"), "price",
             supertrend, lambda n, k: 10 * n, integer=(True, False)),
        Spec("adx", "ADX", ("n",), (14,), ("adx", "plus_di", "minus_di"), "separate", adx,
             lambda n: 20 * n),
        Spec("rsi", "RSI", ("n",), (14,), ("value",), "separate", rsi, _wilder_lb,
             group="momentum"),
        Spec("macd", "MACD", ("fast", "slow", "signal"), (12, 26, 9),
             ("macd", "signal", "histogram"), "separate", macd,
             lambda fast, slow, sig: 5 * (slow + 1) + sig, group="momentum"),
        Spec("stoch", "Stochastic", ("k", "d"), (14, 3), ("k", "d"), "separate", stoch,
             lambda k, d: k + d - 2, group="momentum"),
        Spec("cci", "CCI", ("n",), (20,), ("value",), "separate", cci, lambda n: n - 1,
             group="momentum"),
        Spec("roc", "ROC", ("n",), (12,), ("value",), "separate", roc, lambda n: n,
             group="momentum"),
        Spec("willr", "Williams %R", ("n",), (14,), ("value",), "separate", willr,
             lambda n: n - 1, group="momentum"),
        Spec("bb", "Bollinger Bands", ("n", "k"), (20, 2), ("upper", "middle", "lower"), "price",
             bb, lambda n, k: n - 1, group="volatility", integer=(True, False)),
        Spec("atr", "ATR", ("n",), (14,), ("value",), "separate", atr, _wilder_lb,
             group="volatility"),
        Spec("hv", "Historical volatility", ("n",), (20,), ("value",), "separate", hv,
             lambda n: n, group="volatility"),
        Spec("donchian", "Donchian Channels", ("n",), (20,), ("upper", "middle", "lower"),
             "price", donchian, lambda n: n - 1, group="volatility"),
        Spec("keltner", "Keltner Channels", ("n", "k", "atr_n"), (20, 2, 10),
             ("upper", "middle", "lower"), "price", keltner,
             lambda n, k, a: max(5 * (n + 1), 10 * a), group="volatility",
             integer=(True, False, True)),
        Spec("obv", "OBV", (), (), ("value",), "separate", obv, lambda: 0, anchored="start",
             group="volume"),
        Spec("mfi", "MFI", ("n",), (14,), ("value",), "separate", mfi, lambda n: n,
             group="volume"),
        Spec("ad", "Accumulation/Distribution", (), (), ("value",), "separate", ad, lambda: 0,
             anchored="start", group="volume"),
        Spec("rvol", "Relative volume", ("n",), (20,), ("value",), "separate", rvol,
             lambda n: n, group="volume"),
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


def frame(rows: list[tuple]) -> Frame:
    """``(ts, open, high, low, close, volume)`` rows -> a float frame."""
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"], dtype=float)
    index = pd.DatetimeIndex([r[0] for r in rows])
    data = {
        name: [float(r[i]) for r in rows]
        for i, name in enumerate(("open", "high", "low", "close", "volume"), start=1)
    }
    return pd.DataFrame(data, index=index, dtype=float)


def compute(request: Request, f: Frame) -> dict[str, pd.Series]:
    return request.spec.compute(f, *request.args)
