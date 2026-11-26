"""A7.2 (M3.2): the sector rotation map, by hand."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import PriceBar, Symbol
from stockviz.services import sector_rotation as svc


def _weekdays(n: int, start: date = date(2025, 1, 6)) -> list[date]:
    out, day = [], start
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def test_quadrants() -> None:
    assert svc.quadrant(101, 101) == "leading"
    assert svc.quadrant(101, 99) == "weakening"
    assert svc.quadrant(99, 99) == "lagging"
    assert svc.quadrant(99, 101) == "improving"


def test_composite_is_the_mean_member_return_compounded() -> None:
    idx = pd.to_datetime(_weekdays(3))
    closes = pd.DataFrame({"A": [10.0, 11.0, 12.1], "B": [20.0, 19.0, None]}, index=idx)
    line = svc.composite(closes)
    # Day 2: mean(+10%, -5%) = +2.5%; day 3: only A (+10%).
    assert [round(v, 6) for v in line] == [1.0, 1.025, round(1.025 * 1.1, 6)]


def test_an_outperforming_sector_leads_and_points_do_not_move() -> None:
    days = pd.to_datetime(_weekdays(5 * 30))
    bench = pd.Series([100 * 1.0005**i for i in range(len(days))], index=days)
    # Flat versus the benchmark for 20 weeks, then pulling ahead.
    sector = pd.Series(
        [bench.iloc[i] * (1.0 if i < 100 else 1.002 ** (i - 100)) for i in range(len(days))],
        index=days,
    )
    points = svc.trail(sector, bench, weeks=5)
    assert points and points[-1]["quadrant"] == "leading"
    assert float(points[-1]["rs_trend"]) > 100 and float(points[-1]["rs_momentum"]) > 100  # type: ignore[arg-type]
    # Ratio, trend and momentum by hand for the last week.
    weekly_ratio = 100 * svc.weekly(sector) / svc.weekly(bench)
    trend = 100 * weekly_ratio / weekly_ratio.rolling(svc.TREND_WEEKS).mean()
    momentum = 100 * trend / trend.shift(svc.MOMENTUM_WEEKS)
    assert points[-1]["rs_trend"] == round(float(trend.iloc[-1]), 2)
    assert points[-1]["rs_momentum"] == round(float(momentum.iloc[-1]), 2)
    earlier = svc.trail(sector.iloc[:-10], bench.iloc[:-10], weeks=30)
    later = {p["week"]: p for p in svc.trail(sector, bench, weeks=30)}
    assert all(later[p["week"]] == p for p in earlier[:-1])  # the last week was still open


def test_route_builds_sectors_from_members(session: Session, client: TestClient) -> None:
    tickers = {"T1": "Tech", "T2": "Tech", "T3": "Tech", "E1": "Energy", "E2": "Energy",
               "E3": "Energy", "S1": "Solo"}  # fmt: skip
    for ticker, sector in tickers.items():
        session.add(Symbol(ticker=ticker, name=ticker, currency="USD", sector=sector))
    session.commit()
    days = _weekdays(5 * 20, start=date.today() - timedelta(days=150))
    for i, day in enumerate(days):
        for ticker, sector in tickers.items():
            drift = 1.002 if sector == "Tech" else 0.999
            price = Decimal(str(round(100 * drift**i, 4)))
            session.add(PriceBar(ticker=ticker, ts=datetime.combine(day, datetime.min.time()),
                                 interval="1d", open=price, high=price, low=price, close=price,
                                 volume=1, source="test"))  # fmt: skip
    session.commit()
    body = client.get("/v1/sector-rotation", params={"market": "US", "weeks": 4}).json()
    assert body["benchmark"] == "equal_weight"  # no ^GSPC bars stored
    names = {s["sector"]: s for s in body["sectors"]}
    assert set(names) == {"Tech", "Energy"}  # Solo has fewer than 3 members
    assert names["Tech"]["points"][-1]["rs_trend"] > 100
    assert names["Energy"]["points"][-1]["rs_trend"] < 100
    assert "not RRG" in body["note"]
