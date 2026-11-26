"""Relative strength percentile and distance from the 52-week high (A3.5, M2.7).

**Universe.** A symbol is ranked against the other active, non-index symbols
of its market: the ones that share its venue index (``^GSPC`` for US
listings, ``^NSEI`` for NSE and BSE, ``event_study.BENCHMARK_BY_VENUE``). The
universe is today's symbol list, not a point-in-time one, so it is
survivorship-biased, and the response says so. Only rows computed on the
market's newest metrics date count, so a symbol whose prices stalled neither
ranks nor is ranked.

**Method.** The nightly ``metrics`` job stores each symbol's price return
over 21, 63, 126 and 252 sessions (``symbol_metrics.return_*``). Within one
market every symbol is divided by the same index, so ranking the returns
ranks the RS line's change over the same horizon. The percentile is the
share of the other members with a lower return, ties counting half:
``100 * (below + 0.5 * tied) / (n - 1)``. It is null with fewer than
``MIN_UNIVERSE`` members holding a return.

Read on request from ``symbol_metrics`` (one query of the market's rows).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlmodel import Session, col, select

from stockviz.models import Symbol, SymbolMetrics
from stockviz.services.event_study import benchmark_for
from stockviz.services.instruments import is_index_ticker
from stockviz.services.markets.calendar import venue_for_ticker

MIN_UNIVERSE = 5
"""Fewer members than this and a percentile says nothing; it is left null."""

PERIODS: tuple[tuple[str, str, int], ...] = (
    ("1m", "return_1m", 21),
    ("3m", "return_3m", 63),
    ("6m", "return_6m", 126),
    ("12m", "return_12m", 252),
)

MARKET_BY_BENCHMARK = {"^GSPC": "US", "^NSEI": "IN"}
MARKET_NAMES = {"US": "US", "IN": "India"}
BENCHMARK_NAMES = {"^GSPC": "S&P 500", "^NSEI": "Nifty 50"}

UNIVERSE_NOTE = "Current symbol list, not point in time: survivorship-biased."


def market_for(ticker: str) -> str | None:
    """``US`` or ``IN`` for a ticker whose venue has an index; else None."""
    bench = benchmark_for(ticker)
    return MARKET_BY_BENCHMARK.get(bench) if bench else None


def is_indian(ticker: str) -> bool:
    return venue_for_ticker(ticker) in ("XNSE", "XBOM")


@dataclass(frozen=True)
class PeriodStrength:
    period: str
    sessions: int
    return_pct: float | None
    percentile: float | None


@dataclass
class RelativeStrength:
    ticker: str
    market: str | None
    benchmark: str | None
    as_of: date | None
    universe_size: int = 0
    periods: list[PeriodStrength] = field(default_factory=list)
    high_52w: float | None = None
    last_close: float | None = None
    distance_from_high_pct: float | None = None
    reason: str | None = None


def percentile(value: float, others: list[float]) -> float | None:
    """Share of ``others`` below ``value`` (ties half), 0-100."""
    if len(others) + 1 < MIN_UNIVERSE:
        return None
    below = sum(1 for o in others if o < value)
    tied = sum(1 for o in others if o == value)
    return 100 * (below + 0.5 * tied) / len(others)


def relative_strength(session: Session, ticker: str) -> RelativeStrength:
    ticker = ticker.upper()
    market = market_for(ticker)
    bench = benchmark_for(ticker)
    rows = list(
        session.exec(
            select(SymbolMetrics)
            .join(Symbol, col(Symbol.ticker) == col(SymbolMetrics.ticker))
            .where(Symbol.is_active)
        ).all()
    )
    own = next((r for r in rows if r.ticker == ticker), None)
    out = RelativeStrength(
        ticker=ticker, market=market, benchmark=bench, as_of=own.as_of if own else None
    )
    if own is not None and own.high_52w is not None and own.last_close is not None:
        out.high_52w = float(own.high_52w)
        out.last_close = float(own.last_close)
        if out.high_52w > 0:
            out.distance_from_high_pct = (out.last_close / out.high_52w - 1) * 100

    if market is None:
        out.reason = "No index for this symbol's market, so no universe to rank against."
        out.periods = [PeriodStrength(p, n, None, None) for p, _, n in PERIODS]
        return out
    members = [
        r
        for r in rows
        if not is_index_ticker(r.ticker) and market_for(r.ticker) == market and r.as_of
    ]
    newest = max((r.as_of for r in members if r.as_of), default=None)
    universe = [r for r in members if r.as_of == newest]
    out.universe_size = len(universe)
    ranked = own is not None and own.as_of == newest
    if own is None:
        out.reason = "No metrics for this symbol yet."
    elif not ranked:
        out.reason = (
            "This symbol's latest metrics are older than its market's, so it is not ranked."
        )
    for period, column, sessions in PERIODS:
        value = getattr(own, column) if own is not None else None
        pct = None
        if ranked and value is not None:
            others = [
                getattr(r, column)
                for r in universe
                if r.ticker != ticker and getattr(r, column) is not None
            ]
            pct = percentile(value, others)
        out.periods.append(PeriodStrength(period, sessions, value, pct))
    if ranked and newest is not None:
        out.as_of = newest
    return out
