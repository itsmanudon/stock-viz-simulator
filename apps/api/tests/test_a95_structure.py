"""A9.5 (M2.12): pivots, labels and zones by stated rules, with no repainting."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import PriceBar
from stockviz.services import structure as st
from tests.symbols import seed_symbols


def _bars(highs: list[float]) -> list[st.Bar]:
    start = date(2026, 1, 5)
    return [st.Bar(start + timedelta(days=i), h, h - 2, h - 1) for i, h in enumerate(highs)]


# Two peaks (10 then 12) and three troughs; n = 2.
PATH: list[float] = [5, 6, 10, 7, 6, 8, 12, 9, 7, 6, 8, 9, 8]


def test_pivots_and_labels_by_hand() -> None:
    out = st.structure(_bars(PATH), n=2)
    highs = [(p["price"], p["label"]) for p in out.pivots if p["kind"] == "high"]
    assert highs == [(10, None), (12, "HH")]
    lows = [(p["price"], p["label"]) for p in out.pivots if p["kind"] == "low"]
    assert lows == [(4, None), (4, "LL")]  # lows at 6 - 2 and 6 - 2 (bars 4 and 9)
    confirm = next(p for p in out.pivots if p["price"] == 12)
    assert confirm["confirmed_at"] == date(2026, 1, 5) + timedelta(days=8)  # two bars after


def test_no_pivot_in_the_last_n_bars_and_nothing_repaints() -> None:
    bars = _bars(PATH)
    early = st.structure(bars[:-3], n=2).pivots
    late = st.structure(bars, n=2).pivots
    assert all(p in late for p in early)  # adding bars never moves or drops a pivot
    assert all(isinstance(p["day"], date) and p["day"] <= bars[-3].day for p in late)


def test_zones_cluster_nearby_pivots() -> None:
    points = [
        {"day": date(2026, 1, 1), "price": 100.0},
        {"day": date(2026, 2, 1), "price": 100.4},
        {"day": date(2026, 3, 1), "price": 110.0},
    ]
    zones = st.zones(points, width=0.5, last_close=105.0)
    assert zones == [{"low": 100.0, "high": 100.4, "touches": 2, "side": "support",
                      "first": date(2026, 1, 1), "last": date(2026, 2, 1)}]  # fmt: skip


def test_route(session: Session, client: TestClient) -> None:
    seed_symbols(session, "ACME", currency="USD")
    for i, h in enumerate(PATH * 4):
        session.add(PriceBar(ticker="ACME", ts=datetime(2026, 1, 5) + timedelta(days=i),
                             interval="1d", open=Decimal(h - 1), high=Decimal(h),
                             low=Decimal(h - 2), close=Decimal(h - 1), volume=1,
                             source="test"))  # fmt: skip
    session.commit()
    body = client.get("/v1/symbols/ACME/structure", params={"n": 2, "sessions": 52}).json()
    assert body["pivots"] and body["zones"] and "pivot" in body["rules"]
    assert all(z["touches"] >= 2 for z in body["zones"])
    assert client.get("/v1/symbols/ACME/structure", params={"n": 1}).status_code == 400
