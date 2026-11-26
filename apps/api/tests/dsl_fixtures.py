"""Deterministic synthetic histories for the Rule DSL tests (A2.1).

Ten years of daily bars on the real venue calendars, seeded, with the cases
the evaluator must handle:

- ``SYNA`` (XNYS): an unadjusted 2-for-1 split step (prices halve, volume
  doubles), quarterly and annual fundamentals from 2017 (USD), Aegis-style
  news from 2020 with sentiments and events, the ^GSPC benchmark, and a
  history that ends on a Wednesday (a partial last week and month).
- ``SYNB.NS`` (XNSE): NSE sessions, so NSE holidays (Good Friday 2016
  among them) are absent; delivery data only from 2022, with gaps;
  fundamentals reported in USD for an INR listing (the FX path); ^NSEI.
- ``SYNC`` (XNYS): starts in 2016, a two-week hole in its bars, no
  fundamentals, no news and no benchmark (every such binding is unknown).

A3.3: each symbol also carries its owner's drawings (``_drawings``), read by
``drawing("...")`` and ``avwap("...")``: lines and zones anchored mid-history
(so many bars lie before their first anchor), a leftward ray, a weekend
anchor, an AVWAP anchored inside SYNC's hole, and on SYNC an ambiguous label
and a label on a kind ``drawing()`` cannot read.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache

import numpy as np
import pandas as pd

from stockviz.services.dsl.data import SymbolData, bars_frame
from stockviz.services.dsl.drawings import DrawingRef, Drawings
from stockviz.services.dsl.pit import Fact, Fundamentals, News, NewsDoc, to_ns
from stockviz.services.markets.calendar import is_session

START = date(2015, 1, 2)
END = date(2025, 6, 11)  # a Wednesday


@lru_cache(maxsize=8)
def sessions(venue: str, start: date = START, end: date = END) -> tuple[date, ...]:
    out = []
    day = start
    while day <= end:
        if is_session(day, venue):
            out.append(day)
        day += timedelta(days=1)
    return tuple(out)


def _walk(rng: np.random.Generator, n: int, start: float, vol: float = 0.015) -> np.ndarray:
    return start * np.exp(np.cumsum(rng.normal(0.0003, vol, n)))


def _bars(rng: np.random.Generator, days: list[date], start: float) -> pd.DataFrame:
    close = _walk(rng, len(days), start)
    opens = close * (1 + rng.normal(0, 0.006, len(days)))
    high = np.maximum(opens, close) * (1 + np.abs(rng.normal(0, 0.008, len(days))))
    low = np.minimum(opens, close) * (1 - np.abs(rng.normal(0, 0.008, len(days))))
    volume = np.round(1e6 * np.exp(rng.normal(0, 0.4, len(days))))
    rows = list(zip(days, opens, high, low, close, volume, strict=True))
    return bars_frame(rows)


def _facts(rng: np.random.Generator, first_year: int, currency: str) -> tuple[Fact, ...]:
    facts: list[Fact] = []
    revenue = 1000.0
    for year in range(first_year, 2026):
        for q, month in enumerate((3, 6, 9, 12), start=1):
            end = date(year, month, 28)
            if end > END:
                break
            revenue *= 1 + rng.normal(0.02, 0.03)
            margin = rng.normal(0.15, 0.08)
            avail = end + timedelta(days=int(rng.integers(25, 45)))
            for concept, value in (
                ("revenue", revenue),
                ("net_income", revenue * margin),
                ("gross_profit", revenue * 0.45),
                ("operating_income", revenue * (margin + 0.05)),
                ("ebitda", revenue * (margin + 0.1)),
                ("free_cash_flow", revenue * 0.1),
                ("dividends_paid", revenue * 0.03),
            ):
                facts.append(
                    Fact(concept, "quarter", end, Decimal(str(round(value, 2))), avail, "yfinance",
                         currency)
                )  # fmt: skip
            for concept, value in (
                ("equity", revenue * 4),
                ("cash", revenue * 0.8),
                ("total_debt", revenue * rng.uniform(0.5, 2.5)),
                ("total_assets", revenue * 9),
                ("current_assets", revenue * 2),
                ("current_liabilities", revenue * 1.2),
                ("shares_outstanding", 50.0),
            ):
                facts.append(
                    Fact(concept, "instant", end, Decimal(str(round(value, 2))), avail, "yfinance",
                         currency)
                )  # fmt: skip
            if q == 4:  # a restatement weeks later: a new version
                facts.append(
                    Fact("revenue", "quarter", end, Decimal(str(round(revenue * 1.01, 2))),
                         avail + timedelta(days=30), "yfinance", currency)
                )  # fmt: skip
    return tuple(facts)


def _news(rng: np.random.Generator, days: list[date], first: date) -> News:
    docs: list[NewsDoc] = []
    for day in days:
        if day < first or rng.random() > 0.15:
            continue
        hour = int(rng.integers(0, 24))
        at = datetime(day.year, day.month, day.day, hour, 30, tzinfo=UTC)
        label = str(rng.choice(["positive", "neutral", "negative", "mixed"]))
        sentiments = [(to_ns(at + timedelta(minutes=5)), label)]
        if rng.random() < 0.1:  # a later analysis changes the label
            sentiments.append((to_ns(at + timedelta(days=2)), "negative"))
        events = []
        if rng.random() < 0.3:
            events.append((to_ns(at + timedelta(minutes=10)), str(rng.choice(["earnings", "m&a"]))))
        docs.append(NewsDoc(to_ns(at), tuple(sentiments), tuple(events)))
    coverage = datetime(first.year, first.month, first.day, tzinfo=UTC)
    return News(tuple(docs), to_ns(coverage))


@lru_cache(maxsize=1)
def universe() -> dict[str, SymbolData]:
    rng = np.random.default_rng(20261125)
    us = list(sessions("XNYS"))
    ns = list(sessions("XNSE"))

    # SYNA: split step, fundamentals, news, benchmark, partial last week.
    a = _bars(rng, us, 80.0)
    split = us[1300]
    after = a.index >= pd.Timestamp(split)
    a.loc[after, ["open", "high", "low", "close"]] /= 2
    a.loc[after, "volume"] *= 2
    spx = pd.Series(_walk(rng, len(us), 2000.0, 0.01), index=pd.DatetimeIndex(us))
    syna = SymbolData(
        "SYNA", "XNYS", a, spx, "^GSPC",
        Fundamentals(_facts(rng, 2017, "USD"), "USD"),
        _news(rng, us, date(2020, 1, 15)),
    )  # fmt: skip

    # SYNB.NS: NSE sessions, delivery from 2022 with gaps, USD reporting.
    b = _bars(rng, ns, 1500.0)
    from_2022 = b.index >= pd.Timestamp(2022, 1, 1)
    delivery = rng.uniform(20, 95, len(b))
    gaps = rng.random(len(b)) < 0.03
    b["delivery_pct"] = np.where(from_2022 & ~gaps, np.round(delivery, 2), np.nan)
    b["deliverable_qty"] = np.where(
        from_2022 & ~gaps, np.round(b["volume"].to_numpy() * delivery / 100), np.nan
    )
    nifty = pd.Series(_walk(rng, len(ns), 9000.0, 0.01), index=pd.DatetimeIndex(ns))
    fx_days = [d for d in ns if d.weekday() < 5]
    inr = tuple((d, Decimal(str(round(1 / (65 + i * 0.004), 8)))) for i, d in enumerate(fx_days))
    synb = SymbolData(
        "SYNB.NS", "XNSE", b, nifty, "^NSEI",
        Fundamentals(_facts(rng, 2016, "USD"), "INR", {"INR": inr}),
        News((), to_ns(datetime(2020, 1, 15, tzinfo=UTC))),
        delivery_loaded=True,
    )  # fmt: skip

    # SYNC: later start, a two-week hole, nothing but bars.
    c_days = [d for d in us if d >= date(2016, 3, 1)]
    c_days = [d for d in c_days if not date(2019, 7, 8) <= d <= date(2019, 7, 19)]
    sync = SymbolData("SYNC", "XNYS", _bars(rng, c_days, 30.0))
    return {s.ticker: replace(s, drawings=_drawings(s)) for s in (syna, synb, sync)}


def _drawings(data: SymbolData) -> Drawings:
    """Synthetic drawings near the symbol's own prices (A3.3)."""
    days = data.dates
    close = data.bars["close"].to_numpy(dtype=float)
    n = len(days)

    def at(i: int) -> tuple[date, float]:
        return days[i], round(float(close[i]), 2)

    a, b, c = n // 3, n // 2, (2 * n) // 3
    items = [
        DrawingRef(1, "hline", "Support", ((None, round(float(np.median(close)), 2)),)),
        DrawingRef(2, "trendline", "trend", (at(c), at(a))),  # anchors given right to left
        DrawingRef(3, "ray", "ray up", (at(a), at(b))),
        DrawingRef(4, "ray", "Ray  Left", (at(b), at(a))),  # leftward, double space
        DrawingRef(5, "rectangle", "zone", ((days[b], float(close[b:c].max())),
                                            (days[c], float(close[b:c].min())))),
        DrawingRef(6, "avwap", "swing", ((days[a], None),)),
        DrawingRef(7, "avwap", "late", ((days[n - 30], None),)),
        DrawingRef(8, "text", "note", ((days[a], float(close[a])),)),
    ]  # fmt: skip
    if data.ticker == "SYNB.NS":
        sat = days[b] + timedelta(days=(5 - days[b].weekday()) % 7 or 7)
        items.append(DrawingRef(9, "trendline", "weekend", ((sat, float(close[b])), at(c))))
    if data.ticker == "SYNC":
        items.append(DrawingRef(10, "hline", "support", ((None, float(close[a])),)))  # ambiguous
        items.append(DrawingRef(11, "channel", "chan", (at(a), at(b), at(c))))
        items.append(DrawingRef(12, "avwap", "hole", ((date(2019, 7, 10), None),)))
    return Drawings(1, tuple(items))


def many(count: int) -> list[SymbolData]:
    """``count`` symbols for the performance check: SYNA's calendar, new walks."""
    rng = np.random.default_rng(7)
    us = list(sessions("XNYS"))
    spx = universe()["SYNA"].benchmark
    return [
        SymbolData(f"P{i:03d}", "XNYS", _bars(rng, us, float(rng.uniform(10, 500))), spx, "^GSPC")
        for i in range(count)
    ]


# --- A6.4: intraday histories ------------------------------------------------

INTRADAY_SPANS: dict[str, tuple[tuple[date, date], ...]] = {
    # NSE: the 2 Mar 2024 DR-switch Saturday (09:15-10:00, 11:30-12:30) and
    # the 1 Nov 2024 Muhurat evening (18:00-19:00) with the sessions around them.
    "XNSE": ((date(2024, 2, 26), date(2024, 3, 6)), (date(2024, 10, 28), date(2024, 11, 6))),
    # XNYS: Thanksgiving week 2024 with its 29 Nov half day (13:00 close).
    "XNYS": ((date(2024, 11, 20), date(2024, 12, 4)),),
}


def _minutes(rng: np.random.Generator, venue: str, start_price: float) -> list:
    """Synthetic 1-minute rows on ``venue``'s real trading spans (every minute
    of every span, so no bucket is short), in the ``intraday.Row`` shape."""
    from stockviz.services.markets.calendar import session_minutes

    rows = []
    price = start_price
    for first, last in INTRADAY_SPANS[venue]:
        day = first
        while day <= last:
            hours = session_minutes(day, venue)
            if hours is not None:
                price *= float(np.exp(rng.normal(0, 0.01)))  # an overnight gap
                for span_start, span_end in hours.spans:
                    t = span_start.replace(tzinfo=None)
                    end = span_end.replace(tzinfo=None)
                    while t < end:
                        o = price
                        price *= float(np.exp(rng.normal(0, 0.0012)))
                        hi = max(o, price) * (1 + abs(float(rng.normal(0, 0.0006))))
                        lo = min(o, price) * (1 - abs(float(rng.normal(0, 0.0006))))
                        vol = round(2000 * float(np.exp(rng.normal(0, 0.5))))
                        q = Decimal("0.01")
                        rows.append((t, Decimal(str(o)).quantize(q), Decimal(str(hi)).quantize(q),
                                     Decimal(str(lo)).quantize(q), Decimal(str(price)).quantize(q),
                                     vol, "synthetic", t + timedelta(minutes=1)))  # fmt: skip
                        t += timedelta(minutes=1)
            day += timedelta(days=1)
    return rows


@lru_cache(maxsize=8)
def intraday_universe(interval: str = "5m") -> dict[str, SymbolData]:
    """A6.4: two synthetic intraday histories on ``interval`` bars.

    - ``SYNI.NS`` (XNSE): the DR pause and the Muhurat evening, daily bars
      for every session (today's included, so a test can show ``daily.``
      never reads it), delivery, ^NSEI, fundamentals and news.
    - ``SYNU`` (XNYS): a half day, daily bars ending two sessions before its
      minutes end (``daily.`` at the end reads the last stored day), no
      fundamentals or news.

    Built through the real resampler (``services/bars/intraday.py``), so the
    buckets are the chart's."""
    from stockviz.services.bars.intraday import resample_minutes
    from stockviz.services.dsl.data import intraday_frame

    rng = np.random.default_rng(20261126)
    out: dict[str, SymbolData] = {}
    for ticker, venue, price in (("SYNI.NS", "XNSE", 1500.0), ("SYNU", "XNYS", 80.0)):
        rows = _minutes(rng, venue, price)
        bars = (
            resample_minutes(rows, interval, venue=venue, feed="file")
            if interval != "1m"
            else resample_minutes(rows, "1m", venue=venue, feed="file")
        )
        frame, closed, days = intraday_frame(bars)
        daily_days = list(sessions(venue, date(2023, 1, 2), date(2024, 12, 31)))
        if ticker == "SYNU":
            daily_days = [d for d in daily_days if d <= date(2024, 12, 2)]
        daily = _bars(rng, daily_days, price)
        data = SymbolData(
            ticker, venue, frame, timeframe=interval, closed_at=closed, sessions=days,
            daily=daily, feed="file",
        )  # fmt: skip
        if ticker == "SYNI.NS":
            delivery = rng.uniform(20, 95, len(daily))
            daily["delivery_pct"] = np.round(delivery, 2)
            daily["deliverable_qty"] = np.round(daily["volume"].to_numpy() * delivery / 100)
            nifty = pd.Series(_walk(rng, len(daily_days), 22000.0, 0.01),
                              index=pd.DatetimeIndex(daily_days))  # fmt: skip
            news_days = [d.item() for d in np.unique(days)]
            docs = []
            for day in news_days:
                for _ in range(int(rng.integers(0, 4))):
                    at = datetime(day.year, day.month, day.day, int(rng.integers(0, 24)),
                                  int(rng.integers(0, 60)), tzinfo=UTC)  # fmt: skip
                    label = str(rng.choice(["positive", "neutral", "negative"]))
                    docs.append(NewsDoc(to_ns(at), ((to_ns(at), label),), ()))
            data = replace(
                data,
                benchmark=nifty,
                benchmark_ticker="^NSEI",
                fundamentals=Fundamentals(_facts(rng, 2022, "INR"), "INR"),
                news=News(tuple(sorted(docs, key=lambda d: d.available_at)),
                          to_ns(datetime(2023, 1, 1, tzinfo=UTC))),
                delivery_loaded=True,
            )  # fmt: skip
        out[ticker] = replace(data, drawings=_daily_drawings(data))
    return out


def _daily_drawings(data: SymbolData) -> Drawings:
    """Drawings anchored on daily bars, for ``daily.drawing()`` / ``daily.avwap()``."""
    assert data.daily is not None
    days = [ts.date() for ts in data.daily.index]
    close = data.daily["close"].to_numpy(dtype=float)
    n = len(days)
    return Drawings(1, (
        DrawingRef(1, "hline", "level", ((None, round(float(np.median(close[-60:])), 2)),)),
        DrawingRef(2, "trendline", "trend", ((days[n - 120], float(close[n - 120])),
                                             (days[n - 30], float(close[n - 30])))),
        DrawingRef(3, "avwap", "swing", ((days[n - 90], None),)),
    ))  # fmt: skip
