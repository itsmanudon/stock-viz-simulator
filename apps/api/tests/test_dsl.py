"""Rule DSL (A2.1): parser, canonical form and hash, types, functions, logic,
timeframes and point-in-time gating, each checked by hand on small inputs."""

# pandas-stubs type index labels as Hashable / Index; every value here is a
# Timestamp or a float by construction.
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from stockviz.services.bars.resample import resample
from stockviz.services.dsl import (
    RuleError,
    SymbolData,
    compile_rule,
    evaluate_at,
    parse,
    point,
    vector,
)
from stockviz.services.dsl.data import bars_frame, session_close_ns
from stockviz.services.dsl.evaluate import _kleene_and, _kleene_or
from stockviz.services.dsl.pit import Fact, Fundamentals, News, NewsDoc, to_ns
from stockviz.services.dsl.printer import to_text
from stockviz.services.dsl.timeframes import resample_frame
from stockviz.services.indicators import engine
from tests.dsl_fixtures import sessions, universe
from tests.test_dsl_conformance import CORPUS, NUMERIC

T, F, U = 1.0, 0.0, float("nan")


def _data(closes, *, opens=None, venue="XNYS", start=date(2024, 1, 2), **kw) -> SymbolData:
    days = list(sessions(venue, start, start + timedelta(days=3 * len(closes) + 10)))[: len(closes)]
    opens = opens or closes
    rows = [
        (d, o, max(o, c) + 1, min(o, c) - 1, c, 100 + i)
        for i, (d, o, c) in enumerate(zip(days, opens, closes, strict=True))
    ]
    return SymbolData("TEST", venue, bars_frame(rows), **kw)


def _values(rule: str, data: SymbolData) -> list:
    out = vector(compile_rule(rule, require_condition=False), data)
    return [None if v is pd.NA or (isinstance(v, float) and np.isnan(v)) else v for v in out]


# --- parser -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "line", "column", "fragment"),
    [
        ("close >", 1, 8, "ends too early"),
        ("close > > 1", 1, 9, "unexpected '>'"),
        ("Close > 1", 1, 1, "lowercase"),
        ('close > "x"', 1, 9, "only as a keyword value"),
        ("a < b < c", 1, 7, "cannot be chained"),
        ("close.x > 1", 1, 7, "must follow a call"),
        ("sma(close, n=2, 3)", 1, 17, "positional argument cannot follow"),
        ("close[1.5] > 1", 1, 8, "unexpected '.'"),
        ("close > open and\n  rsi(14) < 30 )", 2, 16, "unexpected ')'"),
        ("   ", 1, 1, "empty"),
        ("close > 1 $", 1, 11, "unexpected character '$'"),
    ],
)
def test_syntax_errors_carry_line_column_and_a_message(text, line, column, fragment) -> None:
    with pytest.raises(RuleError) as caught:
        parse(text)
    err = caught.value
    assert (err.kind, err.line, err.column) == ("syntax", line, column), str(err)
    assert fragment in err.message
    assert "^" in err.pretty()


def test_parse_shapes() -> None:
    tree = parse("weekly.close[1] > (weekly.close)[1]")
    assert to_text(tree) == "weekly.close[1] > (weekly.close)[1]"
    assert type(tree.left).__name__ == "Timeframe"  # type: ignore[attr-defined]
    assert type(tree.right).__name__ == "Offset"  # type: ignore[attr-defined]
    # A keyword in a call is a keyword argument; a comparison needs parentheses.
    with pytest.raises(RuleError, match="positional argument cannot follow"):
        parse("count_true(close = 3, 5)")
    assert type(parse("count_true((close = 3), 5)").args[0]).__name__ == "Compare"  # type: ignore[attr-defined]
    # Keywords are whole words.
    assert to_text(parse("order > 1 and notional < 2")) == "order > 1 and notional < 2"


@pytest.mark.parametrize(
    "rule", CORPUS + NUMERIC + ("a - (b - c) * -d / (e + f)", "not not (a or b)")
)
def test_round_trip_parse_of_print_is_the_tree(rule) -> None:
    tree = parse(rule)
    assert parse(to_text(tree)) == tree
    compiled = (
        compile_rule(rule, require_condition=False)
        if "a -" not in rule and "not not" not in rule
        else None
    )
    if compiled is not None:
        assert parse(compiled.canonical_text) == compiled.canonical
        again = compile_rule(compiled.canonical_text, require_condition=False)
        assert again.canonical_text == compiled.canonical_text


# --- canonical form and hash ------------------------------------------------


def test_hash_ignores_spacing_order_of_and_keywords_and_defaults() -> None:
    base = compile_rule("close > sma(close, 200) and rsi(14) < 30")
    same = [
        "rsi(14)<30   and close>sma(close,200)",
        "rsi() < 30 and close > sma(close, n=200)",
        "(rsi(14) < 30) and (close > sma(close, 200))",
        "close > sma(series=close, n=200) and rsi(n=14) < 30 # trend, then momentum",
    ]
    for text in same:
        assert compile_rule(text).hash == base.hash, text
    assert base.canonical_text == "close > sma(close, 200) and rsi(14) < 30"
    nested = compile_rule(
        "a1 and (b1 and c1)".replace("a1", "close > 1")
        .replace("b1", "open > 2")
        .replace("c1", "low > 3")
    )
    flat = compile_rule("low > 3 and close > 1 and open > 2")
    assert nested.hash == flat.hash
    assert compile_rule("adx(14).adx > 20").hash == compile_rule("adx() > 20").hash
    assert compile_rule("bb(20, k=2).upper > close").canonical_text == "bb(20, 2).upper > close"
    assert compile_rule("close == open").canonical_text == "close = open"
    assert (
        compile_rule(
            'news.count(7, event_type="earnings", sentiment="negative") = 0'
        ).canonical_text
        == 'news.count(7, event_type="earnings", sentiment="negative") = 0'
    )


def test_hash_changes_with_meaning_and_comparisons_are_not_reordered() -> None:
    a = compile_rule("close > open")
    assert compile_rule("open < close").hash != a.hash  # same truth, different text
    assert compile_rule("close >= open").hash != a.hash
    assert compile_rule("close - open > 1").hash != compile_rule("open - close > 1").hash
    assert compile_rule("close + open > 1").canonical_text == "close + open > 1"
    assert len(a.hash) == 64


# --- types ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "column", "fragment"),
    [
        ("smma(close, 3) > 1", 1, "did you mean sma"),
        ("closee > 1", 1, "did you mean close"),
        ("obv > 1", 1, "is a function"),
        ("pe < 20", 1, "fundamental.pe"),
        ("weekly.delivery_pct > 50", 8, "no weekly form"),
        ("weekly.monthly.close > 1", 8, "do not nest"),
        ("weekly.(monthly.close) > 1", 9, "do not nest"),
        ("fundamental.pe[1] < 20", 1, "point-in-time"),
        ("sma(fundamental.pe, 5) < 20", 5, "point-in-time"),
        ("close * fundamental.pe crosses_above 3", 1, "point-in-time"),
        ("weekly.fundamental.pe > 1", 8, "weekly or monthly form"),
        ("(close > open) + 1 > 2", 2, "needs numbers"),
        ("close + open", 1, "must be a condition"),
        ("bb(20, 2) > close", 1, "pick one"),
        ("rsi(14).value > 3", 1, "one output"),
        ("macd().signals > 0", 1, "no output 'signals'"),
        ("rsi(600) > 3", 5, "from 1 to 500"),
        ("bb(20, 11).upper > 3", 8, "at most 10"),
        ("sma(close, 2.5) > 3", 12, "whole number"),
        ("sma(close, volume) > 3", 12, "a number written in the rule"),
        ("sma(5, 3) > 1", 5, "not a constant"),
        ("count_true(close, 3) > 1", 12, "needs a condition"),
        ("min(close) > 1", 1, "two or more"),
        ("rsi(m=3) > 1", 7, "no parameter 'm'"),
        ("rsi(14, n=3) > 1", 11, "twice"),
        ("1 crosses_above 2", 1, "at least one series"),
        ("close[0] > 1", 1, "at least [1]"),
        ('news.count(7, sentiment="angry") = 0', 25, "sentiment must be"),
        ("news.count() = 0", 1, "number of days"),
        ("news.count(400) > 1", 12, "from 1 to 365"),
        ("news.mean(7) > 1", 1, "unknown news function"),
        ("fundamental.pee < 3", 1, "did you mean pe"),
        ("not close", 1, "needs a condition"),
        ("close > open and volume", 18, "joins conditions"),
    ],
)
def test_type_errors_point_at_the_column(text, column, fragment) -> None:
    with pytest.raises(RuleError) as caught:
        compile_rule(text)
    assert caught.value.column == column, str(caught.value)
    assert fragment in caught.value.message, caught.value.message


def test_types_and_lookbacks() -> None:
    rule = compile_rule("fundamental.pe < 20 and close > sma(close, 200)")
    assert str(rule.type) == "boolean point-in-time value"
    assert rule.lookback == 199
    assert compile_rule("close >= highest(high, 252)[1]").lookback == 252
    assert compile_rule("ema(close, 10) > close").lookback == 55
    assert compile_rule("bars_since(close > open) < 3").lookback is None
    assert compile_rule("obv() > 0").lookback is None
    assert compile_rule("weekly.sma(close, 10) > 1").lookback == (9 + 2) * 7
    assert compile_rule("close crosses_above sma(close, 5)").lookback == 5
    needs = compile_rule("rs(5) > 0 and delivery_pct > 1 and news.count(3) = 0").needs
    assert (needs.benchmark, needs.delivery, needs.news, needs.fundamentals) == (
        True,
        True,
        True,
        False,
    )


# --- functions by hand ------------------------------------------------------

CLOSES = [10.0, 11.0, 13.0, 12.0, 15.0, 14.0, 18.0]


def test_primitives_by_hand() -> None:
    d = _data(CLOSES, opens=[10, 10, 14, 11, 14, 15, 17])
    assert _values("sma(close, 3)", d)[2:] == pytest.approx([34 / 3, 12, 40 / 3, 41 / 3, 47 / 3])
    assert _values("sma(close, 3)", d)[:2] == [None, None]
    assert _values("highest(close, 3)", d)[2:] == [13, 13, 15, 15, 18]
    assert _values("lowest(close, 3)", d)[2:] == [10, 11, 12, 12, 14]
    assert _values("sum(close, 2)", d)[1:] == [21, 24, 25, 27, 29, 32]
    assert _values("change(close)", d)[1:] == [1, 2, -1, 3, -1, 4]
    assert _values("change(close, 3)", d)[3:] == [2, 4, 1, 6]
    assert _values("pct_change(close)", d)[1] == pytest.approx(10.0)
    assert _values("abs(change(close))", d)[1:] == [1, 2, 1, 3, 1, 4]
    assert _values("min(open, close)", d) == [10, 10, 13, 11, 14, 14, 17]
    assert _values("max(open, close, 12)", d) == [12, 12, 14, 12, 15, 15, 18]
    assert _values("count_true(close > open, 3)", d)[2:] == [1, 2, 2, 2, 2]
    assert _values("bars_since(close < open)", d) == [None, None, 0, 1, 2, 0, 1]
    assert _values("close[2]", d)[2:] == CLOSES[:5]
    ema = pd.Series(CLOSES).ewm(span=3, adjust=False, min_periods=3).mean().tolist()
    assert _values("ema(close, 3)", d)[2:] == pytest.approx(ema[2:])


def test_bars_since_is_unknown_after_an_unknown_bar() -> None:
    d = _data(CLOSES)
    d.bars["delivery_pct"] = [70, 10, np.nan, 10, 80, 10, 10]
    assert _values("bars_since(delivery_pct > 50)", d) == [0, 1, None, None, 0, 1, 2]


def test_rs_against_the_benchmark_by_hand() -> None:
    d = _data(CLOSES)
    bench = pd.Series([100, 100, 100, 110, 100, 100, 99.0], index=d.bars.index)
    d = SymbolData("TEST", "XNYS", d.bars, bench, "^GSPC")
    # bar 3: stock 12/10 = 1.2, index 110/100 = 1.1 -> 1.2 / 1.1 - 1
    assert _values("rs(3)", d)[3] == pytest.approx(100 * (1.2 / 1.1 - 1))
    assert _values("rs(3)", d)[:3] == [None, None, None]
    assert all(v is None for v in _values("rs(3)", _data(CLOSES)))  # no benchmark: unknown


@pytest.mark.parametrize(
    ("rule", "key", "output"),
    [
        ("rsi(5)", "rsi_5", "value"),
        ("macd(3, 5, 2).signal", "macd_3_5_2", "signal"),
        ("macd(3, 5, 2)", "macd_3_5_2", "macd"),
        ("bb(3, 2).lower", "bb_3_2", "lower"),
        ("stoch(3, 2)", "stoch_3_2", "k"),
        ("wma(3)", "wma_3", "value"),
        ("obv()", "obv", "value"),
    ],
)
def test_indicators_are_the_registry(rule, key, output) -> None:
    d = universe()["SYNC"]
    expected = engine.compute(engine.parse(key), d.bars[["open", "high", "low", "close", "volume"]])
    got = vector(compile_rule(rule, require_condition=False), d).to_numpy(dtype=float)
    np.testing.assert_allclose(got, expected[output].to_numpy(dtype=float), equal_nan=True)


def test_sma_and_ema_primitives_equal_the_registry_on_close() -> None:
    d = universe()["SYNA"]
    f = d.bars[["open", "high", "low", "close", "volume"]]
    for name, key in (("sma(close, 20)", "sma_20"), ("ema(close, 20)", "ema_20")):
        got = vector(compile_rule(name, require_condition=False), d).to_numpy(dtype=float)
        np.testing.assert_array_equal(got, engine.compute(engine.parse(key), f)["value"].to_numpy())


# --- three-valued logic -----------------------------------------------------


def test_kleene_truth_tables() -> None:
    a = np.array([T, T, T, F, F, F, U, U, U])
    b = np.array([T, F, U, T, F, U, T, F, U])
    np.testing.assert_array_equal(_kleene_and([a, b]), [T, F, U, F, F, F, U, F, U])
    np.testing.assert_array_equal(_kleene_or([a, b]), [T, T, T, T, F, U, T, U, U])
    np.testing.assert_array_equal(1.0 - a, [F, F, F, T, T, T, U, U, U])


def test_unknown_inputs_make_unknown_and_reasons_say_why() -> None:
    d = _data(CLOSES, opens=[9, 12, 12, 13, 14, 15, 17])
    # close > open is T F T F T F T; delivery is missing everywhere.
    assert _values("close > open and delivery_pct > 1", d) == [
        None,
        False,
        None,
        False,
        None,
        False,
        None,
    ]
    assert _values("close > open or delivery_pct > 1", d) == [
        True,
        None,
        True,
        None,
        True,
        None,
        True,
    ]
    assert _values("not (delivery_pct > 1)", d) == [None] * 7
    outcome, _rows = evaluate_at("close > open and delivery_pct > 1", d, d.bars.index[0].date())
    assert outcome.status == "unknown"
    assert outcome.reasons == ("delivery_pct: no delivery data for TEST (eod_extras)",)
    outcome, _rows = evaluate_at("close > sma(close, 50)", d, d.bars.index[-1].date())
    assert outcome.reasons == ("sma(close, 50): not enough history (needs 50 bars, has 7)",)
    outcome, _rows = evaluate_at("close / (close - close) > 1", d, d.bars.index[-1].date())
    assert outcome.reasons == ("close / (close - close): division by zero",)


def test_crossing_by_hand() -> None:
    d = _data([1.0, 3, 2, 4, 4, 1])
    # Bar 0 has no bar before it; "1 > 2.5" is already false, so the crossing is false.
    assert _values("close crosses_above 2.5", d) == [False, True, False, True, False, False]
    assert _values("close crosses_below 2.5", d) == [None, False, True, False, False, True]


# --- timeframes -------------------------------------------------------------


def test_weekly_closes_on_the_venues_last_session_and_skips_the_partial_week() -> None:
    # NSE was shut for Holi (24 Mar 2016) and Good Friday (25 Mar): that week
    # closes on Wednesday.
    days = [d for d in sessions("XNSE") if date(2016, 3, 14) <= d <= date(2016, 3, 30)]
    assert date(2016, 3, 24) not in days and date(2016, 3, 25) not in days
    closes = [float(i + 1) for i in range(len(days))]
    data = SymbolData(
        "T.NS", "XNSE", bars_frame([(d, c, c, c, c, 1) for d, c in zip(days, closes, strict=True)])
    )
    got = dict(
        zip([ts.date() for ts in data.bars.index], _values("weekly.close", data), strict=True)
    )
    assert got[date(2016, 3, 17)] is None  # week of 14 Mar not over on Thursday
    assert got[date(2016, 3, 18)] == closes[days.index(date(2016, 3, 18))]  # Friday closes it
    assert got[date(2016, 3, 22)] == got[date(2016, 3, 18)]  # mid-week: last week's bar
    assert got[date(2016, 3, 23)] == closes[days.index(date(2016, 3, 23))]  # holiday week closes
    assert got[date(2016, 3, 30)] == got[date(2016, 3, 23)]  # partial last week never used


def test_resampled_bars_equal_services_bars_resample() -> None:
    data = universe()["SYNB.NS"]
    mine = resample_frame(data.bars, "1wk", data.venue).frame

    class Row:
        def __init__(self, ts, r):
            self.ts, self.open, self.high, self.low, self.close = (
                ts.to_pydatetime(),
                *(Decimal(str(float(r[c]))) for c in ("open", "high", "low", "close")),
            )
            self.volume, self.source, self.adjustment_semantics = (
                int(r["volume"]),
                "t",
                "split_adjusted",
            )

    rows = [Row(ts, r) for ts, r in data.bars.iterrows()]
    theirs = resample(rows, "1wk", venue=data.venue, now=datetime(2030, 1, 1, tzinfo=UTC))
    closed = [b for b in theirs if not b.partial]
    assert len(mine) == len(theirs)
    for bar, (ts, row) in zip(closed, mine.iterrows(), strict=False):
        assert bar.ts.date() == ts.date()
        assert float(bar.close) == row["close"] and float(bar.high) == row["high"]
        assert float(bar.low) == row["low"] and float(bar.open) == row["open"]
        assert bar.volume == row["volume"]


def test_monthly_alignment_uses_the_last_closed_month() -> None:
    data = universe()["SYNA"]
    values = vector(compile_rule("monthly.close", require_condition=False), data)
    may_end = pd.Timestamp(2025, 5, 30)  # last May session
    assert values[may_end] == data.bars.loc[may_end, "close"]
    assert values[pd.Timestamp(2025, 6, 11)] == data.bars.loc[may_end, "close"]
    assert values[pd.Timestamp(2025, 5, 29)] == data.bars.loc[pd.Timestamp(2025, 4, 30), "close"]


# --- point in time ----------------------------------------------------------


def _fundamental_data() -> SymbolData:
    d = _data([100.0] * 10, start=date(2024, 3, 1))
    days = [ts.date() for ts in d.bars.index]
    q_ends = [date(2023, 3, 31), date(2023, 6, 30), date(2023, 9, 30), date(2023, 12, 31)]
    facts = [
        Fact("net_income", "quarter", e, Decimal(25), days[4], "yfinance", "USD") for e in q_ends
    ]
    facts.append(
        Fact("shares_outstanding", "instant", q_ends[-1], Decimal(10), days[4], "yfinance")
    )
    # A restatement known later: net income 50 a quarter.
    facts += [
        Fact("net_income", "quarter", e, Decimal(50), days[7], "yfinance", "USD") for e in q_ends
    ]
    return SymbolData("TEST", "XNYS", d.bars, fundamentals=Fundamentals(tuple(facts), "USD"))


def test_fundamentals_only_from_available_at() -> None:
    d = _fundamental_data()
    pe = _values("fundamental.pe", d)
    # market cap 100 x 10 = 1000; TTM net income 100, then 200 after the restatement.
    assert pe == [None] * 4 + [10.0] * 3 + [5.0] * 3
    day = d.bars.index[3].date()
    outcome, _ = evaluate_at("fundamental.pe < 20", d, day)
    assert outcome.reasons == (f"fundamental.pe: no fundamentals known on {day.isoformat()}",)
    assert point("fundamental.pe < 7", d, d.bars.index[6].date()) is False
    assert point("fundamental.pe < 7", d, d.bars.index[7].date()) is True


def test_news_counts_only_what_was_available_by_the_close() -> None:
    d = _data([1.0] * 6, start=date(2024, 6, 3))
    days = [ts.date() for ts in d.bars.index]
    close_2 = session_close_ns(days[2], "XNYS")
    docs = (
        NewsDoc(close_2 - 1, ((close_2 - 1, "negative"),)),  # before day 2's close
        NewsDoc(close_2 + 1, ((close_2 + 1, "negative"),)),  # after it: counts from day 3
        # Labelled positive at first; negative only from day 4's close onwards.
        NewsDoc(
            close_2 - 5,
            ((close_2 - 5, "positive"), (session_close_ns(days[4], "XNYS"), "negative")),
        ),
    )
    start = to_ns(datetime(2024, 6, 4, tzinfo=UTC))
    d = SymbolData("TEST", "XNYS", d.bars, news=News(docs, start))
    assert _values("news.count(30)", d) == [None, 0, 2, 3, 3, 3]
    assert _values('news.count(30, sentiment="negative")', d) == [None, 0, 1, 2, 3, 3]
    assert _values('news.count(30, sentiment="positive")', d) == [None, 0, 1, 1, 0, 0]
    assert _values('news.count(1, event_type="earnings")', d)[1:] == [0, 0, 0, 0, 0]
    outcome, _ = evaluate_at("news.count(7) = 0", d, days[0])
    assert outcome.reasons == ("news.count(7): no news coverage yet",)  # nothing held by then
    outcome, _ = evaluate_at("news.count(7) = 0", replace(d, bars=d.bars.iloc[:1]), days[0])
    assert outcome.status == "unknown"


def test_explain_lists_each_sub_expression_once() -> None:
    d = _data(CLOSES, opens=[9, 12, 12, 13, 14, 15, 17])
    _outcome, rows = evaluate_at(
        "close > open and weekly.close > 0", d, d.bars.index[-1].date(), explain=True
    )
    texts = [(r.text, r.timeframe, r.value) for r in rows]
    assert texts[0] == ("close > open and weekly.close > 0", "daily", "true")
    assert ("close", "daily", "18") in texts
    assert ("weekly.close", "daily", "12") in texts  # week of 1 Jan, closed Friday 5 Jan
    assert ("close", "weekly", "12") in texts
    assert len(texts) == len(set(texts))
