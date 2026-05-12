"""HTTP-level tests for /v1/watchlist.

Like the trading router tests, these mint real JWTs against the in-memory
SQLite engine so the auth dependency is exercised end-to-end.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz.models import PriceBar, Symbol, User
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token


def _auth_headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _seed_symbol(session: Session, ticker: str = "AAPL", name: str = "Apple Inc.") -> None:
    session.add(Symbol(ticker=ticker, name=name, sector="Technology"))
    session.commit()
    session.add(
        PriceBar(
            ticker=ticker,
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


def _make_user(session: Session, email: str = "watcher@stockviz.dev") -> int:
    user = User(email=email, name="Watcher")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def test_watchlist_requires_auth(client: TestClient) -> None:
    assert client.get("/v1/watchlist").status_code == 401
    assert client.post("/v1/watchlist/AAPL").status_code == 401
    assert client.delete("/v1/watchlist/AAPL").status_code == 401


def test_watchlist_starts_empty(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    response = client.get("/v1/watchlist", headers=_auth_headers(user_id))
    assert response.status_code == 200
    assert response.json() == []


def test_add_then_list_includes_metadata_and_close(session: Session, client: TestClient) -> None:
    _seed_symbol(session)
    user_id = _make_user(session)

    response = client.post("/v1/watchlist/aapl", headers=_auth_headers(user_id))
    assert response.status_code == 201
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert body["name"] == "Apple Inc."
    assert body["sector"] == "Technology"
    assert Decimal(body["last_close"]) == Decimal("150")

    response = client.get("/v1/watchlist", headers=_auth_headers(user_id))
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    assert items[0]["ticker"] == "AAPL"


def test_add_is_idempotent(session: Session, client: TestClient) -> None:
    _seed_symbol(session)
    user_id = _make_user(session)
    headers = _auth_headers(user_id)

    assert client.post("/v1/watchlist/AAPL", headers=headers).status_code == 201
    assert client.post("/v1/watchlist/AAPL", headers=headers).status_code == 201

    items = client.get("/v1/watchlist", headers=headers).json()
    assert len(items) == 1


def test_add_unknown_symbol_returns_404(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    response = client.post("/v1/watchlist/NOPE", headers=_auth_headers(user_id))
    assert response.status_code == 404


def test_delete_removes_item(session: Session, client: TestClient) -> None:
    _seed_symbol(session)
    user_id = _make_user(session)
    headers = _auth_headers(user_id)

    client.post("/v1/watchlist/AAPL", headers=headers)
    response = client.delete("/v1/watchlist/AAPL", headers=headers)
    assert response.status_code == 204
    assert client.get("/v1/watchlist", headers=headers).json() == []


def test_delete_missing_returns_404(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    response = client.delete("/v1/watchlist/AAPL", headers=_auth_headers(user_id))
    assert response.status_code == 404


def test_watchlists_are_isolated_per_user(session: Session, client: TestClient) -> None:
    _seed_symbol(session, "AAPL", "Apple Inc.")
    _seed_symbol(session, "MSFT", "Microsoft Corp.")
    alice = _make_user(session, email="alice@stockviz.dev")
    bob = _make_user(session, email="bob@stockviz.dev")

    client.post("/v1/watchlist/AAPL", headers=_auth_headers(alice))
    client.post("/v1/watchlist/MSFT", headers=_auth_headers(bob))

    alice_items = client.get("/v1/watchlist", headers=_auth_headers(alice)).json()
    bob_items = client.get("/v1/watchlist", headers=_auth_headers(bob)).json()
    assert [i["ticker"] for i in alice_items] == ["AAPL"]
    assert [i["ticker"] for i in bob_items] == ["MSFT"]
