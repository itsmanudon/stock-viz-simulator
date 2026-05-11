"""HTTP-level tests for /v1/recommendations."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import Recommendation, Symbol


def _seed(session: Session) -> None:
    session.add_all(
        [
            Symbol(ticker="AAPL", name="Apple Inc.", sector="Technology"),
            Symbol(ticker="MSFT", name="Microsoft", sector="Technology"),
            Symbol(ticker="OLD", name="Stale", sector="Financial Services"),
        ]
    )
    session.commit()
    # Two scores for AAPL — the endpoint should pick the most recent.
    session.add_all(
        [
            Recommendation(
                ticker="AAPL",
                score=Decimal(2),
                rationale="stale",
                computed_at=datetime(2025, 4, 1),
            ),
            Recommendation(
                ticker="AAPL",
                score=Decimal(5),
                rationale="Below historical mean; uptrend",
                computed_at=datetime(2025, 4, 11),
            ),
            Recommendation(
                ticker="MSFT",
                score=Decimal(3),
                rationale="Below mean",
                computed_at=datetime(2025, 4, 11),
            ),
            Recommendation(
                ticker="OLD",
                score=Decimal(1),
                rationale=None,
                computed_at=datetime(2025, 4, 11),
            ),
        ]
    )
    session.commit()


def test_recommendations_returns_latest_per_ticker(session: Session, client: TestClient) -> None:
    _seed(session)
    response = client.get("/v1/recommendations")
    assert response.status_code == 200
    body = response.json()

    by_ticker = {r["ticker"]: r for r in body}
    assert set(by_ticker) == {"AAPL", "MSFT", "OLD"}
    # AAPL's stale row was filtered out by the latest-per-ticker subquery.
    assert by_ticker["AAPL"]["score"] == 5
    # Rationale is split on ";" into a list.
    assert by_ticker["AAPL"]["rationale"] == ["Below historical mean", "uptrend"]
    # Null rationale becomes an empty list.
    assert by_ticker["OLD"]["rationale"] == []


def test_recommendations_min_score_filter(session: Session, client: TestClient) -> None:
    _seed(session)
    response = client.get("/v1/recommendations", params={"min_score": 4})
    assert response.status_code == 200
    tickers = [r["ticker"] for r in response.json()]
    assert tickers == ["AAPL"]  # Only score >= 4


def test_recommendations_sorted_score_desc(session: Session, client: TestClient) -> None:
    _seed(session)
    response = client.get("/v1/recommendations")
    scores = [r["score"] for r in response.json()]
    assert scores == sorted(scores, reverse=True)
