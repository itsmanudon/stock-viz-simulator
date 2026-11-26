"""Market breadth and diffusion (A7.1, M3.3), computed on read from stored daily bars.

Per market (``US``, ``IN``: the venues behind ``^GSPC`` and ``^NSEI``), per
session, over the active non-index symbols **with a stored bar that
session** (so a value is what the stored data said then; the symbol list is
today's, survivorship-biased, as every stamp says):

- **Advancers / decliners / unchanged:** close against the symbol's previous
  stored close.
- **New 52-week highs / lows:** the session's high at or above the highest
  high of the 252 stored bars before it (lows mirrored); needs 252 earlier bars.
- **Diffusion:** the share of members whose close is above its 20, 50, 100 and
  200-bar simple average (members with that much history), and with RSI(14)
  at or above 50 (the engine's Wilder RSI, the chart's and the screener's).

Derived from those counts, in session order:

- **A/D line:** the running sum of advancers - decliners from the window start.
- **A/D ratio (20, 40):** advancers / decliners summed over the last N sessions.
- **McClellan oscillator:** EMA19 - EMA39 of net advances (alpha 0.10 and 0.05,
  seeded at the first net value of the loaded history); **summation index:**
  its running sum.
- **Breadth thrust (Zweig):** the 10-session EMA of advancers / (advancers +
  decliners); a thrust is the EMA rising from under 0.40 to over 0.615 within
  10 sessions.

Warm-up: bars load from ``WARMUP_DAYS`` before ``from`` and the EMAs run over
them, so a window's values do not depend on where it starts beyond that, and
a value never changes when later bars arrive.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from sqlmodel import Session, col, select

from stockviz.models import PriceBar, Symbol
from stockviz.services.indicators import engine
from stockviz.services.instruments import is_index_ticker
from stockviz.services.relative_strength import market_for

MARKETS = ("US", "IN")
SMA_WINDOWS = (20, 50, 100, 200)
HIGH_LOW_BARS = 252
RSI_PERIOD = 14
WARMUP_DAYS = 420
THRUST_LOW, THRUST_HIGH, THRUST_WITHIN = 0.40, 0.615, 10
CACHE_SECONDS = 600
UNIVERSE_NOTE = (
    "Active symbols stored today, each counted on the sessions it has a bar: "
    "not point in time for delistings (survivorship-biased)."
)
METHOD = {
    "advancers": "Close above the symbol's previous stored close",
    "new_highs": "High at or above the highest high of the previous 252 stored bars",
    "pct_above_sma": "Share of members with close above its N-bar simple average",
    "pct_rsi_50": "Share of members with RSI(14) (Wilder) at or above 50",
    "ad_line": "Running sum of advancers - decliners from the window start",
    "ad_ratio": "Advancers / decliners, each summed over the last N sessions",
    "mcclellan": "EMA19 - EMA39 of advancers - decliners (alpha 0.10, 0.05)",
    "summation": "Running sum of the McClellan oscillator",
    "thrust": "10-session EMA of advancers / (advancers + decliners) rising from "
    "under 0.40 to over 0.615 within 10 sessions (Zweig)",
}


@dataclass
class Breadth:
    market: str
    start: date
    end: date
    members: int
    points: list[dict[str, object]] = field(default_factory=list)


def _frames(session: Session, market: str, start: date, end: date) -> dict[str, pd.DataFrame]:
    tickers = [
        s.ticker
        for s in session.exec(select(Symbol).where(col(Symbol.is_active))).all()
        if not is_index_ticker(s.ticker) and market_for(s.ticker) == market
    ]
    if not tickers:
        return {}
    since = datetime.combine(start - timedelta(days=WARMUP_DAYS), datetime.min.time())
    until = datetime.combine(end, datetime.max.time())
    bars = session.exec(
        select(PriceBar).where(
            col(PriceBar.ticker).in_(tickers),
            col(PriceBar.interval) == "1d",
            col(PriceBar.ts) >= since,
            col(PriceBar.ts) <= until,
        )
    ).all()
    rows = [(b.ticker, b.ts, b.high, b.low, b.close) for b in bars]
    if not rows:
        return {}
    df = pd.DataFrame(rows, columns=["ticker", "ts", "high", "low", "close"])
    df["day"] = pd.to_datetime(df["ts"]).dt.normalize()
    out: dict[str, pd.DataFrame] = {}
    for name in ("high", "low", "close"):
        out[name] = (
            df.pivot_table(index="day", columns="ticker", values=name, aggfunc="last")
            .sort_index()
            .astype(float)
        )
    return out


def _per_symbol(frame: pd.DataFrame, fn) -> pd.DataFrame:
    """Apply ``fn`` to each symbol's own stored bars (gaps skipped), realigned."""
    cols = {}
    for ticker in frame.columns:
        series = frame[ticker].dropna()
        cols[ticker] = fn(series).reindex(frame.index)
    return pd.DataFrame(cols, index=frame.index)


def _ema(values: np.ndarray, alpha: float) -> np.ndarray:
    out = np.empty_like(values)
    for i, v in enumerate(values):
        out[i] = v if i == 0 else alpha * v + (1 - alpha) * out[i - 1]
    return out


def compute(frames: dict[str, pd.DataFrame], start: date, end: date) -> list[dict[str, object]]:
    """The per-session breadth rows from pivoted high/low/close frames (pure)."""
    if not frames:
        return []
    close, high, low = frames["close"], frames["high"], frames["low"]
    present = close.notna()
    prev = _per_symbol(close, lambda s: s.shift(1))
    up = (close > prev) & present
    down = (close < prev) & present
    flat = (close == prev) & present
    prior_high = _per_symbol(high, lambda s: s.shift(1).rolling(HIGH_LOW_BARS).max())
    prior_low = _per_symbol(low, lambda s: s.shift(1).rolling(HIGH_LOW_BARS).min())
    new_high = (high >= prior_high) & present
    new_low = (low <= prior_low) & present
    table = pd.DataFrame(
        {
            "advancers": up.sum(axis=1),
            "decliners": down.sum(axis=1),
            "unchanged": flat.sum(axis=1),
            "members": present.sum(axis=1),
            "new_highs": new_high.sum(axis=1),
            "new_lows": new_low.sum(axis=1),
        }
    )
    for n in SMA_WINDOWS:
        sma = _per_symbol(close, lambda s, n=n: s.rolling(n).mean())
        judged = sma.notna() & present
        above = (close > sma) & judged
        table[f"pct_above_{n}"] = (above.sum(axis=1) / judged.sum(axis=1).replace(0, np.nan)) * 100

    def _rsi(s: pd.Series) -> pd.Series:
        return engine.rsi(pd.DataFrame({"close": s}), RSI_PERIOD)["value"]

    rsi = _per_symbol(close, _rsi)
    judged = rsi.notna() & present
    table["pct_rsi_50"] = (
        ((rsi >= 50) & judged).sum(axis=1) / judged.sum(axis=1).replace(0, np.nan) * 100
    )

    net = (table["advancers"] - table["decliners"]).astype(float).to_numpy()
    osc = _ema(net, 0.10) - _ema(net, 0.05) if len(net) else net
    table["mcclellan"] = osc
    table["summation"] = np.cumsum(osc)
    total = (table["advancers"] + table["decliners"]).astype(float)
    share = (table["advancers"] / total.replace(0, np.nan)).fillna(0.5).to_numpy()
    thrust_ema = _ema(share, 2 / (10 + 1)) if len(share) else share
    table["thrust_ema10"] = thrust_ema
    thrust = np.zeros(len(thrust_ema), dtype=bool)
    last_low: int | None = None
    for i, v in enumerate(thrust_ema):
        if v < THRUST_LOW:
            last_low = i
        if v > THRUST_HIGH and last_low is not None and i - last_low <= THRUST_WITHIN:
            thrust[i] = True
            last_low = None
    table["thrust"] = thrust

    in_window = (table.index >= pd.Timestamp(start)) & (table.index <= pd.Timestamp(end))
    window: pd.DataFrame = table.loc[in_window].copy()
    window = window.loc[window["members"] > 0]
    net_window = pd.Series(window["advancers"] - window["decliners"])
    window["ad_line"] = net_window.cumsum()
    for n in (20, 40):
        adv = np.asarray(table["advancers"].rolling(n).sum(), dtype=float)
        dec = np.asarray(table["decliners"].rolling(n).sum(), dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(dec > 0, adv / dec, np.nan)
        window[f"ad_ratio_{n}"] = pd.Series(ratio, index=table.index).reindex(window.index)

    def _num(value: object, digits: int = 4) -> float | None:
        if value is None:
            return None
        number = float(value)  # type: ignore[arg-type]
        return None if np.isnan(number) else round(number, digits)

    points: list[dict[str, object]] = []
    for day, row in zip(window.index, window.to_dict("records"), strict=True):
        point: dict[str, object] = {"date": pd.Timestamp(day).date()}
        for key in ("advancers", "decliners", "unchanged", "members", "new_highs", "new_lows"):
            point[key] = int(row[key])
        point["ad_line"] = int(row["ad_line"])
        point["highs_minus_lows"] = int(row["new_highs"]) - int(row["new_lows"])
        for n in SMA_WINDOWS:
            point[f"pct_above_{n}"] = _num(row[f"pct_above_{n}"], 2)
        point["pct_rsi_50"] = _num(row["pct_rsi_50"], 2)
        point["ad_ratio_20"] = _num(row["ad_ratio_20"])
        point["ad_ratio_40"] = _num(row["ad_ratio_40"])
        point["mcclellan"] = _num(row["mcclellan"], 2)
        point["summation"] = _num(row["summation"], 2)
        point["thrust_ema10"] = _num(row["thrust_ema10"])
        point["thrust"] = bool(row["thrust"])
        points.append(point)
    return points


_CACHE: dict[tuple[str, date, date], tuple[float, Breadth]] = {}
_LOCK = threading.Lock()


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()


def breadth(
    session: Session, market: str, start: date, end: date, *, use_cache: bool = True
) -> Breadth:
    if market not in MARKETS:
        raise ValueError(f"market must be one of {', '.join(MARKETS)}")
    if start > end:
        raise ValueError("from must be on or before to")
    key = (market, start, end)
    now = time.monotonic()
    if use_cache:
        with _LOCK:
            hit = _CACHE.get(key)
            if hit and now - hit[0] < CACHE_SECONDS:
                return hit[1]
    frames = _frames(session, market, start, end)
    points = compute(frames, start, end)
    members = len(frames["close"].columns) if frames else 0
    result = Breadth(market=market, start=start, end=end, members=members, points=points)
    if use_cache:
        with _LOCK:
            _CACHE[key] = (now, result)
    return result
