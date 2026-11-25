"""Rule DSL conformance suite (A2.1): point mode equals vector mode.

For every rule in ``CORPUS`` and every bar ``t`` of three synthetic 10-year
histories (``tests/dsl_fixtures.py``), ``point(rule, data, t)`` (the rule on
the data cut at ``t``) equals ``vector(rule, data)[t]``, three-valued and
NaN-aware. Because the cut holds nothing after ``t``, this also proves that
no vector value looks ahead. A second test perturbs everything after ``t``
(bars, benchmark, facts, news) and checks every value up to ``t`` is
unchanged.

Any new function must be added here before it is registered. The work is
spread over a process pool (one task per rule and symbol); the whole check
is several hundred thousand point evaluations.
"""

# pandas-stubs type index labels as Hashable / Index; every value here is a
# Timestamp or a float by construction.
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false

from __future__ import annotations

import math
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from stockviz.services.checklist.dimensions import CHECKLIST_PRESETS
from stockviz.services.dsl import ast, compile_rule, point, vector
from stockviz.services.dsl.functions import FUNCTIONS
from stockviz.services.dsl.pit import Fact, Fundamentals, News, NewsDoc
from stockviz.services.setups.presets import PRESETS
from tests.dsl_fixtures import universe

CORPUS: tuple[str, ...] = (
    # trend and the design note's examples
    "close > sma(close, 200) and sma(close, 50) > sma(close, 200)",
    "weekly.close crosses_above weekly.ema(close, 10)",
    "rsi(14) < 30 and volume > 2 * sma(volume, 20)",
    "close >= highest(high, 252)[1] and pct_change(close, 5) > 0",
    # every registry indicator
    "macd().signal crosses_below macd()",
    "macd(8, 21, 5).histogram > 0",
    "stoch(14, 3).d < 20 or stoch() > 80",
    "adx(14) > 25 and adx(14).plus_di > adx(14).minus_di",
    "supertrend(10, 3).direction = 1",
    "cci(20) crosses_above -100",
    "roc(12) > 5",
    "willr(14) < -80",
    "close < bb(20, 2).lower",
    "bb(20, 2.5).upper - bb(20, 2.5).lower < 0.1 * bb(20, 2.5).middle",
    "atr(14) / close * 100 > 2",
    "hv(20) > hv(60)",
    "close > donchian(20).upper[1]",
    "close < keltner(20, 2, 10).lower",
    "obv() > ema(obv(), 20)",
    "mfi(14) > 80",
    "ad() > ad()[5]",
    "rvol(20) > 1.5",
    "wma(10) > vwap(20)",
    # every primitive
    "lowest(low, 20) > lowest(low, 20)[10]",
    "sum(volume, 5) > 5 * sma(volume, 50)",
    "change(close) > 0 and change(close, 10) < 0",
    "abs(pct_change(close)) > 3",
    "min(open, close) > max(sma(close, 20), ema(close, 20))",
    "count_true(close > open, 10) >= 7",
    "bars_since(close crosses_above sma(close, 50)) <= 5",
    "rs(63) > 0 and rs(126) > rs(126)[20]",
    "ema(rsi(14), 10) crosses_above 50",
    "high - low > 2 * atr(14)[1]",
    # weekly and monthly prefixes, offsets on both timeframes
    "monthly.close > monthly.sma(close, 10)",
    "close > weekly.highest(high, 4)[1]",
    "weekly.(close > open) and monthly.rsi(14) > 50",
    "(weekly.close)[1] < weekly.close[1] or not weekly.(close < sma(close, 20))",
    "monthly.close crosses_above monthly.ema(close, 6) or weekly.macd().histogram > 0",
    "weekly.rs(13) > 0",
    # fundamentals (point in time)
    "fundamental.pe < 25 and fundamental.roe > 15",
    "fundamental.revenue_growth > 10 or fundamental.debt_to_equity < 0.5",
    "fundamental.dividend_yield > 1 and close > sma(close, 100)",
    "fundamental.current_ratio > 1.5 and fundamental.p_fcf < 30 and fundamental.ev_ebitda < 20",
    "fundamental.net_margin > 10 and fundamental.payout_ratio < 50 and fundamental.gross_margin > 30",
    "fundamental.market_cap / 1000000 > fundamental.enterprise_value / 2000000",
    # news (available_at)
    'news.count(7, sentiment="negative") = 0',
    'news.count(30) > 2 and news.count(30, event_type="earnings") >= 1',
    # delivery and missing data
    "delivery_pct > 60 and close > open",
    "sma(delivery_pct, 5) > 50",
    "close > open or delivery_pct > 70",
    "not (rsi(14) > 70) and deliverable_qty > sma(deliverable_qty, 20)",
    "bars_since(delivery_pct > 80) < 3",
    # A2.2: every shipped preset
    *(preset.rule for preset in PRESETS),
    # A2.4: the venue index binding, and every checklist dimension setup
    "index_close > sma(index_close, 200)",
    "index_close crosses_above sma(index_close, 50) and close > open",
    "weekly.index_close > weekly.index_close[4]",
    *(preset.rule for preset in CHECKLIST_PRESETS),
)

NUMERIC: tuple[str, ...] = (
    "index_close / sma(index_close, 20)",
    "ema(rsi(14), 10)",
    "wma(10) - vwap(20)",
    "weekly.macd(12, 26, 9).signal",
    "fundamental.pe",
    "rs(63)",
    'news.count(30, sentiment="positive")',
    "bars_since(close > open)",
)


def _same(a, b) -> bool:
    if a is None or (isinstance(a, float) and math.isnan(a)) or a is pd.NA:
        return b is None or b is pd.NA or (isinstance(b, float) and math.isnan(b))
    if b is None or b is pd.NA or (isinstance(b, float) and math.isnan(b)):
        return False
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    return math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-12)


STRIDE = max(1, int(os.environ.get("DSL_CONFORMANCE_STRIDE", "1")))
"""Check every bar locally (1). CI sets a stride (``.github/workflows/ci.yml``)
so the check fits a small runner: every STRIDE-th bar plus the last, with a
per-rule offset so the corpus still covers every bar position between rules."""


def check_every_bar(rule: str, ticker: str) -> tuple[str, str, int, list[str]]:
    """Point against the vector at every bar (or every STRIDE-th). Returns
    (rule, ticker, bars, mismatches)."""
    data = universe()[ticker]
    compiled = compile_rule(rule, require_condition=False)
    full = vector(compiled, data)
    bad: list[str] = []
    items = list(full.items())
    start = sum(map(ord, rule + ticker)) % STRIDE
    chosen = items[start::STRIDE]
    if items and items[-1] not in chosen:
        chosen.append(items[-1])
    for ts, expected in chosen:
        got = point(compiled, data, ts.date())  # pyright: ignore[reportAttributeAccessIssue]
        want = None if expected is pd.NA else expected
        if not _same(got, want):
            bad.append(f"{ts.date()}: point {got!r} vector {want!r}")
            if len(bad) >= 5:
                break
    return rule, ticker, len(full), bad


def _tasks() -> list[tuple[str, str]]:
    return [(r, t) for r in CORPUS + NUMERIC for t in universe()]


def test_corpus_covers_every_function_and_is_large_enough() -> None:
    assert len(CORPUS) >= 40
    assert {p.rule for p in PRESETS} <= set(CORPUS)  # presets must conform (A2.2)
    assert {p.rule for p in CHECKLIST_PRESETS} <= set(CORPUS)  # checklist dimensions (A2.4)
    compiled = [compile_rule(r) for r in CORPUS]  # all type-check as conditions
    used = {n.name for c in compiled for n in ast.walk(c.canonical) if isinstance(n, ast.Call)}
    kinds = {type(n).__name__ for c in compiled for n in ast.walk(c.canonical)}
    assert {"Offset", "Cross", "Timeframe", "Fundamental", "News", "Not", "Or", "Neg"} <= kinds
    assert set(FUNCTIONS) <= used, sorted(set(FUNCTIONS) - used)


def test_point_equals_vector_at_every_bar() -> None:
    tasks = _tasks()
    workers = max(1, min(8, (os.cpu_count() or 2)))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(check_every_bar, *zip(*tasks, strict=True)))
    failures = [f"{r} on {t}: {bad}" for r, t, _n, bad in results if bad]
    assert not failures, "\n".join(failures)
    bars = sum(n for _r, _t, n, _b in results)
    assert bars > (len(CORPUS) + len(NUMERIC)) * 3 * 2400  # every bar, three ~10-year histories


def _perturbed(data, cut_day):
    """Everything after ``cut_day`` changed: bars, benchmark, facts, news."""
    rng = np.random.default_rng(99)
    bars = data.bars.copy()
    later = bars.index > pd.Timestamp(cut_day)
    for column in ("open", "high", "low", "close", "volume", "delivery_pct", "deliverable_qty"):
        bars.loc[later, column] = bars.loc[later, column] * rng.uniform(0.5, 1.5, later.sum())
    bench = data.benchmark
    if bench is not None:
        bench = bench.copy()
        late = bench.index > pd.Timestamp(cut_day)
        bench[late] = bench[late] * rng.uniform(0.5, 1.5, late.sum())
    fundamentals = data.fundamentals
    if fundamentals is not None:
        extra = tuple(
            Fact(c, "quarter", cut_day - timedelta(days=5), Decimal("-999"),
                 cut_day + timedelta(days=1), "edgar", "USD")
            for c in ("revenue", "net_income", "shares_outstanding")
        )  # fmt: skip
        fundamentals = Fundamentals(
            fundamentals.facts + extra, fundamentals.trading_currency, fundamentals.fx
        )
    news = data.news
    if news is not None and news.docs:
        from stockviz.services.dsl.data import session_close_ns

        after = session_close_ns(cut_day, data.venue) + 1
        flood = tuple(NewsDoc(after + i, ((after + i, "negative"),), ((after + i, "earnings"),))
                      for i in range(50))  # fmt: skip
        news = News(news.docs + flood, news.coverage_start)
    return replace(data, bars=bars, benchmark=bench, fundamentals=fundamentals, news=news)


@pytest.mark.parametrize("ticker", ["SYNA", "SYNB.NS", "SYNC"])
def test_no_look_ahead_when_the_future_changes(ticker: str) -> None:
    data = universe()[ticker]
    days = [ts.date() for ts in data.bars.index]
    picks = [days[i] for i in (260, 900, len(days) // 2, len(days) - 40, len(days) - 3)]
    for rule in CORPUS + NUMERIC:
        compiled = compile_rule(rule, require_condition=False)
        full = vector(compiled, data)
        for day in picks:
            changed = vector(compiled, _perturbed(data, day))
            before = full.loc[: pd.Timestamp(day)]
            after = changed.loc[: pd.Timestamp(day)]
            mismatch = [
                ts.date()
                for ts in before.index
                if not _same(
                    None if before[ts] is pd.NA else before[ts],
                    None if after[ts] is pd.NA else after[ts],
                )
            ]
            assert not mismatch, f"{rule} on {ticker} cut {day}: changed at {mismatch[:3]}"
            # And the perturbation really changed something after the cut.
            assert len(changed) == len(full)
