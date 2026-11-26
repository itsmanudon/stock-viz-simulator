"""Rule DSL conformance on intraday timeframes (A6.4): point equals vector.

The A2.1 suite (``tests/test_dsl_conformance.py``) extended to bar instants.
For every rule in ``CORPUS`` and every bar of two synthetic intraday
histories (``tests/dsl_fixtures.py::intraday_universe``: NSE with the 2 Mar
2024 DR pause and the 1 Nov 2024 Muhurat evening, XNYS with a half day),
``point(rule, data, t)`` (the rule on the data cut at bar ``t``, as a stream
judges each closed bar) equals ``vector(rule, data)[t]``. A second test
changes everything after ``t``: later bars, the daily bars of ``t``'s own
session and after, the benchmark, facts dated from ``t``'s session, and news
available after ``t``'s close, and checks no value up to ``t`` moves. So
``daily.`` never reads the current session's daily bar.

``DSL_CONFORMANCE_STRIDE`` applies as in the daily suite (every bar locally).
"""

# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportOptionalSubscript=false

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from stockviz.services.dsl import RuleError, compile_rule, point, vector
from stockviz.services.dsl.pit import Fact, Fundamentals, News, NewsDoc
from tests.dsl_fixtures import intraday_universe
from tests.test_dsl_conformance import STRIDE, _same

CORPUS: tuple[str, ...] = (
    # intraday bars alone
    "close > sma(close, 20) and sma(close, 20) > sma(close, 50)",
    "rsi(14) crosses_above 30",
    "close crosses_above vwap(20)",
    "macd().signal crosses_below macd()",
    "close < bb(20, 2).lower or stoch() > 80",
    "atr(14) / close * 100 > 0.2",
    "obv() > ema(obv(), 20)",
    "bars_since(close crosses_above ema(close, 9)) <= 3",
    "highest(high, 12)[1] < close and volume > 1.5 * sma(volume, 20)",
    "count_true(close > open, 6) >= 4",
    "pct_change(close, 3) > 0.5 or change(close) < 0",
    # daily. alignment (the session before), offsets inside and outside it
    "close > daily.close",
    "close > daily.high[1]",
    "(daily.close)[12] < close",
    "daily.close crosses_above daily.sma(close, 10)",
    "daily.rsi(14) > 50 and rsi(14) > 50",
    "daily.(close > open) or close crosses_below daily.low",
    # weekly / monthly on intraday: through the daily frame
    "weekly.close > weekly.close[1] and monthly.rsi(14) > 40",
    # bindings an intraday rule reads under daily.
    "daily.rs(20) > 0 or daily.index_close > daily.sma(index_close, 50)",
    "daily.delivery_pct > 50 and close > open",
    'close > daily.drawing("level").price',
    'close crosses_below daily.avwap("swing")',
    'daily.drawing("trend").price < close or close > daily.avwap("swing").upper1',
    # bindings read at each bar
    'news.count(1, sentiment="negative") = 0 and close > open',
    "fundamental.pe < 40 and fundamental.roe > 5",
)

NUMERIC: tuple[str, ...] = (
    "daily.close",
    "daily.sma(close, 5) - close",
    "weekly.high",
    "news.count(2)",
    "fundamental.pe",
    "rsi(14)",
    'daily.avwap("swing")',
)

ONE_MINUTE_RULES: tuple[str, ...] = (
    "rsi(14) crosses_above 30",
    "close > daily.close and close crosses_above sma(close, 30)",
    "obv() > ema(obv(), 20)",
    "news.count(1) > 0 or fundamental.pe > 10",
    "daily.close",
)


def check_every_bar(rule: str, ticker: str, interval: str) -> tuple[str, str, str, int, list[str]]:
    data = intraday_universe(interval)[ticker]
    compiled = compile_rule(rule, require_condition=False, timeframe=interval)
    full = vector(compiled, data)
    items = list(full.items())
    start = sum(map(ord, rule + ticker + interval)) % STRIDE
    chosen = items[start::STRIDE]
    if items and items[-1] not in chosen:
        chosen.append(items[-1])
    bad: list[str] = []
    for ts, expected in chosen:
        got = point(compiled, data, ts.to_pydatetime())
        want = None if expected is pd.NA else expected
        if not _same(got, want):
            bad.append(f"{ts}: point {got!r} vector {want!r}")
            if len(bad) >= 5:
                break
    return rule, ticker, interval, len(full), bad


def _tasks() -> list[tuple[str, str, str]]:
    tasks = [(r, t, "5m") for r in CORPUS + NUMERIC for t in intraday_universe("5m")]
    tasks += [(r, "SYNI.NS", iv) for r in CORPUS + NUMERIC for iv in ("15m", "60m")]
    tasks += [(r, t, "1m") for r in ONE_MINUTE_RULES for t in intraday_universe("1m")]
    return tasks


def test_point_equals_vector_at_every_intraday_bar() -> None:
    tasks = _tasks()
    workers = max(1, min(8, (os.cpu_count() or 2)))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(check_every_bar, *zip(*tasks, strict=True)))
    failures = [f"{r} on {t} {iv}: {bad}" for r, t, iv, _n, bad in results if bad]
    assert not failures, "\n".join(failures)
    bars = sum(n for *_x, n, _b in results)
    assert bars > 60_000


def _perturbed(data, t: pd.Timestamp):
    """Everything not known at bar ``t``'s close changed."""
    rng = np.random.default_rng(7)
    i = int(data.bars.index.get_loc(t))
    today = pd.Timestamp(data.sessions[i].item())
    bars = data.bars.copy()
    later = bars.index > t
    for column in ("open", "high", "low", "close", "volume"):
        bars.loc[later, column] = bars.loc[later, column] * rng.uniform(0.5, 1.5, later.sum())
    daily = data.daily.copy()
    from_today = daily.index >= today
    for column in ("open", "high", "low", "close", "volume", "delivery_pct", "deliverable_qty"):
        daily.loc[from_today, column] = daily.loc[from_today, column] * rng.uniform(
            0.5, 1.5, from_today.sum()
        )
    bench = data.benchmark
    if bench is not None:
        bench = bench.copy()
        late = bench.index >= today
        bench[late] = bench[late] * rng.uniform(0.5, 1.5, late.sum())
    fundamentals = data.fundamentals
    if fundamentals is not None:
        extra = tuple(
            Fact(c, "quarter", today.date() - timedelta(days=5), Decimal("-999"), today.date(),
                 "edgar", "INR")
            for c in ("revenue", "net_income", "shares_outstanding")
        )  # fmt: skip
        fundamentals = Fundamentals(
            fundamentals.facts + extra, fundamentals.trading_currency, fundamentals.fx
        )
    news = data.news
    if news is not None:
        after = int(data.closed_at[i]) + 1
        flood = tuple(NewsDoc(after + k, ((after + k, "negative"),), ()) for k in range(30))
        news = News(news.docs + flood, news.coverage_start)
    return replace(
        data, bars=bars, daily=daily, benchmark=bench, fundamentals=fundamentals, news=news
    )


@pytest.mark.parametrize("ticker", ["SYNI.NS", "SYNU"])
def test_no_look_ahead_when_the_future_and_todays_daily_bar_change(ticker: str) -> None:
    data = intraday_universe("5m")[ticker]
    index = data.bars.index
    picks = [index[i] for i in (80, 400, len(index) // 2, len(index) - 30, len(index) - 2)]
    # Each session's first and last bar: the edges of daily. alignment.
    days = data.sessions
    picks += [index[i] for i in (int(np.flatnonzero(days == days[200])[0]),
                                 int(np.flatnonzero(days == days[200])[-1]))]  # fmt: skip
    for rule in CORPUS + NUMERIC:
        compiled = compile_rule(rule, require_condition=False, timeframe="5m")
        full = vector(compiled, data)
        for t in picks:
            changed = vector(compiled, _perturbed(data, t))
            before, after = full.loc[:t], changed.loc[:t]
            mismatch = [
                ts
                for ts in before.index
                if not _same(
                    None if before[ts] is pd.NA else before[ts],
                    None if after[ts] is pd.NA else after[ts],
                )
            ]
            assert not mismatch, f"{rule} on {ticker} cut {t}: changed at {mismatch[:3]}"


def test_daily_reads_the_session_before_never_today() -> None:
    data = intraday_universe("5m")["SYNI.NS"]
    values = vector(compile_rule("daily.close", require_condition=False, timeframe="5m"), data)
    daily = data.daily["close"]
    for k, ts in enumerate(data.bars.index):
        session = data.sessions[k].item()
        prior = daily.loc[: pd.Timestamp(session) - pd.Timedelta(days=1)]
        assert values[ts] == prior.iloc[-1]
        assert pd.Timestamp(session) in daily.index  # today's bar is stored, and unread


def test_special_sessions_are_bars_of_their_own() -> None:
    data = intraday_universe("5m")["SYNI.NS"]
    index = data.bars.index
    dr = [
        ts for ts, d in zip(index, data.sessions, strict=True) if d == np.datetime64("2024-03-02")
    ]
    # 09:15-10:00 and 11:30-12:30 IST: 9 + 12 five-minute bars, none in the pause.
    assert len(dr) == 21
    assert datetime(2024, 3, 2, 4, 30) not in dr  # 10:00 IST, the pause
    assert dr[9] == pd.Timestamp(2024, 3, 2, 6, 0)  # 11:30 IST
    muhurat = [ts for ts, d in zip(index, data.sessions, strict=True)
               if d == np.datetime64("2024-11-01")]  # fmt: skip
    assert muhurat[0] == pd.Timestamp(2024, 11, 1, 12, 30) and len(muhurat) == 12  # 18:00 IST
    values = vector(compile_rule("daily.close", require_condition=False, timeframe="5m"), data)
    assert values[muhurat[0]] == data.daily["close"].loc[pd.Timestamp(2024, 10, 31)]


@pytest.mark.parametrize(
    ("rule", "fragment"),
    [
        ("index_close > 0", "write daily.index_close"),
        ("rs(20) > 0", "write daily.rs(...)"),
        ("delivery_pct > 50", "write daily.delivery_pct"),
        ('close > drawing("level").price', 'write daily.drawing("level").price'),
        ('close > avwap("swing")', 'write daily.avwap("swing")'),
        ("daily.fundamental.pe > 1", "drop the daily. prefix"),
        ("daily.news.count(3) > 1", "drop the daily. prefix"),
        ("daily.weekly.close > 1", "do not nest"),
        ("weekly.delivery_pct > 1", "daily data"),
    ],
)
def test_per_binding_intraday_refusals(rule: str, fragment: str) -> None:
    with pytest.raises(RuleError) as exc:
        compile_rule(rule, timeframe="5m")
    assert fragment in exc.value.message


def test_daily_prefix_is_refused_on_the_daily_timeframe() -> None:
    with pytest.raises(RuleError) as exc:
        compile_rule("daily.close > 1")
    assert "intraday timeframes" in exc.value.message


def test_daily_compile_is_unchanged_by_the_timeframe_argument() -> None:
    for rule in CORPUS[:11]:
        a = compile_rule(rule)
        b = compile_rule(rule, timeframe="daily")
        assert (a.canonical_text, a.hash, a.lookback, a.needs) == (
            b.canonical_text, b.hash, b.lookback, b.needs,
        )  # fmt: skip
        assert compile_rule(rule, timeframe="5m").hash == a.hash  # the rule's text, not its bars


def test_intraday_lookback_counts_intraday_bars() -> None:
    assert (
        compile_rule("rsi(14) > 30", timeframe="5m").lookback
        == compile_rule("rsi(14) > 30").lookback
    )
    assert compile_rule("close > daily.sma(close, 200)", timeframe="5m").lookback == 0
    assert compile_rule("(daily.close)[3] < close", timeframe="5m").lookback == 3
    assert compile_rule("close > daily.close", timeframe="5m").needs.daily


def test_data_for_another_timeframe_is_refused() -> None:
    data = intraday_universe("5m")["SYNU"]
    with pytest.raises(ValueError, match="compiled for daily"):
        vector(compile_rule("close > open"), data)


def test_point_takes_an_aware_instant() -> None:
    from datetime import UTC

    data = intraday_universe("5m")["SYNU"]
    ts = data.bars.index[100]
    naive = point("close > open", data, ts.to_pydatetime())
    aware = point("close > open", data, ts.to_pydatetime().replace(tzinfo=UTC))
    assert naive == aware
    with pytest.raises(ValueError):
        point("close > open", data, date(2024, 11, 21))
