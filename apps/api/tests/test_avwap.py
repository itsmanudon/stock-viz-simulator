"""A3.3 (M2.5): anchored VWAP maths, weekly sampling, the API route and the
``avwap`` drawing kind."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz.models import PriceBar, User
from stockviz.services import avwap
from stockviz.settings import get_settings
from tests.symbols import seed_symbols

SECRET = get_settings().internal_api_token


def _auth(user_id: int) -> dict[str, str]:
    return {
        "Authorization": "Bearer "
        + jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    }


# --- maths -------------------------------------------------------------------


def test_hand_computed_example_with_bands() -> None:
    # Typical prices 10, 12, 11 (H, L, C chosen so (H+L+C)/3 is exact).
    days = [date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8), date(2025, 1, 9)]
    high = np.array([99.0, 11.0, 13.0, 12.0])
    low = np.array([1.0, 9.0, 11.0, 10.0])
    close = np.array([50.0, 10.0, 12.0, 11.0])
    volume = np.array([5.0, 100.0, 300.0, 100.0])
    s = avwap.compute(days, high, low, close, volume, date(2025, 1, 7))
    assert s.anchor_index == 1
    assert math.isnan(s.vwap[0]) and math.isnan(s.sd[0])  # before the anchor
    # Bar 1: only itself.
    assert s.vwap[1] == pytest.approx(10.0) and s.sd[1] == pytest.approx(0.0)
    # Bar 2: (10*100 + 12*300) / 400 = 11.5; E[tp^2] = (100*100 + 144*300)/400 = 133;
    # var = 133 - 132.25 = 0.75.
    assert s.vwap[2] == pytest.approx(11.5)
    assert s.sd[2] == pytest.approx(math.sqrt(0.75))
    # Bar 3: (1000 + 3600 + 1100) / 500 = 11.4; E[tp^2] = (10000 + 43200 + 12100)/500
    # = 130.6; var = 130.6 - 129.96 = 0.64; sd = 0.8.
    assert s.vwap[3] == pytest.approx(11.4)
    assert s.sd[3] == pytest.approx(0.8)
    assert s.band(1)[3] == pytest.approx(12.2) and s.band(-2)[3] == pytest.approx(9.8)


def test_anchor_on_a_weekend_starts_on_the_next_bar_and_zero_volume_is_unknown() -> None:
    days = [date(2025, 1, 3), date(2025, 1, 6), date(2025, 1, 7)]  # Fri, Mon, Tue
    h = np.array([11.0, 11.0, 13.0])
    lo = np.array([9.0, 9.0, 11.0])
    c = np.array([10.0, 10.0, 12.0])
    s = avwap.compute(days, h, lo, c, np.array([1.0, 0.0, 2.0]), date(2025, 1, 4))
    assert s.anchor_index == 1
    assert math.isnan(s.vwap[1])  # no volume since the anchor yet
    assert s.vwap[2] == pytest.approx(12.0)
    late = avwap.compute(days, h, lo, c, np.ones(3), date(2025, 2, 1))
    assert late.anchor_index is None and np.isnan(late.vwap).all()


def test_a_value_never_changes_when_later_bars_arrive() -> None:
    rng = np.random.default_rng(3)
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(60)]
    c = 100 + rng.normal(0, 1, 60).cumsum()
    h, lo, v = c + 1, c - 1, rng.uniform(100, 1000, 60)
    full = avwap.compute(days, h, lo, c, v, days[10])
    for t in (10, 25, 59):
        cut = avwap.compute(
            days[: t + 1], h[: t + 1], lo[: t + 1], c[: t + 1], v[: t + 1], days[10]
        )
        np.testing.assert_array_equal(cut.vwap, full.vwap[: t + 1])
        np.testing.assert_array_equal(cut.sd, full.sd[: t + 1])


def test_sample_last_of_period() -> None:
    keys = ["w1", "w1", "w1", "w2", "w2", "w3"]
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    assert avwap.sample_last_of_period(keys, values) == [(2, 3.0), (4, 5.0), (5, 6.0)]


# --- API ---------------------------------------------------------------------

FIRST = date(2025, 3, 3)  # a Monday


def _seed(session: Session) -> list[date]:
    seed_symbols(session, "AAPL")
    days: list[date] = []
    day = FIRST
    i = 0
    while day <= date(2025, 4, 30):
        if day.weekday() < 5:
            close = Decimal(100 + i)
            session.add(
                PriceBar(
                    ticker="AAPL",
                    ts=datetime.combine(day, datetime.min.time()),
                    interval="1d",
                    open=close,
                    high=close + 2,
                    low=close - 2,
                    close=close,
                    volume=1000 + 10 * i,
                    source="test",
                )
            )
            days.append(day)
            i += 1
        day += timedelta(days=1)
    session.commit()
    return days


def _expected(days: list[date], anchor: date) -> avwap.AvwapSeries:
    n = len(days)
    c = np.array([100.0 + i for i in range(n)])
    return avwap.compute(
        days, c + 2, c - 2, c, np.array([1000.0 + 10 * i for i in range(n)]), anchor
    )


def test_daily_route_matches_the_maths(session: Session, client: TestClient) -> None:
    days = _seed(session)
    res = client.get("/v1/symbols/aapl/avwap", params={"anchor": "2025-03-10", "bands": 2})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ticker"] == "AAPL" and body["anchor_bar"] == "2025-03-10"
    assert body["interval"] == "1d" and body["computed_from"] == "daily" and body["bands"] == 2
    exp = _expected(days, date(2025, 3, 10))
    first = exp.anchor_index
    assert first is not None
    assert len(body["points"]) == len(days) - first
    for k, point in enumerate(body["points"]):
        i = first + k
        assert point["ts"].startswith(days[i].isoformat())
        assert point["vwap"] == round(exp.vwap[i], 4)
        assert point["upper2"] == round(exp.band(2)[i], 4)
        assert point["lower1"] == round(exp.band(-1)[i], 4)
    no_bands = client.get("/v1/symbols/AAPL/avwap", params={"anchor": "2025-03-10"}).json()
    assert no_bands["points"][3]["upper1"] is None


def test_weekly_and_monthly_sample_the_daily_avwap(session: Session, client: TestClient) -> None:
    days = _seed(session)
    exp = _expected(days, date(2025, 3, 12))
    weekly = client.get(
        "/v1/symbols/AAPL/avwap", params={"anchor": "2025-03-12", "interval": "1wk"}
    ).json()
    # Weeks from the anchor's week: each point sits on the week's last session (a Friday here).
    fridays = [d for d in days if d.weekday() == 4 and d >= date(2025, 3, 12)]
    last = days[-1]
    want = [*fridays, *([last] if last.weekday() != 4 else [])]
    assert [p["ts"][:10] for p in weekly["points"]] == [d.isoformat() for d in want]
    for p in weekly["points"]:
        i = days.index(date.fromisoformat(p["ts"][:10]))
        assert p["vwap"] == round(exp.vwap[i], 4)
    # The anchor's week holds only its Wednesday to Friday: the Friday's daily value.
    assert weekly["points"][0]["ts"][:10] == "2025-03-14"
    monthly = client.get(
        "/v1/symbols/AAPL/avwap", params={"anchor": "2025-03-12", "interval": "1mo"}
    ).json()
    assert [p["ts"][:10] for p in monthly["points"]] == ["2025-03-31", "2025-04-30"]


def test_route_errors(session: Session, client: TestClient) -> None:
    _seed(session)
    assert client.get("/v1/symbols/NOPE/avwap", params={"anchor": "2025-03-10"}).status_code == 404
    before = client.get("/v1/symbols/AAPL/avwap", params={"anchor": "2025-01-02"})
    assert before.status_code == 422 and "stored daily bars" in before.json()["detail"]
    after = client.get("/v1/symbols/AAPL/avwap", params={"anchor": "2025-05-30"})
    assert after.status_code == 422
    assert client.get("/v1/symbols/AAPL/avwap", params={"anchor": "x"}).status_code == 422
    bad = client.get("/v1/symbols/AAPL/avwap", params={"anchor": "2025-03-10", "bands": 3})
    assert bad.status_code == 422
    bad = client.get("/v1/symbols/AAPL/avwap", params={"anchor": "2025-03-10", "interval": "1h"})
    assert bad.status_code == 422


# --- the avwap drawing kind --------------------------------------------------


def _user(session: Session) -> int:
    user = User(email="avwap@x.dev", name="A")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def test_avwap_drawing_rules(session: Session, client: TestClient) -> None:
    _seed(session)
    uid = _user(session)

    def post(**body):
        return client.post("/v1/drawings", json={"ticker": "AAPL", **body}, headers=_auth(uid))

    ok = post(kind="avwap", points=[{"ts": "2025-03-10", "price": None}], label="swing")
    assert ok.status_code == 201, ok.text
    assert ok.json()["points"] == [{"ts": "2025-03-10", "price": None}]
    assert ok.json()["position"] is None
    no_label = post(kind="avwap", points=[{"ts": "2025-03-10"}])
    assert no_label.status_code == 422 and "label" in no_label.json()["detail"]
    priced = post(kind="avwap", points=[{"ts": "2025-03-10", "price": "100"}], label="x")
    assert priced.status_code == 422 and "date only" in priced.json()["detail"]
    undated = post(kind="avwap", points=[{"ts": None, "price": None}], label="x")
    assert undated.status_code == 422
    outside = post(kind="avwap", points=[{"ts": "2025-06-10", "price": None}], label="x")
    assert outside.status_code == 422
    two = post(kind="avwap", points=[{"ts": "2025-03-10"}, {"ts": "2025-03-11"}], label="x")
    assert two.status_code == 422
    # Other kinds still need a price on every point.
    priceless = post(kind="hline", points=[{"ts": None, "price": None}])
    assert priceless.status_code == 422 and "needs a price" in priceless.json()["detail"]
    listed = client.get("/v1/drawings?ticker=AAPL", headers=_auth(uid)).json()
    assert [d["kind"] for d in listed["drawings"]] == ["avwap"]
    # Renaming to blank is refused (rules name it by its label).
    did = ok.json()["id"]
    cleared = client.patch(f"/v1/drawings/{did}", json={"label": None}, headers=_auth(uid))
    assert cleared.status_code == 422
