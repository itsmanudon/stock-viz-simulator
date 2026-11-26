"""A4.5: the scan event study on Rule DSL triggers (A2.4's evidence engine)."""

from __future__ import annotations

import math
import random
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import PriceBar
from stockviz.services.checklist import evidence
from stockviz.services.checklist.evidence import (
    MIN_EVENTS,
    Event,
    StudyResult,
    _group,
    round_trip_cost,
    schedule_for,
    study,
    study_horizons,
)
from stockviz.services.dsl import compile_rule, vector
from stockviz.services.dsl.data import SymbolData, bars_frame
from stockviz.services.dsl.pit import News, NewsDoc, to_ns
from stockviz.services.scan_event_study import clustered_t, horizon_out
from stockviz.services.simulation.fees import US_EQUITY
from tests.symbols import seed_symbols

DAYS = [d.date() for d in pd.bdate_range("2020-01-01", periods=400)]


def _data(ticker: str, closes: list[float], volume: list[float] | None = None) -> SymbolData:
    vols = volume or [1000.0] * len(closes)
    rows = [(d, c, c, c, c, v) for d, c, v in zip(DAYS, closes, vols, strict=False)]
    return SymbolData(ticker, "XNYS", bars_frame(rows))


# --- edge detection and cooldown ------------------------------------------------


def test_events_are_false_to_true_edges_and_cooldown_skips() -> None:
    n = 120
    vol = [1000.0] * n
    # true runs starting at 10 (3 bars), 14 and 40 (2 bars)
    for i in (10, 11, 12, 14, 40, 41):
        vol[i] = 5000.0
    data = _data("AAA", [100.0 + i for i in range(n)], vol)
    rule = compile_rule("volume > 3000")
    out = study_horizons([data], rule, start=DAYS[0], end=DAYS[n - 1], horizons=(5,), cooldown=0)
    assert [e.day for e in out[5].events] == [DAYS[10], DAYS[14], DAYS[40]]
    assert out[5].overlapping == 1  # 14 is within 5 bars of 10
    cooled = study_horizons(
        [data], rule, start=DAYS[0], end=DAYS[n - 1], horizons=(5,), cooldown=10
    )
    assert [e.day for e in cooled[5].events] == [DAYS[10], DAYS[40]]
    assert cooled[5].overlapping_skipped == 1


def test_an_event_without_its_window_is_incomplete_for_that_horizon() -> None:
    n = 100
    vol = [1000.0] * n
    vol[50] = vol[90] = 5000.0
    data = _data("AAA", [100.0 + i for i in range(n)], vol)
    out = study_horizons(
        [data], compile_rule("volume > 3000"), start=DAYS[0], end=DAYS[n - 1],
        horizons=(5, 20, 60), cooldown=0,
    )  # fmt: skip
    assert [r.n for r in out.values()] == [2, 1, 0]
    assert out[60].incomplete == 2 and out[20].incomplete == 1
    assert out[5].incomplete == 0


# --- outcome net of costs, base rate, t ------------------------------------------


def test_forward_returns_net_of_dated_costs_and_base_rate_by_hand() -> None:
    n = 30
    a = [100.0] * n
    b = [50.0] * n
    vol = [1000.0] * n
    vol[5] = 5000.0
    a[10] = 110.0  # A: +10% over 5 sessions from bar 5
    b[10] = 51.0  # B: +2% (B never triggers: base only)
    a[5] = 100.0
    data_a = _data("AAA", a, vol)
    data_b = _data("BBB", b)
    out = study_horizons(
        [data_a, data_b], compile_rule("volume > 3000"), start=DAYS[0], end=DAYS[n - 1],
        horizons=(5,), cooldown=0, dated_costs=True,
    )  # fmt: skip
    (event,) = out[5].events
    cost = round_trip_cost(US_EQUITY, 100.0, 110.0, on_entry=DAYS[5], on_exit=DAYS[10])
    assert event.gross == pytest.approx(0.10)
    assert event.cost == pytest.approx(cost) and cost > 0
    assert event.net == pytest.approx(0.10 - cost)
    assert event.base == pytest.approx((0.10 + 0.02) / 2)  # same date, both symbols
    assert event.excess == pytest.approx(0.10 - cost - 0.06)


def test_t_statistics_against_a_hand_example() -> None:
    excess = [0.01, 0.03, -0.01, 0.05]
    days = [DAYS[0], DAYS[0], DAYS[1], DAYS[2]]
    r = StudyResult(start=DAYS[0], end=DAYS[3], horizon=5)
    r.events = [Event("X", d, e, 0.0, 0.0) for d, e in zip(days, excess, strict=True)]
    mean = 0.02
    sd = math.sqrt(sum((x - mean) ** 2 for x in excess) / 3)
    assert r.t_stat == pytest.approx(mean / (sd / 2))  # 1.5491933
    # Clustered by date: deviations summed per date: d0 -0.01+0.01=0, d1 -0.03, d2 0.03.
    t, g = clustered_t(excess, days)
    se = math.sqrt(3 / 2 * (0.0 + 0.03**2 + 0.03**2) / 16)
    assert g == 3 and t == pytest.approx(mean / se)


def test_minimum_sample_shows_counts_only() -> None:
    r = StudyResult(start=DAYS[0], end=DAYS[3], horizon=5, base_rate=0.01)
    r.events = [Event("X", DAYS[i], 0.01, 0.0, 0.0) for i in range(MIN_EVENTS - 1)]
    out = horizon_out(r)
    assert out.n == MIN_EVENTS - 1 and not out.enough
    assert out.mean_net is None and out.t_stat is None and out.histogram is None
    r.events.append(Event("X", DAYS[40], 0.02, 0.0, 0.0))
    full = horizon_out(r)
    assert full.enough and full.mean_net is not None and full.histogram is not None
    assert sum(full.histogram.counts) == MIN_EVENTS
    assert full.net_percentiles is not None


# --- news and delivery triggers ---------------------------------------------------


def test_news_trigger_events_follow_documents() -> None:
    closes = [100.0 + 0.1 * i for i in range(200)]
    data = _data("AAA", closes)
    docs = tuple(
        NewsDoc(to_ns(datetime.combine(DAYS[i], time(14, 0), tzinfo=UTC)))
        for i in (30, 31, 90, 150)
    )
    coverage = to_ns(datetime.combine(DAYS[0], time(0, 0), tzinfo=UTC))
    data = SymbolData(data.ticker, data.venue, data.bars, news=News(docs, coverage))
    rule = compile_rule("news.count(1) >= 1")
    out = study_horizons([data], rule, start=DAYS[0], end=DAYS[199], horizons=(5,), cooldown=0)
    # 30 and 31 are one true run: one event.
    assert [e.day for e in out[5].events] == [DAYS[30], DAYS[90], DAYS[150]]


def test_delivery_trigger() -> None:
    data = _data("AAA.NS", [100.0 + i for i in range(80)])
    data = SymbolData("AAA.NS", "XNSE", data.bars.copy())
    data.bars["delivery_pct"] = 40.0
    data.bars.iloc[[20, 21, 50], data.bars.columns.get_loc("delivery_pct")] = 70.0
    out = study_horizons(
        [data], compile_rule("delivery_pct > 60"), start=DAYS[0], end=DAYS[79],
        horizons=(5,), cooldown=0,
    )  # fmt: skip
    assert [e.day for e in out[5].events] == [DAYS[20], DAYS[50]]
    assert out[5].fee_schedules == {"in_equity_delivery_nse": 2}


# --- the checklist's grades are unchanged ------------------------------------------


def _legacy_study(datasets, rule, *, start, end, horizon=20) -> StudyResult:
    """A2.4's ``study`` as it was before A4.5 (dev at e0f124d), kept verbatim."""
    result = StudyResult(start=start, end=end, horizon=horizon)
    base_sum: dict = {}
    base_n: dict = {}
    pending = []
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    for full in datasets:
        data = full.cut(end) if len(full.bars) and full.bars.index[-1] > end_ts else full
        n = len(data.bars)
        if n <= horizon:
            continue
        result.symbols += 1
        closes = data.bars["close"].to_numpy(dtype=float)
        days = data.bars.index
        stamps = days.to_numpy(dtype="datetime64[D]")
        dates = data.dates
        with np.errstate(divide="ignore", invalid="ignore"):
            forward = np.full(n, np.nan)
            forward[: n - horizon] = closes[horizon:] / closes[: n - horizon] - 1.0
        in_window = (days >= start_ts) & (days <= end_ts) & np.isfinite(forward)
        group = _group(data)
        for i in np.flatnonzero(in_window):
            key = (group, stamps[i])
            base_sum[key] = base_sum.get(key, 0.0) + float(forward[i])
            base_n[key] = base_n.get(key, 0) + 1
        state = vector(rule, data).astype("Float64").to_numpy(dtype=float, na_value=np.nan)
        schedule = schedule_for(data.venue)
        last_used = -(10**9)
        for i in np.flatnonzero(in_window):
            if i == 0 or state[i] != 1.0 or state[i - 1] != 0.0:
                continue
            if i - last_used < horizon:
                result.overlapping_skipped += 1
                continue
            last_used = i
            cost = round_trip_cost(schedule, closes[i], closes[i + horizon])
            result.fee_schedules[schedule.name] = result.fee_schedules.get(schedule.name, 0) + 1
            pending.append((data.ticker, group, dates[i], float(forward[i]), cost))
    for ticker, group, day, gross, cost in pending:
        key = (group, np.datetime64(day, "D"))
        result.events.append(Event(ticker, day, gross, cost, base_sum[key] / base_n[key]))
    total_n = sum(base_n.values())
    result.base_rate = sum(base_sum.values()) / total_n if total_n else None
    return result


def _walk(i: int, seed: int, venue: str) -> SymbolData:
    rng = np.random.default_rng(seed + i)
    days = [d.date() for d in pd.bdate_range("2016-01-01", periods=900 + 37 * i)]
    close = 100 * np.cumprod(1 + rng.normal(0.0003, 0.015, len(days)))
    volume = rng.integers(500, 3000, len(days)).astype(float)
    rows = [(d, c, c * 1.01, c * 0.99, c, v) for d, c, v in zip(days, close, volume, strict=True)]
    suffix = ".NS" if venue == "XNSE" else ""
    return SymbolData(f"W{i}{suffix}", venue, bars_frame(rows))


@pytest.mark.parametrize(
    "text",
    [
        "close crosses_above sma(close, 50)",
        "volume > 2500",
        "rsi(14) < 30",
        "close > sma(close, 20) and volume > 1500",
    ],
)
@pytest.mark.parametrize("horizon", [5, 20])
def test_study_equals_the_pre_a45_engine(text: str, horizon: int) -> None:
    datasets = [_walk(i, 11, "XNYS") for i in range(5)] + [_walk(i, 23, "XNSE") for i in range(3)]
    rule = compile_rule(text)
    start, end = date(2016, 6, 1), date(2019, 6, 28)
    new = study(datasets, rule, start=start, end=end, horizon=horizon)
    old = _legacy_study(datasets, rule, start=start, end=end, horizon=horizon)
    assert new.n > 0
    assert new.events == old.events
    assert (new.symbols, new.overlapping_skipped, new.fee_schedules) == (
        old.symbols,
        old.overlapping_skipped,
        old.fee_schedules,
    )
    assert new.base_rate == old.base_rate and new.grade == old.grade


def test_round_trip_cost_without_dates_is_unchanged() -> None:
    assert round_trip_cost(US_EQUITY, 100.0, 110.0) == pytest.approx(
        round_trip_cost(US_EQUITY, 100.0, 110.0, on_entry=None, on_exit=None)
    )
    assert Decimal(100_000) == evidence.NOTIONAL


# --- the route --------------------------------------------------------------------


def _seed_walk(session: Session, ticker: str, seed: int, n: int = 500) -> None:
    seed_symbols(session, ticker)
    rng = random.Random(seed)
    price = 100.0
    day = date(2022, 1, 3)
    k = 0
    while k < n:
        if day.weekday() < 5:
            price *= 1 + rng.gauss(0.0003, 0.02)
            session.add(
                PriceBar(
                    ticker=ticker,
                    ts=datetime(day.year, day.month, day.day),
                    interval="1d",
                    open=Decimal(f"{price:.4f}"),
                    high=Decimal(f"{price * 1.01:.4f}"),
                    low=Decimal(f"{price * 0.99:.4f}"),
                    close=Decimal(f"{price:.4f}"),
                    volume=1_000_000,
                    source="test",
                )
            )
            k += 1
        day += timedelta(days=1)
    session.commit()


def test_route_shape_stamp_and_events(client: TestClient, session: Session) -> None:
    for i, t in enumerate(("AAA", "BBB", "CCC", "DDD")):
        _seed_walk(session, t, seed=i)
    body = {
        "trigger": {"rule": "close crosses_above sma(close, 10)"},
        "universe": {"tickers": ["AAA", "BBB", "CCC", "DDD"]},
        "from": "2022-03-01",
        "to": "2023-11-30",
    }
    res = client.post("/v1/research/scan-event-study", json=body)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["from"] == "2022-03-01" and out["to"] == "2023-11-30"
    assert [h["horizon"] for h in out["horizons"]] == [5, 20, 60]
    h5 = out["horizons"][0]
    assert h5["n"] >= MIN_EVENTS and h5["enough"]
    assert h5["t_stat"] is not None and h5["base_rate"] is not None
    assert out["universe"]["survivorship_biased"] is True
    assert "Association, not cause" in out["disclaimer"]
    assert out["events"] and {"ticker", "date", "net", "excess"} <= set(out["events"][0])
    assert out["trigger"]["canonical"] == "close crosses_above sma(close, 10)"
    assert out["events_found"] >= h5["n"]
    cooled = client.post("/v1/research/scan-event-study", json={**body, "cooldown": 20}).json()
    assert cooled["events_skipped_cooldown"] > 0
    assert cooled["horizons"][0]["n"] < h5["n"]


def test_route_errors(client: TestClient, session: Session) -> None:
    _seed_walk(session, "AAA", seed=1, n=50)
    bad = client.post(
        "/v1/research/scan-event-study",
        json={"trigger": {"rule": "close >"}, "universe": {"tickers": ["AAA"]}},
    )
    assert bad.status_code == 422 and bad.json()["detail"]["kind"] == "syntax"
    number = client.post(
        "/v1/research/scan-event-study",
        json={"trigger": {"rule": "sma(close, 5)"}, "universe": {"tickers": ["AAA"]}},
    )
    assert number.status_code == 422
    signed_out = client.post(
        "/v1/research/scan-event-study",
        json={"trigger": {"rule": "close > 1"}, "universe": {"watchlist_id": 1}},
    )
    assert signed_out.status_code == 401
    unknown = client.post(
        "/v1/research/scan-event-study",
        json={"trigger": {"rule": "close > 1"}, "universe": {"tickers": ["NOPE"]}},
    )
    assert unknown.status_code == 404
    few = client.post(
        "/v1/research/scan-event-study",
        json={"trigger": {"rule": "close > 1"}, "universe": {"tickers": ["AAA"]},
              "to": "2022-03-31"},
    ).json()  # fmt: skip
    assert all(not h["enough"] and h["mean_net"] is None for h in few["horizons"])
