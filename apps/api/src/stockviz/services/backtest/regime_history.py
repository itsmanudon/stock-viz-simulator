"""A3.5's market regime on every past session, for a backtest's regime split (A4.3).

The live badge (``services/regime.py``) judges today only. Here the same
``REGIME_RULES`` are evaluated on each date with only what was stored on or
before it, so no session is labelled with later data:

- ``index_close``, ``index_sma_200`` and ``vol_pct_20`` come from the
  market's index closes up to that date (the 200-session SMA; the 20-session
  volatility's percentile among its last 1,260 values, needing 252), exactly
  as :func:`regime.index_inputs` computes them on a prefix.
- ``breadth_200`` cannot come from ``symbol_metrics``: it holds the newest
  night only. It is recomputed from stored daily bars: on each date, the
  share of the market's symbols (active, non-index, the same members as the
  live badge, so the same survivorship bias as the pinned universe) whose
  close is above the mean of their own last 200 stored closes, counted only
  when a symbol has 200 bars to that date. Under ``MIN_BREADTH`` judged
  symbols breadth is unknown. One aggregate SQL query per request.

A backtest date takes the regime of the newest index date on or before it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
from sqlalchemy import bindparam, text
from sqlmodel import Session, col, select

from stockviz.models import PriceBar, Symbol
from stockviz.services.indicators import engine
from stockviz.services.instruments import instrument_of, is_index_ticker
from stockviz.services.regime import (
    MARKETS,
    MIN_VOL_HISTORY,
    SMA_SESSIONS,
    VOL_SESSIONS,
    VOL_WINDOW,
    classify,
)
from stockviz.services.relative_strength import market_for

MIN_BREADTH = 5
BREADTH_STALE_DAYS = 7

METHOD = (
    "Each session is labelled with A3.5's regime rules evaluated on data stored on or before "
    "it: the index's close, 200-session average and volatility percentile, and breadth "
    "recomputed from stored daily bars (close above its own 200-session average, at least "
    f"{MIN_BREADTH} symbols judged). A day's return counts under the state known at the "
    "previous close."
)


@dataclass
class RegimeHistory:
    market: str | None
    index: str | None
    states: dict[date, str | None]
    index_sessions: int
    breadth_sessions: int
    reason: str | None


def _index_series(session: Session, index: str, end: date) -> tuple[list[date], list[float]]:
    rows = session.exec(
        select(col(PriceBar.ts), col(PriceBar.close))
        .where(PriceBar.instrument_id == instrument_of(index), PriceBar.interval == "1d")
        .order_by(col(PriceBar.ts))
    ).all()
    out_d: list[date] = []
    out_c: list[float] = []
    for ts, close in rows:
        if close is None or ts.date() > end:
            continue
        out_d.append(ts.date())
        out_c.append(float(close))
    return out_d, out_c


def _members(session: Session, market: str) -> list[str]:
    tickers = session.exec(select(Symbol.ticker).where(col(Symbol.is_active))).all()
    return sorted(t for t in tickers if not is_index_ticker(t) and market_for(t) == market)


_BREADTH_SQL = """
    SELECT d, SUM(CASE WHEN close > sma THEN 1 ELSE 0 END) AS above, COUNT(*) AS judged
    FROM (
        SELECT {day} AS d, close,
               AVG(close) OVER w AS sma, COUNT(*) OVER w AS n
        FROM price_bars
        WHERE interval = '1d' AND ticker IN :tickers AND ts >= :lo AND ts < :hi
        WINDOW w AS (PARTITION BY instrument_id ORDER BY ts
                     ROWS BETWEEN 199 PRECEDING AND CURRENT ROW)
    ) AS t
    WHERE n = 200 AND d >= :start
    GROUP BY d
    ORDER BY d
"""


def _breadth(
    session: Session, tickers: list[str], start: date, end: date
) -> dict[date, float | None]:
    if not tickers:
        return {}
    lo = start - timedelta(days=SMA_SESSIONS * 2 + 30)
    conn = session.connection()
    day = "DATE(ts)" if conn.dialect.name == "sqlite" else "CAST(ts AS DATE)"
    query = text(_BREADTH_SQL.format(day=day)).bindparams(bindparam("tickers", expanding=True))
    rows = conn.execute(
        query,
        {"tickers": tickers, "lo": lo, "hi": end + timedelta(days=1), "start": start},
    )
    out: dict[date, float | None] = {}
    for d, above, judged in rows:
        day = d if isinstance(d, date) else date.fromisoformat(str(d))
        out[day] = float(above) / float(judged) * 100 if judged >= MIN_BREADTH else None
    return out


def _index_values(closes: list[float]) -> tuple[list[float | None], list[float | None]]:
    """Per index date: the 200-session SMA and the volatility percentile, prefix only."""
    arr = np.asarray(closes, dtype=float)
    n = len(arr)
    sma: list[float | None] = [None] * n
    if n >= SMA_SESSIONS:
        csum = np.concatenate([[0.0], np.cumsum(arr)])
        for i in range(SMA_SESSIONS - 1, n):
            sma[i] = float((csum[i + 1] - csum[i + 1 - SMA_SESSIONS]) / SMA_SESSIONS)
    frame = engine.frame([(i, c, c, c, c, 0) for i, c in enumerate(closes)])
    hv = engine.hv(frame, VOL_SESSIONS)["value"].to_numpy(dtype=float)
    pct: list[float | None] = [None] * n
    seen: list[float] = []
    for i in range(n):
        if np.isnan(hv[i]):
            continue
        seen.append(float(hv[i]))
        window = np.asarray(seen[-VOL_WINDOW:])
        if len(window) >= MIN_VOL_HISTORY:
            pct[i] = float((window <= window[-1]).sum() / len(window) * 100)
    return sma, pct


def regime_history(session: Session, ticker: str, start: date, end: date) -> RegimeHistory:
    """States by index date for the market ``ticker`` trades in, over [start, end]."""
    market = market_for(ticker)
    index = dict(MARKETS).get(market) if market else None
    if market is None or index is None:
        return RegimeHistory(None, None, {}, 0, 0, "No regime is defined for this market.")
    dates, closes = _index_series(session, index, end)
    if not dates:
        return RegimeHistory(market, index, {}, 0, 0, f"No stored bars for {index}.")
    sma, pct = _index_values(closes)
    breadth = _breadth(session, _members(session, market), start, end)
    breadth_days = sorted(breadth)
    states: dict[date, str | None] = {}
    j = -1
    for i, d in enumerate(dates):
        if d < start - timedelta(days=BREADTH_STALE_DAYS):
            continue
        while j + 1 < len(breadth_days) and breadth_days[j + 1] <= d:
            j += 1
        b = (
            breadth[breadth_days[j]]
            if j >= 0 and (d - breadth_days[j]).days <= BREADTH_STALE_DAYS
            else None
        )
        state, _ = classify(
            {
                "index_close": closes[i],
                "index_sma_200": sma[i],
                "breadth_200": b,
                "vol_pct_20": pct[i],
            }
        )
        states[d] = state
    reason = None
    if not any(s is not None for s in states.values()):
        reason = (
            f"Not enough history: {index} needs 200 sessions for its average and 252 volatility "
            f"values, and breadth needs {MIN_BREADTH} symbols with 200 stored bars."
        )
    return RegimeHistory(market, index, states, len(dates), len(breadth), reason)


def states_on(history: RegimeHistory, days: list[date]) -> list[str | None]:
    """Each day's state: the newest index date on or before it (within a week)."""
    keys = sorted(history.states)
    out: list[str | None] = []
    j = -1
    for d in days:
        while j + 1 < len(keys) and keys[j + 1] <= d:
            j += 1
        out.append(
            history.states[keys[j]] if j >= 0 and (d - keys[j]).days <= BREADTH_STALE_DAYS else None
        )
    return out


__all__ = ["METHOD", "MIN_BREADTH", "RegimeHistory", "regime_history", "states_on"]
