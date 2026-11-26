"""A ``SimulatedFeed`` replay through the stream worker (A6.5).

A replay streams stored minutes of one feed (``file``: the owner's local
files; ``iex``/``sip``: US minutes) through the same worker a live feed uses.
Its bars are written as feed ``replayed`` and its firings carry
``feed = replayed``: never called live.

**Warm-up.** A rule needs bars before the first one it judges (``rsi(14)``
needs 14). The replayed feed starts empty, so before streaming, the source
bars of the sessions before the window are copied into it unjudged
(:func:`~stockviz.services.stream.worker.prime_replayed`): enough sessions for
the longest rule among the symbols' alerts, at least
:data:`MIN_WARMUP_SESSIONS`. With the same bars, a replayed alert gives the
same answer as A6.4's judgement over the stored source bars and as the
backtest.

**Symbols.** The ones named, or else the watched symbols (:func:`watched`):
those of active intraday alerts first, then watchlists, capped.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, col, select

from stockviz.models import WatchlistItem
from stockviz.services.alerts.intraday import intraday_alerts
from stockviz.services.bars.intraday import INTERVAL_MINUTES
from stockviz.services.dsl import RuleError, compile_rule
from stockviz.services.feeds.simulated import SimulatedFeed
from stockviz.services.markets.calendar import (
    previous_session,
    session_minutes,
    venue_for_ticker,
    venue_zone,
)
from stockviz.services.stream.worker import prime_replayed

MIN_WARMUP_SESSIONS = 2
SESSION_MINUTES_FLOOR = 375
"""The shortest regular session counted for warm-up (NSE, 6 h 15 min)."""
DEFAULT_SYMBOL_CAP = 30


def watched(session: Session, *, limit: int = DEFAULT_SYMBOL_CAP) -> list[str]:
    """Alert symbols first (intraday rule alerts), then watchlist symbols."""
    out: list[str] = []
    for alert, _version in intraday_alerts(session):
        if alert.ticker and alert.ticker not in out:
            out.append(alert.ticker)
    rows = session.exec(
        select(WatchlistItem.ticker).distinct().order_by(col(WatchlistItem.ticker))
    ).all()
    for ticker in rows:
        if ticker and ticker not in out:
            out.append(ticker)
    return out[:limit]


def warmup_sessions(session: Session, tickers: Sequence[str]) -> int:
    """Sessions of warm-up the symbols' intraday alerts need."""
    need = 0
    wanted = {t.upper() for t in tickers}
    for alert, version in intraday_alerts(session):
        if (alert.ticker or "").upper() not in wanted:
            continue
        try:
            rule = compile_rule(version.rule_text, timeframe=version.timeframe)
        except RuleError:
            continue
        minutes = (rule.lookback or 0) * INTERVAL_MINUTES.get(version.timeframe, 1)
        need = max(need, math.ceil(minutes / SESSION_MINUTES_FLOOR) + 1)
    return max(need, MIN_WARMUP_SESSIONS)


def warmup_start(ticker: str, start: datetime, sessions: int) -> datetime:
    """The open of the session ``sessions`` before the one ``start`` is in."""
    venue = venue_for_ticker(ticker)
    day = start.astimezone(venue_zone(venue)).date()
    for _ in range(sessions):
        day = previous_session(day, venue)
    hours = session_minutes(day, venue)
    return hours.open if hours is not None else start - timedelta(days=sessions * 2 + 4)


@dataclass(frozen=True)
class ReplayPlan:
    feed: SimulatedFeed
    tickers: list[str]
    primed: int
    bars: int


def plan_replay(
    session: Session,
    tickers: Sequence[str],
    *,
    source_feed: str,
    start: datetime,
    end: datetime,
    speed: float = 0.0,
) -> ReplayPlan:
    """Prime the warm-up and load the window's bars (commits the warm-up)."""
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    upper = [t.upper() for t in tickers]
    sessions = warmup_sessions(session, upper)
    primed = 0
    for ticker in upper:
        lo = warmup_start(ticker, start, sessions)
        warm = SimulatedFeed.from_store(session, [ticker], feed=source_feed, start=lo, end=start)
        primed += prime_replayed(session, warm.bars, source=f"replay_{source_feed}")
    session.commit()
    feed = SimulatedFeed.from_store(
        session, upper, feed=source_feed, start=start, end=end, speed=speed
    )
    return ReplayPlan(feed=feed, tickers=upper, primed=primed, bars=len(feed.bars))
