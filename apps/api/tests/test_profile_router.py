"""`/v1/profile`: display settings only, since the leaderboard went (A0)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlmodel import Session

from stockviz.models import User
from stockviz.settings import get_settings

SECRET = get_settings().internal_api_token


def _auth_headers(user_id: int) -> dict[str, str]:
    token = jose_jwt.encode({"sub": str(user_id)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def _make_user(session: Session) -> int:
    user = User(email="trader@stockviz.dev", name="Trader")
    session.add(user)
    session.commit()
    session.refresh(user)
    assert user.id is not None
    return user.id


def test_profile_requires_auth(client: TestClient) -> None:
    assert client.get("/v1/profile").status_code == 401
    assert client.patch("/v1/profile", json={"display_currency": "EUR"}).status_code == 401


def test_profile_returns_only_display_settings(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    resp = client.get("/v1/profile", headers=_auth_headers(user_id))
    assert resp.status_code == 200
    assert resp.json() == {"user_id": user_id, "display_currency": "USD"}


def test_patch_sets_the_display_currency(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    headers = _auth_headers(user_id)
    resp = client.patch("/v1/profile", json={"display_currency": "inr"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["display_currency"] == "INR"
    assert client.get("/v1/profile", headers=headers).json()["display_currency"] == "INR"


def test_patch_refuses_an_unsupported_currency(session: Session, client: TestClient) -> None:
    user_id = _make_user(session)
    resp = client.patch(
        "/v1/profile", json={"display_currency": "XYZ"}, headers=_auth_headers(user_id)
    )
    assert resp.status_code == 400


def test_removed_routes_are_gone(client: TestClient) -> None:
    assert client.get("/v1/leaderboard").status_code == 404
    assert client.get("/v1/symbols/AAPL/comments").status_code == 404
    assert client.get("/v1/stream/quotes/AAPL").status_code == 404
