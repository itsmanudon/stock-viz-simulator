"""HTTP-level tests for /v1/recommendations."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlmodel import Session

from stockviz.models import Recommendation, Symbol, SymbolMetrics


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
                votes=[
                    {
                        "id": "below_mean",
                        "label": "Below historical mean",
                        "passed": True,
                        "detail": "Below historical mean ($70.00 < $88.00)",
                    },
                    {
                        "id": "below_median",
                        "label": "Below historical median",
                        "passed": True,
                        "detail": "Below historical median ($70.00 < $86.00)",
                    },
                    {
                        "id": "within_one_stdev",
                        "label": "Within 1 stdev below mean",
                        "passed": True,
                        "detail": "Within 1 stdev below mean (gap $18.00, stdev $20.00)",
                    },
                    {
                        "id": "volume_above_mean",
                        "label": "Volume above average",
                        "passed": True,
                        "detail": "Volume above average (3,000,000 vs avg 1,000,000)",
                    },
                    {
                        "id": "recent_uptrend",
                        "label": "3-bar uptrend",
                        "passed": True,
                        "detail": "3-bar uptrend (92.00 → 96.00)",
                    },
                    {
                        "id": "positive_slope",
                        "label": "Positive 5-bar slope",
                        "passed": False,
                        "detail": "Non-positive 5-bar slope (-0.1000/bar)",
                    },
                    {
                        "id": "positive_sentiment",
                        "label": "Positive news sentiment",
                        "passed": False,
                        "detail": "No scored headlines in the trailing week",
                    },
                ],
                computed_at=datetime(2025, 4, 11),
            ),
            Recommendation(
                ticker="MSFT",
                score=Decimal(3),
                rationale="Below historical mean",
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
    # Structured votes are returned in engine order.
    assert [vote["id"] for vote in by_ticker["AAPL"]["votes"]] == [
        "below_mean",
        "below_median",
        "within_one_stdev",
        "volume_above_mean",
        "recent_uptrend",
        "positive_slope",
        "positive_sentiment",
    ]
    assert by_ticker["AAPL"]["votes"][0]["passed"] is True
    assert by_ticker["AAPL"]["votes"][-1]["passed"] is False
    # Older rows without votes JSON reconstruct pass/fail from rationale.
    msft_votes = {vote["id"]: vote for vote in by_ticker["MSFT"]["votes"]}
    assert msft_votes["below_mean"]["passed"] is True
    assert msft_votes["volume_above_mean"]["passed"] is False
    assert by_ticker["AAPL"]["sentiment_7d"] is None


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


def test_recommendations_include_trailing_sentiment(session: Session, client: TestClient) -> None:
    _seed(session)
    session.add(
        SymbolMetrics(ticker="AAPL", rsi_14=55.0, sentiment_7d=0.42, sentiment_article_count=3)
    )
    session.commit()
    response = client.get("/v1/recommendations")
    by_ticker = {r["ticker"]: r for r in response.json()}
    assert by_ticker["AAPL"]["sentiment_7d"] == 0.42
    assert by_ticker["MSFT"]["sentiment_7d"] is None
