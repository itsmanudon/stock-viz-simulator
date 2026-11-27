"""A7.1 (M3.3): market breadth and diffusion, by hand on small frames."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import PriceBar
from stockviz.services import breadth as svc
from tests.symbols import seed_symbols

DAYS = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"])


def _frames(closes: dict[str, list[float | None]]) -> dict[str, pd.DataFrame]:
    close = pd.DataFrame(closes, index=DAYS[: len(next(iter(closes.values())))], dtype=float)
    return {"close": close, "high": close + 1, "low": close - 1}


def test_counts_ad_line_and_mcclellan_by_hand(monkeypatch) -> None:
    monkeypatch.setattr(svc, "HIGH_LOW_BARS", 2)
    frames = _frames({
        "A": [10, 11, 12, 11],
        "B": [20, 19, 19, 21],
        "C": [30, 31, None, 32],  # no bar on day 3: not a member that day
    })  # fmt: skip
    points = svc.compute(frames, date(2026, 1, 5), date(2026, 1, 8))
    rows = [(p["advancers"], p["decliners"], p["unchanged"], p["members"]) for p in points]
    # Day 1 has no previous close; day 2: A up, B down, C up; day 3: A up, B flat
    # (C absent); day 4: A down, B up, C up (against its previous stored close).
    assert rows == [(0, 0, 0, 3), (2, 1, 0, 3), (1, 0, 1, 2), (2, 1, 0, 3)]
    assert [p["ad_line"] for p in points] == [0, 1, 2, 3]
    # McClellan: EMA19 - EMA39 of net (0, 1, 1, 1), alpha 0.10 and 0.05, seeded at 0.
    e19 = e39 = 0.0
    expected = []
    for net in (0, 1, 1, 1):
        e19 = 0.10 * net + 0.90 * e19
        e39 = 0.05 * net + 0.95 * e39
        expected.append(round(e19 - e39, 2))
    expected[0] = 0.0
    assert [p["mcclellan"] for p in points] == expected
    # 52-week (here 2-bar) highs: A's high on day 3 (13) tops days 1-2's (12).
    assert points[2]["new_highs"] == 1


def test_values_do_not_change_when_later_bars_arrive() -> None:
    stamps: list[date] = []
    day = date(2025, 1, 1)
    while len(stamps) < 320:
        if day.weekday() < 5:
            stamps.append(day)
        day += timedelta(days=1)
    days = pd.to_datetime(stamps)
    import numpy as np

    rng = np.random.default_rng(7)
    close = pd.DataFrame(
        {t: 100 * np.cumprod(1 + rng.normal(0, 0.01, len(days))) for t in "ABCDE"}, index=days
    )
    frames = {"close": close, "high": close * 1.01, "low": close * 0.99}
    short = {k: v.iloc[:300] for k, v in frames.items()}
    start, end = stamps[260], stamps[299]
    early = svc.compute(short, start, end)
    late = svc.compute(frames, start, stamps[-1])
    assert early == late[: len(early)]
    assert all(p["pct_above_200"] is not None for p in early)


def test_route_counts_a_market(session: Session, client: TestClient) -> None:
    svc.clear_cache()
    seed_symbols(session, "AAPL", currency="USD")
    seed_symbols(session, "MSFT", currency="USD")
    start = datetime(2026, 1, 5)
    for i in range(3):
        for ticker, base in (("AAPL", 100), ("MSFT", 200)):
            price = Decimal(base + (i if ticker == "AAPL" else -i))
            session.add(PriceBar(ticker=ticker, ts=start + timedelta(days=i), interval="1d",
                                 open=price, high=price, low=price, close=price, volume=1,
                                 source="test"))  # fmt: skip
    session.commit()
    body = client.get("/v1/breadth", params={"market": "US", "from": "2026-01-05",
                                              "to": "2026-01-07"}).json()  # fmt: skip
    assert body["members"] == 2 and len(body["points"]) == 3
    assert [(p["advancers"], p["decliners"]) for p in body["points"]] == [(0, 0), (1, 1), (1, 1)]
    assert "survivorship" in body["universe_note"] and "mcclellan" in body["method"]


@pytest.mark.parametrize("params", [{"market": "XX"}, {"from": "2026-02-01", "to": "2026-01-01"}])
def test_route_refuses(client: TestClient, params) -> None:
    assert client.get("/v1/breadth", params=params).status_code in (400, 422)
