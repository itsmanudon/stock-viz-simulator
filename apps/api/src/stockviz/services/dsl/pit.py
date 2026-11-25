"""Point-in-time bindings for the Rule DSL (A2.1): fundamentals and news.

Both are pure: they hold rows loaded once per symbol and answer for every
daily bar at once.

**Fundamentals.** ``fundamental.<metric>`` on a bar dated ``d`` is what
``services/fundamentals/valuation.py::valuation(ticker, d)`` returns: the
facts with ``available_at <= d`` (the version known that day, EDGAR over
yfinance, as ``facts_as_of``), the TTM and balance-sheet rules of
``valuation.ttm`` / ``latest_stock``, that bar's close converted into the
reporting currency at the FX rate on or before ``d``, and growth against
the facts known 365 days earlier. ``tests/test_dsl_data.py`` holds the two
equal on a database. The work is done once per *known state* (a distinct
``available_at`` date) instead of once per bar; only price-dependent
metrics are per bar.

**News.** ``news.count(n, sentiment=, event_type=)`` on a bar is the number
of the symbol's Aegis documents with ``available_at`` in the ``n`` days up
to and including that session's close (never ``published_at``, AG-12). A
sentiment filter uses the document's newest sentiment analysis available by
that close; an event-type filter needs an event of that type available by
then. Bars before the first document StockViz holds from Aegis (any
symbol) are unknown: there was no news coverage to count.
"""

# pyright: reportArgumentType=false, reportCallIssue=false, reportIndexIssue=false

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast

import numpy as np

from stockviz.services.fundamentals.store import SOURCE_RANK
from stockviz.services.fundamentals.valuation import latest_stock, ttm

# --- fundamentals -----------------------------------------------------------


@dataclass(frozen=True)
class Fact:
    concept: str
    period_type: str
    period_end: date
    value: Decimal
    available_at: date
    source: str
    currency: str | None = None
    point_in_time: bool = False


Known = dict[str, dict[tuple[str, str, date], Fact]]
"""concept -> (concept, period type, period end) -> the version known."""

_FLOWS = (
    "revenue",
    "net_income",
    "gross_profit",
    "operating_income",
    "ebitda",
    "operating_cash_flow",
    "capex",
    "free_cash_flow",
    "dividends_paid",
)
_STOCKS = (
    "equity",
    "cash",
    "total_debt",
    "total_assets",
    "current_assets",
    "current_liabilities",
    "shares_outstanding",
)
_NAN = float("nan")


def _f(value: Decimal | None) -> float:
    return float(value) if value is not None else _NAN


@dataclass
class _State:
    """Price-free components of one known state (NaN where valuation has None)."""

    has_facts: bool
    reporting_currency: str | None
    values: dict[str, float]


def _components(known: Known) -> _State:
    def flow(concept: str):
        return ttm(cast(Any, known.get(concept, {})), concept)

    values: dict[str, float] = {}
    used: list[Fact] = []
    for concept in _FLOWS:
        value, _basis, facts = flow(concept)
        values[concept] = _f(value)
        if concept in ("revenue", "net_income"):
            used.extend(cast(list[Fact], facts))
    if np.isnan(values["free_cash_flow"]) and not np.isnan(
        values["operating_cash_flow"] + values["capex"]
    ):
        ocf, _b, _u = flow("operating_cash_flow")
        capex, _b, _u = flow("capex")
        if ocf is not None and capex is not None:
            values["free_cash_flow"] = float(ocf - capex)
    for concept in _STOCKS:
        fact = cast(Fact | None, latest_stock(cast(Any, known.get(concept, {})), concept))
        values[concept] = _f(fact.value) if fact is not None else _NAN
        if fact is not None and concept in (
            "equity",
            "cash",
            "total_debt",
            "total_assets",
            "shares_outstanding",
        ):
            used.append(fact)
    currencies = {f.currency for f in used if f.currency}
    return _State(
        has_facts=any(known.values()),
        reporting_currency=currencies.pop() if len(currencies) == 1 else None,
        values=values,
    )


def _nz(x: np.ndarray) -> np.ndarray:
    return np.where(np.isnan(x), 0.0, x)


def _ratio(num: np.ndarray, den: np.ndarray, positive: bool = False) -> np.ndarray:
    ok = ~np.isnan(num) & ~np.isnan(den) & (den != 0)
    if positive:
        ok &= den > 0
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(ok, num / np.where(ok, den, 1.0), _NAN)


@dataclass(frozen=True)
class Fundamentals:
    """A symbol's facts and FX rates; ``series`` answers per bar."""

    facts: tuple[Fact, ...]
    trading_currency: str = "USD"
    fx: dict[str, tuple[tuple[date, Decimal], ...]] = field(default_factory=dict)
    """currency -> (date, USD per unit), oldest first."""

    def cut(self, day: date) -> Fundamentals:
        """Only what was known on ``day``."""
        return Fundamentals(
            tuple(f for f in self.facts if f.available_at <= day),
            self.trading_currency,
            {c: tuple(r for r in rows if r[0] <= day) for c, rows in self.fx.items()},
        )

    # The known states: state 0 knows nothing, state k the facts available on
    # or before the k-th distinct available_at date.
    def _states(self) -> tuple[np.ndarray, list[_State]]:
        ordered = sorted(self.facts, key=lambda f: f.available_at)
        dates: list[date] = []
        states = [_components({})]
        best: Known = {}
        i = 0
        while i < len(ordered):
            day = ordered[i].available_at
            changed: dict[str, dict] = {}
            while i < len(ordered) and ordered[i].available_at == day:
                fact = ordered[i]
                if fact.period_type in ("annual", "quarter", "instant"):
                    bucket = changed.get(fact.concept)
                    if bucket is None:
                        bucket = dict(best.get(fact.concept, {}))
                        changed[fact.concept] = bucket
                    key = (fact.concept, fact.period_type, fact.period_end)
                    held = bucket.get(key)
                    rank = (SOURCE_RANK.get(fact.source, 0), fact.available_at)
                    if held is None or rank > (SOURCE_RANK.get(held.source, 0), held.available_at):
                        bucket[key] = fact
                i += 1
            best = {**best, **changed}
            dates.append(day)
            states.append(_components(best))
        return np.array(dates, dtype="datetime64[D]"), states

    def _rate(self, currency: str, days: np.ndarray) -> np.ndarray:
        if currency == "USD":
            return np.ones(len(days))
        rows = self.fx.get(currency, ())
        if not rows:
            return np.full(len(days), _NAN)
        rdates = np.array([r[0] for r in rows], dtype="datetime64[D]")
        rates = np.array([float(r[1]) for r in rows])
        idx = np.searchsorted(rdates, days, side="right") - 1
        return np.where(idx >= 0, rates[np.maximum(idx, 0)], _NAN)

    def table(self, days: Sequence[date] | np.ndarray, close: np.ndarray) -> _Table:
        """Every metric for bars dated ``days`` with closes ``close``."""
        days = np.asarray(days, dtype="datetime64[D]")
        state_dates, states = self._states()
        s_now = np.searchsorted(state_dates, days, side="right")
        s_ago = np.searchsorted(state_dates, days - np.timedelta64(365, "D"), side="right")

        def comp(name: str, idx: np.ndarray = s_now) -> np.ndarray:
            return np.array([states[k].values[name] for k in range(len(states))])[idx]

        fx = np.full(len(days), _NAN)
        reps = np.array([states[k].reporting_currency or "" for k in range(len(states))])[s_now]
        for rep in set(reps.tolist()):
            if not rep:
                continue
            mask = reps == rep
            if rep == self.trading_currency:
                fx[mask] = 1.0
            else:
                with np.errstate(divide="ignore", invalid="ignore"):
                    fx[mask] = self._rate(self.trading_currency, days[mask]) / self._rate(
                        rep, days[mask]
                    )
        price = np.asarray(close, dtype=float) * fx
        shares = comp("shares_outstanding")
        ok = ~np.isnan(price) & ~np.isnan(shares) & (shares != 0)
        mcap = np.where(ok, price * np.where(ok, shares, 0), _NAN)
        debt, cash, equity = comp("total_debt"), comp("cash"), comp("equity")
        ev = mcap + _nz(debt) - _nz(cash)
        revenue, ni = comp("revenue"), comp("net_income")
        gross, op = comp("gross_profit"), comp("operating_income")
        invested = np.where(~np.isnan(equity) & ~np.isnan(debt), equity + debt - _nz(cash), _NAN)
        dividends = comp("dividends_paid")
        values = {
            "market_cap": mcap,
            "enterprise_value": ev,
            "pe": _ratio(mcap, ni, True),
            "pb": _ratio(mcap, equity, True),
            "ps": _ratio(mcap, revenue, True),
            "ev_ebitda": _ratio(ev, comp("ebitda"), True),
            "ev_revenue": _ratio(ev, revenue, True),
            "p_fcf": _ratio(mcap, comp("free_cash_flow"), True),
            "dividend_yield": _ratio(dividends, mcap) * 100,
            "gross_margin": _ratio(gross, revenue, True) * 100,
            "operating_margin": _ratio(op, revenue, True) * 100,
            "net_margin": _ratio(ni, revenue, True) * 100,
            "roe": _ratio(ni, equity, True) * 100,
            "roa": _ratio(ni, comp("total_assets"), True) * 100,
            "roic_pretax": _ratio(op, invested, True) * 100,
            "debt_to_equity": _ratio(debt, equity, True),
            "current_ratio": _ratio(comp("current_assets"), comp("current_liabilities"), True),
            "payout_ratio": _ratio(dividends, ni, True) * 100,
        }
        for key in ("revenue", "net_income"):
            now, then = comp(key), comp(key, s_ago)
            values[f"{key}_growth"] = _ratio(now - then, then, True) * 100
        return _Table(values, price, shares, ni, equity, [states[k].has_facts for k in s_now])

    def series(self, metric: str, days: Sequence[date] | np.ndarray, close: np.ndarray):
        return self.table(days, close).values[metric]


@dataclass
class _Table:
    values: dict[str, np.ndarray]
    price: np.ndarray
    shares: np.ndarray
    net_income: np.ndarray
    equity: np.ndarray
    has_facts: list[bool]

    _SPECIFIC = {  # noqa: RUF012
        "ps": "no revenue",
        "ev_ebitda": "no EBITDA",
        "ev_revenue": "no revenue",
        "p_fcf": "no free cash flow",
        "dividend_yield": "no dividends reported",
        "gross_margin": "no gross profit",
        "operating_margin": "no operating income",
        "net_margin": "no net income",
        "roe": "no equity",
        "roa": "no assets",
        "roic_pretax": "no equity or debt",
        "debt_to_equity": "no debt or equity",
        "current_ratio": "no current assets or liabilities",
        "payout_ratio": "no dividends or net income",
        "revenue_growth": "no figure a year earlier",
        "net_income_growth": "no figure a year earlier",
    }

    def reason(self, metric: str, i: int, day: date) -> str | None:
        """Why ``metric`` is missing on bar ``i`` (valuation's wording)."""
        if not np.isnan(self.values[metric][i]):
            return None
        if not self.has_facts[i]:
            return f"no fundamentals known on {day.isoformat()}"
        missing_price = "no close or FX rate" if np.isnan(self.price[i]) else None
        shares = self.shares[i]
        missing_shares = "no shares outstanding" if np.isnan(shares) or shares == 0 else None
        priced = missing_price or missing_shares
        if metric in ("market_cap", "enterprise_value"):
            return priced or "inputs missing"
        if metric == "pe":
            ni = self.net_income[i]
            return "loss" if not np.isnan(ni) and ni < 0 else priced or "no net income"
        if metric == "pb":
            return priced or ("no equity" if np.isnan(self.equity[i]) else "negative equity")
        specific = self._SPECIFIC[metric]
        if metric in ("ps", "ev_ebitda", "ev_revenue", "p_fcf", "dividend_yield"):
            return priced or specific
        return specific


# --- news -------------------------------------------------------------------

_NS_PER_DAY = 86_400 * 1_000_000_000


def to_ns(when: datetime) -> int:
    """An aware (or naive UTC) datetime as UTC epoch nanoseconds."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return int(when.timestamp() * 1_000_000) * 1000


@dataclass(frozen=True)
class NewsDoc:
    available_at: int  # UTC epoch ns
    sentiments: tuple[tuple[int, str | None], ...] = ()
    """(analysis available_at, label), oldest first."""
    events: tuple[tuple[int, str], ...] = ()
    """(event available_at, event type lowercased)."""


@dataclass(frozen=True)
class News:
    docs: tuple[NewsDoc, ...]
    coverage_start: int | None
    """First ``available_at`` of any Aegis document held; None: no news synced."""

    def cut(self, cutoff: int) -> News:
        docs = tuple(
            NewsDoc(
                d.available_at,
                tuple(s for s in d.sentiments if s[0] <= cutoff),
                tuple(e for e in d.events if e[0] <= cutoff),
            )
            for d in self.docs
            if d.available_at <= cutoff
        )
        start = self.coverage_start
        return News(docs, start if start is not None and start <= cutoff else None)

    def count(
        self,
        days: int,
        cutoffs: np.ndarray,
        *,
        sentiment: str | None = None,
        event_type: str | None = None,
    ) -> np.ndarray:
        """Per bar: documents in the ``days`` up to each cutoff (int64 ns)."""
        cutoffs = np.asarray(cutoffs, dtype=np.int64)
        out = np.zeros(len(cutoffs))
        window = days * _NS_PER_DAY
        wanted_type = event_type.lower() if event_type else None
        for doc in self.docs:
            hit = (doc.available_at > cutoffs - window) & (doc.available_at <= cutoffs)
            if not hit.any():
                continue
            if sentiment is not None:
                times = np.array([s[0] for s in doc.sentiments], dtype=np.int64)
                labels = np.array([s[1] or "" for s in doc.sentiments] or [""])
                idx = np.searchsorted(times, cutoffs, side="right") - 1
                hit &= (idx >= 0) & (labels[np.maximum(idx, 0)] == sentiment)
            if wanted_type is not None:
                times = [t for t, kind in doc.events if kind == wanted_type]
                hit &= cutoffs >= min(times) if times else False
            out += hit
        if self.coverage_start is None:
            out[:] = np.nan
        else:
            out[cutoffs < self.coverage_start] = np.nan
        return out

    def reason(self) -> str:
        if self.coverage_start is None:
            return "no news coverage yet"
        start = datetime.fromtimestamp(self.coverage_start / 1e9, UTC).date()
        return f"no news coverage before {start.isoformat()}"


__all__ = ["Fact", "Fundamentals", "News", "NewsDoc", "to_ns"]
