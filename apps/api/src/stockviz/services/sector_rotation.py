"""The sector rotation map (A7.2, M3.2): RS-Trend against RS-Momentum, weekly.

Openly documented maths, not the RRG® method (whose exact normalisation is
proprietary), and the RRG® name is not used:

- **Sectors** are ``symbols.sector`` within a market (``US``, ``IN``); a sector
  needs at least ``MIN_MEMBERS`` active non-index members with stored bars.
- **A sector line** is the equal-weight composite of its members: each
  session, the mean of the members' daily returns (members with a bar that
  session and the one before), compounded from 1. No sector index is stored,
  so the line is built from today's members (survivorship-biased).
- **The benchmark** is the venue index (``^GSPC``, ``^NSEI``) from stored
  bars; without index bars, the equal-weight composite of every member of the
  market, labelled so.
- **Weekly:** each line is sampled at the last stored session of each ISO
  week.
- **RS ratio** = 100 x sector / benchmark. **RS-Trend** = 100 x RS ratio / its
  ``TREND_WEEKS``-week simple average. **RS-Momentum** = 100 x RS-Trend / RS-Trend
  ``MOMENTUM_WEEKS`` weeks earlier. Both centre on 100.
- **Quadrants:** Leading (trend >= 100, momentum >= 100), Weakening (trend
  >= 100, momentum < 100), Lagging (both < 100), Improving (trend < 100,
  momentum >= 100).

A week's point uses only bars up to that week, so a point never changes when
later bars arrive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from sqlmodel import Session, col, select

from stockviz.models import PriceBar, Symbol
from stockviz.services.instruments import is_index_ticker
from stockviz.services.relative_strength import market_for

MIN_MEMBERS = 3
TREND_WEEKS = 10
MOMENTUM_WEEKS = 4
HISTORY_DAYS = 2 * 365
BENCHMARKS = {"US": "^GSPC", "IN": "^NSEI"}
BENCHMARK_NAMES = {"^GSPC": "S&P 500", "^NSEI": "Nifty 50"}
NOTE = (
    "Sector lines are equal-weight composites of today's stored members "
    "(survivorship-biased), not sector indices. Openly documented maths; not RRG®."
)
METHOD = {
    "rs_ratio": "100 x sector composite / benchmark",
    "rs_trend": f"100 x RS ratio / its {TREND_WEEKS}-week simple average",
    "rs_momentum": f"100 x RS-Trend / RS-Trend {MOMENTUM_WEEKS} weeks earlier",
    "quadrant": "Leading: both >= 100; Weakening: trend >= 100, momentum < 100; "
    "Lagging: both < 100; Improving: trend < 100, momentum >= 100",
}


def quadrant(trend: float, momentum: float) -> str:
    if trend >= 100:
        return "leading" if momentum >= 100 else "weakening"
    return "improving" if momentum >= 100 else "lagging"


@dataclass
class SectorTrail:
    sector: str
    members: int
    points: list[dict[str, object]] = field(default_factory=list)


@dataclass
class Rotation:
    market: str
    benchmark: str
    benchmark_name: str
    as_of: date | None
    sectors: list[SectorTrail] = field(default_factory=list)


def composite(closes: pd.DataFrame) -> pd.Series:
    """Equal-weight compounded line: each session the mean member return."""
    returns = closes.pct_change(fill_method=None)
    mean = returns.mean(axis=1, skipna=True).fillna(0.0)
    return pd.Series((1 + mean).cumprod(), index=closes.index)


def _day(value: object) -> date:
    stamp = pd.Timestamp(value)  # type: ignore[arg-type]
    return date(stamp.year, stamp.month, stamp.day)


def weekly(series: pd.Series) -> pd.Series:
    """The last stored value of each ISO week, labelled by that session."""
    last: dict[tuple[int, int], tuple[object, float]] = {}
    for stamp, value in zip(series.index, series.to_numpy(dtype=float), strict=True):
        year, week, _ = _day(stamp).isocalendar()
        last[(year, week)] = (stamp, float(value))
    ordered = [last[k] for k in sorted(last)]
    return pd.Series([v for _, v in ordered], index=pd.DatetimeIndex([t for t, _ in ordered]))


def trail(sector_line: pd.Series, bench_line: pd.Series, weeks: int) -> list[dict[str, object]]:
    """RS-Trend and RS-Momentum for the last ``weeks`` weeks (pure)."""
    joined = pd.concat([weekly(sector_line), weekly(bench_line)], axis=1, join="inner").dropna()
    if joined.empty:
        return []
    ratio = 100 * joined.iloc[:, 0] / joined.iloc[:, 1]
    rs_trend = 100 * ratio / ratio.rolling(TREND_WEEKS).mean()
    rs_momentum = 100 * rs_trend / rs_trend.shift(MOMENTUM_WEEKS)
    out = pd.DataFrame({"trend": rs_trend, "momentum": rs_momentum}).dropna().tail(weeks)
    points: list[dict[str, object]] = []
    for day, row in zip(out.index, out.to_dict("records"), strict=True):
        t, m = float(row["trend"]), float(row["momentum"])
        if not (np.isfinite(t) and np.isfinite(m)):
            continue
        points.append(
            {
                "week": _day(day),
                "rs_trend": round(t, 2),
                "rs_momentum": round(m, 2),
                "quadrant": quadrant(t, m),
            }
        )
    return points


def _closes(session: Session, tickers: list[str], since: datetime) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    bars = session.exec(
        select(PriceBar).where(
            col(PriceBar.ticker).in_(tickers),
            col(PriceBar.interval) == "1d",
            col(PriceBar.ts) >= since,
        )
    ).all()
    if not bars:
        return pd.DataFrame()
    df = pd.DataFrame([(b.ticker, b.ts, float(b.close)) for b in bars],
                      columns=["ticker", "ts", "close"])  # fmt: skip
    df["day"] = pd.to_datetime(df["ts"]).dt.normalize()
    return df.pivot_table(
        index="day", columns="ticker", values="close", aggfunc="last"
    ).sort_index()


def rotation(
    session: Session, market: str, *, weeks: int = 10, today: date | None = None
) -> Rotation:
    if market not in BENCHMARKS:
        raise ValueError("market must be US or IN")
    since = datetime.combine((today or date.today()) - timedelta(days=HISTORY_DAYS),
                             datetime.min.time())  # fmt: skip
    members: dict[str, list[str]] = {}
    for s in session.exec(select(Symbol).where(col(Symbol.is_active))).all():
        if is_index_ticker(s.ticker) or market_for(s.ticker) != market or not s.sector:
            continue
        members.setdefault(s.sector, []).append(s.ticker)
    everyone = sorted({t for ts in members.values() for t in ts})
    closes = _closes(session, everyone, since)
    bench_ticker = BENCHMARKS[market]
    bench = _closes(session, [bench_ticker], since)
    if not bench.empty and bench_ticker in bench.columns:
        bench_line = pd.Series(bench[bench_ticker]).dropna()
        bench_name = BENCHMARK_NAMES[bench_ticker]
    else:
        bench_line = composite(closes) if not closes.empty else pd.Series(dtype=float)
        bench_ticker = "equal_weight"
        bench_name = "Equal-weight market (no index bars stored)"
    result = Rotation(market=market, benchmark=bench_ticker, benchmark_name=bench_name,
                      as_of=_day(closes.index.max()) if not closes.empty else None)  # fmt: skip
    if closes.empty or bench_line.empty:
        return result
    for sector, tickers in sorted(members.items()):
        held = [t for t in tickers if t in closes.columns]
        if len(held) < MIN_MEMBERS:
            continue
        points = trail(composite(pd.DataFrame(closes[held])), pd.Series(bench_line), weeks)
        if points:
            result.sectors.append(SectorTrail(sector=sector, members=len(held), points=points))
    return result
