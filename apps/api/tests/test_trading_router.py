"""HTTP-level tests for /v1/portfolio and /v1/trades.

Exercises the auth dependency end-to-end: missing token -> 401; bad token
-> 401; valid headers -> business path. Uses a known user.id since the
conftest fixture isolates each test on its own SQLite engine.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz.auth import require_user_id
from stockviz.main import app
from stockviz.models import PriceBar, Symbol, User
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token


def _auth_headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _seed_market(session: Session) -> None:
    session.add_all([Symbol(ticker="AAPL", name="Apple Inc.")])
    session.commit()
    session.add(
        PriceBar(
            ticker="AAPL",
            ts=datetime(2025, 4, 10),
            interval="1d",
            open=Decimal("145"),
            high=Decimal("151"),
            low=Decimal("144"),
            close=Decimal("150"),
            volume=1_000_000,
            source="test",
        )
    )
    session.commit()


def _make_user(session: Session) -> int:
    user = User(email="trader@stockviz.dev", name="Trader")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def test_portfolio_requires_internal_token(client: TestClient) -> None:
    response = client.get("/v1/portfolio")
    assert response.status_code == 401


def test_portfolio_rejects_bad_token(client: TestClient) -> None:
    response = client.get("/v1/portfolio", headers={"Authorization": "Bearer not-a-valid-jwt"})
    assert response.status_code == 401


def test_portfolio_bootstraps_with_starting_cash(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    response = client.get("/v1/portfolio", headers=_auth_headers(user_id))
    assert response.status_code == 200
    body = response.json()
    # First read auto-creates with the default starting cash.
    assert Decimal(body["cash_balance"]) == Decimal("100000.00")
    assert body["positions"] == []


def test_trade_buy_then_portfolio_reflects(session: Session, client: TestClient) -> None:
    _seed_market(session)
    user_id = _make_user(session)

    # Place a 5-share buy.
    response = client.post(
        "/v1/trades",
        headers=_auth_headers(user_id),
        json={"ticker": "AAPL", "side": "buy", "quantity": "5"},
    )
    assert response.status_code == 201
    trade = response.json()
    assert trade["price"] == "150.000000"
    assert trade["side"] == "buy"

    # Portfolio reflects the buy.
    response = client.get("/v1/portfolio", headers=_auth_headers(user_id))
    body = response.json()
    assert Decimal(body["cash_balance"]) == Decimal("100000.00") - Decimal("750.00")
    assert len(body["positions"]) == 1
    assert body["positions"][0]["ticker"] == "AAPL"
    assert Decimal(body["positions"][0]["quantity"]) == Decimal(5)

    # /v1/trades returns the history.
    response = client.get("/v1/trades", headers=_auth_headers(user_id))
    body = response.json()
    assert len(body) == 1
    assert body[0]["ticker"] == "AAPL"


def test_insufficient_cash_returns_422(session: Session, client: TestClient) -> None:
    _seed_market(session)
    user_id = _make_user(session)
    response = client.post(
        "/v1/trades",
        headers=_auth_headers(user_id),
        json={"ticker": "AAPL", "side": "buy", "quantity": "10000"},
    )
    assert response.status_code == 422


def test_unknown_symbol_returns_404(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    response = client.post(
        "/v1/trades",
        headers=_auth_headers(user_id),
        json={"ticker": "NOPE", "side": "buy", "quantity": "1"},
    )
    assert response.status_code == 404


def test_auth_dependency_override_works(session: Session, client: TestClient) -> None:
    """The auth headers are the production path; ensure the dep itself is overridable
    for tests / scripts that want to inject a user id directly."""

    user_id = _make_user(session)
    app.dependency_overrides[require_user_id] = lambda: user_id
    try:
        response = client.get("/v1/portfolio")  # no headers
        assert response.status_code == 200
    finally:
        app.dependency_overrides.pop(require_user_id, None)
