"""Market regime badge (A3.5, M3.1): a rule-based state per market.

Three inputs per market (US: ``^GSPC``; India: ``^NSEI``):

- ``index_close`` and ``index_sma_200``: the index's latest close and its
  200-session simple average;
- ``breadth_200``: the percent of the market's active, non-index symbols
  (rows on the market's newest ``symbol_metrics`` date) whose close is above
  their own 200-session average (``symbol_metrics.sma_200``);
- ``vol_pct_20``: where the index's 20-session realised volatility
  (annualised, ``engine.hv``) sits among its daily values over the last
  ``VOL_WINDOW`` sessions (about five years), as a percentile 0-100
  (share of the window at or below today's value). No VIX: India VIX and US
  VIX are not ingested (a deferred data task).

The states are rules over those inputs, written in Rule DSL notation and
kept as data (``REGIME_RULES``), so the text shown on the badge is the text
evaluated. They are read in order with Kleene logic: the first rule met
gives the state; a rule that is unknown (an input missing) before any is
met makes the state unknown; ``Choppy`` is the rest. Descriptive only, never
advice. The research node's HMM (A9) may later add a "model" line.
"""

from __future__ import annotations

import operator
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date

import numpy as np
from sqlmodel import Session, col, select

from stockviz.models import PriceBar, Symbol, SymbolMetrics
from stockviz.services.indicators import engine
from stockviz.services.instruments import instrument_of, is_index_ticker
from stockviz.services.relative_strength import BENCHMARK_NAMES, MARKET_NAMES, market_for

VOL_WINDOW = 1260
"""Sessions of 20-day volatility the percentile ranks against (about 5 years)."""
MIN_VOL_HISTORY = 252
"""Fewer volatility values than this and the percentile is unknown."""
SMA_SESSIONS = 200
VOL_SESSIONS = 20

MARKETS: tuple[tuple[str, str], ...] = (("US", "^GSPC"), ("IN", "^NSEI"))

INPUTS: dict[str, str] = {
    "index_close": "The index's latest close.",
    "index_sma_200": "The index's 200-session simple moving average.",
    "breadth_200": "Percent of the market's symbols closing above their own 200-session average.",
    "vol_pct_20": (
        "Percentile (0-100) of the index's 20-session realised volatility "
        "among its last 1,260 sessions (about five years)."
    ),
}

_OPS: dict[str, Callable[[float, float], bool]] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}


@dataclass(frozen=True)
class Clause:
    left: str
    op: str
    right: str | float
    """Another input's name, or a number."""

    def text(self) -> str:
        right = self.right if isinstance(self.right, str) else f"{self.right:g}"
        return f"{self.left} {self.op} {right}"

    def evaluate(self, values: Mapping[str, float | None]) -> bool | None:
        left = values.get(self.left)
        right = values.get(self.right) if isinstance(self.right, str) else self.right
        if left is None or right is None:
            return None
        return _OPS[self.op](left, right)


@dataclass(frozen=True)
class RegimeRule:
    state: str
    clauses: tuple[Clause, ...]
    description: str

    def text(self) -> str:
        return " and ".join(c.text() for c in self.clauses) if self.clauses else "otherwise"

    def evaluate(self, values: Mapping[str, float | None]) -> bool | None:
        """Kleene ``and``: false if any clause is false, else unknown if any is."""
        results = [c.evaluate(values) for c in self.clauses]
        if any(r is False for r in results):
            return False
        if any(r is None for r in results):
            return None
        return True


CALM_TREND = "Calm trend"
CHOPPY = "Choppy"
HIGH_VOL_DOWN = "High-vol down"

REGIME_RULES: tuple[RegimeRule, ...] = (
    RegimeRule(
        HIGH_VOL_DOWN,
        (Clause("index_close", "<", "index_sma_200"), Clause("vol_pct_20", ">=", 80)),
        "The index is below its 200-session average and its volatility is in the top fifth "
        "of the last five years.",
    ),
    RegimeRule(
        CALM_TREND,
        (
            Clause("index_close", ">", "index_sma_200"),
            Clause("breadth_200", ">=", 50),
            Clause("vol_pct_20", "<", 60),
        ),
        "The index is above its 200-session average, at least half the market is above its own, "
        "and volatility is below the 60th percentile.",
    ),
    RegimeRule(CHOPPY, (), "Neither of the above."),
)

DISCLAIMER = "A description of recent market conditions from fixed rules. Not advice."


@dataclass
class MarketRegime:
    market: str
    name: str
    index: str
    index_name: str
    as_of: date | None
    state: str | None
    values: dict[str, float | None]
    breadth_count: int = 0
    breadth_universe: int = 0
    breadth_as_of: date | None = None
    vol_window_sessions: int = 0
    hv_20: float | None = None
    rules: list[tuple[RegimeRule, bool | None]] = field(default_factory=list)
    reason: str | None = None


def classify(
    values: Mapping[str, float | None],
) -> tuple[str | None, list[tuple[RegimeRule, bool | None]]]:
    """The state for a set of inputs, and each rule's result (Kleene)."""
    results: list[tuple[RegimeRule, bool | None]] = []
    state: str | None = None
    decided = False
    for rule in REGIME_RULES:
        result = rule.evaluate(values)
        results.append((rule, result))
        if decided:
            continue
        if result is True:
            state, decided = rule.state, True
        elif result is None:
            state, decided = None, True
    return state, results


def index_inputs(closes: list[float]) -> dict[str, float | int | None]:
    """Close, SMA 200, HV 20 and its percentile from the index's daily closes (oldest first)."""
    out: dict[str, float | int | None] = {
        "index_close": None,
        "index_sma_200": None,
        "hv_20": None,
        "vol_pct_20": None,
        "vol_window": 0,
    }
    if not closes:
        return out
    arr = np.asarray(closes, dtype=float)
    out["index_close"] = float(arr[-1])
    if len(arr) >= SMA_SESSIONS:
        out["index_sma_200"] = float(arr[-SMA_SESSIONS:].mean())
    frame = engine.frame([(i, c, c, c, c, 0) for i, c in enumerate(closes)])
    hv = engine.hv(frame, VOL_SESSIONS)["value"].to_numpy(dtype=float)
    hv = hv[~np.isnan(hv)]
    if len(hv):
        out["hv_20"] = float(hv[-1])
        window = hv[-VOL_WINDOW:]
        out["vol_window"] = len(window)
        if len(window) >= MIN_VOL_HISTORY:
            out["vol_pct_20"] = float((window <= window[-1]).sum() / len(window) * 100)
    return out


def _index_closes(session: Session, index: str) -> tuple[list[float], date | None]:
    rows = session.exec(
        select(col(PriceBar.ts), col(PriceBar.close))
        .where(PriceBar.instrument_id == instrument_of(index), PriceBar.interval == "1d")
        .order_by(col(PriceBar.ts).desc())
        .limit(VOL_WINDOW + VOL_SESSIONS + 1)
    ).all()
    rows = list(reversed(rows))
    return [float(c) for _, c in rows if c is not None], (rows[-1][0].date() if rows else None)


def _breadth(session: Session, market: str) -> tuple[float | None, int, int, date | None]:
    rows = session.exec(
        select(SymbolMetrics)
        .join(Symbol, col(Symbol.ticker) == col(SymbolMetrics.ticker))
        .where(Symbol.is_active)
    ).all()
    members = [
        r
        for r in rows
        if r.as_of and not is_index_ticker(r.ticker) and market_for(r.ticker) == market
    ]
    newest = max((r.as_of for r in members if r.as_of), default=None)
    judged = [
        r
        for r in members
        if r.as_of == newest and r.sma_200 is not None and r.last_close is not None
    ]
    above = sum(1 for r in judged if float(r.last_close or 0) > float(r.sma_200 or 0))
    pct = above / len(judged) * 100 if judged else None
    return pct, above, len(judged), newest


def market_regime(session: Session, market: str, index: str) -> MarketRegime:
    closes, as_of = _index_closes(session, index)
    inputs = index_inputs(closes)
    breadth, above, judged, breadth_as_of = _breadth(session, market)
    values: dict[str, float | None] = {
        "index_close": inputs["index_close"],  # pyright: ignore[reportAssignmentType]
        "index_sma_200": inputs["index_sma_200"],  # pyright: ignore[reportAssignmentType]
        "breadth_200": breadth,
        "vol_pct_20": inputs["vol_pct_20"],  # pyright: ignore[reportAssignmentType]
    }
    state, results = classify(values)
    missing = [k for k, v in values.items() if v is None]
    reason = None
    if state is None:
        reason = (
            f"Not enough data: {', '.join(missing)} unknown." if missing else "Not enough data."
        )
    return MarketRegime(
        market=market,
        name=MARKET_NAMES[market],
        index=index,
        index_name=BENCHMARK_NAMES[index],
        as_of=as_of,
        state=state,
        values=values,
        breadth_count=above,
        breadth_universe=judged,
        breadth_as_of=breadth_as_of,
        vol_window_sessions=int(inputs["vol_window"] or 0),
        hv_20=inputs["hv_20"],  # pyright: ignore[reportArgumentType]
        rules=results,
        reason=reason,
    )


# A small in-process cache: the inputs move once a night.
CACHE_SECONDS = 600
_cache: dict[str, tuple[float, list[MarketRegime]]] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def regimes(session: Session, *, use_cache: bool = True) -> list[MarketRegime]:
    now = time.monotonic()
    if use_cache:
        with _lock:
            hit = _cache.get("all")
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    out = [market_regime(session, market, index) for market, index in MARKETS]
    with _lock:
        _cache["all"] = (now, out)
    return out
