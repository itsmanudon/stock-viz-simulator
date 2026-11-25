"""The screener's Rule DSL step (A2.2, M4.3).

After the SQL filters (``services/screener.py``) pick the candidates, the rule
is judged for **every** candidate before any sort or page, in vector mode on
the symbol's own data (``dsl.evaluate_at``, the code the conformance suite
holds equal to point mode).

**Which bar.** Each venue (MIC) has one session for the whole screen: the
newest stored daily bar of any active symbol on that venue, on or before the
target date (``as_of``, else the venue's latest completed session). Every
symbol of the venue is judged on that session; one whose newest bar is
older is ``unknown`` ("no bar for 2026-11-24; latest 2026-11-20"), never
judged on stale prices. So a late or failed ingest for one symbol shows up,
and the screen never mixes two nights on one venue.

**Cache.** Results are kept in process per (rule hash, ticker, session
date) for ``CACHE_SECONDS``, bounded at ``CACHE_MAX`` entries (LRU). A new
session is a new key, so the nightly ingest needs no invalidation; a same-day
data repair shows after the TTL.

**User-scoped rules (A3.3).** A rule that reads drawings (``drawing()``,
``avwap()``) is judged on ``user_id``'s drawings (the signed-in caller, or a
saved screen's owner) and never cached: drawings change at any time, and one
user's result must never reach another.
"""

from __future__ import annotations

import threading
import time as clock
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import func
from sqlmodel import Session, col, select

from stockviz.models import PriceBar, Symbol
from stockviz.services.bars.resample import bar_date
from stockviz.services.dsl import CompiledRule, evaluate_at, load_symbol
from stockviz.services.instruments import instruments_of, is_index_ticker
from stockviz.services.markets.calendar import latest_completed_session, venue_for_ticker

CACHE_SECONDS = 15 * 60
CACHE_MAX = 50_000


@dataclass(frozen=True)
class RowRule:
    status: str  # met | not_met | unknown
    reason: str | None
    bar_date: date | None


@dataclass(frozen=True)
class RuleRun:
    results: dict[str, RowRule]
    sessions: dict[str, date]  # venue -> the session judged
    cached: bool  # every result came from the cache


class _Cache:
    def __init__(self) -> None:
        self._data: OrderedDict[tuple[str, str, date], tuple[float, RowRule]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple[str, str, date]) -> RowRule | None:
        with self._lock:
            hit = self._data.get(key)
            if hit is None:
                return None
            stamp, value = hit
            if clock.monotonic() - stamp > CACHE_SECONDS:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def put(self, key: tuple[str, str, date], value: RowRule) -> None:
        with self._lock:
            self._data[key] = (clock.monotonic(), value)
            self._data.move_to_end(key)
            while len(self._data) > CACHE_MAX:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


CACHE = _Cache()


def target_dates(venues: set[str], *, as_of: date | None, now: datetime) -> dict[str, date]:
    """Per venue: ``as_of`` capped at the latest completed session, or that session."""
    out: dict[str, date] = {}
    for venue in venues:
        latest = latest_completed_session(now, venue)
        out[venue] = min(as_of, latest) if as_of is not None else latest
    return out


def venue_sessions(session: Session, targets: dict[str, date]) -> dict[str, date]:
    """Per venue: the newest stored daily bar of its active symbols on or before its target."""
    tickers = session.exec(select(Symbol.ticker).where(col(Symbol.is_active))).all()
    by_venue: dict[str, list[str]] = {}
    for ticker in tickers:
        if is_index_ticker(ticker):
            continue
        venue = venue_for_ticker(ticker)
        if venue in targets:
            by_venue.setdefault(venue, []).append(ticker)
    out: dict[str, date] = {}
    for venue, names in by_venue.items():
        upper = datetime.combine(targets[venue] + timedelta(days=1), time.min)
        newest = session.exec(
            select(func.max(PriceBar.ts)).where(
                col(PriceBar.instrument_id).in_(instruments_of(names)),
                col(PriceBar.interval) == "1d",
                col(PriceBar.ts) < upper,
            )
        ).one()
        if newest is not None:
            out[venue] = bar_date(newest, venue)
    return out


def _judge(
    session: Session, rule: CompiledRule, ticker: str, day: date, user_id: int | None = None
) -> RowRule:
    data = load_symbol(
        session, ticker, end=day, start=day, lookback=rule.lookback, needs=rule.needs,
        user_id=user_id,
    )  # fmt: skip
    if data.bars.empty:
        return RowRule("unknown", f"no daily bars on or before {day.isoformat()}", None)
    last = data.dates[-1]
    if last != day:
        return RowRule("unknown", f"no bar for {day.isoformat()}; latest {last.isoformat()}", last)
    outcome, _rows = evaluate_at(rule, data, last)
    reason = "; ".join(outcome.reasons) if outcome.status == "unknown" else None
    if outcome.status == "unknown" and not reason:
        reason = "data the rule needs is missing"
    return RowRule(outcome.status, reason, last)


def evaluate_rule(
    session: Session,
    rule: CompiledRule,
    tickers: list[str],
    *,
    as_of: date | None,
    now: datetime,
    use_cache: bool = True,
    user_id: int | None = None,
) -> RuleRun:
    """The rule's result for each ticker, on its venue's session. ``user_id``
    owns the drawings a user-scoped rule reads (A3.3)."""
    use_cache = use_cache and not rule.user_scoped
    venues = {venue_for_ticker(t) for t in tickers}
    sessions = venue_sessions(session, target_dates(venues, as_of=as_of, now=now))
    results: dict[str, RowRule] = {}
    all_cached = bool(tickers)
    for ticker in tickers:
        venue = venue_for_ticker(ticker)
        day = sessions.get(venue)
        if day is None:
            results[ticker] = RowRule("unknown", "no daily bars on this venue yet", None)
            all_cached = False
            continue
        key = (rule.hash, ticker, day)
        hit = CACHE.get(key) if use_cache else None
        if hit is None:
            all_cached = False
            hit = _judge(session, rule, ticker, day, user_id)
            if use_cache:
                CACHE.put(key, hit)
        results[ticker] = hit
    return RuleRun(results, sessions, all_cached)


__all__ = ["CACHE", "CACHE_SECONDS", "RowRule", "RuleRun", "evaluate_rule", "venue_sessions"]
