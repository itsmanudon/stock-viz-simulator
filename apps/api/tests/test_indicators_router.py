"""HTTP-level tests for the /v1/symbols/{ticker}/indicators endpoint."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import PriceBar, Symbol


def _seed(session: Session, ticker: str = "AAPL", n: int = 60) -> None:
    session.add(Symbol(ticker=ticker, name="Apple"))
    for i in range(n):
        session.add(
            PriceBar(
                ticker=ticker,
                ts=datetime(2025, 1, 1).replace(day=1).replace(microsecond=i),
                interval="1d",
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                # Linear ramp so SMAs produce a clean signal.
                close=Decimal(str(100 + i * 0.5)),
                volume=1_000_000,
                source="test",
            )
        )
    session.commit()


def test_indicators_returns_requested_sma(session: Session, client: TestClient) -> None:
    _seed(session)
    response = client.get("/v1/symbols/AAPL/indicators", params={"names": "sma_20,sma_50"})
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert "sma_20" in body["series"]
    assert "sma_50" in body["series"]
    assert len(body["series"]["sma_20"]) == 60 - 20 + 1  # 41 valid points
    assert len(body["series"]["sma_50"]) == 60 - 50 + 1  # 11 valid points
    assert body["macd"] is None


def test_indicators_macd_returns_three_aligned_series(session: Session, client: TestClient) -> None:
    _seed(session, n=80)
    response = client.get("/v1/symbols/AAPL/indicators", params={"names": "macd"})
    assert response.status_code == 200
    body = response.json()
    assert body["macd"]
    sample = body["macd"][0]
    assert {"ts", "macd", "signal", "histogram"} <= set(sample.keys())


def test_indicators_rejects_unknown_name(session: Session, client: TestClient) -> None:
    _seed(session)
    response = client.get("/v1/symbols/AAPL/indicators", params={"names": "bollinger"})
    assert response.status_code == 400


def test_indicators_404_when_symbol_missing(client: TestClient) -> None:
    response = client.get("/v1/symbols/NOPE/indicators", params={"names": "sma_20"})
    assert response.status_code == 404
