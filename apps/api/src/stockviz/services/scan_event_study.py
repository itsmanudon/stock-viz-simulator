"""Scan event study (A4.5, M7.3): what followed a Rule DSL trigger.

Any condition can be the trigger: a setup version or inline text, including
Aegis news (``news.count(1) >= 1``) and delivery (``delivery_pct > 60``)
rules. The measuring is A2.4's evidence engine
(``checklist/evidence.py::study_horizons``), the code that grades the
checklist and the indicator badges, run with several horizons and an
optional cooldown:

- **Event:** the first bar the rule is true after a bar it was false (the
  edge, not every true bar), in vector mode (conformance-proven equal to
  point mode, so no value reads a later bar). A bar after an unknown one is
  not an event. With a cooldown of N sessions, an edge within N bars of the
  previous event on its symbol is skipped.
- **Outcome:** the close-to-close return over 5, 20 and 60 stored sessions
  from the event's close, net of a round trip under the venue's schedule
  (A2.4's mapping: US ``us_equity``, NSE/BSE equity delivery) at the
  version in force on each leg's date (A4.2), on a 100,000 position.
  Dividends are not added. An event without the full window is
  ``incomplete`` for that horizon.
- **Base rate:** the mean forward return (before costs) of every symbol of
  the same universe and market on the same date; excess = net - base.
- **Statistics:** n, mean and median net and excess, hit rates (net > 0;
  excess > 0), percentiles and a histogram, the t-statistic of the mean
  excess (A2.4's: sample standard deviation), and a second t with the
  standard error clustered by event date (events on one date share the
  market's move). Under 30 events (A2.4's ``MIN_EVENTS``) only counts.

Data is cut at the window's end before anything is computed. The universe
is the pinned list with today's provider history: survivorship-biased.
Association, not cause.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

import numpy as np
from sqlmodel import Session, col, select

from stockviz import _time
from stockviz.models import Symbol
from stockviz.models.watchlist import Watchlist, WatchlistItem
from stockviz.schemas import (
    HistogramOut,
    ScanEventOut,
    ScanEventStudyIn,
    ScanEventStudyOut,
    ScanHorizonOut,
    ScanPercentilesOut,
    ScanTriggerOut,
    ScanUniverseIn,
    ScanUniverseSourceOut,
)
from stockviz.services.backtest.strategy_run import (
    StrategyNeedsUser,
    StrategyNotFound,
    _resolve_rule,
)
from stockviz.services.backtest.universe import evidence_universe
from stockviz.services.checklist.evidence import (
    MIN_EVENTS,
    WINDOW_YEARS,
    StudyResult,
    study_horizons,
)
from stockviz.services.dsl import load_symbol
from stockviz.services.instruments import is_index_ticker
from stockviz.services.markets.calendar import (
    INDIAN_VENUES,
    latest_completed_session,
    venue_for_ticker,
)
from stockviz.services.setups.rules import uses

MAX_MARKET_SYMBOLS = 300
MAX_EVENTS_SHOWN = 200
HISTOGRAM_BINS = 20
DISCLAIMER = (
    "Association, not cause: what followed the trigger in past data, net of modelled "
    "costs, on a survivorship-biased universe. Not a forecast and not advice."
)
METHOD = {
    "event": (
        "The first session the rule is true after a session it was false (vector mode; a "
        "session after an unknown one is not an event). Cooldown N: an event within N "
        "sessions of the previous event on its symbol is skipped."
    ),
    "outcome": (
        "Close-to-close return over each horizon of stored sessions from the event's close, "
        "minus a round trip under the venue's fee schedule at the version in force on each "
        "leg's date (US: us_equity; NSE/BSE: equity delivery), on a 100,000 position. "
        "Dividends not added."
    ),
    "base_rate": (
        "The mean forward return, before costs, of every symbol in the same universe and "
        "market on the same date (all symbol-days). Excess = net return - base rate."
    ),
    "t_stat": (
        "Mean excess / (sample standard deviation / sqrt(n)), as the checklist's evidence "
        "grade. The clustered t uses a standard error clustered by event date "
        "(sqrt(G/(G-1) x sum over dates of the summed deviations squared) / n)."
    ),
    "minimum": f"Under {MIN_EVENTS} events a horizon shows its counts only.",
}


class ScanStudyError(ValueError):
    """The study cannot run as asked (a 400)."""


def _market_of(ticker: str) -> str:
    return "IN" if venue_for_ticker(ticker) in INDIAN_VENUES else "US"


def _universe(
    session: Session, body: ScanEventStudyIn, user_id: int | None
) -> tuple[list[str], ScanUniverseSourceOut]:
    return resolve_universe(session, body.universe, user_id)


def resolve_universe(
    session: Session, u: ScanUniverseIn, user_id: int | None
) -> tuple[list[str], ScanUniverseSourceOut]:
    """Tickers, a watchlist or a market (the study's and A4.7's drills')."""
    if u.tickers is not None:
        tickers = list(dict.fromkeys(t.strip().upper() for t in u.tickers if t.strip()))
        if not tickers:
            raise ScanStudyError("The ticker list is empty")
        for t in tickers:
            if session.get(Symbol, t) is None:
                raise StrategyNotFound(f"Symbol {t!r} not found")
            if is_index_ticker(t):
                raise ScanStudyError(f"{t} is an index")
        return tickers, ScanUniverseSourceOut(kind="list", tickers=len(tickers))
    if u.watchlist_id is not None:
        if user_id is None:
            raise StrategyNeedsUser("Sign in to study a watchlist")
        wl = session.get(Watchlist, u.watchlist_id)
        if wl is None or wl.user_id != user_id:
            raise StrategyNotFound(f"Watchlist {u.watchlist_id} not found")
        rows = session.exec(
            select(WatchlistItem)
            .where(col(WatchlistItem.watchlist_id) == wl.id)
            .order_by(col(WatchlistItem.added_at), col(WatchlistItem.ticker))
        ).all()
        tickers = [r.ticker.upper() for r in rows if not is_index_ticker(r.ticker)]
        if not tickers:
            raise ScanStudyError(f"Watchlist {wl.name!r} is empty")
        return tickers, ScanUniverseSourceOut(
            kind="watchlist", name=wl.name, watchlist_id=wl.id, tickers=len(tickers)
        )
    assert u.market is not None
    active = session.exec(select(Symbol.ticker).where(col(Symbol.is_active))).all()
    tickers = sorted(t for t in active if not is_index_ticker(t) and _market_of(t) == u.market)
    if not tickers:
        raise ScanStudyError(f"No active symbols in market {u.market}")
    if len(tickers) > MAX_MARKET_SYMBOLS:
        raise ScanStudyError(
            f"Market {u.market} has {len(tickers)} symbols, more than {MAX_MARKET_SYMBOLS}: "
            "study a watchlist or a list instead"
        )
    name = "US listings" if u.market == "US" else "Indian listings (NSE, BSE)"
    return tickers, ScanUniverseSourceOut(
        kind="market", market=u.market, name=name, tickers=len(tickers)
    )


def _percentiles(values: np.ndarray) -> ScanPercentilesOut:
    p = np.percentile(values, [5, 25, 50, 75, 95])
    return ScanPercentilesOut(p5=_r(p[0]), p25=_r(p[1]), p50=_r(p[2]), p75=_r(p[3]), p95=_r(p[4]))


def _histogram(values: np.ndarray) -> HistogramOut:
    lo, hi = np.percentile(values, [1, 99])
    if not hi > lo:
        lo, hi = float(values.min()), float(values.max())
    if not hi > lo:
        hi = lo + 1e-9
    edges = np.linspace(lo, hi, HISTOGRAM_BINS + 1)
    counts, _ = np.histogram(np.clip(values, lo, hi), bins=edges)
    return HistogramOut(edges=[_r(e) for e in edges], counts=[int(c) for c in counts])


def clustered_t(values: list[float], clusters: list[date]) -> tuple[float | None, int]:
    """Mean / standard error clustered by ``clusters`` (CR1, G/(G-1)); None
    with fewer than two clusters or no spread."""
    n = len(values)
    groups: dict[date, float] = {}
    if n < 2:
        return None, len(set(clusters))
    mean = sum(values) / n
    for v, c in zip(values, clusters, strict=True):
        groups[c] = groups.get(c, 0.0) + (v - mean)
    g = len(groups)
    if g < 2:
        return None, g
    var = g / (g - 1) * sum(s * s for s in groups.values()) / (n * n)
    if var <= 0 or not math.isfinite(var):
        return None, g
    return float(mean / math.sqrt(var)), g


def _r(value: float) -> float:
    return round(float(value), 6)


def horizon_out(result: StudyResult) -> ScanHorizonOut:
    n = result.n
    enough = n >= MIN_EVENTS
    out = ScanHorizonOut(
        horizon=result.horizon,
        n=n,
        symbols=len({e.ticker for e in result.events}),
        incomplete=result.incomplete,
        overlapping=result.overlapping,
        enough=enough,
        base_rate=_r(result.base_rate) if result.base_rate is not None else None,
        fee_schedules=dict(result.fee_schedules),
    )
    if not enough:
        return out
    net = np.array([e.net for e in result.events])
    excess = np.array([e.excess for e in result.events])
    t_c, clusters = clustered_t([float(x) for x in excess], [e.day for e in result.events])
    t = result.t_stat
    return out.model_copy(
        update={
            "mean_net": _r(net.mean()),
            "median_net": _r(np.median(net)),
            "mean_excess": _r(excess.mean()),
            "median_excess": _r(np.median(excess)),
            "hit_rate": _r((net > 0).mean()),
            "hit_rate_excess": _r((excess > 0).mean()),
            "t_stat": round(t, 4) if t is not None else None,
            "t_stat_clustered": round(t_c, 4) if t_c is not None else None,
            "clusters": clusters,
            "net_percentiles": _percentiles(net),
            "excess_percentiles": _percentiles(excess),
            "histogram": _histogram(net),
        }
    )


def run_scan_event_study(
    session: Session, body: ScanEventStudyIn, *, user_id: int | None, now: datetime | None = None
) -> ScanEventStudyOut:
    """Raises ``StrategyNotFound``, ``StrategyNeedsUser``, ``ScanStudyError``
    or ``RuleError``."""
    rule = _resolve_rule(session, body.trigger, "trigger", user_id)
    tickers, source = _universe(session, body, user_id)
    now = now or _time.utcnow()
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    end = body.to or latest_completed_session(now, venue_for_ticker(tickers[0]))
    start = body.from_ or end - timedelta(days=365 * WINDOW_YEARS)
    if start > end:
        raise ScanStudyError("'from' must be on or before 'to'")
    compiled = rule.compiled
    lookback = None if compiled.lookback is None else compiled.lookback + 1
    datasets = [
        load_symbol(
            session,
            t,
            end=end,
            start=start,
            lookback=lookback,
            needs=compiled.needs,
            user_id=user_id,
        )
        for t in tickers
    ]
    horizons = tuple(body.horizons)
    results = study_horizons(
        datasets, compiled, start=start, end=end, horizons=horizons, cooldown=body.cooldown,
        dated_costs=True,
    )  # fmt: skip
    by_event: dict[tuple[str, date], ScanEventOut] = {}
    for h in horizons:
        for e in results[h].events:
            key = (e.ticker, e.day)
            row = by_event.get(key)
            if row is None:
                row = ScanEventOut(
                    ticker=e.ticker,
                    date=e.day,
                    net={str(x): None for x in horizons},
                    excess={str(x): None for x in horizons},
                )
                by_event[key] = row
            row.net[str(h)] = _r(e.net)
            row.excess[str(h)] = _r(e.excess)
    # Events found = counted for the shortest horizon plus its incomplete ones.
    shortest = results[horizons[0]]
    found = shortest.n + shortest.incomplete
    events = sorted(by_event.values(), key=lambda r: (r.date, r.ticker), reverse=True)
    return ScanEventStudyOut(
        trigger=ScanTriggerOut(
            text=compiled.text,
            canonical=compiled.canonical_text,
            hash=compiled.hash,
            setup_version_id=rule.version_id,
            uses=uses(compiled),
            warmup_bars=compiled.lookback,
        ),
        source=source,
        from_=start,
        to=end,
        cooldown=body.cooldown,
        horizons=[horizon_out(results[h]) for h in horizons],
        min_events=MIN_EVENTS,
        events_found=found,
        events_skipped_cooldown=shortest.overlapping_skipped,
        events=events[:MAX_EVENTS_SHOWN],
        events_shown=min(len(events), MAX_EVENTS_SHOWN),
        method=METHOD,
        universe=evidence_universe(),
        disclaimer=DISCLAIMER,
    )


__all__ = [
    "DISCLAIMER",
    "MAX_MARKET_SYMBOLS",
    "ScanStudyError",
    "clustered_t",
    "horizon_out",
    "resolve_universe",
    "run_scan_event_study",
]
