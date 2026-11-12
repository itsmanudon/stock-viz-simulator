"""Phase 6.2: the unified screener across markets, and saved screens."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz.models import PriceBar, User
from stockviz.services.metrics import refresh_symbol_metrics
from stockviz.settings import get_settings
from tests.symbols import seed_symbols

SECRET = get_settings().internal_api_token

# ticker, currency, daily step (rising, falling, flat)
UNIVERSE = [
    ("AAPL", "USD", 0.5),
    ("MSFT", "USD", -0.2),
    ("KO", "USD", 0.0),
    ("INFY.NS", "INR", 2.0),
    ("TCS.NS", "INR", -0.3),
]


def _seed(session: Session, bars: int = 260) -> None:
    for ticker, currency, step in UNIVERSE:
        seed_symbols(session, ticker, currency=currency)
        for i in range(bars):
            close = Decimal(str(round(100 + step * i, 2)))
            session.add(
                PriceBar(
                    ticker=ticker,
                    ts=datetime(2025, 1, 1) + timedelta(days=i),
                    interval="1d",
                    open=close,
                    high=close + 1,
                    low=close - 1,
                    close=close,
                    volume=1000 + i,
                    source="test",
                )
            )
    session.commit()
    refresh_symbol_metrics(session)
    session.commit()


def test_market_filter_and_snapshot_columns(session: Session, client: TestClient) -> None:
    _seed(session)
    india = client.get("/v1/screener", params={"market": "IN"}).json()
    assert {r["ticker"] for r in india["rows"]} == {"INFY.NS", "TCS.NS"}
    infy = next(r for r in india["rows"] if r["ticker"] == "INFY.NS")
    assert (infy["market"], infy["mic"], infy["currency"]) == ("IN", "XNSE", "INR")
    assert infy["sma_200"] is not None and infy["sma_200_gap_pct"] > 0
    assert infy["hv_20"] is not None and infy["atr_pct_14"] is not None

    both = client.get("/v1/screener", params={"market": "US,IN", "currency": "INR"}).json()
    assert both["total"] == 2


def test_sort_page_and_total(session: Session, client: TestClient) -> None:
    _seed(session)
    first = client.get(
        "/v1/screener",
        params={"momentum_days": 30, "sort": "momentum_pct", "dir": "desc", "limit": 2},
    ).json()
    assert first["total"] == 5 and len(first["rows"]) == 2
    assert [r["ticker"] for r in first["rows"]] == ["INFY.NS", "AAPL"]
    rest = client.get(
        "/v1/screener",
        params={"momentum_days": 30, "sort": "momentum_pct", "dir": "desc", "offset": 2},
    ).json()
    assert [r["ticker"] for r in rest["rows"]] == ["KO", "MSFT", "TCS.NS"]


def test_trend_filters(session: Session, client: TestClient) -> None:
    _seed(session)
    up = client.get("/v1/screener", params={"above_sma_200": "true"}).json()
    assert {r["ticker"] for r in up["rows"]} == {"AAPL", "INFY.NS"}
    down = client.get("/v1/screener", params={"above_sma_50": "false"}).json()
    assert {"MSFT", "TCS.NS"} <= {r["ticker"] for r in down["rows"]}


def test_missing_values_sort_last_and_stay_null(session: Session, client: TestClient) -> None:
    _seed(session, bars=60)  # too short for SMA 200
    page = client.get("/v1/screener", params={"sort": "sma_200_gap_pct", "dir": "desc"}).json()
    assert all(r["sma_200"] is None for r in page["rows"])
    assert page["total"] == 5


def _headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def test_saved_screens_are_private_and_named(session: Session, client: TestClient) -> None:
    owner, other = User(email="s1@stockviz.dev", name="A"), User(email="s2@stockviz.dev", name="B")
    session.add_all([owner, other])
    session.commit()
    assert owner.id and other.id
    h1, h2 = _headers(owner.id), _headers(other.id)

    made = client.post(
        "/v1/screens", json={"name": "India oversold", "query": "?market=IN&rsi_max=30"}, headers=h1
    )
    assert made.status_code == 201 and made.json()["query"] == "market=IN&rsi_max=30"
    replaced = client.post(
        "/v1/screens", json={"name": "India oversold", "query": "market=IN&rsi_max=25"}, headers=h1
    ).json()
    assert replaced["id"] == made.json()["id"] and replaced["query"].endswith("25")

    assert client.get("/v1/screens", headers=h2).json() == []
    assert client.delete(f"/v1/screens/{replaced['id']}", headers=h2).status_code == 404
    assert client.get("/v1/screens").status_code == 401
    assert client.delete(f"/v1/screens/{replaced['id']}", headers=h1).status_code == 204
